"""
DB 스키마 단위 테스트.
12개 테이블 존재, 컬럼명, 기본값 등 검증.
"""
import uuid
from datetime import datetime

import pytest

from db.database import initialize_database

EXPECTED_TABLES = {
    "artwork_groups",
    "artwork_files",
    "tags",
    "save_jobs",
    "job_pages",
    "no_metadata_queue",
    "undo_entries",
    "copy_records",
    "classify_rules",
    "thumbnail_cache",
    "tag_aliases",
    "operation_locks",
}


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = initialize_database(db_path)
    yield c
    c.close()


def _table_columns(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _column_types(conn, table: str) -> dict[str, str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"]: row["type"] for row in rows}


class TestDatabaseInit:
    def test_initialize_success(self, conn):
        assert conn is not None

    def test_all_12_tables_exist(self, conn):
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        existing = {row["name"] for row in rows}
        missing = EXPECTED_TABLES - existing
        assert not missing, f"누락된 테이블: {missing}"

    def test_wal_mode(self, conn):
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_migrates_legacy_tags_without_tag_type(self, tmp_path):
        db_path = str(tmp_path / "legacy_tags.db")
        import sqlite3
        legacy = sqlite3.connect(db_path)
        legacy.executescript(
            """
            CREATE TABLE artwork_groups (
                group_id TEXT PRIMARY KEY,
                source_site TEXT NOT NULL DEFAULT 'pixiv',
                artwork_id TEXT NOT NULL,
                downloaded_at TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE TABLE tags (
                group_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (group_id, tag)
            );
            CREATE TABLE tag_aliases (
                alias TEXT PRIMARY KEY,
                canonical TEXT NOT NULL,
                source_site TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO artwork_groups
                (group_id, source_site, artwork_id, downloaded_at, indexed_at)
                VALUES ('g1', 'pixiv', 'legacy_001', '2026-01-01', '2026-01-01');
            INSERT INTO tags (group_id, tag) VALUES ('g1', 'legacy_tag');
            INSERT INTO tag_aliases
                (alias, canonical, source_site, created_at)
                VALUES ('legacy_alias', 'Legacy Canonical', 'pixiv', '2026-01-01');
            """
        )
        legacy.close()

        migrated = initialize_database(db_path)
        try:
            tag_cols = _table_columns(migrated, "tags")
            alias_cols = _table_columns(migrated, "tag_aliases")
            assert {"group_id", "tag", "tag_type", "canonical"}.issubset(tag_cols)
            assert {"alias", "canonical", "tag_type", "parent_series", "enabled"}.issubset(alias_cols)

            tag = migrated.execute(
                "SELECT tag, tag_type FROM tags WHERE group_id = 'g1'"
            ).fetchone()
            assert tag["tag"] == "legacy_tag"
            assert tag["tag_type"] == "general"

            alias = migrated.execute(
                "SELECT canonical, tag_type, source FROM tag_aliases WHERE alias = 'legacy_alias'"
            ).fetchone()
            assert alias["canonical"] == "Legacy Canonical"
            assert alias["tag_type"] == "general"
            assert alias["source"] == "pixiv"
        finally:
            migrated.close()


class TestArtworkGroups:
    def _insert_group(self, conn) -> str:
        group_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO artwork_groups
               (group_id, source_site, artwork_id, downloaded_at, indexed_at)
               VALUES (?, 'pixiv', 'test_001', ?, ?)""",
            (group_id, now, now),
        )
        conn.commit()
        return group_id

    def test_metadata_sync_status_default_pending(self, conn):
        group_id = self._insert_group(conn)
        row = conn.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id=?",
            (group_id,),
        ).fetchone()
        assert row["metadata_sync_status"] == "pending"

    def test_status_default_inbox(self, conn):
        group_id = self._insert_group(conn)
        row = conn.execute(
            "SELECT status FROM artwork_groups WHERE group_id=?", (group_id,)
        ).fetchone()
        assert row["status"] == "inbox"

    def test_unique_constraint(self, conn):
        import sqlite3
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO artwork_groups
               (group_id, source_site, artwork_id, downloaded_at, indexed_at)
               VALUES (?, 'pixiv', 'dup_001', ?, ?)""",
            (str(uuid.uuid4()), now, now),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO artwork_groups
                   (group_id, source_site, artwork_id, downloaded_at, indexed_at)
                   VALUES (?, 'pixiv', 'dup_001', ?, ?)""",
                (str(uuid.uuid4()), now, now),
            )
            conn.commit()


class TestTagsTable:
    def test_has_group_id_not_artwork_id(self, conn):
        cols = _table_columns(conn, "tags")
        assert "group_id" in cols, "tags 테이블에 group_id 컬럼이 없음"
        assert "artwork_id" not in cols, "tags 테이블에 artwork_id 컬럼이 있으면 안 됨"

    def test_tag_type_default_general(self, conn):
        now = datetime.now().isoformat()
        group_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO artwork_groups
               (group_id, source_site, artwork_id, downloaded_at, indexed_at)
               VALUES (?, 'pixiv', 'tag_test', ?, ?)""",
            (group_id, now, now),
        )
        conn.execute(
            "INSERT INTO tags (group_id, tag) VALUES (?, ?)",
            (group_id, "テスト"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT tag_type FROM tags WHERE group_id=?", (group_id,)
        ).fetchone()
        assert row["tag_type"] == "general"


class TestThumbnailCache:
    def test_has_thumb_path_column(self, conn):
        cols = _table_columns(conn, "thumbnail_cache")
        assert "thumb_path" in cols

    def test_no_blob_column(self, conn):
        types = _column_types(conn, "thumbnail_cache")
        assert "BLOB" not in types.values(), "thumbnail_cache에 BLOB 컬럼이 있으면 안 됨"


class TestUndoEntries:
    def test_has_undo_status(self, conn):
        cols = _table_columns(conn, "undo_entries")
        assert "undo_status" in cols

    def test_undo_status_default_pending(self, conn):
        now = datetime.now().isoformat()
        entry_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO undo_entries
               (entry_id, operation_type, performed_at, undo_expires_at)
               VALUES (?, 'classify', ?, ?)""",
            (entry_id, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT undo_status FROM undo_entries WHERE entry_id=?", (entry_id,)
        ).fetchone()
        assert row["undo_status"] == "pending"


class TestOperationLocks:
    def test_columns_exist(self, conn):
        cols = _table_columns(conn, "operation_locks")
        assert {"lock_name", "locked_by", "locked_at", "expires_at"}.issubset(cols)
