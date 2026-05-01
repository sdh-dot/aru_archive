"""Gallery present-only filter 회귀 테스트.

실제 SQLite로 _GALLERY_BASE / _GALLERY_WHERE / _COUNT_SQL을 실행해
present 파일이 있는 group만 표시되는지 검증한다.

DB schema는 변경하지 않는다. 테스트용 minimal schema로 필요 컬럼만
재구성한다 (artwork_groups, artwork_files, thumbnail_cache).
"""
from __future__ import annotations
import sqlite3
import pytest

from app.main_window import (
    _GALLERY_BASE, _GALLERY_WHERE, _COUNT_SQL, _PRESENT_EXISTS_FRAGMENT,
)


def _bootstrap(conn):
    conn.executescript("""
        CREATE TABLE artwork_groups (
            group_id TEXT PRIMARY KEY,
            artwork_id TEXT,
            artwork_title TEXT,
            metadata_sync_status TEXT,
            status TEXT,
            source_site TEXT,
            indexed_at TEXT
        );
        CREATE TABLE artwork_files (
            file_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            page_index INTEGER NOT NULL DEFAULT 0,
            file_role TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            file_format TEXT NOT NULL,
            file_status TEXT NOT NULL DEFAULT 'present',
            created_at TEXT
        );
        CREATE TABLE thumbnail_cache (
            file_id TEXT PRIMARY KEY,
            thumb_path TEXT
        );
    """)
    conn.commit()


def _add_group(conn, *, group_id, status="inbox", metadata_sync_status="full"):
    conn.execute(
        "INSERT INTO artwork_groups (group_id, artwork_id, artwork_title, "
        "metadata_sync_status, status, source_site, indexed_at) "
        "VALUES (?, '', ?, ?, ?, 'pixiv', '2026-01-01')",
        (group_id, group_id, metadata_sync_status, status),
    )


def _add_file(conn, *, file_id, group_id, file_status="present",
              file_role="original", file_format="jpg"):
    conn.execute(
        "INSERT INTO artwork_files (file_id, group_id, page_index, file_role, "
        "file_path, file_format, file_status, created_at) "
        "VALUES (?, ?, 0, ?, ?, ?, ?, '2026-01-01')",
        (file_id, group_id, file_role, f"/tmp/{file_id}.{file_format}",
         file_format, file_status),
    )


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _bootstrap(c)
    yield c
    c.close()


def _gallery_query(cat="all"):
    where = _GALLERY_WHERE.get(cat, "")
    return f"{_GALLERY_BASE} {where} ORDER BY g.indexed_at DESC"


class TestGalleryBaseFiltersToPresent:
    def test_group_with_present_file_is_included(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        conn.commit()
        rows = conn.execute(_gallery_query("all")).fetchall()
        assert len(rows) == 1
        assert rows[0]["group_id"] == "g1"

    def test_group_with_only_missing_files_is_excluded(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="missing")
        conn.commit()
        rows = conn.execute(_gallery_query("all")).fetchall()
        assert len(rows) == 0

    def test_group_with_only_deleted_files_is_excluded(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="deleted")
        conn.commit()
        rows = conn.execute(_gallery_query("all")).fetchall()
        assert len(rows) == 0

    def test_group_with_missing_and_deleted_only_is_excluded(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="missing")
        _add_file(conn, file_id="f2", group_id="g1", file_status="deleted")
        conn.commit()
        rows = conn.execute(_gallery_query("all")).fetchall()
        assert len(rows) == 0

    def test_group_with_present_and_missing_mix_is_included(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        _add_file(conn, file_id="f2", group_id="g1", file_status="missing")
        conn.commit()
        rows = conn.execute(_gallery_query("all")).fetchall()
        assert len(rows) == 1

    def test_group_with_only_moved_or_orphan_is_excluded(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="moved")
        _add_group(conn, group_id="g2")
        _add_file(conn, file_id="f2", group_id="g2", file_status="orphan")
        conn.commit()
        rows = conn.execute(_gallery_query("all")).fetchall()
        assert len(rows) == 0


class TestRefreshGalleryItemUsesAnd:
    def test_single_group_query_returns_present_group(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        conn.commit()
        sql = _GALLERY_BASE + " AND g.group_id = ?"
        row = conn.execute(sql, ("g1",)).fetchone()
        assert row is not None
        assert row["group_id"] == "g1"

    def test_single_group_query_returns_none_for_missing_only_group(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="missing")
        conn.commit()
        sql = _GALLERY_BASE + " AND g.group_id = ?"
        row = conn.execute(sql, ("g1",)).fetchone()
        assert row is None


class TestCountSqlFiltersToPresent:
    def test_count_all_excludes_missing_only(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        _add_group(conn, group_id="g2")
        _add_file(conn, file_id="f2", group_id="g2", file_status="missing")
        conn.commit()
        n = conn.execute(_COUNT_SQL["all"]).fetchone()[0]
        assert n == 1

    def test_count_inbox_excludes_missing_only(self, conn):
        _add_group(conn, group_id="g1", status="inbox")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        _add_group(conn, group_id="g2", status="inbox")
        _add_file(conn, file_id="f2", group_id="g2", file_status="missing")
        conn.commit()
        n = conn.execute(_COUNT_SQL["inbox"]).fetchone()[0]
        assert n == 1

    def test_count_managed_excludes_missing_only(self, conn):
        _add_group(conn, group_id="g1")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_status="present", file_role="managed")
        _add_group(conn, group_id="g2")
        _add_file(conn, file_id="f2", group_id="g2",
                  file_status="missing", file_role="managed")
        conn.commit()
        n = conn.execute(_COUNT_SQL["managed"]).fetchone()[0]
        assert n == 1

    def test_count_no_metadata_excludes_missing_only(self, conn):
        _add_group(conn, group_id="g1", metadata_sync_status="metadata_missing")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        _add_group(conn, group_id="g2", metadata_sync_status="metadata_missing")
        _add_file(conn, file_id="f2", group_id="g2", file_status="missing")
        conn.commit()
        n = conn.execute(_COUNT_SQL["no_metadata"]).fetchone()[0]
        assert n == 1

    def test_count_warning_excludes_missing_only(self, conn):
        _add_group(conn, group_id="g1", metadata_sync_status="json_only")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        _add_group(conn, group_id="g2", metadata_sync_status="xmp_write_failed")
        _add_file(conn, file_id="f2", group_id="g2", file_status="missing")
        conn.commit()
        n = conn.execute(_COUNT_SQL["warning"]).fetchone()[0]
        assert n == 1

    def test_count_failed_excludes_missing_only(self, conn):
        _add_group(conn, group_id="g1", metadata_sync_status="file_write_failed")
        _add_file(conn, file_id="f1", group_id="g1", file_status="present")
        _add_group(conn, group_id="g2", metadata_sync_status="convert_failed")
        _add_file(conn, file_id="f2", group_id="g2", file_status="missing")
        conn.commit()
        n = conn.execute(_COUNT_SQL["failed"]).fetchone()[0]
        assert n == 1


class TestPresentFragmentReusable:
    def test_fragment_contains_file_status_present(self):
        assert "file_status = 'present'" in _PRESENT_EXISTS_FRAGMENT
        assert "EXISTS" in _PRESENT_EXISTS_FRAGMENT
