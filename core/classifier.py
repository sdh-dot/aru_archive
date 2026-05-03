"""
파일 분류 엔진.

역할:
  1. 분류 가능한 artwork group인지 확인한다.
  2. 복사 대상 파일을 고른다. managed 우선, BMP original은 제외한다.
  3. series/character/artist/tag 정책에 따라 목적지 경로 미리보기를 만든다.
  4. 사용자가 승인한 preview를 실제 파일 복사와 DB 기록으로 확정한다.

분류 가능 상태: full | json_only | xmp_write_failed
분류 불가 상태: pending | metadata_missing | 실패 계열 전부
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from core.path_utils import sanitize_path_component
from core.tag_localizer import resolve_display_name_with_info

# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _parse_json_list(raw: str | None) -> list[str]:
    """JSON 배열 문자열을 파싱해 문자열 리스트로 반환한다."""
    if not raw:
        return []
    try:
        return [t.strip() for t in json.loads(raw) if (t or "").strip()]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CLASSIFIABLE_STATUSES: frozenset[str] = frozenset(
    {"full", "json_only", "xmp_write_failed"}
)


# ---------------------------------------------------------------------------
# series-only resolver — explicit series 와 character.parent_series 의 관계로
# 시리즈 폴더만 모드의 destination 을 결정한다.
#
# series-only mode 의 cfg signature:
#   enable_series_character         = False
#   enable_series_uncategorized     = True
#   enable_character_without_series = False
#
# 이 모듈의 함수들은 metadata pipeline / DB schema / classified_copy 생성
# 정책을 변경하지 않는다. preview 단계에서 시리즈 destination 결정과
# needs_review 판정에만 영향을 준다.
# ---------------------------------------------------------------------------

# series-only resolver 가 반환하는 review reason 상수.
SERIES_ONLY_REASON_PARENT_CONFLICT      = "series_parent_conflict"
SERIES_ONLY_REASON_MULTI_REQ_CONFIRM    = "multiple_parent_series_requires_confirmation"
SERIES_ONLY_REASON_UNIDENTIFIED         = "series_unidentified"

# series-only resolver 가 반환하는 ready rule 상수.
SERIES_ONLY_RULE_SERIES_TAG             = "series_tag"
SERIES_ONLY_RULE_PARENT_SERIES          = "parent_series"
SERIES_ONLY_RULE_MULTIPLE_PARENT_SERIES = "multiple_parent_series"


def is_series_only_mode(cfg: dict) -> bool:
    """cfg 가 series-only mode signature 인지 검사한다.

    Wizard Step 5 의 ``classification_level == 'series_only'`` 가 적용되면
    `_apply_level_to_cfg` 가 위 3개 플래그를 세팅한다. 이 함수는 그 결과를
    classifier 단에서 다시 검출해 series-only resolver 분기를 트리거한다.
    """
    return bool(
        cfg.get("enable_series_character") is False
        and cfg.get("enable_series_uncategorized") is True
        and cfg.get("enable_character_without_series") is False
    )


def resolve_series_only_destination(
    explicit_series: list[str],
    parent_series_map: dict[str, str],
    *,
    allow_multi_destination: bool = True,
) -> dict:
    """series-only mode 의 destination 결정 로직 (pure function).

    Args:
        explicit_series:    raw_tags 에서 직접 series alias 매칭으로 식별된
                            canonical series 목록 (Pixiv 가 명시한 series).
                            character.parent_series 로부터 역추론된 series 는
                            포함하지 않는다.
        parent_series_map:  character canonical → parent_series canonical
                            매핑. 비어 있는 parent_series 는 caller 가 미리
                            제외해서 넘긴다.
        allow_multi_destination:
                            True 면 explicit 가 없고 parent_series 가 여러
                            개일 때 모두 destination 으로 emit 한다.
                            False 면 needs_review (사용자 확인 필요) 로 분기.

    Returns:
        ready 케이스:
            {
                "status": "ready",
                "rule":   "series_tag" | "parent_series" | "multiple_parent_series",
                "series": [series_canonical, ...],
            }
        needs_review 케이스:
            {
                "status": "needs_review",
                "reason": "series_parent_conflict" |
                          "multiple_parent_series_requires_confirmation" |
                          "series_unidentified",
                "series":        [...],   # explicit series (있을 때)
                "parent_series": [...],   # detected parent_series keys
            }
    """
    explicit_set: list[str] = list(dict.fromkeys(explicit_series or []))
    parent_keys: list[str] = sorted(
        {s for s in (parent_series_map or {}).values() if s}
    )

    if explicit_set:
        # Rule 1/2: explicit series O — parent_series 와 비교해 충돌 확인.
        if parent_keys and not (set(explicit_set) & set(parent_keys)):
            return {
                "status":        "needs_review",
                "reason":        SERIES_ONLY_REASON_PARENT_CONFLICT,
                "series":        sorted(explicit_set),
                "parent_series": parent_keys,
            }
        return {
            "status": "ready",
            "rule":   SERIES_ONLY_RULE_SERIES_TAG,
            "series": sorted(explicit_set),
        }

    # Rule 3: explicit X, parent_series 1 → 단일 destination.
    if len(parent_keys) == 1:
        return {
            "status": "ready",
            "rule":   SERIES_ONLY_RULE_PARENT_SERIES,
            "series": parent_keys,
        }

    # Rule 4/5: explicit X, parent_series 다수.
    if len(parent_keys) > 1:
        if allow_multi_destination:
            return {
                "status": "ready",
                "rule":   SERIES_ONLY_RULE_MULTIPLE_PARENT_SERIES,
                "series": parent_keys,
            }
        return {
            "status":        "needs_review",
            "reason":        SERIES_ONLY_REASON_MULTI_REQ_CONFIRM,
            "series":        [],
            "parent_series": parent_keys,
        }

    # Rule 6: explicit X, parent_series X → 시리즈 미식별.
    return {
        "status":        "needs_review",
        "reason":        SERIES_ONLY_REASON_UNIDENTIFIED,
        "series":        [],
        "parent_series": [],
    }


def _resolve_series_only_inputs(
    raw_tags: list[str],
    conn: Optional[sqlite3.Connection],
) -> tuple[list[str], dict[str, str]]:
    """raw_tags 로부터 explicit series 와 character/group.parent_series 매핑을 만든다.

    `core.tag_classifier.classify_pixiv_tags` 의 evidence 를 사용해
    direct/normalized/popularity-suffix 매칭으로 식별된 series 만 explicit 로
    분리하고, character / group evidence 의 parent_series 를 역추론용 매핑으로
    모은다 (PR #121).

    classify_pixiv_tags 호출이 실패해도 빈 결과를 반환 — preview 흐름이
    끊기지 않도록 한다.
    """
    if not raw_tags:
        return [], {}
    try:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(raw_tags, conn=conn)
    except Exception:
        return [], {}

    inferred: set[str] = set()
    for ev in result.get("evidence", {}).get("series", []):
        source = ev.get("source")
        if source in ("inferred_from_character", "inferred_from_group") and ev.get("canonical"):
            inferred.add(ev["canonical"])

    all_series = list(result.get("series_tags") or [])
    explicit_series = [s for s in all_series if s not in inferred]

    parent_series_map: dict[str, str] = {}
    for ev in result.get("evidence", {}).get("characters", []):
        canonical = ev.get("canonical")
        parent    = ev.get("parent_series") or ""
        if canonical and parent:
            parent_series_map.setdefault(canonical, parent)
    for ev in result.get("evidence", {}).get("groups", []):
        canonical = ev.get("canonical")
        parent    = ev.get("parent_series") or ""
        if canonical and parent:
            # group 의 canonical 이 character 와 같은 이름일 가능성은 매우 낮지만
            # setdefault 로 기존 character 매핑을 우선한다 — 두 값이 같은 series 를
            # 가리키므로 결과는 동일.
            parent_series_map.setdefault(canonical, parent)

    return explicit_series, parent_series_map


# ---------------------------------------------------------------------------
# 분류 대상 파일 선택
# ---------------------------------------------------------------------------

def select_classify_target(
    conn: sqlite3.Connection, group_id: str
) -> Optional[dict]:
    """
    분류 복사 대상 파일을 선택한다.

    우선순위:
    1. file_role='managed'  AND file_status='present'
    2. file_role='original' AND file_status='present'  (BMP 제외)
    sidecar / classified_copy는 대상 아님.
    BMP original만 남아 있으면 None 반환 (PNG managed 생성 먼저 필요).
    """
    rows = conn.execute(
        """
        SELECT file_id, file_path, file_format, file_role, file_size, page_index
        FROM   artwork_files
        WHERE  group_id    = ?
          AND  file_status = 'present'
          AND  file_role   NOT IN ('sidecar', 'classified_copy')
        ORDER BY
          CASE file_role WHEN 'managed' THEN 0 ELSE 1 END,
          page_index
        """,
        (group_id,),
    ).fetchall()

    for row in rows:
        d = dict(row)
        # BMP original은 직접 분류 금지 (PNG managed 생성 후 재시도 필요)
        if d["file_role"] == "original" and d["file_format"] == "bmp":
            continue
        return d
    return None


# ---------------------------------------------------------------------------
# 분류 설정 헬퍼
# ---------------------------------------------------------------------------

def _cls_cfg(config: dict) -> dict:
    """classification 설정의 현재 정책값을 기본값과 병합한다."""
    c = config.get("classification", {})
    return {
        "enable_series_character":         c.get("enable_series_character", True),
        "enable_series_uncategorized":     c.get("enable_series_uncategorized", True),
        "enable_character_without_series": c.get("enable_character_without_series", True),
        "fallback_by_author":              c.get("fallback_by_author", True),
        "enable_by_author":                c.get("enable_by_author", False),
        "enable_by_tag":                   c.get("enable_by_tag", False),
        "on_conflict":                     c.get("on_conflict", "rename"),
        # 다국어 폴더명
        "folder_locale":                   c.get("folder_locale", "canonical"),
        "fallback_locale":                 c.get("fallback_locale", "canonical"),
        "enable_localized_folder_names":   c.get("enable_localized_folder_names", True),
        # 일괄 분류
        "batch_existing_copy_policy":      c.get("batch_existing_copy_policy", "keep_existing"),
    }


# ---------------------------------------------------------------------------
# 목적지 경로 목록 생성
# ---------------------------------------------------------------------------

def _build_destinations(
    group_row: dict,
    source_file: dict,
    classified_dir: str,
    cfg: dict,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """
    그룹·파일 정보를 바탕으로 복사 목적지 목록을 만든다.

    각 항목: {rule_type, dest_path, conflict, will_copy}
    localization 활성 시 series_canonical, series_display, character_canonical,
    character_display, locale, used_fallback 추가.
    """
    filename  = Path(source_file["file_path"]).name
    base      = Path(classified_dir)
    dests: list[dict] = []

    locale         = cfg.get("folder_locale", "canonical")
    fallback_locale = cfg.get("fallback_locale", "canonical")
    use_locale     = (
        cfg.get("enable_localized_folder_names", True)
        and locale != "canonical"
        and conn is not None
    )

    def _display(canonical: str, tag_type: str, parent_series: str = "") -> tuple[str, bool]:
        if not use_locale:
            return canonical, False
        return resolve_display_name_with_info(
            conn, canonical, tag_type,
            parent_series=parent_series or None,
            locale=locale,
            fallback_locale=fallback_locale,
        )

    def _add(rule_type: str, folder: Path, extra: dict | None = None) -> None:
        entry: dict = {
            "rule_type": rule_type,
            "dest_path": str(folder / filename),
            "conflict":  "none",
            "will_copy": True,
        }
        if extra:
            entry.update(extra)
        dests.append(entry)

    series_tags = list(dict.fromkeys(_parse_json_list(group_row.get("series_tags_json"))))
    char_tags   = list(dict.fromkeys(_parse_json_list(group_row.get("character_tags_json"))))
    has_series  = bool(series_tags)
    has_char    = bool(char_tags)

    # Tier 1: BySeries/{series}/{char} — 시리즈 + 캐릭터 모두 있을 때
    if has_series and has_char and cfg["enable_series_character"]:
        for series in series_tags:
            s_display, s_fb = _display(series, "series")
            s = sanitize_path_component(s_display)
            for char in char_tags:
                c_display, c_fb = _display(char, "character", series)
                c = sanitize_path_component(c_display)
                extra = {
                    "series_canonical": series, "series_display": s_display,
                    "character_canonical": char, "character_display": c_display,
                    "locale": locale if use_locale else "canonical",
                    "used_fallback": s_fb or c_fb,
                } if use_locale else {}
                _add("series_character", base / "BySeries" / s / c, extra)

    # Tier 2: BySeries/{series}/_uncategorized — 시리즈만 있을 때
    elif has_series and cfg["enable_series_uncategorized"]:
        for series in series_tags:
            s_display, s_fb = _display(series, "series")
            s = sanitize_path_component(s_display)
            extra = {
                "series_canonical": series, "series_display": s_display,
                "locale": locale if use_locale else "canonical",
                "used_fallback": s_fb,
            } if use_locale else {}
            _add("series_uncategorized", base / "BySeries" / s / "_uncategorized", extra)

    # Tier 3: ByCharacter/{char} — 캐릭터만 있을 때
    elif has_char and cfg["enable_character_without_series"]:
        for char in char_tags:
            c_display, c_fb = _display(char, "character")
            c = sanitize_path_component(c_display)
            extra = {
                "character_canonical": char, "character_display": c_display,
                "locale": locale if use_locale else "canonical",
                "used_fallback": c_fb,
            } if use_locale else {}
            _add("character", base / "ByCharacter" / c, extra)

    # Author fallback: 시리즈/캐릭터 모두 없을 때만
    if not has_series and not has_char and cfg["fallback_by_author"]:
        artist = (group_row.get("artist_name") or "").strip()
        _add("author_fallback", base / "ByAuthor" / sanitize_path_component(artist, "_unknown_artist"))

    # Always-on author: 시리즈/캐릭터 유무와 무관하게 항상 추가
    if cfg["enable_by_author"]:
        artist = (group_row.get("artist_name") or "").strip()
        _add("author", base / "ByAuthor" / sanitize_path_component(artist, "_unknown_artist"))

    # ByTag (기본 비활성)
    if cfg["enable_by_tag"]:
        for tag in _parse_json_list(group_row.get("tags_json")):
            _add("by_tag", base / "ByTag" / sanitize_path_component(tag))

    # 같은 경로가 중복 생성된 경우 dedupe (먼저 등장한 항목 유지)
    seen_paths: set[str] = set()
    deduped: list[dict] = []
    for d in dests:
        p = d["dest_path"]
        if p not in seen_paths:
            seen_paths.add(p)
            deduped.append(d)
    return deduped


# ---------------------------------------------------------------------------
# 충돌 해결
# ---------------------------------------------------------------------------

def resolve_copy_destination(
    dest_path: Path, on_conflict: str = "rename"
) -> tuple[Path, str]:
    """
    실제 복사될 경로와 충돌 상태를 반환한다.

    conflict 상태:
      'none'    — 충돌 없음, 그대로 복사
      'renamed' — 충돌, 새 이름으로 복사
      'skipped' — 충돌, 복사 생략
    """
    if not dest_path.exists():
        return dest_path, "none"

    if on_conflict == "skip":
        return dest_path, "skipped"

    # rename: filename_1.ext, filename_2.ext, …
    stem   = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent
    for i in range(1, 1001):
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate, "renamed"

    # 1000번 이상 충돌 시 skip으로 폴백
    return dest_path, "skipped"


# ---------------------------------------------------------------------------
# 미리보기 생성
# ---------------------------------------------------------------------------

def build_classify_preview(
    conn: sqlite3.Connection,
    group_id: str,
    config: dict,
) -> Optional[dict]:
    """
    분류 복사 미리보기를 생성한다. 실제 파일 복사는 하지 않는다.

    분류 불가 상태이거나 classified_dir 미설정이면 None 반환.

    반환:
        {
            group_id, source_file_id, source_path,
            destinations: [{rule_type, dest_path, conflict, will_copy}],
            estimated_copies, estimated_bytes,
        }
    """
    group = conn.execute(
        "SELECT * FROM artwork_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if not group:
        return None

    if group["metadata_sync_status"] not in CLASSIFIABLE_STATUSES:
        return None

    classified_dir = config.get("classified_dir", "")
    if not classified_dir:
        return None

    source = select_classify_target(conn, group_id)
    if source is None:
        return None

    cfg   = _cls_cfg(config)

    # series-only mode 전용 destination resolver — explicit series 와
    # character.parent_series 의 관계로 destination / needs_review 를 결정한다.
    # 결과는 _build_destinations 의 series_tags_json virtual override 로 반영해
    # 기존 Tier 2 (series_uncategorized) 경로를 그대로 사용한다.
    series_only_review: dict | None = None
    series_only_rule: str = ""
    group_dict_for_build = dict(group)
    if is_series_only_mode(cfg):
        raw_tags_for_resolver = _parse_json_list(group_dict_for_build.get("tags_json"))
        explicit_series, parent_series_map = _resolve_series_only_inputs(
            raw_tags_for_resolver, conn
        )
        # 기존 DB 의 series_tags_json 도 보조 source 로 사용 — Pixiv API 가
        # 명시한 series 가 raw_tags 에 없는 edge case 를 보완한다.
        db_series = _parse_json_list(group_dict_for_build.get("series_tags_json"))
        explicit_series = list(dict.fromkeys([*explicit_series, *db_series]))
        # _resolve_series_only_inputs 가 inferred series 를 이미 explicit
        # 목록에서 제외해서 반환하므로 추가 후처리는 불필요.

        resolver = resolve_series_only_destination(
            explicit_series,
            parent_series_map,
            allow_multi_destination=bool(
                config.get("classification", {}).get(
                    "allow_multi_destination", True,
                )
            ),
        )
        if resolver["status"] == "ready":
            series_only_rule = resolver["rule"]
            # group dict 의 series_tags_json 을 resolver 결과로 override —
            # _build_destinations 의 Tier 2 가 이 값을 기반으로 dest 를 만든다.
            group_dict_for_build["series_tags_json"] = json.dumps(
                resolver["series"], ensure_ascii=False
            )
        else:
            series_only_review = resolver
            # destination 을 생성하지 않는다 — needs_review.
            group_dict_for_build["series_tags_json"] = "[]"
            group_dict_for_build["character_tags_json"] = "[]"
            # author fallback 도 발동하지 않도록 cfg 임시 복사.
            cfg = dict(cfg)
            cfg["fallback_by_author"] = False

    dests = _build_destinations(group_dict_for_build, source, classified_dir, cfg, conn=conn)

    # series-only ready 케이스: 각 destination 에 resolver rule 메타를 부착해
    # UI 가 시리즈 태그 / 캐릭터 소속 / 복수 소속 를 구분할 수 있게 한다.
    if series_only_rule:
        for d in dests:
            d["series_only_rule"] = series_only_rule

    on_conflict = cfg["on_conflict"]
    for d in dests:
        p = Path(d["dest_path"])
        if p.exists():
            if on_conflict == "skip":
                d["conflict"]  = "would_skip"
                d["will_copy"] = False
            else:
                d["conflict"] = "would_rename"

    file_size = source.get("file_size") or 0
    if file_size == 0:
        try:
            file_size = Path(source["file_path"]).stat().st_size
        except OSError:
            file_size = 0

    copies = sum(1 for d in dests if d["will_copy"])
    # used_fallback=True인 항목에서 실제로 canonical로 폴백한 태그만 수집.
    # display == canonical이면 localization이 없어 canonical 그대로 사용된 것.
    _fb_set: set[str] = set()
    for d in dests:
        if not d.get("used_fallback"):
            continue
        for key_c, key_d in (
            ("series_canonical", "series_display"),
            ("character_canonical", "character_display"),
        ):
            c = d.get(key_c)
            disp = d.get(key_d)
            if c and disp and c == disp:
                _fb_set.add(c)
    fallback_tags = list(_fb_set)

    # 분류 실패 원인 분석 및 inferred series evidence 검출
    group_dict = dict(group)
    series_tags_list = _parse_json_list(group_dict.get("series_tags_json"))
    char_tags_list   = _parse_json_list(group_dict.get("character_tags_json"))
    raw_tags_list    = _parse_json_list(group_dict.get("tags_json"))
    classification_info: dict | None = None

    # character alias로부터 역추론된 series evidence 검출
    inferred_series_evidence: list[dict] = []
    if series_tags_list and raw_tags_list:
        try:
            from core.tag_classifier import classify_pixiv_tags
            reclassify_ev = classify_pixiv_tags(raw_tags_list, conn=conn)
            for ev in reclassify_ev.get("evidence", {}).get("series", []):
                if ev.get("source") == "inferred_from_character":
                    inferred_series_evidence.append(ev)
        except Exception:
            pass

    if series_only_review is not None:
        # series-only resolver 가 needs_review 를 반환한 케이스 — 새 reason
        # 코드를 classification_info 로 노출한다. raw_tags 는 후보 보조용.
        try:
            from core.tag_candidate_generator import GENERAL_TAG_BLACKLIST
        except Exception:
            GENERAL_TAG_BLACKLIST = frozenset()
        candidate_source = [
            t for t in raw_tags_list if t not in GENERAL_TAG_BLACKLIST
        ][:10]
        reason = series_only_review.get("reason", "")
        suggestion_map = {
            SERIES_ONLY_REASON_PARENT_CONFLICT:
                "명시 시리즈와 캐릭터 소속 시리즈가 다릅니다. "
                "잘못된 alias 를 정리하거나 분류 기준을 확인하세요.",
            SERIES_ONLY_REASON_MULTI_REQ_CONFIRM:
                "캐릭터 소속 시리즈가 여러 개입니다. "
                "여러 폴더 분류를 허용하거나 캐릭터 alias 를 정리하세요.",
            SERIES_ONLY_REASON_UNIDENTIFIED:
                "시리즈 / 캐릭터 alias 후보를 확인해 시리즈를 식별하세요.",
        }
        classification_info = {
            "classification_reason": reason,
            "missing_parts":         ["series"],
            "series_context":        "",
            "candidate_source_tags": candidate_source,
            "suggested_action":      suggestion_map.get(reason, ""),
            "series":                series_only_review.get("series", []),
            "parent_series":         series_only_review.get("parent_series", []),
        }
    elif series_tags_list and not char_tags_list:
        # series_uncategorized: series는 감지됐지만 character가 없음
        try:
            from core.tag_candidate_generator import GENERAL_TAG_BLACKLIST
        except Exception:
            GENERAL_TAG_BLACKLIST = frozenset()
        series_set = set(series_tags_list)
        candidate_source = [
            t for t in raw_tags_list
            if t not in series_set and t not in GENERAL_TAG_BLACKLIST
        ][:10]
        classification_info = {
            "classification_reason": "series_detected_but_character_missing",
            "missing_parts": ["character"],
            "series_context": series_tags_list[0] if series_tags_list else "",
            "candidate_source_tags": candidate_source,
            "suggested_action": "태그 후보에서 캐릭터 alias를 승인하거나 태그 재분류를 실행하세요.",
        }
    elif not series_tags_list and not char_tags_list:
        # author_fallback: series도 character도 없음
        try:
            from core.tag_candidate_generator import GENERAL_TAG_BLACKLIST
        except Exception:
            GENERAL_TAG_BLACKLIST = frozenset()
        candidate_source = [
            t for t in raw_tags_list
            if t not in GENERAL_TAG_BLACKLIST
        ][:10]
        classification_info = {
            "classification_reason": "series_and_character_missing",
            "missing_parts": ["series", "character"],
            "series_context": "",
            "candidate_source_tags": candidate_source,
            "suggested_action": "series/character alias 후보를 확인하세요.",
        }

    return {
        "group_id":                  group_id,
        "artwork_title":             group["artwork_title"] or "",
        "source_file_id":            source["file_id"],
        "source_path":               source["file_path"],
        "destinations":              dests,
        "estimated_copies":          copies,
        "estimated_bytes":           file_size * copies,
        "folder_locale":             cfg.get("folder_locale", "canonical"),
        "fallback_tags":             fallback_tags,
        "classification_info":       classification_info,
        "deduped_destinations":      len(dests),
        "inferred_series_evidence":  inferred_series_evidence,
    }


def build_classify_previews(
    conn: sqlite3.Connection,
    group_ids: list[str],
    config: dict,
) -> list[dict]:
    """여러 group_id에 대한 미리보기 목록 반환 (None은 제외)."""
    result = []
    for gid in group_ids:
        p = build_classify_preview(conn, gid, config)
        if p is not None:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# 복사 실행
# ---------------------------------------------------------------------------

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def execute_classify_preview(
    conn: sqlite3.Connection,
    preview: dict,
    config: dict,
    *,
    entry_id: Optional[str] = None,
    _commit: bool = True,
) -> dict:
    """
    preview를 기준으로 실제 파일 복사를 실행한다.

    - 원본/managed 파일은 이동하지 않고 복사만 수행
    - undo_entries 생성 (entry_id 제공 시 기존 항목 재사용 — 일괄 분류용)
    - copy_records 기록
    - artwork_files에 classified_copy 행 추가
    - artwork_groups.status → 'classified'
    """
    now = datetime.now(timezone.utc).isoformat()

    if entry_id is None:
        undo_days  = int(config.get("undo_retention_days", 7))
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=undo_days)
        ).isoformat()
        entry_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO undo_entries
               (entry_id, operation_type, performed_at, undo_expires_at,
                undo_status, description)
               VALUES (?, 'classify', ?, ?, 'pending', ?)""",
            (
                entry_id, now, expires_at,
                f"classify:{preview['group_id'][:8]}…",
            ),
        )

    on_conflict = _cls_cfg(config)["on_conflict"]
    source_path = preview["source_path"]
    copied:   int = 0
    skipped:  int = 0
    copy_log: list[str] = []

    # 원본의 metadata_embedded 값을 그대로 상속한다. 분류는 메타데이터 임베딩
    # 상태를 바꾸지 않으므로, 원본이 0이면 복사본도 0이어야 한다. 원본 row가
    # 사라졌거나 조회에 실패하면 안전 기본값 0(스키마 default와 동일)을 사용.
    src_row = conn.execute(
        "SELECT metadata_embedded FROM artwork_files WHERE file_id = ?",
        (preview["source_file_id"],),
    ).fetchone()
    src_metadata_embedded = int(src_row["metadata_embedded"]) if src_row else 0

    for dest_info in preview["destinations"]:
        if not dest_info["will_copy"]:
            skipped += 1
            continue

        dest_path, conflict = resolve_copy_destination(
            Path(dest_info["dest_path"]), on_conflict
        )

        if conflict == "skipped":
            skipped += 1
            continue

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, str(dest_path))

        file_size = dest_path.stat().st_size
        mtime_iso = datetime.fromtimestamp(
            dest_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        file_hash = _sha256(str(dest_path))

        ext = dest_path.suffix.lower().lstrip(".")
        copy_file_id = str(uuid.uuid4())

        conn.execute(
            """INSERT INTO artwork_files
               (file_id, group_id, page_index, file_role, file_path,
                file_format, file_hash, file_size, metadata_embedded,
                file_status, created_at, source_file_id, classify_rule_id)
               VALUES (?, ?, 0, 'classified_copy', ?, ?, ?, ?,
                       ?, 'present', ?, ?, ?)""",
            (
                copy_file_id, preview["group_id"],
                str(dest_path), ext, file_hash, file_size,
                src_metadata_embedded,
                now, preview["source_file_id"],
                dest_info.get("rule_type", "builtin"),
            ),
        )

        conn.execute(
            """INSERT INTO copy_records
               (entry_id, src_file_id, dest_file_id, src_path, dest_path,
                rule_id, dest_file_size, dest_mtime_at_copy,
                dest_hash_at_copy, copied_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                preview["source_file_id"],
                copy_file_id,
                source_path,
                str(dest_path),
                dest_info.get("rule_type", "builtin"),
                file_size,
                mtime_iso,
                file_hash,
                now,
            ),
        )

        copied += 1
        copy_log.append(str(dest_path))

    if copied > 0:
        conn.execute(
            "UPDATE artwork_groups SET status = 'classified', updated_at = ? "
            "WHERE group_id = ?",
            (now, preview["group_id"]),
        )

    if _commit:
        conn.commit()

    return {
        "success":  True,
        "copied":   copied,
        "skipped":  skipped,
        "entry_id": entry_id,
        "copy_log": copy_log,
        "group_id": preview["group_id"],
    }


# ---------------------------------------------------------------------------
# 레거시 클래스 (MVP-A 골격 호환)
# ---------------------------------------------------------------------------

class Classifier:
    """
    규칙 기반 분류 엔진 (클래스 인터페이스).
    함수형 API(build_classify_preview 등)를 내부에서 위임한다.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def evaluate(self, group_id: str) -> list[dict]:
        return []
