"""
operation_locks 기반 동시 작업 제어.
SQLite operation_locks 테이블을 사용하여 작업 중복 실행을 방지한다.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Generator


class LockAcquisitionError(Exception):
    """operation_locks 획득 실패 시 발생."""
    pass


def acquire_lock(
    conn: sqlite3.Connection,
    lock_name: str,
    locked_by: str,
    timeout_sec: int,
) -> bool:
    """
    operation_locks 테이블에 잠금을 획득한다.

    이미 유효한 잠금이 존재하면 False 반환.
    만료된 잠금(expires_at < now)은 자동 해제 후 재시도.

    lock_name 패턴:
      save:{source_site}:{artwork_id}  — 120초
      classify:{group_id}              — 60초
      reindex                          — 600초
      thumbnail:{file_id}              — 30초
      undo:{entry_id}                  — 60초
      db_maintenance                   — 120초
    """
    locked_at = datetime.now().isoformat()
    expires_at = (datetime.now() + timedelta(seconds=timeout_sec)).isoformat()
    try:
        conn.execute(
            "INSERT INTO operation_locks (lock_name, locked_by, locked_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (lock_name, locked_by, locked_at, expires_at),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # 이미 잠금 존재 → 만료 여부 확인
        row = conn.execute(
            "SELECT expires_at FROM operation_locks WHERE lock_name=?",
            (lock_name,),
        ).fetchone()
        if row and row["expires_at"] < datetime.now().isoformat():
            # 만료된 잠금 강제 해제 후 재시도
            conn.execute(
                "DELETE FROM operation_locks WHERE lock_name=?", (lock_name,)
            )
            conn.commit()
            return acquire_lock(conn, lock_name, locked_by, timeout_sec)
        return False


def release_lock(conn: sqlite3.Connection, lock_name: str) -> None:
    """operation_locks에서 잠금을 해제한다."""
    conn.execute("DELETE FROM operation_locks WHERE lock_name=?", (lock_name,))
    conn.commit()


@contextmanager
def locked_operation(
    conn: sqlite3.Connection,
    lock_name: str,
    locked_by: str,
    timeout_sec: int = 30,
) -> Generator[None, None, None]:
    """
    컨텍스트 매니저: 잠금 획득 → 작업 수행 → 자동 해제.
    획득 실패 시 LockAcquisitionError 발생.

    사용 예:
        with locked_operation(conn, "save:pixiv:12345", "native_host", 120):
            # 저장 로직
    """
    if not acquire_lock(conn, lock_name, locked_by, timeout_sec):
        raise LockAcquisitionError(f"잠금 획득 실패: {lock_name}")
    try:
        yield
    finally:
        release_lock(conn, lock_name)


def cleanup_expired_locks(conn: sqlite3.Connection) -> int:
    """만료된 잠금을 모두 삭제하고 삭제 개수를 반환한다."""
    now = datetime.now().isoformat()
    cur = conn.execute(
        "DELETE FROM operation_locks WHERE expires_at < ?", (now,)
    )
    conn.commit()
    return cur.rowcount
