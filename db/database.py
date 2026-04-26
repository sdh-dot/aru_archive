"""
Aru Archive SQLite 연결 및 초기화.
WAL 모드, NORMAL 동기화, FK 활성화.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


def get_connection(db_path: str) -> sqlite3.Connection:
    """
    SQLite 연결을 반환한다.
    - WAL 모드: 읽기/쓰기 동시 접근 허용
    - NORMAL 동기화: 성능과 안전성 균형
    - FK: ON (참조 무결성)
    - row_factory: sqlite3.Row (dict-like 접근)
    - timeout: 5초 (busy_timeout)
    """
    conn = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database(db_path: str, schema_path: str | None = None) -> sqlite3.Connection:
    """
    데이터베이스를 초기화하고 연결을 반환한다.
    schema_path가 None이면 같은 패키지의 schema.sql을 사용한다.
    """
    if schema_path is None:
        schema_path = str(Path(__file__).parent / "schema.sql")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    execute_script_file(conn, schema_path)
    return conn


def execute_script_file(conn: sqlite3.Connection, schema_path: str) -> None:
    """SQL 스크립트 파일을 읽어 실행한다."""
    script = Path(schema_path).read_text(encoding="utf-8")
    conn.executescript(script)
    conn.commit()


@contextmanager
def get_db(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """
    컨텍스트 매니저 방식의 DB 연결.
    with 블록 종료 시 자동으로 닫는다.
    """
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def checkpoint(conn: sqlite3.Connection) -> None:
    """WAL 체크포인트 실행. MainApp 정상 종료 시 호출한다."""
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
