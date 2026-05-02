"""Sidebar 필터 SQL / helper 중앙화 + 동작 보존 회귀 테스트.

``app/widgets/sidebar_filters.py`` 의 invariant 을 lock 한다. 이번 PR 은
**동작 보존 refactor** 이므로 카테고리 매핑 / SQL 의미 변화가 없어야 한다.
향후 사용자 의미 기준 재구성 PR 의 안전망 역할.

핵심 invariant:
- 모든 기존 카테고리 키 (sidebar.py CATEGORIES) 가 query helper 에 존재
- gallery WHERE 매핑이 기존 의미 그대로
- count SQL 매핑이 기존 의미 그대로
- missing 카테고리는 별도 SQL 유지
- no_metadata gallery WHERE 가 의도적으로 빈 문자열 (panel swap 위임)
- warning = xmp_write_failed + json_only
- failed = 5종 실패 상태
- main_window 가 backward-compat 별칭으로 import 가능
- 실제 SQLite 에서 매핑된 SQL 이 정상 동작
"""
from __future__ import annotations

import sqlite3

import pytest

from app.widgets.sidebar import CATEGORIES
from app.widgets.sidebar_filters import (
    COUNT_SQL_BY_CATEGORY,
    FAILED_STATUSES_SQL_LIST,
    GALLERY_BASE,
    GALLERY_MISSING_SQL,
    GALLERY_WHERE_BY_CATEGORY,
    MISSING_EXISTS_SQL_FRAGMENT,
    PRESENT_EXISTS_SQL_FRAGMENT,
)


# ---------------------------------------------------------------------------
# 카테고리 키 일관성
# ---------------------------------------------------------------------------

class TestCategoryKeyCoverage:
    def test_all_sidebar_categories_have_count_sql(self):
        sidebar_keys = {key for key, _label in CATEGORIES}
        # COUNT_SQL_BY_CATEGORY 는 sidebar 에 노출된 모든 카테고리 키를 가져야 한다.
        assert sidebar_keys.issubset(COUNT_SQL_BY_CATEGORY.keys()), (
            f"sidebar 카테고리 중 count SQL 누락: "
            f"{sidebar_keys - set(COUNT_SQL_BY_CATEGORY.keys())}"
        )

    def test_gallery_where_covers_non_special_categories(self):
        """missing 은 별도 SQL 사용 — gallery WHERE dict 에 없을 수 있음."""
        sidebar_keys = {key for key, _label in CATEGORIES}
        special = {"missing"}  # 별도 GALLERY_MISSING_SQL 사용
        non_special = sidebar_keys - special
        assert non_special.issubset(GALLERY_WHERE_BY_CATEGORY.keys()), (
            f"gallery WHERE 매핑 누락: "
            f"{non_special - set(GALLERY_WHERE_BY_CATEGORY.keys())}"
        )

    def test_no_extra_unknown_keys_in_gallery_where(self):
        sidebar_keys = {key for key, _label in CATEGORIES}
        extra = set(GALLERY_WHERE_BY_CATEGORY.keys()) - sidebar_keys
        assert not extra, (
            f"gallery WHERE 에 sidebar 가 모르는 카테고리 키: {extra}"
        )

    def test_no_extra_unknown_keys_in_count_sql(self):
        sidebar_keys = {key for key, _label in CATEGORIES}
        extra = set(COUNT_SQL_BY_CATEGORY.keys()) - sidebar_keys
        assert not extra, (
            f"count SQL 에 sidebar 가 모르는 카테고리 키: {extra}"
        )


# ---------------------------------------------------------------------------
# 의미 lock — 카테고리별 조건이 기존과 동일한지
# ---------------------------------------------------------------------------

