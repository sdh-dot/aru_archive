"""
워크플로우 상태 요약 서비스.

GUI 없이 순수 DB 조회만 수행한다.
WorkflowWizardView의 각 단계에서 현재 상태를 집계하는 데 사용한다.
"""
from __future__ import annotations

import sqlite3


def build_workflow_file_status_summary(conn: sqlite3.Connection) -> dict:
    """
    파일/그룹 상태 전체 집계를 반환한다.

    반환 예:
    {
        "total_groups": 300,
        "metadata_status_counts": {
            "metadata_missing": 120,
            "json_only": 150,
            "full": 20,
            "xmp_write_failed": 10
        },
        "extension_counts": {"jpg": 120, "png": 15, ...},
        "pixiv_id_extractable": 95,
        "pixiv_id_missing": 25,
        "xmp_capable": 240,
        "classifiable": 180,
        "excluded": 120,
        "inbox_count": 200,
        "classified_count": 100,
    }
    """
    # metadata_sync_status 별 group 수
    status_counts: dict[str, int] = {}
    for row in conn.execute(
        "SELECT metadata_sync_status, COUNT(*) AS cnt "
        "FROM artwork_groups GROUP BY metadata_sync_status"
    ).fetchall():
        status_counts[row["metadata_sync_status"]] = row["cnt"]

    total_groups: int = sum(status_counts.values())

    # 파일 포맷별 수 (artwork_files)
    ext_counts: dict[str, int] = {}
    for row in conn.execute(
        "SELECT file_format, COUNT(*) AS cnt FROM artwork_files GROUP BY file_format"
    ).fetchall():
        ext_counts[row["file_format"]] = row["cnt"]

    # Pixiv ID 추출 가능 여부
    row = conn.execute(
        "SELECT COUNT(*) FROM artwork_groups "
        "WHERE artwork_id IS NOT NULL AND artwork_id != ''"
    ).fetchone()
    pixiv_extractable: int = row[0] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) FROM artwork_groups "
        "WHERE artwork_id IS NULL OR artwork_id = ''"
    ).fetchone()
    pixiv_missing: int = row[0] if row else 0

    # 분류 가능 (full | json_only | xmp_write_failed)
    row = conn.execute(
        "SELECT COUNT(*) FROM artwork_groups "
        "WHERE metadata_sync_status IN ('full','json_only','xmp_write_failed')"
    ).fetchone()
    classifiable: int = row[0] if row else 0

    excluded: int = total_groups - classifiable

    # XMP 기록 가능 (AruArchive JSON이 있는 상태)
    row = conn.execute(
        "SELECT COUNT(*) FROM artwork_groups "
        "WHERE metadata_sync_status IN ('full','json_only','xmp_write_failed')"
    ).fetchone()
    xmp_capable: int = row[0] if row else 0

    # status별 그룹 수
    row = conn.execute(
        "SELECT COUNT(*) FROM artwork_groups WHERE status = 'inbox'"
    ).fetchone()
    inbox_count: int = row[0] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) FROM artwork_groups WHERE status = 'classified'"
    ).fetchone()
    classified_count: int = row[0] if row else 0

    return {
        "total_groups":          total_groups,
        "metadata_status_counts": status_counts,
        "extension_counts":      ext_counts,
        "pixiv_id_extractable":  pixiv_extractable,
        "pixiv_id_missing":      pixiv_missing,
        "xmp_capable":           xmp_capable,
        "classifiable":          classifiable,
        "excluded":              excluded,
        "inbox_count":           inbox_count,
        "classified_count":      classified_count,
    }


