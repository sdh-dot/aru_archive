"""
태그 팩 로드·검증·DB seed 기능.

tag pack JSON 형식:
{
  "pack_id": "...",
  "name": "...",
  "version": "...",
  "source": "built_in",
  "series": [...],
  "characters": [...]
}

DB 저장 정책:
  series alias   → tag_aliases (tag_type='series',    parent_series='')
  character alias→ tag_aliases (tag_type='character', parent_series=parent_series)
  localization   → tag_localizations (INSERT OR IGNORE)
  source = 'built_in_pack:{pack_id}'

Mojibake 차단 정책 (PR-6):
  Strong 신호 1건이라도 발견되면 import 전체를 중단 (TagPackImportBlockedError).
  Weak 신호는 해당 row를 건너뛰고 경고를 기록한 뒤 나머지를 import.
  source = 'built_in_pack:*' 도 동일하게 lint 적용 (알려진 정상 pack 통과 확인 완료).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from core.mojibake_heuristics import classify_mojibake_severity, is_suspected_mojibake

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Import-blocking exception
# ---------------------------------------------------------------------------

class TagPackImportBlockedError(Exception):
    """Raised when a tag pack contains strong mojibake signals.

    Attributes
    ----------
    reasons_summary : dict
        Counts of strong/weak signals found.  Keys: ``"strong"``, ``"weak"``.
    samples : list[dict]
        Up to 5 sample rows that triggered a strong signal.
        Each dict has keys: table, field, value, reasons.
    """

    def __init__(self, reasons_summary: dict, samples: list[dict]) -> None:
        self.reasons_summary = reasons_summary
        self.samples = samples
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        lines = [
            "TagPackImportBlocked: 가져오려는 태그팩에 깨진 문자로 보이는 항목이 포함되어 있어 import를 중단했습니다.",
            "",
            "원본 파일 인코딩을 확인하거나 `tools/diagnose_mojibake.py`로 진단 후 수정하세요.",
            "",
            "차단 사유:",
            f"  - strong 신호 {self.reasons_summary.get('strong', 0)}건",
            f"  - weak   신호 {self.reasons_summary.get('weak',   0)}건",
            "",
            "의심 row sample (top 5):",
        ]
        for i, s in enumerate(self.samples[:5], 1):
            lines.append(
                f"  {i}. table={s.get('table','?')} field={s.get('field','?')}"
                f" value={s.get('value','')!r} reasons={s.get('reasons', [])}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal lint helpers
# ---------------------------------------------------------------------------

def _lint_pack_data(data: dict) -> tuple[list[dict], list[dict]]:
    """Scan all text fields in *data* for mojibake signals.

    Returns
    -------
    (strong_hits, weak_hits)
        Each element is a list of dicts with keys:
        table, field, value, reasons, tag_type, canonical.
    """
    strong_hits: list[dict] = []
    weak_hits: list[dict] = []

    def _check(value: str | None, table: str, field: str,
                tag_type: str, canonical: str, locale: str | None = None) -> None:
        if not value:
            return
        suspected, reasons = is_suspected_mojibake(value, locale=locale)
        if not suspected:
            return
        severity = classify_mojibake_severity(reasons)
        hit = {
            "table": table,
            "field": field,
            "value": value,
            "reasons": reasons,
            "tag_type": tag_type,
            "canonical": canonical,
        }
        if severity == "strong":
            strong_hits.append(hit)
        else:
            weak_hits.append(hit)

    for s in data.get("series", []):
        if not isinstance(s, dict):
            continue
        canonical = s.get("canonical", "")
        _check(canonical, "tag_aliases", "canonical", "series", canonical)
        for alias in s.get("aliases", []):
            _check(alias, "tag_aliases", "alias", "series", canonical)
        for locale, display_name in s.get("localizations", {}).items():
            if locale.startswith("_"):
                continue
            _check(display_name, "tag_localizations", "display_name",
                   "series", canonical, locale=locale)

    for char in data.get("characters", []):
        if not isinstance(char, dict):
            continue
        canonical = char.get("canonical", "")
        _check(canonical, "tag_aliases", "canonical", "character", canonical)
        for alias in char.get("aliases", []):
            _check(alias, "tag_aliases", "alias", "character", canonical)
        for locale, display_name in char.get("localizations", {}).items():
            if locale.startswith("_"):
                continue
            _check(display_name, "tag_localizations", "display_name",
                   "character", canonical, locale=locale)

    return strong_hits, weak_hits


def _apply_pack_lint(data: dict, *, pack_label: str = "") -> set[str]:
    """Run mojibake lint on *data* and raise or warn as appropriate.

    Parameters
    ----------
    data:
        Parsed JSON dict (series + characters).
    pack_label:
        Human-readable identifier for log messages.

    Returns
    -------
    set of ``(table, field, value)`` tuples that should be **skipped**
    (weak signals only).  Callers compare each row against this set.

    Raises
    ------
    TagPackImportBlockedError
        When at least one strong signal is found.
    """
    strong_hits, weak_hits = _lint_pack_data(data)

    if strong_hits:
        reasons_summary = {"strong": len(strong_hits), "weak": len(weak_hits)}
        raise TagPackImportBlockedError(reasons_summary, strong_hits[:5])

    skip_values: set[str] = set()
    for hit in weak_hits:
        val = hit["value"]
        skip_values.add(val)
        logger.warning(
            "tag pack lint 경고 (%s): field=%s value=%r reasons=%s — 해당 row 건너뜀",
            pack_label, hit["field"], val, hit["reasons"],
        )

    return skip_values


def load_tag_pack(path: Union[str, Path]) -> dict:
    """JSON tag pack 파일을 로드한다."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_tag_pack(pack: dict) -> None:
    """기본 구조 검증. 실패 시 ValueError."""
    for key in ("pack_id", "name", "version"):
        if key not in pack:
            raise ValueError(f"tag pack에 필수 키 없음: {key}")
    if not isinstance(pack.get("series", []), list):
        raise ValueError("'series'는 list여야 합니다")
    if not isinstance(pack.get("characters", []), list):
        raise ValueError("'characters'는 list여야 합니다")


