"""
Aru Archive SQLite 연결 및 초기화.
WAL 모드, NORMAL 동기화, FK 활성화.
"""
from __future__ import annotations

import shutil
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
    _pre_migrate_schema(conn)
    execute_script_file(conn, schema_path)
    _migrate_schema(conn)
    return conn


def backup_database(src_path: str, backup_path: str) -> bool:
    """DB 파일을 backup_path에 복사한다.

    - backup_path가 이미 존재하면 덮어쓰지 않고 False 반환.
    - src_path가 존재하지 않으면 False 반환.
    - IO 오류 시 False 반환.
    - 성공 시 True 반환.

    원본 DB와 연관 WAL/SHM 파일은 복사하지 않는다.
    호출 전 DB 연결을 닫거나 WAL 체크포인트를 완료하는 것을 권장한다.
    """
    src = Path(src_path)
    dst = Path(backup_path)
    if dst.exists():
        return False
    if not src.exists():
        return False
    try:
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def _table_columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _pre_migrate_schema(conn: sqlite3.Connection) -> None:
    """
    CREATE TABLE IF NOT EXISTS 실행 전에 필요한 호환 마이그레이션.

    오래된 DB에 최신 schema.sql을 바로 executescript()하면, 기존 테이블은
    생성되지 않은 채 최신 인덱스만 생성되며 새 컬럼(tag_type 등)을 찾지 못해
    초기화가 중단될 수 있다.
    """
    _migrate_artwork_groups(conn)
    _migrate_tags(conn)
    _migrate_tag_aliases(conn)
    _ensure_startup_query_indexes(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """기존 DB 스키마를 최신 버전으로 마이그레이션한다."""
    _migrate_artwork_groups(conn)
    _migrate_tags(conn)
    _migrate_tag_aliases(conn)
    _migrate_undo_entries(conn)
    _migrate_tag_localizations(conn)
    _migrate_external_dictionary_entries(conn)
    _migrate_delete_batches(conn)
    _migrate_delete_records(conn)
    _migrate_classification_overrides(conn)
    _ensure_startup_query_indexes(conn)


def _ensure_startup_query_indexes(conn: sqlite3.Connection) -> None:
    """Create composite indexes used by MainWindow startup queries."""
    if _table_exists(conn, "artwork_groups"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artwork_groups_indexed_at "
            "ON artwork_groups(indexed_at DESC)"
        )
    if _table_exists(conn, "artwork_files"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artwork_files_group_status "
            "ON artwork_files(group_id, file_status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artwork_files_group_role_page "
            "ON artwork_files(group_id, file_role, page_index)"
        )
    conn.commit()


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    cols: set[str],
    column: str,
    definition: str,
) -> None:
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        cols.add(column)


def _migrate_artwork_groups(conn: sqlite3.Connection) -> None:
    """기존 artwork_groups에 최신 schema.sql이 인덱싱하는 컬럼을 보강한다."""
    if not _table_exists(conn, "artwork_groups"):
        return

    cols = {row["name"] for row in _table_columns(conn, "artwork_groups")}
    _add_column_if_missing(conn, "artwork_groups", cols, "source_site", "TEXT NOT NULL DEFAULT 'pixiv'")
    _add_column_if_missing(conn, "artwork_groups", cols, "artwork_id", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "artwork_groups", cols, "artwork_url", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "artwork_title", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "artist_id", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "artist_name", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "artist_url", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "artwork_kind", "TEXT NOT NULL DEFAULT 'single_image'")
    _add_column_if_missing(conn, "artwork_groups", cols, "total_pages", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "artwork_groups", cols, "cover_file_id", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "tags_json", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "character_tags_json", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "series_tags_json", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "downloaded_at", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "artwork_groups", cols, "indexed_at", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "artwork_groups", cols, "updated_at", "TEXT")
    _add_column_if_missing(conn, "artwork_groups", cols, "status", "TEXT NOT NULL DEFAULT 'inbox'")
    _add_column_if_missing(conn, "artwork_groups", cols, "metadata_sync_status", "TEXT NOT NULL DEFAULT 'pending'")
    _add_column_if_missing(conn, "artwork_groups", cols, "schema_version", "TEXT NOT NULL DEFAULT '1.0'")
    conn.commit()


