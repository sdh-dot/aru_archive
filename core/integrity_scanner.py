"""파일 무결성 검사 — 외부에서 삭제된 파일을 DB의 missing 상태로 마킹,
그리고 다시 나타난 파일을 present 상태로 복원.

본 모듈은 실제 파일을 삭제하지 않는다. Path.exists()로 file system을
read-only 조회하고, DB의 artwork_files.file_status만 갱신한다.

흐름:
    find_missing_files(conn) → list[dict]
    mark_files_as_missing(conn, file_ids) → dict
    find_restored_files(conn) → list[dict]
    mark_files_as_present(conn, file_ids) → dict
    run_integrity_scan(conn, dry_run=...) → dict (통합)

deleted/missing 상태는 missing 검사 대상에서 제외되어 idempotent하다.
present/deleted 상태는 restored 검사 대상에서 제외되어 idempotent하다.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def find_missing_files(
    conn: sqlite3.Connection,
    *,
    roles: tuple[str, ...] = ("original", "managed"),
    group_ids: Optional[list[str]] = None,
) -> list[dict]:
    """artwork_files 중 실제 파일이 없는 row 반환.

    검사 대상:
    - file_status NOT IN ('missing', 'deleted')
    - file_role IN roles (default: original, managed)
    - group_ids가 주어지면 해당 group_id만 검사
    - file_path가 비어있거나 NULL이면 skip

    반환 dict 키: file_id, group_id, file_path, file_role, file_status
    """
    if not roles:
        return []

    role_placeholders = ",".join("?" * len(roles))
    sql = (
        "SELECT file_id, group_id, file_path, file_role, file_status "
        "FROM artwork_files "
        f"WHERE file_role IN ({role_placeholders}) "
        "  AND file_status NOT IN ('missing', 'deleted') "
        "  AND file_path IS NOT NULL AND file_path != ''"
    )
    params: list = list(roles)

    if group_ids is not None:
        if not group_ids:
            return []
        gid_placeholders = ",".join("?" * len(group_ids))
        sql += f" AND group_id IN ({gid_placeholders})"
        params.extend(group_ids)

    rows = conn.execute(sql, params).fetchall()
    missing: list[dict] = []
    for row in rows:
        # sqlite3.Row 또는 tuple 양쪽 지원
        try:
            file_path = row["file_path"]
            file_id = row["file_id"]
            group_id = row["group_id"]
            file_role = row["file_role"]
            file_status = row["file_status"]
        except (TypeError, IndexError):
            file_path = row[2]
            file_id = row[0]
            group_id = row[1]
            file_role = row[3]
            file_status = row[4]

        if not file_path:
            continue
        if not Path(file_path).exists():
            missing.append({
                "file_id": file_id,
                "group_id": group_id,
                "file_path": file_path,
                "file_role": file_role,
                "file_status": file_status,
            })
    return missing


def mark_files_as_missing(
    conn: sqlite3.Connection,
    file_ids: list[str],
    *,
    reason: str = "external_delete",
) -> dict:
    """file_status를 'missing'으로 갱신. 실제 파일은 건드리지 않음.

    이미 missing/deleted인 파일은 skip.

    Returns: {"requested": int, "updated": int, "skipped": int}
    """
    if not file_ids:
        return {"requested": 0, "updated": 0, "skipped": 0}

    updated = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    for fid in file_ids:
        cur = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id = ?",
            (fid,),
        )
        row = cur.fetchone()
        if not row:
            skipped += 1
            continue
        try:
            current_status = row["file_status"]
        except (TypeError, IndexError):
            current_status = row[0]

        if current_status in ("missing", "deleted"):
            skipped += 1
            continue

        try:
            conn.execute(
                "UPDATE artwork_files SET file_status = 'missing', last_seen_at = ? "
                "WHERE file_id = ?",
                (now, fid),
            )
        except sqlite3.OperationalError:
            # last_seen_at 컬럼이 없는 환경 방어
            conn.execute(
                "UPDATE artwork_files SET file_status = 'missing' "
                "WHERE file_id = ?",
                (fid,),
            )
        updated += 1

    conn.commit()

    if updated > 0:
        logger.info(
            "integrity_scan: marked %d files as missing (reason=%s)",
            updated,
            reason,
        )

    return {
        "requested": len(file_ids),
        "updated": updated,
        "skipped": skipped,
    }


def find_restored_files(
    conn: sqlite3.Connection,
    *,
    roles: tuple[str, ...] = ("original", "managed"),
    group_ids: Optional[list[str]] = None,
) -> list[dict]:
    """file_status='missing'인 row 중 실제 파일이 다시 존재하는 row 반환.

    검사 대상:
    - file_status = 'missing'
    - file_role IN roles (default: original, managed)
    - group_ids가 주어지면 해당 group_id만 검사
    - file_path가 비어있거나 NULL이면 skip

    same-path 기준만 사용 — moved/renamed 추적 없음.
    실제 파일을 이동/복사/수정하지 않는다.

    반환 dict 키: file_id, group_id, file_path, file_role, file_status
    """
    if not roles:
        return []

    role_placeholders = ",".join("?" * len(roles))
    sql = (
        "SELECT file_id, group_id, file_path, file_role, file_status "
        "FROM artwork_files "
        f"WHERE file_role IN ({role_placeholders}) "
        "  AND file_status = 'missing' "
        "  AND file_path IS NOT NULL AND file_path != ''"
    )
    params: list = list(roles)

    if group_ids is not None:
        if not group_ids:
            return []
        gid_placeholders = ",".join("?" * len(group_ids))
        sql += f" AND group_id IN ({gid_placeholders})"
        params.extend(group_ids)

    rows = conn.execute(sql, params).fetchall()
    restored: list[dict] = []
    for row in rows:
        # sqlite3.Row 또는 tuple 양쪽 지원
        try:
            file_path = row["file_path"]
            file_id = row["file_id"]
            group_id = row["group_id"]
            file_role = row["file_role"]
            file_status = row["file_status"]
        except (TypeError, IndexError):
            file_path = row[2]
            file_id = row[0]
            group_id = row[1]
            file_role = row[3]
            file_status = row[4]

        if not file_path:
            continue
        if Path(file_path).exists():
            restored.append({
                "file_id": file_id,
                "group_id": group_id,
                "file_path": file_path,
                "file_role": file_role,
                "file_status": file_status,
            })
    return restored


def mark_files_as_present(
    conn: sqlite3.Connection,
    file_ids: list[str],
    *,
    reason: str = "file_restored",
) -> dict:
    """file_status를 'present'로 복원. 실제 파일은 건드리지 않음.

    이미 present이거나 deleted인 파일은 skip (idempotent).

    Returns: {"requested": int, "updated": int, "skipped": int}
    """
    if not file_ids:
        return {"requested": 0, "updated": 0, "skipped": 0}

    updated = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    for fid in file_ids:
        cur = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id = ?",
            (fid,),
        )
        row = cur.fetchone()
        if not row:
            skipped += 1
            continue
        try:
            current_status = row["file_status"]
        except (TypeError, IndexError):
            current_status = row[0]

        if current_status in ("present", "deleted"):
            skipped += 1
            continue

        try:
            conn.execute(
                "UPDATE artwork_files SET file_status = 'present', last_seen_at = ? "
                "WHERE file_id = ?",
                (now, fid),
            )
        except sqlite3.OperationalError:
            # last_seen_at 컬럼이 없는 환경 방어
            conn.execute(
                "UPDATE artwork_files SET file_status = 'present' "
                "WHERE file_id = ?",
                (fid,),
            )
        updated += 1

    conn.commit()

    if updated > 0:
        logger.info(
            "integrity_scan: restored %d files to present (reason=%s)",
            updated,
            reason,
        )

    return {
        "requested": len(file_ids),
        "updated": updated,
        "skipped": skipped,
    }


def run_integrity_scan(
    conn: sqlite3.Connection,
    *,
    roles: tuple[str, ...] = ("original", "managed"),
    group_ids: Optional[list[str]] = None,
    dry_run: bool = True,
) -> dict:
    """find_missing_files / find_restored_files → (dry_run=False이면) 각 mark 함수 호출.

    Returns: {
        "missing_files": list[dict],
        "missing_count": int,
        "affected_group_count": int,
        "updated": int,             # dry_run=True이면 0 (missing 마킹 건수)
        "dry_run": bool,
        "restored_files": list[dict],   # find_restored_files() 결과
        "restored_count": int,          # len(restored_files)
        "restore_updated": int,         # dry_run=True이면 0, 아니면 mark_files_as_present() updated
    }
    """
    missing_files = find_missing_files(conn, roles=roles, group_ids=group_ids)
    affected_groups = {m["group_id"] for m in missing_files if m["group_id"]}

    updated = 0
    if not dry_run and missing_files:
        result = mark_files_as_missing(
            conn,
            [m["file_id"] for m in missing_files],
            reason="external_delete",
        )
        updated = result["updated"]

    restored_files = find_restored_files(conn, roles=roles, group_ids=group_ids)

    restore_updated = 0
    if not dry_run and restored_files:
        restore_result = mark_files_as_present(
            conn,
            [r["file_id"] for r in restored_files],
            reason="file_restored",
        )
        restore_updated = restore_result["updated"]

    return {
        "missing_files": missing_files,
        "missing_count": len(missing_files),
        "affected_group_count": len(affected_groups),
        "updated": updated,
        "dry_run": dry_run,
        "restored_files": restored_files,
        "restored_count": len(restored_files),
        "restore_updated": restore_updated,
    }
