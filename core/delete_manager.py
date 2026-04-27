"""
파일 영구 삭제 관리자.

정책:
- 삭제는 휴지통 이동이 아닌 완전(영구) 삭제.
- 반드시 build_delete_preview() → execute_delete_preview(confirmed=True) 순으로 호출.
- 파일 삭제 후 artwork_files.file_status='deleted' 로 표시.
- delete_batches / delete_records 테이블에 감사 기록 남김.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def build_delete_preview(
    conn: sqlite3.Connection,
    *,
    group_ids: Optional[list[str]] = None,
    file_ids: Optional[list[str]] = None,
    reason: str = "manual_delete",
) -> dict:
    """
    삭제 대상 파일 목록과 위험도, DB/메타데이터 상태를 점검한다.
    실제 삭제는 수행하지 않는다.

    group_ids 또는 file_ids 중 하나 이상을 지정해야 한다.
    group_ids를 지정하면 해당 group의 present 파일 전체가 대상이 된다.
    """
    if not group_ids and not file_ids:
        return _empty_preview(reason)

    # --- 대상 파일 수집 ---
    rows: list[sqlite3.Row] = []

    if group_ids:
        placeholders = ",".join("?" * len(group_ids))
        rows += conn.execute(
            f"""SELECT af.file_id, af.group_id, af.file_path, af.file_role,
                       af.file_format, af.file_hash, af.file_size, af.file_status,
                       g.metadata_sync_status, g.artist_name
                FROM artwork_files af
                JOIN artwork_groups g ON g.group_id = af.group_id
                WHERE af.group_id IN ({placeholders})
                  AND af.file_status NOT IN ('deleted')""",
            group_ids,
        ).fetchall()

    if file_ids:
        placeholders = ",".join("?" * len(file_ids))
        rows += conn.execute(
            f"""SELECT af.file_id, af.group_id, af.file_path, af.file_role,
                       af.file_format, af.file_hash, af.file_size, af.file_status,
                       g.metadata_sync_status, g.artist_name
                FROM artwork_files af
                JOIN artwork_groups g ON g.group_id = af.group_id
                WHERE af.file_id IN ({placeholders})
                  AND af.file_status NOT IN ('deleted')""",
            file_ids,
        ).fetchall()

    # 중복 제거 (file_id 기준)
    seen: set[str] = set()
    unique_rows: list[dict] = []
    for r in rows:
        d = dict(r)
        if d["file_id"] not in seen:
            seen.add(d["file_id"])
            unique_rows.append(d)

    # --- 각 파일 점검 ---
    file_items: list[dict] = []
    warnings: list[str] = []

    role_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}

    for d in unique_rows:
        item = _inspect_file(conn, d, warnings)
        file_items.append(item)
        role_counts[item["file_role"]] = role_counts.get(item["file_role"], 0) + 1
        s = item["metadata_sync_status"] or "unknown"
        status_counts[s] = status_counts.get(s, 0) + 1

    # --- 삭제 후 빈 group 수 계산 ---
    groups_becoming_empty = _count_groups_becoming_empty(conn, file_items)

    preview = {
        "reason": reason,
        "total_files": len(file_items),
        "file_items": file_items,
        "role_counts": role_counts,
        "status_counts": status_counts,
        "groups_affected": len({it["group_id"] for it in file_items if it.get("group_id")}),
        "groups_becoming_empty": groups_becoming_empty,
        "warnings": warnings,
    }
    preview["risk"] = compute_delete_risk(preview)
    return preview


def execute_delete_preview(
    conn: sqlite3.Connection,
    preview: dict,
    *,
    confirmed: bool = False,
) -> dict:
    """
    delete preview 기준으로 파일을 영구 삭제한다.

    confirmed=False면 실행하지 않고 즉시 반환한다.
    파일 삭제 후 artwork_files.file_status='deleted' 로 갱신한다.
    delete_batches / delete_records 에 감사 기록을 남긴다.
    """
    if not confirmed:
        return {"status": "not_confirmed", "deleted": 0, "failed": 0, "skipped": 0}

    file_items: list[dict] = preview.get("file_items", [])
    if not file_items:
        return {"status": "empty", "deleted": 0, "failed": 0, "skipped": 0}

    batch_id = str(uuid.uuid4())
    reason = preview.get("reason", "manual_delete")
    deleted = 0
    failed = 0
    skipped = 0
    records: list[dict] = []

    for item in file_items:
        file_path = item.get("file_path", "")
        file_id = item.get("file_id", "")
        status = item.get("file_status", "")

        # missing/deleted 파일은 건너뜀
        if status in ("missing", "deleted"):
            skipped += 1
            records.append(_make_record(batch_id, item, "skipped", "file already missing/deleted"))
            continue

        result_status = "deleted"
        error_msg: Optional[str] = None

        try:
            p = Path(file_path)
            if p.exists():
                p.unlink()
            # JSON sidecar 제거 시도
            _try_remove_json_sidecar(file_path)
            deleted += 1
        except Exception as exc:
            logger.warning("파일 삭제 실패 (%s): %s", file_path, exc)
            result_status = "failed"
            error_msg = str(exc)
            failed += 1

        # DB 갱신
        if file_id:
            try:
                conn.execute(
                    "UPDATE artwork_files SET file_status='deleted' WHERE file_id=?",
                    (file_id,),
                )
            except Exception as exc:
                logger.warning("DB 갱신 실패 (file_id=%s): %s", file_id, exc)

        records.append(_make_record(batch_id, item, result_status, error_msg))

    # --- delete_batches 기록 ---
    summary = {
        "role_counts": preview.get("role_counts", {}),
        "risk": preview.get("risk", ""),
        "groups_becoming_empty": preview.get("groups_becoming_empty", 0),
    }
    conn.execute(
        """INSERT INTO delete_batches
           (delete_batch_id, operation_type, total_files,
            deleted_files, failed_files, skipped_files, created_at, summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (batch_id, reason, len(file_items),
         deleted, failed, skipped, _now(),
         json.dumps(summary, ensure_ascii=False)),
    )

    # --- delete_records 기록 ---
    for rec in records:
        conn.execute(
            """INSERT INTO delete_records
               (delete_id, delete_batch_id, group_id, file_id, original_path,
                file_role, file_hash, file_size, metadata_sync_status,
                delete_reason, deleted_at, result_status, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec["delete_id"], batch_id,
                rec.get("group_id"), rec.get("file_id"),
                rec["original_path"], rec.get("file_role"),
                rec.get("file_hash"), rec.get("file_size"),
                rec.get("metadata_sync_status"),
                reason, rec["deleted_at"],
                rec["result_status"], rec.get("error_message"),
            ),
        )

    conn.commit()
    logger.info(
        "삭제 완료 (batch=%s): deleted=%d failed=%d skipped=%d",
        batch_id, deleted, failed, skipped,
    )

    return {
        "status": "done",
        "batch_id": batch_id,
        "deleted": deleted,
        "failed": failed,
        "skipped": skipped,
    }


def compute_delete_risk(preview: dict) -> str:
    """
    삭제 위험도를 반환한다: 'low' | 'medium' | 'high'.

    High:
      - original 파일 포함
      - 삭제 후 group이 empty가 되는 항목 존재
      - metadata full/json_only의 유일한 파일 삭제

    Medium:
      - managed / sidecar 포함
      - group에 다른 original이 남아 있음

    Low:
      - classified_copy만 삭제
    """
    role_counts: dict[str, int] = preview.get("role_counts", {})
    groups_becoming_empty: int = preview.get("groups_becoming_empty", 0)
    status_counts: dict[str, int] = preview.get("status_counts", {})

    has_original = role_counts.get("original", 0) > 0
    has_managed = role_counts.get("managed", 0) > 0
    has_sidecar = role_counts.get("sidecar", 0) > 0
    has_classified = role_counts.get("classified_copy", 0) > 0

    if has_original or groups_becoming_empty > 0:
        return "high"
    if has_managed or has_sidecar:
        return "medium"
    if has_classified and not has_original and not has_managed:
        return "low"
    # full/json_only 있으면 medium 이상
    if status_counts.get("full", 0) > 0 or status_counts.get("json_only", 0) > 0:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _empty_preview(reason: str) -> dict:
    return {
        "reason": reason,
        "total_files": 0,
        "file_items": [],
        "role_counts": {},
        "status_counts": {},
        "groups_affected": 0,
        "groups_becoming_empty": 0,
        "warnings": [],
        "risk": "low",
    }


def _inspect_file(
    conn: sqlite3.Connection,
    d: dict,
    warnings: list[str],
) -> dict:
    """단일 파일에 대한 삭제 전 점검 결과를 반환한다."""
    file_path = d.get("file_path", "")
    file_id = d.get("file_id", "")
    group_id = d.get("group_id", "")
    file_role = d.get("file_role", "")
    file_status = d.get("file_status", "")
    metadata_sync_status = d.get("metadata_sync_status", "")

    exists_on_disk = Path(file_path).exists() if file_path else False
    json_path = _json_sidecar_path(file_path)
    has_json = json_path.exists() if json_path else False

    # group에 삭제 후 present 파일이 남는지 확인
    remaining = conn.execute(
        """SELECT COUNT(*) FROM artwork_files
           WHERE group_id=? AND file_id!=? AND file_status='present'""",
        (group_id, file_id),
    ).fetchone()[0] if group_id and file_id else 0

    item = {
        "file_id": file_id,
        "group_id": group_id,
        "file_path": file_path,
        "file_role": file_role,
        "file_format": d.get("file_format", ""),
        "file_hash": d.get("file_hash"),
        "file_size": d.get("file_size"),
        "file_status": file_status,
        "metadata_sync_status": metadata_sync_status,
        "artist_name": d.get("artist_name"),
        "exists_on_disk": exists_on_disk,
        "has_json_sidecar": has_json,
        "remaining_present_files": remaining,
    }

    if file_status == "missing":
        warnings.append(f"파일이 DB에 missing 상태: {file_path}")
    if not exists_on_disk and file_status == "present":
        warnings.append(f"DB는 present이지만 파일 없음: {file_path}")
    if file_role == "original":
        warnings.append(f"original 파일 포함: {os.path.basename(file_path)}")

    return item


def _count_groups_becoming_empty(
    conn: sqlite3.Connection,
    file_items: list[dict],
) -> int:
    """삭제 후 present 파일이 0개가 되는 group 수를 계산한다."""
    # file_id 집합
    deleting_ids: set[str] = {it["file_id"] for it in file_items if it.get("file_id")}
    groups_seen: set[str] = {it["group_id"] for it in file_items if it.get("group_id")}

    empty_count = 0
    for gid in groups_seen:
        present = conn.execute(
            "SELECT file_id FROM artwork_files WHERE group_id=? AND file_status='present'",
            (gid,),
        ).fetchall()
        surviving = [r["file_id"] for r in present if r["file_id"] not in deleting_ids]
        if not surviving:
            empty_count += 1
    return empty_count


def _make_record(
    batch_id: str,
    item: dict,
    result_status: str,
    error_message: Optional[str],
) -> dict:
    return {
        "delete_id": str(uuid.uuid4()),
        "group_id": item.get("group_id"),
        "file_id": item.get("file_id"),
        "original_path": item.get("file_path", ""),
        "file_role": item.get("file_role"),
        "file_hash": item.get("file_hash"),
        "file_size": item.get("file_size"),
        "metadata_sync_status": item.get("metadata_sync_status"),
        "deleted_at": _now(),
        "result_status": result_status,
        "error_message": error_message,
    }


def _json_sidecar_path(file_path: str) -> Optional[Path]:
    if not file_path:
        return None
    p = Path(file_path)
    return p.with_suffix(".json")


def _try_remove_json_sidecar(file_path: str) -> None:
    jp = _json_sidecar_path(file_path)
    if jp and jp.exists():
        try:
            jp.unlink()
            logger.debug("JSON sidecar 삭제: %s", jp)
        except Exception as exc:
            logger.debug("JSON sidecar 삭제 실패: %s", exc)