def _migrate_tags(conn: sqlite3.Connection) -> None:
    """기존 tags 테이블을 group_id/tag/tag_type 복합 PK 구조로 맞춘다."""
    if not _table_exists(conn, "tags"):
        return

    info = _table_columns(conn, "tags")
    cols = {row["name"] for row in info}
    pk_cols = [row["name"] for row in sorted(info, key=lambda r: r["pk"]) if row["pk"]]
    if {"group_id", "tag", "tag_type", "canonical"}.issubset(cols) and pk_cols == [
        "group_id",
        "tag",
        "tag_type",
    ]:
        return

    group_expr = "group_id" if "group_id" in cols else "artwork_id"
    tag_type_expr = "tag_type" if "tag_type" in cols else "'general'"
    canonical_expr = "canonical" if "canonical" in cols else "NULL"

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS tags__migration")
        conn.execute(
            """CREATE TABLE tags__migration (
                group_id  TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
                tag       TEXT NOT NULL,
                tag_type  TEXT NOT NULL DEFAULT 'general',
                canonical TEXT,
                PRIMARY KEY (group_id, tag, tag_type)
            )"""
        )
        conn.execute(
            f"""INSERT OR IGNORE INTO tags__migration
                (group_id, tag, tag_type, canonical)
                SELECT {group_expr}, tag, COALESCE({tag_type_expr}, 'general'), {canonical_expr}
                FROM tags
                WHERE {group_expr} IS NOT NULL AND tag IS NOT NULL"""
        )
        conn.execute("DROP TABLE tags")
        conn.execute("ALTER TABLE tags__migration RENAME TO tags")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_undo_entries(conn: sqlite3.Connection) -> None:
    """undo_entries에 undo_result_json 컬럼이 없으면 추가한다."""
    try:
        cols = {row["name"] for row in _table_columns(conn, "undo_entries")}
    except Exception:
        return
    if "undo_result_json" not in cols:
        conn.execute("ALTER TABLE undo_entries ADD COLUMN undo_result_json TEXT")
        conn.commit()


def _migrate_tag_aliases(conn: sqlite3.Connection) -> None:
    """기존 DB의 tag_aliases 스키마를 복합 PK 버전으로 마이그레이션한다."""
    if not _table_exists(conn, "tag_aliases"):
        return

    info = _table_columns(conn, "tag_aliases")
    cols = {row["name"] for row in info}
    pk_cols = [row["name"] for row in sorted(info, key=lambda r: r["pk"]) if row["pk"]]
    if {"tag_type", "parent_series", "enabled"}.issubset(cols) and pk_cols == [
        "alias",
        "tag_type",
        "parent_series",
    ]:
        # 복합 PK 는 이미 적용된 상태 — kind 컬럼만 보강 (PR #121, NPC/group 구분).
        # tag_aliases 의 모든 row 정책에 영향을 주지 않는 단순 부가 컬럼이며
        # 분류 알고리즘은 kind 를 읽지 않는다.
        _add_column_if_missing(
            conn, "tag_aliases", cols, "kind",
            "TEXT NOT NULL DEFAULT ''",
        )
        conn.commit()
        return

    tag_type_expr = "tag_type" if "tag_type" in cols else "'general'"
    parent_expr = "parent_series" if "parent_series" in cols else "''"
    media_expr = "media_type" if "media_type" in cols else "NULL"
    kind_expr = "kind" if "kind" in cols else "''"
    source_expr = "source" if "source" in cols else (
        "source_site" if "source_site" in cols else "NULL"
    )
    confidence_expr = "confidence_score" if "confidence_score" in cols else "NULL"
    enabled_expr = "enabled" if "enabled" in cols else "1"
    created_by_expr = "created_by" if "created_by" in cols else "NULL"
    created_at_expr = "created_at" if "created_at" in cols else "datetime('now')"
    updated_at_expr = "updated_at" if "updated_at" in cols else "NULL"

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS tag_aliases__migration")
        conn.execute(
            """CREATE TABLE tag_aliases__migration (
                alias            TEXT NOT NULL,
                canonical        TEXT NOT NULL,
                tag_type         TEXT NOT NULL DEFAULT 'general',
                parent_series    TEXT NOT NULL DEFAULT '',
                media_type       TEXT,
                kind             TEXT NOT NULL DEFAULT '',
                source           TEXT,
                confidence_score REAL,
                enabled          INTEGER NOT NULL DEFAULT 1,
                created_by       TEXT,
                created_at       TEXT NOT NULL,
                updated_at       TEXT,
                PRIMARY KEY (alias, tag_type, parent_series)
            )"""
        )
        conn.execute(
            f"""INSERT OR IGNORE INTO tag_aliases__migration
                (alias, canonical, tag_type, parent_series, media_type, kind,
                 source, confidence_score, enabled, created_by, created_at,
                 updated_at)
                SELECT alias, canonical, COALESCE({tag_type_expr}, 'general'),
                       COALESCE({parent_expr}, ''), {media_expr},
                       COALESCE({kind_expr}, ''), {source_expr},
                       {confidence_expr}, COALESCE({enabled_expr}, 1),
                       {created_by_expr}, COALESCE({created_at_expr}, datetime('now')),
                       {updated_at_expr}
                FROM tag_aliases
                WHERE alias IS NOT NULL AND canonical IS NOT NULL"""
        )
        conn.execute("DROP TABLE tag_aliases")
        conn.execute("ALTER TABLE tag_aliases__migration RENAME TO tag_aliases")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_tag_localizations(conn: sqlite3.Connection) -> None:
    """tag_localizations 테이블이 없으면 생성한다 (기존 DB 호환)."""
    if _table_exists(conn, "tag_localizations"):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tag_localizations (
            localization_id TEXT PRIMARY KEY,
            canonical       TEXT NOT NULL,
            tag_type        TEXT NOT NULL,
            parent_series   TEXT NOT NULL DEFAULT '',
            locale          TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            sort_name       TEXT,
            source          TEXT,
            enabled         INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT,
            UNIQUE(canonical, tag_type, parent_series, locale)
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_local_canonical "
        "ON tag_localizations(canonical, tag_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_local_locale "
        "ON tag_localizations(locale, enabled)"
    )
    conn.commit()