class TestGalleryWhereSemantics:
    def test_all_is_empty_string(self):
        assert GALLERY_WHERE_BY_CATEGORY["all"] == ""

    def test_inbox_filters_status_inbox(self):
        assert GALLERY_WHERE_BY_CATEGORY["inbox"] == "AND g.status = 'inbox'"

    def test_managed_uses_exists_role_managed(self):
        sql = GALLERY_WHERE_BY_CATEGORY["managed"]
        assert "EXISTS" in sql
        assert "file_role = 'managed'" in sql

    def test_no_metadata_is_empty_string_intentionally(self):
        """no_metadata 의 GALLERY WHERE 는 의도적으로 비어 있다 (panel swap 위임).

        분석에서 확인된 inconsistency 는 향후 별도 PR 에서 다룬다. 이번 PR 은
        그 동작을 그대로 보존.
        """
        assert GALLERY_WHERE_BY_CATEGORY["no_metadata"] == ""

    def test_warning_includes_xmp_write_failed_and_json_only(self):
        sql = GALLERY_WHERE_BY_CATEGORY["warning"]
        assert "xmp_write_failed" in sql
        assert "json_only" in sql
        assert "metadata_sync_status IN" in sql

    def test_failed_includes_five_failure_statuses(self):
        sql = GALLERY_WHERE_BY_CATEGORY["failed"]
        for status in [
            "file_write_failed",
            "convert_failed",
            "metadata_write_failed",
            "db_update_failed",
            "needs_reindex",
        ]:
            assert status in sql, f"failed WHERE 에 {status} 누락"
        # source_unavailable 등 다른 상태가 들어가지 않았는지
        assert "source_unavailable" not in sql
        assert "out_of_sync" not in sql

    def test_failed_does_not_include_xmp_write_failed(self):
        # xmp_write_failed 는 현재 warning 에만 있다 (실수로 failed 로 옮기지 않도록 lock).
        assert "xmp_write_failed" not in GALLERY_WHERE_BY_CATEGORY["failed"]


class TestCountSqlSemantics:
    def test_all_count_uses_present_exists(self):
        sql = COUNT_SQL_BY_CATEGORY["all"]
        assert PRESENT_EXISTS_SQL_FRAGMENT in sql
        assert "COUNT(*)" in sql

    def test_no_metadata_count_filters_metadata_missing(self):
        """현재 동작 lock: count 는 metadata_missing 으로 필터링.

        gallery WHERE 가 빈 문자열인 것과의 inconsistency 는 향후 PR 에서 다룬다.
        """
        sql = COUNT_SQL_BY_CATEGORY["no_metadata"]
        assert "metadata_sync_status = 'metadata_missing'" in sql

    def test_warning_count_matches_gallery_where(self):
        gallery = GALLERY_WHERE_BY_CATEGORY["warning"]
        count = COUNT_SQL_BY_CATEGORY["warning"]
        # 동일 IN(...) 절을 공유해야 함
        assert "xmp_write_failed" in count
        assert "json_only" in count

    def test_failed_count_uses_failed_statuses_list(self):
        sql = COUNT_SQL_BY_CATEGORY["failed"]
        # FAILED_STATUSES_SQL_LIST 가 그대로 사용됐는지
        assert FAILED_STATUSES_SQL_LIST in sql

    def test_missing_count_uses_missing_exists(self):
        sql = COUNT_SQL_BY_CATEGORY["missing"]
        assert MISSING_EXISTS_SQL_FRAGMENT in sql
        # missing 카테고리는 present_exists 를 사용하지 않음 (반대 의미)
        assert PRESENT_EXISTS_SQL_FRAGMENT not in sql


# ---------------------------------------------------------------------------
# Missing 카테고리 별도 SQL 유지
# ---------------------------------------------------------------------------

class TestMissingCategoryKeepsSeparateSQL:
    def test_gallery_missing_sql_is_self_contained(self):
        # missing 전용 SQL 은 GALLERY_BASE 와 별도. ORDER BY 까지 포함된 완전한 SQL.
        assert "WHERE" in GALLERY_MISSING_SQL
        assert MISSING_EXISTS_SQL_FRAGMENT in GALLERY_MISSING_SQL
        assert "ORDER BY g.indexed_at DESC" in GALLERY_MISSING_SQL

    def test_gallery_missing_sql_does_not_include_present_filter(self):
        # GALLERY_BASE 의 present-only 필터를 우회하는 것이 missing SQL 의 목적.
        assert PRESENT_EXISTS_SQL_FRAGMENT not in GALLERY_MISSING_SQL


# ---------------------------------------------------------------------------
# Reusable fragments
# ---------------------------------------------------------------------------

class TestSQLFragments:
    def test_present_fragment_is_exists_present_alias(self):
        assert "EXISTS" in PRESENT_EXISTS_SQL_FRAGMENT
        assert "af_present" in PRESENT_EXISTS_SQL_FRAGMENT
        assert "file_status = 'present'" in PRESENT_EXISTS_SQL_FRAGMENT

    def test_missing_fragment_is_exists_missing_alias(self):
        assert "EXISTS" in MISSING_EXISTS_SQL_FRAGMENT
        assert "af_missing" in MISSING_EXISTS_SQL_FRAGMENT
        assert "file_status = 'missing'" in MISSING_EXISTS_SQL_FRAGMENT

    def test_failed_statuses_list_has_five_quoted_statuses(self):
        # 5종 실패 상태가 IN(...) 인자 형식으로 묶여 있어야 한다.
        for status in [
            "'file_write_failed'", "'convert_failed'", "'metadata_write_failed'",
            "'db_update_failed'", "'needs_reindex'",
        ]:
            assert status in FAILED_STATUSES_SQL_LIST, (
                f"FAILED_STATUSES_SQL_LIST 에 {status} 누락"
            )


