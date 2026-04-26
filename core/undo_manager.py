"""
Undo 관리 모듈.

원칙:
  - Inbox 원본(original / managed / sidecar)은 절대 삭제하지 않는다.
  - Undo 대상은 file_role='classified_copy' 복사본만이다.
  - copy_records 행 자체는 삭제하지 않는다 (이력 보존).
  - 수정된 복사본은 force_modified=True 없이는 삭제하지 않는다.

undo_status 전이:
  pending → completed | partial | failed
  pending → expired  (expire_old_undo_entries)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SAFE_ROLES = frozenset({"original", "managed", "sidecar"})

# UI 표시용 상태 레이블
STATUS_LABEL: dict[str, str] = {
    "pending":   "Undo 가능",
    "completed": "Undo 완료",
    "partial":   "일부 완료",
    "failed":    "Undo 실패",
    "expired":   "Undo 만료",
}


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def list_undo_entries(
    conn: sqlite3.Connection,
    limit: int = 100,
    status: Optional[str] = None,
) -> list[dict]:
    """
    최근 undo_entries를 최신순으로 반환한다.
    각 항목에 copy_records 집계(count, total_size)를 포함한다.
    """
    where = "WHERE u.undo_status = ?" if status else ""
    params: tuple = (status, limit) if status else (limit,)
    rows = conn.execute(
        f"""
        SELECT
            u.entry_id,
            u.operation_type,
            u.performed_at,
            u.undo_expires_at,
            u.undo_status,
            u.undone_at,
            u.description,
            u.undo_result_json,
            COUNT(c.id)            AS copy_count,
            COALESCE(SUM(c.dest_file_size), 0) AS total_size
        FROM undo_entries u
        LEFT JOIN copy_records c ON c.entry_id = u.entry_id
        {where}
        GROUP BY u.entry_id
        ORDER BY u.performed_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_undo_entry_detail(conn: sqlite3.Connection, entry_id: str) -> dict:
    """
    undo_entries + copy_records를 조인해 상세 정보를 반환한다.
    """
    entry = conn.execute(
        "SELECT * FROM undo_entries WHERE entry_id = ?", (entry_id,)
    ).fetchone()
    if not entry:
        raise ValueError(f"undo_entries 없음: {entry_id}")

    records = conn.execute(
        """SELECT c.*, af.file_role, af.file_status
           FROM copy_records c
           LEFT JOIN artwork_files af ON af.file_id = c.dest_file_id
           WHERE c.entry_id = ?
           ORDER BY c.id""",
        (entry_id,),
    ).fetchall()

    return {
        **dict(entry),
        "records": [dict(r) for r in records],
    }


# ---------------------------------------------------------------------------
# 평가
# ---------------------------------------------------------------------------