def _migrate_external_dictionary_entries(conn: sqlite3.Connection) -> None:
    """external_dictionary_entries 테이블이 없으면 생성한다 (기존 DB 호환)."""
    if _table_exists(conn, "external_dictionary_entries"):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS external_dictionary_entries (
            entry_id         TEXT PRIMARY KEY,
            source           TEXT NOT NULL,
            source_version   TEXT,
            source_url       TEXT,
            danbooru_tag     TEXT,
            danbooru_category TEXT,
            canonical        TEXT NOT NULL,
            tag_type         TEXT NOT NULL,
            parent_series    TEXT NOT NULL DEFAULT '',
            alias            TEXT,
            locale           TEXT,
            display_name     TEXT,
            confidence_score REAL NOT NULL DEFAULT 0,
            evidence_json    TEXT,
            status           TEXT NOT NULL DEFAULT 'staged',
            imported_at      TEXT NOT NULL,
            updated_at       TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ext_dict_status ON "
        "external_dictionary_entries(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ext_dict_source ON "
        "external_dictionary_entries(source)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ext_dict_canonical ON "
        "external_dictionary_entries(canonical, tag_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ext_dict_alias ON "
        "external_dictionary_entries(alias)"
    )
    conn.commit()


def _migrate_delete_batches(conn: sqlite3.Connection) -> None:
    """delete_batches 테이블이 없으면 생성한다."""
    if _table_exists(conn, "delete_batches"):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS delete_batches (
            delete_batch_id TEXT PRIMARY KEY,
            operation_type  TEXT NOT NULL,
            total_files     INTEGER NOT NULL DEFAULT 0,
            deleted_files   INTEGER NOT NULL DEFAULT 0,
            failed_files    INTEGER NOT NULL DEFAULT 0,
            skipped_files   INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            summary_json    TEXT
        )"""
    )
    conn.commit()


def _migrate_delete_records(conn: sqlite3.Connection) -> None:
    """delete_records 테이블이 없으면 생성한다."""
    if _table_exists(conn, "delete_records"):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS delete_records (
            delete_id         TEXT PRIMARY KEY,
            delete_batch_id   TEXT NOT NULL,
            group_id          TEXT,
            file_id           TEXT,
            original_path     TEXT NOT NULL,
            file_role         TEXT,
            file_hash         TEXT,
            file_size         INTEGER,
            metadata_sync_status TEXT,
            delete_reason     TEXT,
            deleted_at        TEXT NOT NULL,
            result_status     TEXT NOT NULL,
            error_message     TEXT,
            FOREIGN KEY(delete_batch_id) REFERENCES delete_batches(delete_batch_id)
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_delete_records_batch "
        "ON delete_records(delete_batch_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_delete_records_file "
        "ON delete_records(file_id)"
    )
    conn.commit()


def _migrate_classification_overrides(conn: sqlite3.Connection) -> None:
    """classification_overrides 테이블이 없으면 생성한다."""
    if _table_exists(conn, "classification_overrides"):
        return
    conn.execute(
        """CREATE TABLE IF NOT EXISTS classification_overrides (
            override_id         TEXT PRIMARY KEY,
            group_id            TEXT NOT NULL,
            series_canonical    TEXT,
            character_canonical TEXT,
            folder_locale       TEXT,
            reason              TEXT,
            source              TEXT NOT NULL DEFAULT 'manual',
            enabled             INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_classification_overrides_group "
        "ON classification_overrides(group_id, enabled)"
    )
    conn.commit()


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