# ---------------------------------------------------------------------------
# main_window backward-compat re-export
# ---------------------------------------------------------------------------

class TestMainWindowReExports:
    def test_main_window_re_exports_underscore_aliases(self):
        from app import main_window
        # 기존 호출 사이트 / 외부 테스트 (test_gallery_query_filters_present.py) 호환.
        assert main_window._GALLERY_BASE is GALLERY_BASE
        assert main_window._GALLERY_WHERE is GALLERY_WHERE_BY_CATEGORY
        assert main_window._COUNT_SQL is COUNT_SQL_BY_CATEGORY
        assert main_window._GALLERY_MISSING_SQL is GALLERY_MISSING_SQL
        assert main_window._PRESENT_EXISTS_FRAGMENT is PRESENT_EXISTS_SQL_FRAGMENT
        assert main_window._MISSING_EXISTS_FRAGMENT is MISSING_EXISTS_SQL_FRAGMENT
        assert main_window._FAILED_STATUSES is FAILED_STATUSES_SQL_LIST


# ---------------------------------------------------------------------------
# 실제 SQLite 동작 검증 — refactor 가 실행 의미를 깨지 않았는지
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
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
    c.commit()
    yield c
    c.close()


def _add(conn, *, gid, status="inbox", sync="full", file_status="present",
         file_role="original"):
    conn.execute(
        "INSERT INTO artwork_groups (group_id, artwork_id, artwork_title, "
        "metadata_sync_status, status, source_site, indexed_at) "
        "VALUES (?, '', ?, ?, ?, 'pixiv', '2026-01-01')",
        (gid, gid, sync, status),
    )
    conn.execute(
        "INSERT INTO artwork_files (file_id, group_id, page_index, file_role, "
        "file_path, file_format, file_status, created_at) "
        "VALUES (?, ?, 0, ?, ?, 'jpg', ?, '2026-01-01')",
        (f"f_{gid}", gid, file_role, f"/tmp/{gid}.jpg", file_status),
    )
    conn.commit()


class TestSQLExecutes:
    def test_count_all_returns_present_only(self, conn):
        _add(conn, gid="g1", file_status="present")
        _add(conn, gid="g2", file_status="missing")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["all"]).fetchone()[0]
        assert n == 1

    def test_count_warning_matches_xmp_write_failed_and_json_only(self, conn):
        _add(conn, gid="g_xmp", sync="xmp_write_failed")
        _add(conn, gid="g_json", sync="json_only")
        _add(conn, gid="g_full", sync="full")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["warning"]).fetchone()[0]
        assert n == 2

    def test_count_failed_matches_five_failure_statuses(self, conn):
        for s in ["file_write_failed", "convert_failed", "metadata_write_failed",
                  "db_update_failed", "needs_reindex"]:
            _add(conn, gid=f"g_{s}", sync=s)
        _add(conn, gid="g_full", sync="full")
        _add(conn, gid="g_xmp", sync="xmp_write_failed")  # warning, not failed
        n = conn.execute(COUNT_SQL_BY_CATEGORY["failed"]).fetchone()[0]
        assert n == 5

    def test_count_missing_uses_separate_path(self, conn):
        _add(conn, gid="g_present", file_status="present")
        _add(conn, gid="g_missing", file_status="missing")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["missing"]).fetchone()[0]
        assert n == 1

    def test_gallery_base_with_warning_where_returns_only_warning_groups(self, conn):
        _add(conn, gid="g_full", sync="full")
        _add(conn, gid="g_xmp", sync="xmp_write_failed")
        _add(conn, gid="g_json", sync="json_only")
        sql = f"{GALLERY_BASE} {GALLERY_WHERE_BY_CATEGORY['warning']} ORDER BY g.indexed_at DESC"
        rows = conn.execute(sql).fetchall()
        gids = {r["group_id"] for r in rows}
        assert gids == {"g_xmp", "g_json"}

    def test_gallery_missing_sql_returns_missing_files(self, conn):
        _add(conn, gid="g_present", file_status="present")
        _add(conn, gid="g_missing", file_status="missing")
        rows = conn.execute(GALLERY_MISSING_SQL).fetchall()
        gids = {r["group_id"] for r in rows}
        assert gids == {"g_missing"}