def evaluate_undo_entry(conn: sqlite3.Connection, entry_id: str) -> dict:
    """
    Undo 실행 전 안전성 평가.

    각 copy_record의 상태:
      deletable   — dest_path 존재, classified_copy, 미수정
      missing     — dest_path가 이미 없음
      modified    — dest_path 존재, 크기/mtime이 복사 당시와 다름
      unsafe_role — dest_file_id가 original/managed/sidecar
      already_done / expired — undo_status에 따라
    """
    entry = conn.execute(
        "SELECT * FROM undo_entries WHERE entry_id = ?", (entry_id,)
    ).fetchone()
    if not entry:
        raise ValueError(f"undo_entries 없음: {entry_id}")

    undo_status = entry["undo_status"]

    # 이미 처리된 항목은 빠르게 반환
    if undo_status in ("completed", "partial", "failed"):
        return {
            "entry_id":             entry_id,
            "undo_status":          undo_status,
            "can_undo":             False,
            "requires_confirmation": False,
            "summary":              {"total": 0, "deletable": 0, "modified": 0,
                                     "missing": 0, "unsafe": 0},
            "records":              [],
        }
    if undo_status == "expired":
        return {
            "entry_id":             entry_id,
            "undo_status":          "expired",
            "can_undo":             False,
            "requires_confirmation": False,
            "summary":              {"total": 0, "deletable": 0, "modified": 0,
                                     "missing": 0, "unsafe": 0},
            "records":              [],
        }

    records_db = conn.execute(
        """SELECT c.id, c.dest_path, c.dest_file_size,
                  c.dest_mtime_at_copy, c.dest_hash_at_copy,
                  c.rule_id,
                  af.file_role, af.file_status
           FROM copy_records c
           LEFT JOIN artwork_files af ON af.file_id = c.dest_file_id
           WHERE c.entry_id = ?
           ORDER BY c.id""",
        (entry_id,),
    ).fetchall()

    summary = {"total": 0, "deletable": 0, "modified": 0, "missing": 0, "unsafe": 0}
    record_results: list[dict] = []

    for row in records_db:
        summary["total"] += 1
        dest_path = Path(row["dest_path"])
        file_role = row["file_role"] or ""
        rec_status: str

        # 안전하지 않은 파일 역할 — 절대 삭제 금지
        if file_role in _SAFE_ROLES:
            rec_status = "unsafe_role"
            summary["unsafe"] += 1
        elif not dest_path.exists():
            rec_status = "missing"
            summary["missing"] += 1
        else:
            rec_status = _check_modification(row, dest_path)
            if rec_status == "modified":
                summary["modified"] += 1
            else:
                rec_status = "deletable"
                summary["deletable"] += 1

        record_results.append({
            "copy_record_id": row["id"],
            "dest_path":      row["dest_path"],
            "rule_type":      row["rule_id"] or "",
            "status":         rec_status,
        })

    can_undo = summary["deletable"] > 0 or summary["missing"] > 0
    requires_confirmation = summary["modified"] > 0

    return {
        "entry_id":              entry_id,
        "undo_status":           undo_status,
        "can_undo":              can_undo,
        "requires_confirmation": requires_confirmation,
        "summary":               summary,
        "records":               record_results,
    }