def seed_tag_pack(conn: sqlite3.Connection, pack: dict) -> dict:
    """
    pack의 series/characters aliases를 tag_aliases에 INSERT OR IGNORE.
    localizations를 tag_localizations에 INSERT OR IGNORE.

    alias가 이미 다른 canonical에 등록되어 있으면 충돌로 기록하고 건너뛴다.

    반환:
        {
            "series_aliases":    N,
            "character_aliases": N,
            "localizations":     N,
            "conflicts": [{"alias": ..., "existing_canonical": ..., "pack_canonical": ...}],
        }
    """
    validate_tag_pack(pack)
    pack_id = pack["pack_id"]
    source = f"built_in_pack:{pack_id}"
    now = datetime.now(timezone.utc).isoformat()

    # PR-6: mojibake lint — strong 신호 발견 시 즉시 중단, weak 신호는 skip 목록 반환
    skip_values = _apply_pack_lint(pack, pack_label=pack_id)

    series_count = 0
    char_count = 0
    loc_count = 0
    conflicts: list[dict] = []

    for series in pack.get("series", []):
        canonical = series["canonical"]
        media_type = series.get("media_type", "")

        for alias in series.get("aliases", []):
            if alias in skip_values:
                continue
            try:
                existing = conn.execute(
                    "SELECT canonical FROM tag_aliases "
                    "WHERE alias=? AND tag_type='series' AND enabled=1",
                    (alias,),
                ).fetchone()
                if existing and existing["canonical"] != canonical:
                    conflicts.append({
                        "alias":              alias,
                        "existing_canonical": existing["canonical"],
                        "pack_canonical":     canonical,
                    })
                    logger.debug(
                        "series alias 충돌 (건너뜀): %s → %s (기존 %s)",
                        alias, canonical, existing["canonical"],
                    )
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO tag_aliases
                       (alias, canonical, tag_type, parent_series, media_type,
                        source, enabled, created_at)
                       VALUES (?, ?, 'series', '', ?, ?, 1, ?)""",
                    (alias, canonical, media_type, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    series_count += 1
            except Exception as exc:
                logger.debug("series alias 삽입 실패 (%s): %s", alias, exc)

        for locale, display_name in series.get("localizations", {}).items():
            if display_name in skip_values:
                continue
            try:
                lid = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO tag_localizations
                       (localization_id, canonical, tag_type, parent_series,
                        locale, display_name, source, enabled, created_at)
                       VALUES (?, ?, 'series', '', ?, ?, ?, 1, ?)""",
                    (lid, canonical, locale, display_name, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    loc_count += 1
            except Exception as exc:
                logger.debug("series localization 삽입 실패 (%s/%s): %s", canonical, locale, exc)

    for character in pack.get("characters", []):
        canonical = character["canonical"]
        parent_series = character.get("parent_series", "")

        for alias in character.get("aliases", []):
            if alias in skip_values:
                continue
            try:
                existing = conn.execute(
                    "SELECT canonical FROM tag_aliases "
                    "WHERE alias=? AND tag_type='character' AND enabled=1",
                    (alias,),
                ).fetchone()
                if existing and existing["canonical"] != canonical:
                    conflicts.append({
                        "alias":              alias,
                        "existing_canonical": existing["canonical"],
                        "pack_canonical":     canonical,
                    })
                    logger.debug(
                        "character alias 충돌 (건너뜀): %s → %s (기존 %s)",
                        alias, canonical, existing["canonical"],
                    )
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO tag_aliases
                       (alias, canonical, tag_type, parent_series,
                        source, enabled, created_at)
                       VALUES (?, ?, 'character', ?, ?, 1, ?)""",
                    (alias, canonical, parent_series, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    char_count += 1
            except Exception as exc:
                logger.debug("character alias 삽입 실패 (%s): %s", alias, exc)

        for locale, display_name in character.get("localizations", {}).items():
            if display_name in skip_values:
                continue
            try:
                lid = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO tag_localizations
                       (localization_id, canonical, tag_type, parent_series,
                        locale, display_name, source, enabled, created_at)
                       VALUES (?, ?, 'character', ?, ?, ?, ?, 1, ?)""",
                    (lid, canonical, parent_series, locale, display_name, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    loc_count += 1
            except Exception as exc:
                logger.debug("character localization 삽입 실패 (%s/%s): %s", canonical, locale, exc)

    conn.commit()
    if conflicts:
        logger.warning(
            "tag pack '%s' alias 충돌 %d건 (건너뜀): %s",
            pack_id, len(conflicts),
            [c["alias"] for c in conflicts],
        )
    return {
        "series_aliases":    series_count,
        "character_aliases": char_count,
        "localizations":     loc_count,
        "conflicts":         conflicts,
    }


def validate_localized_tag_pack(path: "Union[str, Path]") -> dict:
    """
    localized tag pack JSON을 검증한다.

    확인:
    - valid JSON
    - characters/series 존재
    - aliases/canonical/parent_series 구조 보존
    - localizations.ko / ja 형식 확인
    - _review 필드가 있어도 import가 깨지지 않는지 확인

    반환: {"valid": bool, "errors": [...], "warnings": [...], "stats": {...}}
    """
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict = {
        "characters": 0,
        "series": 0,
        "has_ko": 0,
        "has_ja": 0,
        "review_items": 0,
    }

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return {"valid": False, "errors": [f"JSON 파싱 오류: {e}"], "warnings": [], "stats": stats}
    except OSError as e:
        return {"valid": False, "errors": [f"파일 읽기 오류: {e}"], "warnings": [], "stats": stats}

    for key in ("characters", "series"):
        if key not in data:
            warnings.append(f"'{key}' 키 없음 (빈 목록으로 처리)")
    if not isinstance(data.get("characters", []), list):
        errors.append("'characters'는 list여야 합니다")
    if not isinstance(data.get("series", []), list):
        errors.append("'series'는 list여야 합니다")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "stats": stats}

    for char in data.get("characters", []):
        if not isinstance(char, dict):
            warnings.append("characters 항목이 dict가 아닌 항목 발견 (건너뜀)")
            continue
        stats["characters"] += 1
        if "canonical" not in char:
            warnings.append(f"canonical 없는 character 항목: {char}")
        locs = char.get("localizations", {})
        if locs.get("ko"):
            stats["has_ko"] += 1
        if locs.get("ja"):
            stats["has_ja"] += 1
        if "_review" in char:
            stats["review_items"] += 1

    for s in data.get("series", []):
        if not isinstance(s, dict):
            continue
        stats["series"] += 1
        locs = s.get("localizations", {})
        if locs.get("ko"):
            stats["has_ko"] += 1
        if locs.get("ja"):
            stats["has_ja"] += 1
        if "_review" in s:
            stats["review_items"] += 1

    return {"valid": True, "errors": errors, "warnings": warnings, "stats": stats}


def import_localized_tag_pack(
    conn: sqlite3.Connection,
    path: "Union[str, Path]",
    *,
    apply_review_items: bool = False,
) -> dict:
    """
    localized tag pack JSON을 import한다.

    기본 정책:
    - aliases는 tag_aliases에 반영
    - localizations는 tag_localizations에 반영
    - _review가 있는 항목은 기본적으로 자동 병합하지 않음
    - _review.merge_candidate / variant_tag는 자동 병합하지 않고 report에만 표시
    - 기존 user source localization이 있으면 conflict를 report (덮어쓰지 않음)

    반환:
    {
        "series_aliases":          N,
        "character_aliases":       N,
        "localizations":           N,
        "review_items":            N,
        "merge_candidates":        N,
        "variant_items":           N,
        "group_general_candidates":N,
        "conflicts":               [...],
        "merge_candidate_details": [...],
    }
    """
    validation = validate_localized_tag_pack(path)
    if not validation["valid"]:
        raise ValueError(f"localized tag pack 검증 실패: {validation['errors']}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    pack_id = data.get("pack_id", "localized_import")
    source = "imported_localized_pack"
    now = datetime.now(timezone.utc).isoformat()

    # PR-6: mojibake lint — DB 쓰기 전 전체 scan.
    # Strong 신호 발견 시 TagPackImportBlockedError raise → DB 무변화 보장.
    # Weak 신호는 skip_values에 포함 → 해당 row만 건너뜀.
    skip_values = _apply_pack_lint(data, pack_label=pack_id)

    series_count = 0
    char_count = 0
    loc_count = 0
    conflicts: list[dict] = []
    merge_candidates: list[dict] = []
    variant_items: list[dict] = []
    group_general_candidates: list[dict] = []
    review_count = 0

    # --- series ---
    for s in data.get("series", []):
        if not isinstance(s, dict):
            continue
        canonical = s.get("canonical", "")
        if not canonical:
            continue

        review = s.get("_review", {})
        if review:
            review_count += 1
            _collect_review_items(
                review, canonical, "series", merge_candidates,
                variant_items, group_general_candidates,
            )

        for alias in s.get("aliases", []):
            if alias in skip_values:
                continue
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO tag_aliases
                       (alias, canonical, tag_type, parent_series, source, enabled, created_at)
                       VALUES (?, ?, 'series', '', ?, 1, ?)""",
                    (alias, canonical, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    series_count += 1
            except Exception as exc:
                logger.debug("series alias 삽입 실패 (%s): %s", alias, exc)

        for locale, display_name in s.get("localizations", {}).items():
            if not display_name or locale.startswith("_"):
                continue
            if display_name in skip_values:
                continue
            lc, conf = _upsert_localization(
                conn, canonical, "series", "", locale, display_name, source, now
            )
            loc_count += lc
            if conf:
                conflicts.append(conf)

    # --- characters ---
    for char in data.get("characters", []):
        if not isinstance(char, dict):
            continue
        canonical = char.get("canonical", "")
        parent_series = char.get("parent_series", "")
        if not canonical:
            continue

        review = char.get("_review", {})
        if review:
            review_count += 1
            _collect_review_items(
                review, canonical, "character", merge_candidates,
                variant_items, group_general_candidates,
            )

        for alias in char.get("aliases", []):
            if alias in skip_values:
                continue
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO tag_aliases
                       (alias, canonical, tag_type, parent_series, source, enabled, created_at)
                       VALUES (?, ?, 'character', ?, ?, 1, ?)""",
                    (alias, canonical, parent_series, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    char_count += 1
            except Exception as exc:
                logger.debug("character alias 삽입 실패 (%s): %s", alias, exc)

        for locale, display_name in char.get("localizations", {}).items():
            if not display_name or locale.startswith("_"):
                continue
            if display_name in skip_values:
                continue
            lc, conf = _upsert_localization(
                conn, canonical, "character", parent_series, locale,
                display_name, source, now,
            )
            loc_count += lc
            if conf:
                conflicts.append(conf)

    conn.commit()

    return {
        "series_aliases":           series_count,
        "character_aliases":        char_count,
        "localizations":            loc_count,
        "review_items":             review_count,
        "merge_candidates":         len(merge_candidates),
        "variant_items":            len(variant_items),
        "group_general_candidates": len(group_general_candidates),
        "conflicts":                conflicts,
        "merge_candidate_details":  merge_candidates,
        "variant_details":          variant_items,
        "group_general_details":    group_general_candidates,
    }


def _upsert_localization(
    conn: sqlite3.Connection,
    canonical: str,
    tag_type: str,
    parent_series: str,
    locale: str,
    display_name: str,
    source: str,
    now: str,
) -> tuple[int, dict | None]:
    """
    tag_localizations에 localization을 삽입한다.
    기존 user source 데이터가 있으면 충돌로 기록하고 덮어쓰지 않는다.

    반환: (삽입 수, conflict dict 또는 None)
    """
    existing = conn.execute(
        """SELECT display_name, source FROM tag_localizations
           WHERE canonical=? AND tag_type=? AND parent_series=? AND locale=?""",
        (canonical, tag_type, parent_series, locale),
    ).fetchone()

    if existing:
        if (
            existing["source"] in ("user", "user_import", "user_confirmed")
            and existing["display_name"] != display_name
        ):
            return 0, {
                "canonical": canonical,
                "locale": locale,
                "existing_display_name": existing["display_name"],
                "new_display_name": display_name,
                "reason": "user source 충돌 — 덮어쓰지 않음",
            }
        return 0, None

    try:
        lid = str(uuid.uuid4())
        conn.execute(
            """INSERT OR IGNORE INTO tag_localizations
               (localization_id, canonical, tag_type, parent_series,
                locale, display_name, source, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (lid, canonical, tag_type, parent_series, locale, display_name, source, now),
        )
        if conn.execute("SELECT changes()").fetchone()[0]:
            return 1, None
    except Exception as exc:
        logger.debug("localization 삽입 실패 (%s/%s): %s", canonical, locale, exc)
    return 0, None


def _collect_review_items(
    review: dict,
    canonical: str,
    tag_type: str,
    merge_candidates: list[dict],
    variant_items: list[dict],
    group_general_candidates: list[dict],
) -> None:
    """_review 필드에서 merge/variant/group 후보를 수집한다."""
    mc = review.get("merge_candidate")
    if mc:
        merge_candidates.append({
            "canonical": canonical,
            "tag_type": tag_type,
            "merge_into": mc,
            "reason": review.get("reason", ""),
        })

    if review.get("variant_tag"):
        variant_items.append({
            "canonical": canonical,
            "tag_type": tag_type,
            "base_character": review.get("base_character_candidate", ""),
            "reason": review.get("reason", ""),
        })

    if review.get("possibly_general_or_group_tag"):
        group_general_candidates.append({
            "canonical": canonical,
            "tag_type": tag_type,
            "reason": review.get("reason", ""),
        })


def seed_builtin_tag_packs(conn: sqlite3.Connection) -> dict:
    """
    resources/tag_packs/ 내 모든 내장 tag pack을 seed한다.
    중복 삽입은 INSERT OR IGNORE로 방지한다.

    반환: {"series_aliases": N, "character_aliases": N, "localizations": N}
    """
    packs_dir = Path(__file__).parent.parent / "resources" / "tag_packs"
    if not packs_dir.exists():
        logger.debug("tag_packs 디렉터리 없음: %s", packs_dir)
        return {"series_aliases": 0, "character_aliases": 0, "localizations": 0}

    total: dict[str, int] = {"series_aliases": 0, "character_aliases": 0, "localizations": 0}
    for pack_file in sorted(packs_dir.glob("*.json")):
        try:
            pack = load_tag_pack(pack_file)
            result = seed_tag_pack(conn, pack)
            for key in total:
                total[key] += result.get(key, 0)
            if any(result.values()):
                logger.info("tag pack seed 완료: %s → %s", pack_file.name, result)
        except Exception as exc:
            logger.warning("tag pack 로드 실패 (%s): %s", pack_file.name, exc)
    return total
