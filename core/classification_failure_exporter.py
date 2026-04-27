"""
분류 실패 태그 Export — 개발자 전용 디버깅 기능.

기본값: OFF (developer.enabled + export_classification_failures 모두 true여야 활성화)

환경변수 강제 활성화:
  ARU_EXPORT_CLASSIFICATION_FAILURES=1   개별 기능 활성화
  ARU_ARCHIVE_DEV_MODE=1                 모든 dev 기능 활성화

우선순위:
  1. ARU_EXPORT_CLASSIFICATION_FAILURES=1  → 강제 ON
  2. ARU_ARCHIVE_DEV_MODE=1               → 강제 ON
  3. config developer.enabled=true AND export_classification_failures=true → ON
  4. 기본값                                → OFF

Note: 환경변수 "0" / 미설정은 config를 강제로 끄지 않는다.

경로 보안:
  기본 report에는 절대 경로 미포함 (파일명만).
  developer.include_absolute_paths_in_debug_reports=true 일 때만 절대 경로 포함.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

# Tags that are known general/attribute tags — never character or series aliases.
# Used to separate "ignored" tags from "truly unknown" tags in failure reports.
_GENERAL_TAGS: frozenset[str] = frozenset({
    "巨乳", "爆乳", "着衣巨乳", "ロリ巨乳", "女の子", "少女", "美少女", "おっぱい",
    "体操服", "体操着", "水着", "ビキニ", "バニーガール", "制服", "セーラー服",
    "チアリーダー", "チアガール", "ふともも", "魅惑のふともも", "魅惑の谷間",
    "黒スト", "黒タイツ", "白タイツ", "ニーソ", "ストッキング", "ハイヒール",
    "眼鏡", "メガネ",
    "笑顔", "照れ", "泣き顔", "上目遣い", "前かがみ",
    "百合", "イラスト", "漫画", "SD", "コイカツ",
    "ウェディングドレス", "ウェディング", "チャイナドレス", "チャイナ服", "チーパオ",
    "レオタード", "ブルマ", "ナース服",
})

_GROUP_TAGS: frozenset[str] = frozenset({
    "便利屋68", "ティーパーティー", "ヘイロー",
    "正義実現委員会", "正義実現委員会のモブ",
    "トリニティ総合学園", "ミレニアムサイエンススクール",
    "生活安全局", "ヴァルキューレ警察学校",
    "連邦生徒会", "ゲヘナ学園", "エデン条約機構",
    "晄輪大祭", "エンジニア部", "補習授業部",
    "キラキラ部", "ブルアカモータリゼーション",
})

_POPULARITY_PATTERN = re.compile(r"^.+?\d+users入り$")

# 실패 판정 대상 rule_type
_FAILURE_RULE_TYPES: frozenset[str] = frozenset({
    "author_fallback",
    "series_uncategorized",
    "character_uncategorized",
    "metadata_missing",
})

# classification_reason → 표준 rule label
_REASON_TO_RULE: dict[str, str] = {
    "series_and_character_missing":          "author_fallback",
    "series_detected_but_character_missing": "series_uncategorized",
}

_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})


# ---------------------------------------------------------------------------
# Public: enabled check
# ---------------------------------------------------------------------------

def is_failure_export_enabled(config: dict | None = None) -> bool:
    """
    분류 실패 export 기능이 켜져 있는지 반환한다.
    기본값은 False.
    """
    if os.environ.get("ARU_EXPORT_CLASSIFICATION_FAILURES", "").strip().lower() in _TRUTHY_ENV:
        return True
    if os.environ.get("ARU_ARCHIVE_DEV_MODE", "").strip().lower() in _TRUTHY_ENV:
        return True
    if config:
        dev = config.get("developer", {})
        if dev.get("enabled") and dev.get("export_classification_failures"):
            return True
    return False


# ---------------------------------------------------------------------------
# Public: convenience wrapper
# ---------------------------------------------------------------------------

def export_from_preview(
    conn: sqlite3.Connection,
    preview: dict,
    config: dict,
) -> str:
    """
    is_failure_export_enabled 체크 → 수집 → 저장 을 한 번에 처리한다.

    반환: 로그용 문자열 (빈 문자열이면 export 미실행)
    """
    if not is_failure_export_enabled(config):
        return ""
    dev = config.get("developer", {})
    include_abs = dev.get("include_absolute_paths_in_debug_reports", False)
    try:
        report = collect_classification_failures(conn, preview, include_absolute_paths=include_abs)
    except Exception as exc:
        logger.debug("collect_classification_failures 실패: %s", exc)
        return ""
    if report["summary"]["failed_groups"] == 0:
        return ""
    output_dir = resolve_output_dir(config)
    try:
        paths = save_classification_failure_report(
            report,
            output_dir,
            write_json=dev.get("classification_failure_export_json", True),
            write_text=dev.get("classification_failure_export_text", True),
        )
    except Exception as exc:
        logger.debug("save_classification_failure_report 실패: %s", exc)
        return ""
    exported = paths.get("json") or paths.get("text") or ""
    return f"[DEV] Classification failure report exported: {exported}"


# ---------------------------------------------------------------------------
# Public: directory resolution
# ---------------------------------------------------------------------------

def resolve_output_dir(config: dict) -> Path:
    """config에서 실패 export 출력 디렉토리를 해석한다."""
    dev = config.get("developer", {})
    raw_dir = dev.get(
        "classification_failure_export_dir",
        ".runtime/debug/classification_failures",
    )
    data_dir = config.get("data_dir", "")
    if data_dir and not Path(raw_dir).is_absolute():
        return Path(data_dir) / raw_dir
    return Path(raw_dir)


# ---------------------------------------------------------------------------
# Public: collect
# ---------------------------------------------------------------------------

def collect_classification_failures(
    conn: sqlite3.Connection,
    preview: dict,
    *,
    include_absolute_paths: bool = False,
) -> dict:
    """
    preview에서 분류 실패 항목을 수집하여 report dict를 반환한다.

    preview 형식:
    - 단일 preview: "destinations" 키 포함
    - 일괄 preview: "previews" 키 포함 (build_classify_batch_preview 반환값)

    각 failed item에 breakdown 필드 포함:
        matched_character_tags, matched_series_tags, inferred_series_tags,
        unmatched_raw_tags, ignored_general_tags, ignored_popularity_tags,
        failure_reason_detail

    tag_frequency는 popularity/general 태그를 제외한 truly unknown 태그만 집계한다.

    반환:
        {
            "summary": {
                "failed_groups": N,
                "unique_raw_tags": M,       # 전체 raw tag 수
                "unique_unmatched_tags": K, # truly unknown tag 수
                "title_only_candidates": T,
                "generated_at": "..."
            },
            "failed_items": [...],
            "tag_frequency": [...],
        }
    """
    if "previews" in preview:
        single_previews: list[dict] = preview.get("previews", [])
    else:
        single_previews = [preview]

    now_str = datetime.now(timezone.utc).isoformat()
    failed_items: list[dict] = []
    all_tag_counter: dict[str, dict] = defaultdict(lambda: {"count": 0, "sample_titles": []})
    unmatched_tag_counter: dict[str, dict] = defaultdict(lambda: {"count": 0, "sample_titles": []})
    title_only_count = 0

    for p in single_previews:
        if not _is_failure_preview(p):
            continue

        group_id    = p.get("group_id", "")
        source_path = p.get("source_path", "")
        rule_type   = _detect_rule_label(p)
        ci          = p.get("classification_info") or {}

        db_info    = _fetch_group_info(conn, group_id)
        artwork_id = db_info.get("artwork_id", "")
        title      = db_info.get("artwork_title") or ""
        artist     = db_info.get("artist_name") or ""

        raw_tags: list[str] = []
        try:
            raw_tags = json.loads(db_info.get("tags_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            raw_tags = list(ci.get("candidate_source_tags", []))

        series_tags_db: list[str] = []
        try:
            series_tags_db = json.loads(db_info.get("series_tags_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass

        char_tags_db: list[str] = []
        try:
            char_tags_db = json.loads(db_info.get("character_tags_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass

        file_name = Path(source_path).name if source_path else ""
        breakdown = _compute_tag_breakdown(raw_tags, title, conn)
        if breakdown.get("failure_reason_detail") == "title_only_candidate":
            title_only_count += 1

        item: dict = {
            "group_id":                   group_id,
            "artwork_id":                 artwork_id,
            "title":                      title,
            "artist":                     artist,
            "file_name":                  file_name,
            "rule_type":                  rule_type,
            "status":                     db_info.get("metadata_sync_status", ""),
            "raw_tags":                   raw_tags,
            "series_tags_json":           series_tags_db,
            "character_tags_json":        char_tags_db,
            "known_series_candidates":    (
                [ci["series_context"]] if ci.get("series_context") else []
            ),
            "known_character_candidates": list(ci.get("candidate_source_tags", [])),
            "warnings":                   list(p.get("fallback_tags", [])),
            "suggested_debug_notes":      _build_debug_notes(raw_tags),
            # breakdown fields
            "matched_character_tags":     breakdown.get("matched_character_tags", []),
            "matched_series_tags":        breakdown.get("matched_series_tags", []),
            "inferred_series_tags":       breakdown.get("inferred_series_tags", []),
            "unmatched_raw_tags":         breakdown.get("unmatched_raw_tags", []),
            "ignored_general_tags":       breakdown.get("ignored_general_tags", []),
            "ignored_popularity_tags":    breakdown.get("ignored_popularity_tags", []),
            "failure_reason_detail":      breakdown.get("failure_reason_detail", "unknown"),
        }
        if include_absolute_paths and source_path:
            item["file_path"] = source_path

        failed_items.append(item)

        display_title = title or file_name or group_id[:8]
        for tag in raw_tags:
            all_tag_counter[tag]["count"] += 1
            s = all_tag_counter[tag]["sample_titles"]
            if display_title not in s and len(s) < 5:
                s.append(display_title)
        for tag in breakdown.get("unmatched_raw_tags", raw_tags):
            unmatched_tag_counter[tag]["count"] += 1
            s = unmatched_tag_counter[tag]["sample_titles"]
            if display_title not in s and len(s) < 5:
                s.append(display_title)

    tag_frequency = sorted(
        [
            {"tag": t, "count": d["count"], "sample_titles": d["sample_titles"]}
            for t, d in unmatched_tag_counter.items()
        ],
        key=lambda x: (-x["count"], x["tag"]),
    )

    return {
        "summary": {
            "failed_groups":          len(failed_items),
            "unique_raw_tags":        len(all_tag_counter),
            "unique_unmatched_tags":  len(unmatched_tag_counter),
            "title_only_candidates":  title_only_count,
            "generated_at":           now_str,
        },
        "failed_items":  failed_items,
        "tag_frequency": tag_frequency,
    }


# ---------------------------------------------------------------------------
# Public: format
# ---------------------------------------------------------------------------

def format_classification_failures_text(report: dict) -> str:
    """Claude/Codex에 바로 붙여넣기 좋은 텍스트 형식으로 변환한다."""
    summary = report.get("summary", {})
    lines: list[str] = [
        "# Aru Archive Classification Failure Tags",
        "",
        "## Summary",
        f"- failed groups: {summary.get('failed_groups', 0)}",
        f"- unique raw tags: {summary.get('unique_raw_tags', 0)}",
        f"- unique unmatched tags: {summary.get('unique_unmatched_tags', 0)}",
        f"- title-only candidates: {summary.get('title_only_candidates', 0)}",
        f"- generated_at: {summary.get('generated_at', '')}",
        "",
    ]

    tag_freq = report.get("tag_frequency", [])
    if tag_freq:
        lines.append("## Frequent Unknown Tags")
        for i, entry in enumerate(tag_freq[:20], 1):
            lines.append(f"{i}. {entry['tag']} — {entry['count']} files")
        lines.append("")

    failed = report.get("failed_items", [])
    if failed:
        lines.append("## Failed Files")
        for item in failed:
            display = item.get("file_name") or item.get("group_id", "")[:8]
            lines.append("")
            lines.append(f"### {display}")
            lines.append(f"rule_type: {item.get('rule_type', '')}")
            detail = item.get("failure_reason_detail", "")
            if detail:
                lines.append(f"failure_reason_detail: {detail}")
            if item.get("title"):
                lines.append(f"title: {item['title']}")
            if item.get("artist"):
                lines.append(f"artist: {item['artist']}")
            if item.get("file_path"):
                lines.append(f"file_path: {item['file_path']}")
            matched_series = item.get("matched_series_tags", [])
            if matched_series:
                lines.append(f"matched_series: {', '.join(matched_series)}")
            matched_chars = item.get("matched_character_tags", [])
            if matched_chars:
                lines.append(f"matched_characters: {', '.join(matched_chars)}")
            raw_tags = item.get("raw_tags", [])
            if raw_tags:
                lines.append("raw_tags:")
                for tag in raw_tags:
                    lines.append(f"- {tag}")
            unmatched = item.get("unmatched_raw_tags", [])
            if unmatched:
                lines.append("unmatched_raw_tags:")
                for tag in unmatched:
                    lines.append(f"- {tag}")
            ignored_pop = item.get("ignored_popularity_tags", [])
            if ignored_pop:
                lines.append("ignored_popularity_tags:")
                for tag in ignored_pop:
                    lines.append(f"- {tag}")
            ignored_gen = item.get("ignored_general_tags", [])
            if ignored_gen:
                lines.append(f"ignored_general_tags: {len(ignored_gen)} tags")
            notes = item.get("suggested_debug_notes", [])
            if notes:
                lines.append("debug_notes:")
                for note in notes:
                    lines.append(f"- {note}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public: save
# ---------------------------------------------------------------------------

def save_classification_failure_report(
    report: dict,
    output_dir: str | Path,
    *,
    write_json: bool = True,
    write_text: bool = True,
) -> dict:
    """
    JSON / TXT report 파일을 저장한다.

    반환: {"json": str | None, "text": str | None}
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"classification_failures_{ts}"
    saved: dict = {"json": None, "text": None}

    if write_json:
        json_path = out / f"{stem}.json"
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        saved["json"] = str(json_path)
        logger.info("[DEV] Classification failure report (JSON): %s", json_path)

    if write_text:
        text_path = out / f"{stem}.txt"
        text_path.write_text(
            format_classification_failures_text(report),
            encoding="utf-8",
        )
        saved["text"] = str(text_path)
        logger.info("[DEV] Classification failure report (TXT): %s", text_path)

    return saved


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_tag_breakdown(raw_tags: list[str], title: str, conn) -> dict:
    """Compute tag breakdown and failure_reason_detail for a single failed item.

    Calls classify_pixiv_tags(conn=conn) to get the current classification
    capability, then separates tags into matched / ignored / unmatched.
    Falls back to simple regex-based analysis if classify fails.
    """
    popularity = [t for t in raw_tags if _POPULARITY_PATTERN.match(t)]
    general = [t for t in raw_tags if t in _GENERAL_TAGS or t in _GROUP_TAGS]

    classify_result: dict = {}
    if raw_tags:
        try:
            from core.tag_classifier import classify_pixiv_tags
            classify_result = classify_pixiv_tags(raw_tags, conn=conn)
        except Exception as exc:
            logger.debug("classify_for_breakdown failed: %s", exc)

    char_tags: list[str] = classify_result.get("character_tags", [])
    series_tags: list[str] = classify_result.get("series_tags", [])
    general_remaining: list[str] = classify_result.get("tags", [])

    inferred = [
        e["canonical"]
        for e in classify_result.get("evidence", {}).get("series", [])
        if e.get("source") == "inferred_from_character"
    ]
    direct_series = [s for s in series_tags if s not in inferred]

    # Truly unmatched: in general_remaining, not a known general/group tag, not popularity
    unmatched = [
        t for t in general_remaining
        if t not in _GENERAL_TAGS
        and t not in _GROUP_TAGS
        and not _POPULARITY_PATTERN.match(t)
    ]

    # failure_reason_detail
    if not raw_tags:
        detail = "title_only_candidate" if title.strip() else "no_raw_tags"
    elif char_tags and not direct_series:
        detail = "series_missing_but_character_matched"
    elif series_tags and not char_tags:
        detail = "series_detected_character_missing"
    elif not char_tags and not series_tags:
        if unmatched:
            detail = "character_alias_missing"
        elif popularity or general:
            detail = "general_tags_only"
        else:
            detail = "no_raw_tags"
    else:
        detail = "unknown"

    return {
        "matched_character_tags":  char_tags,
        "matched_series_tags":     direct_series,
        "inferred_series_tags":    inferred,
        "unmatched_raw_tags":      unmatched,
        "ignored_general_tags":    general,
        "ignored_popularity_tags": popularity,
        "failure_reason_detail":   detail,
    }


