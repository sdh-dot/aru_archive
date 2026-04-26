"""
일괄 분류 엔진.

역할:
  1. scope에 따라 분류 가능한 group_ids 수집
  2. 여러 group에 대한 분류 미리보기 일괄 생성
  3. batch preview를 기준으로 실제 복사 실행
     - undo_entries 1개 (classify_batch)
     - copy_records / artwork_files classified_copy는 복사본마다 생성
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.classifier import (
    CLASSIFIABLE_STATUSES,
    _cls_cfg,
    build_classify_preview,
    execute_classify_preview,
)

BATCH_CLASSIFIABLE_STATUSES = CLASSIFIABLE_STATUSES


# ---------------------------------------------------------------------------
# scope 별 group_ids 수집
# ---------------------------------------------------------------------------

def collect_classifiable_group_ids(
    conn: sqlite3.Connection,
    scope: str,
    *,
    selected_group_ids: Optional[list[str]] = None,
    current_filter_group_ids: Optional[list[str]] = None,
    classified_dir: str = "",
) -> dict:
    """
    scope에 따라 group_ids를 수집하고 분류 가능 여부를 확인한다.

    scope:
      'selected'       – selected_group_ids 기준
      'current_filter' – current_filter_group_ids 기준
      'all_classifiable' – DB 전체 분류 가능 항목

    반환:
      {
        "included_group_ids": [...],
        "excluded": [{"group_id": "...", "reason": "metadata_missing"}]
      }
    """
    if scope == "selected":
        candidate_ids = list(selected_group_ids or [])
    elif scope == "current_filter":
        candidate_ids = list(current_filter_group_ids or [])
    elif scope == "all_classifiable":
        rows = conn.execute(
            "SELECT group_id FROM artwork_groups ORDER BY indexed_at DESC"
        ).fetchall()
        candidate_ids = [r[0] for r in rows]
    else:
        candidate_ids = []

    if not candidate_ids:
        return {"included_group_ids": [], "excluded": []}

    included: list[str] = []
    excluded: list[dict] = []

    for gid in candidate_ids:
        row = conn.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        if not row:
            excluded.append({"group_id": gid, "reason": "not_found"})
            continue
        status = row[0]
        if status not in BATCH_CLASSIFIABLE_STATUSES:
            excluded.append({"group_id": gid, "reason": status})
            continue
        included.append(gid)

    return {"included_group_ids": included, "excluded": excluded}


# ---------------------------------------------------------------------------
# 일괄 미리보기
# ---------------------------------------------------------------------------

def build_classify_batch_preview(
    conn: sqlite3.Connection,
    group_ids: list[str],
    config: dict,
) -> dict:
    """
    여러 group에 대한 분류 미리보기를 생성한다. 실제 복사는 수행하지 않는다.

    config["classification"]["retag_before_batch_preview"] = True이면
    미리보기 전에 retag_groups_from_existing_tags를 실행한다.

    반환:
      {
        "folder_locale": "ko",
        "total_groups": N,
        "classifiable_groups": M,
        "excluded_groups": K,
        "estimated_copies": C,
        "estimated_bytes": B,
        "previews": [...],
        "warnings": [...],
        "series_uncategorized_count": N,
        "author_fallback_count": N,
        "candidate_count": N,
      }
    """
    from core.tag_candidate_generator import generate_classification_failure_candidates

    cfg = _cls_cfg(config)
    locale = cfg.get("folder_locale", "canonical")

    if config.get("classification", {}).get("retag_before_batch_preview", False):
        from core.tag_reclassifier import retag_groups_from_existing_tags
        retag_groups_from_existing_tags(conn, group_ids)

    previews: list[dict] = []
    excluded_count: int = 0
    warnings: list[str] = []
    fallback_canonicals: set[str] = set()
    series_uncategorized_count: int = 0
    author_fallback_count: int = 0
    candidate_count: int = 0

    for gid in group_ids:
        p = build_classify_preview(conn, gid, config)
        if p is None:
            excluded_count += 1
        else:
            previews.append(p)
            for ft in p.get("fallback_tags", []):
                if ft:
                    fallback_canonicals.add(ft)
            ci = p.get("classification_info")
            if ci:
                reason = ci.get("classification_reason", "")
                if reason == "series_detected_but_character_missing":
                    series_uncategorized_count += 1
                elif reason == "series_and_character_missing":
                    author_fallback_count += 1
                candidates = generate_classification_failure_candidates(conn, gid, ci)
                candidate_count += len(candidates)

    estimated_copies = sum(p["estimated_copies"] for p in previews)
    estimated_bytes  = sum(p["estimated_bytes"]  for p in previews)

    if excluded_count:
        warnings.append(
            f"{excluded_count}개 그룹이 분류 불가 상태로 제외되었습니다."
        )
    if fallback_canonicals:
        names = ", ".join(sorted(fallback_canonicals)[:5])
        warnings.append(
            f"{len(fallback_canonicals)}개 태그에서 '{locale}' 표시명이 없어 "
            f"canonical을 사용했습니다: {names}"
        )
    if series_uncategorized_count:
        warnings.append(
            f"{series_uncategorized_count}개 작품: 시리즈 감지됨, 캐릭터 미분류 (series_uncategorized)"
        )
    if author_fallback_count:
        warnings.append(
            f"{author_fallback_count}개 작품: 시리즈/캐릭터 모두 미분류 (author_fallback)"
        )

    return {
        "folder_locale":              locale,
        "total_groups":               len(group_ids),
        "classifiable_groups":        len(previews),
        "excluded_groups":            excluded_count,
        "estimated_copies":           estimated_copies,
        "estimated_bytes":            estimated_bytes,
        "previews":                   previews,
        "warnings":                   warnings,
        "series_uncategorized_count": series_uncategorized_count,
        "author_fallback_count":      author_fallback_count,
        "candidate_count":            candidate_count,
    }


# ---------------------------------------------------------------------------
# 일괄 실행
# ---------------------------------------------------------------------------

def execute_classify_batch(
    conn: sqlite3.Connection,
    batch_preview: dict,
    config: dict,
    progress_fn=None,
) -> dict:
    """
    batch_preview를 기준으로 실제 복사를 수행한다.

    정책:
      - 원본/managed 파일은 이동하지 않음
      - Classified 폴더에 복사만 수행
      - undo_entries는 batch 전체에 대해 1개 (operation_type='classify_batch')
      - copy_records는 각 복사본마다 생성
      - artwork_files에 classified_copy 행 추가
      - 일부 실패 시 partial
    """
    now        = datetime.now(timezone.utc).isoformat()
    undo_days  = int(config.get("undo_retention_days", 7))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=undo_days)
    ).isoformat()

    entry_id = str(uuid.uuid4())
    previews  = batch_preview.get("previews", [])
    n_groups  = len(previews)

    conn.execute(
        """INSERT INTO undo_entries
           (entry_id, operation_type, performed_at, undo_expires_at,
            undo_status, description)
           VALUES (?, 'classify_batch', ?, ?, 'pending', ?)""",
        (
            entry_id, now, expires_at,
            f"classify_batch: {n_groups}개 작품",
        ),
    )

    total_copied:  int = 0
    total_skipped: int = 0
    total_failed:  int = 0
    group_results: list[dict] = []

    for preview in previews:
        if progress_fn:
            progress_fn(len(group_results), n_groups, preview["group_id"], "running")
        try:
            result = execute_classify_preview(
                conn, preview, config,
                entry_id=entry_id,
                _commit=False,
            )
            total_copied  += result["copied"]
            total_skipped += result["skipped"]
            group_results.append({
                "group_id": preview["group_id"],
                "status":   "ok",
                "copied":   result["copied"],
                "skipped":  result["skipped"],
            })
            if progress_fn:
                progress_fn(len(group_results), n_groups, preview["group_id"], "ok")
        except Exception as exc:
            total_failed += 1
            group_results.append({
                "group_id": preview["group_id"],
                "status":   "error",
                "error":    str(exc),
            })
            if progress_fn:
                progress_fn(len(group_results), n_groups, preview["group_id"], "error")

    # undo_entries.undo_result_json에 요약 기록
    import json as _json
    result_summary = _json.dumps({
        "total_groups":  n_groups,
        "copied":        total_copied,
        "skipped":       total_skipped,
        "failed_groups": total_failed,
    }, ensure_ascii=False)

    conn.execute(
        "UPDATE undo_entries SET undo_result_json = ? WHERE entry_id = ?",
        (result_summary, entry_id),
    )

    conn.commit()

    if total_failed > 0 and total_copied == 0:
        overall_status = "failed"
    elif total_failed > 0:
        overall_status = "partial"
    else:
        overall_status = "completed"

    return {
        "success":        overall_status != "failed",
        "status":         overall_status,
        "entry_id":       entry_id,
        "total_groups":   n_groups,
        "copied":         total_copied,
        "skipped":        total_skipped,
        "failed_groups":  total_failed,
        "group_results":  group_results,
    }