def _check_modification(row: sqlite3.Row, dest_path: Path) -> str:
    """파일이 복사 당시와 다르면 'modified', 같으면 'deletable' 반환."""
    try:
        stat = dest_path.stat()
        current_size = stat.st_size
        # 크기 불일치 → 수정됨
        if row["dest_file_size"] is not None and current_size != row["dest_file_size"]:
            return "modified"
        # mtime 불일치 → 수정됨 (ISO 파싱 비교)
        if row["dest_mtime_at_copy"]:
            stored_mtime = datetime.fromisoformat(row["dest_mtime_at_copy"])
            current_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            # 1초 이상 차이가 있으면 수정으로 판정 (FAT/NTFS 정밀도 차이 허용)
            if abs((current_mtime - stored_mtime).total_seconds()) > 1.0:
                return "modified"
    except Exception:
        pass
    return "deletable"


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def execute_undo_entry(
    conn: sqlite3.Connection,
    entry_id: str,
    *,
    delete_empty_dirs: bool = True,
    force_modified: bool = False,
    classified_dir: Optional[str] = None,
) -> dict:
    """
    classified_copy 파일을 삭제하고 undo_status를 갱신한다.

    Returns:
        {
            "entry_id": ...,
            "undo_status": "completed" | "partial" | "failed",
            "deleted": [...],
            "skipped_missing": [...],
            "skipped_modified": [...],
            "failed": [...],
        }
    """
    entry = conn.execute(
        "SELECT * FROM undo_entries WHERE entry_id = ?", (entry_id,)
    ).fetchone()
    if not entry:
        raise ValueError(f"undo_entries 없음: {entry_id}")
    if entry["undo_status"] != "pending":
        raise ValueError(
            f"Undo 불가 상태: {entry['undo_status']} (pending만 실행 가능)"
        )

    evaluation = evaluate_undo_entry(conn, entry_id)

    # modified 파일이 있고 force_modified=False면 중단
    if evaluation["summary"]["modified"] > 0 and not force_modified:
        return {
            "entry_id":         entry_id,
            "undo_status":      "pending",
            "aborted":          True,
            "reason":           "modified_files",
            "modified_paths":   [
                r["dest_path"] for r in evaluation["records"]
                if r["status"] == "modified"
            ],
            "deleted":          [],
            "skipped_missing":  [],
            "skipped_modified": [],
            "failed":           [],
        }

    deleted:          list[str] = []
    skipped_missing:  list[str] = []
    skipped_modified: list[str] = []
    failed:           list[str] = []
    stop_at = Path(classified_dir) if classified_dir else None

    for rec in evaluation["records"]:
        path = rec["dest_path"]
        status = rec["status"]

        if status == "missing":
            skipped_missing.append(path)
            logger.info("Undo skip (missing): %s", path)
            continue

        if status == "unsafe_role":
            logger.warning("Undo skip (unsafe_role): %s", path)
            continue

        if status == "modified" and not force_modified:
            skipped_modified.append(path)
            continue

        # deletable or (modified + force_modified)
        try:
            dest = Path(path)
            dest.unlink(missing_ok=True)
            # artwork_files.file_status → deleted
            _mark_file_deleted(conn, path)
            deleted.append(path)
            logger.info("Undo deleted: %s", path)

            # 빈 폴더 정리
            if delete_empty_dirs and stop_at and dest.parent.exists():
                cleanup_empty_dirs(dest, stop_at)
        except Exception as exc:
            logger.error("Undo 삭제 실패: %s — %s", path, exc)
            failed.append(path)

    # undo_status 결정
    deletable_count = evaluation["summary"]["deletable"]
    missing_count   = evaluation["summary"]["missing"]
    target_count    = deletable_count + (
        evaluation["summary"]["modified"] if force_modified else 0
    )

    if failed and not deleted:
        new_status = "failed"
    elif failed or (skipped_modified and not force_modified):
        new_status = "partial"
    elif target_count == 0 and missing_count > 0:
        # 모두 missing → 사실상 완료로 간주
        new_status = "completed"
    elif not failed:
        new_status = "completed"
    else:
        new_status = "partial"

    result = {
        "entry_id":         entry_id,
        "undo_status":      new_status,
        "aborted":          False,
        "deleted":          deleted,
        "skipped_missing":  skipped_missing,
        "skipped_modified": skipped_modified,
        "failed":           failed,
    }

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE undo_entries
           SET undo_status=?, undone_at=?, undo_result_json=?
           WHERE entry_id=?""",
        (new_status, now, json.dumps(result, ensure_ascii=False), entry_id),
    )
    conn.commit()

    return result


def _mark_file_deleted(conn: sqlite3.Connection, file_path: str) -> None:
    """artwork_files의 해당 경로 행을 file_status='deleted'로 변경한다."""
    conn.execute(
        "UPDATE artwork_files SET file_status='deleted' WHERE file_path=?",
        (file_path,),
    )


# ---------------------------------------------------------------------------
# 만료 처리
# ---------------------------------------------------------------------------

def expire_old_undo_entries(
    conn: sqlite3.Connection,
    now: Optional[datetime] = None,
) -> int:
    """
    undo_expires_at이 지난 pending 항목을 expired로 변경한다.
    B-2 정책: dest_hash_at_copy / dest_mtime_at_copy를 NULL 처리.

    Returns: 만료 처리된 항목 수
    """
    if now is None:
        now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    expired_entries = conn.execute(
        "SELECT entry_id FROM undo_entries "
        "WHERE undo_status = 'pending' AND undo_expires_at <= ?",
        (now_iso,),
    ).fetchall()

    count = 0
    for (eid,) in expired_entries:
        # B-2: 민감 컬럼 NULL 처리
        conn.execute(
            "UPDATE copy_records SET dest_hash_at_copy=NULL, dest_mtime_at_copy=NULL "
            "WHERE entry_id=?",
            (eid,),
        )
        conn.execute(
            "UPDATE undo_entries SET undo_status='expired' WHERE entry_id=?",
            (eid,),
        )
        count += 1

    if count:
        conn.commit()
        logger.info("만료 처리: %d 항목", count)

    return count


# ---------------------------------------------------------------------------
# 빈 폴더 정리
# ---------------------------------------------------------------------------

def cleanup_empty_dirs(deleted_file: Path, stop_at: Path) -> int:
    """
    deleted_file의 부모 폴더를 거슬러 올라가며 빈 폴더를 삭제한다.
    stop_at 자체 및 그 상위는 삭제하지 않는다.

    Returns: 삭제된 폴더 수
    """
    removed = 0
    current = deleted_file.parent
    while True:
        try:
            current.relative_to(stop_at)
        except ValueError:
            break  # stop_at 범위 밖
        if current == stop_at:
            break
        try:
            if not any(current.iterdir()):
                current.rmdir()
                removed += 1
                current = current.parent
            else:
                break
        except Exception:
            break
    return removed