def _is_failure_preview(preview: dict) -> bool:
    ci = preview.get("classification_info")
    if ci and ci.get("classification_reason") in _REASON_TO_RULE:
        return True
    return any(d.get("rule_type") in _FAILURE_RULE_TYPES for d in preview.get("destinations", []))


def _detect_rule_label(preview: dict) -> str:
    ci = preview.get("classification_info")
    if ci:
        reason = ci.get("classification_reason", "")
        if reason in _REASON_TO_RULE:
            return _REASON_TO_RULE[reason]
    for d in preview.get("destinations", []):
        rt = d.get("rule_type", "")
        if rt in _FAILURE_RULE_TYPES:
            return rt
    return "unknown"


def _build_debug_notes(raw_tags: list[str]) -> list[str]:
    try:
        from core.tag_classifier import _parse_parenthetical, SERIES_ALIASES
        from core.tag_normalize import normalize_tag_key
        norm_series = {normalize_tag_key(k): k for k in SERIES_ALIASES if k}
    except Exception:
        return []

    notes: list[str] = []
    for tag in raw_tags:
        base, inner = _parse_parenthetical(tag)
        if not inner:
            continue
        if inner in SERIES_ALIASES or normalize_tag_key(inner) in norm_series:
            notes.append(f"'{tag}': possible series disambiguator (inner='{inner}')")
        else:
            notes.append(f"'{tag}': possible parenthetical variant tag (inner='{inner}')")
    return notes


def _fetch_group_info(conn: sqlite3.Connection, group_id: str) -> dict:
    try:
        row = conn.execute(
            "SELECT artwork_id, artwork_title, artist_name, tags_json, "
            "series_tags_json, character_tags_json, metadata_sync_status "
            "FROM artwork_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    return {}