def build_dictionary_status_summary(conn: sqlite3.Connection) -> dict:
    """
    사전(aliases / localizations / candidates / external entries) 상태 집계.

    반환 예:
    {
        "tag_aliases_count": 120,
        "tag_localizations_count": 80,
        "pending_candidates": 15,
        "staged_external_entries": 30,
        "accepted_external_entries": 60,
        "classification_failure_candidates": 5,
        "series_aliases_count": 10,
        "character_aliases_count": 110,
    }
    """
    def _count(sql: str, params: tuple = ()) -> int:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else 0

    tag_aliases     = _count("SELECT COUNT(*) FROM tag_aliases WHERE enabled=1")
    series_aliases  = _count(
        "SELECT COUNT(*) FROM tag_aliases WHERE enabled=1 AND tag_type='series'"
    )
    char_aliases    = _count(
        "SELECT COUNT(*) FROM tag_aliases WHERE enabled=1 AND tag_type='character'"
    )
    tag_locs        = _count("SELECT COUNT(*) FROM tag_localizations WHERE enabled=1")
    pending_cands   = _count(
        "SELECT COUNT(*) FROM tag_candidates WHERE status='pending'"
    )
    staged_ext      = _count(
        "SELECT COUNT(*) FROM external_dictionary_entries WHERE status='staged'"
    )
    accepted_ext    = _count(
        "SELECT COUNT(*) FROM external_dictionary_entries WHERE status='accepted'"
    )
    cf_cands        = _count(
        "SELECT COUNT(*) FROM tag_candidates "
        "WHERE status='pending' AND source='classification_failure'"
    )

    return {
        "tag_aliases_count":                 tag_aliases,
        "series_aliases_count":              series_aliases,
        "character_aliases_count":           char_aliases,
        "tag_localizations_count":           tag_locs,
        "pending_candidates":                pending_cands,
        "staged_external_entries":           staged_ext,
        "accepted_external_entries":         accepted_ext,
        "classification_failure_candidates": cf_cands,
    }


def classify_workflow_warnings(
    file_summary: dict,
    dict_summary: dict,
) -> list[dict]:
    """
    file_summary + dict_summary를 기반으로 UI 표시용 경고 목록을 생성한다.

    반환: [{"level": "info"|"warning"|"danger", "code": str, "message": str}]
    """
    warnings: list[dict] = []

    missing = file_summary.get("metadata_status_counts", {}).get("metadata_missing", 0)
    if missing > 0:
        warnings.append({
            "level":   "warning",
            "code":    "metadata_missing",
            "message": f"메타데이터 없는 항목 {missing}개 — 보강이 필요합니다.",
        })

    pending = dict_summary.get("pending_candidates", 0)
    if pending > 0:
        warnings.append({
            "level":   "info",
            "code":    "pending_candidates",
            "message": f"검토 대기 태그 후보 {pending}개 — [후보 태그]에서 승인/거부하세요.",
        })

    staged = dict_summary.get("staged_external_entries", 0)
    if staged > 0:
        warnings.append({
            "level":   "info",
            "code":    "staged_external_entries",
            "message": f"외부 사전 staged 항목 {staged}개 — [웹 사전]에서 승인하세요.",
        })

    classifiable = file_summary.get("classifiable", 0)
    total        = file_summary.get("total_groups", 0)
    if total > 0 and classifiable == 0:
        warnings.append({
            "level":   "danger",
            "code":    "no_classifiable",
            "message": "분류 가능한 항목이 없습니다. 메타데이터 보강을 먼저 실행하세요.",
        })

    return warnings


def compute_preview_risk_level(batch_summary: dict) -> str:
    """
    배치 분류 미리보기 요약에서 위험도를 계산한다.

    반환: "low" | "medium" | "high"
    """
    total       = batch_summary.get("total_groups", 0)
    failures    = batch_summary.get("excluded_count", 0)
    fallbacks   = batch_summary.get("author_fallback_count", 0)
    conflicts   = batch_summary.get("conflict_count", 0)

    if total == 0:
        return "low"

    fallback_ratio  = fallbacks / total
    conflict_ratio  = conflicts / total

    if failures > total * 0.3 or conflict_ratio > 0.2:
        return "high"
    if fallback_ratio > 0.2 or conflict_ratio > 0.05 or total > 500:
        return "medium"
    return "low"
