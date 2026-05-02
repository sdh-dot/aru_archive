"""Sidebar 필터 SQL / helper 중앙화 + 의미 기반 분할 회귀 테스트.

``app/widgets/sidebar_filters.py`` 의 invariant 을 lock 한다. 본 테스트는 PR #91
(동작 보존 refactor) 의 invariant 위에 sidebar semantic refactor 의 추가 invariant
을 더한다.

핵심 invariant:
- 모든 sidebar 카테고리 키 (sidebar.py CATEGORIES) 가 query helper 에 존재
- gallery WHERE 매핑이 의미 정의대로
- count SQL 매핑이 의미 정의대로
- missing 카테고리는 별도 SQL 유지
- no_metadata gallery WHERE 가 의도적으로 빈 문자열 (panel swap 위임)
- no_metadata count 는 ``no_metadata_queue WHERE resolved = 0`` 기반
- work_target = full + json_only + xmp_write_failed (CLASSIFIABLE_STATUSES 와 동일)
- failed = 5종 실패 상태
- other = pending + out_of_sync + source_unavailable
- unregistered = metadata_missing
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
    OTHER_STATUSES_SQL_LIST,
    PRESENT_EXISTS_SQL_FRAGMENT,
    WORK_TARGET_STATUSES_SQL_LIST,
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
# 의미 lock — 카테고리별 조건이 정의된 의미와 일치하는지
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

    def test_no_metadata_is_empty_string_for_panel_swap(self):
        """no_metadata 의 GALLERY WHERE 는 의도적으로 비어 있다 (panel swap 위임)."""
        assert GALLERY_WHERE_BY_CATEGORY["no_metadata"] == ""

    def test_work_target_includes_classifiable_three_statuses(self):
        sql = GALLERY_WHERE_BY_CATEGORY["work_target"]
        for status in ["full", "json_only", "xmp_write_failed"]:
            assert status in sql, f"work_target 에 {status} 누락"
        assert "metadata_sync_status IN" in sql

    def test_unregistered_filters_metadata_missing(self):
        assert (
            GALLERY_WHERE_BY_CATEGORY["unregistered"]
            == "AND g.metadata_sync_status = 'metadata_missing'"
        )

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

    def test_failed_does_not_include_work_target_or_other(self):
        sql = GALLERY_WHERE_BY_CATEGORY["failed"]
        for forbidden in [
            "xmp_write_failed", "json_only", "full",
            "pending", "out_of_sync", "source_unavailable",
            "metadata_missing",
        ]:
            assert forbidden not in sql, (
                f"failed WHERE 에 다른 카테고리 상태 {forbidden} 가 섞임"
            )

    def test_other_includes_three_passive_statuses(self):
        sql = GALLERY_WHERE_BY_CATEGORY["other"]
        for status in ["pending", "out_of_sync", "source_unavailable"]:
            assert status in sql, f"other 에 {status} 누락"

    def test_warning_key_removed(self):
        """warning 키는 의미 분할 후 제거되었다. xmp_write_failed/json_only 는
        work_target 으로, pending 은 other 로 흡수."""
        assert "warning" not in GALLERY_WHERE_BY_CATEGORY


class TestCountSqlSemantics:
    def test_all_count_uses_present_exists(self):
        sql = COUNT_SQL_BY_CATEGORY["all"]
        assert PRESENT_EXISTS_SQL_FRAGMENT in sql
        assert "COUNT(*)" in sql

    def test_no_metadata_count_uses_queue_resolved(self):
        """no_metadata 카운트는 NoMetadataView 데이터 소스 (no_metadata_queue) 와
        일치하도록 큐 기반."""
        sql = COUNT_SQL_BY_CATEGORY["no_metadata"]
        assert "no_metadata_queue" in sql
        assert "resolved = 0" in sql
        # artwork_groups 기반 metadata_missing 카운트와 혼동되지 않도록
        assert "metadata_sync_status" not in sql

    def test_unregistered_count_uses_metadata_missing(self):
        sql = COUNT_SQL_BY_CATEGORY["unregistered"]
        assert "metadata_sync_status = 'metadata_missing'" in sql
        assert PRESENT_EXISTS_SQL_FRAGMENT in sql

    def test_work_target_count_uses_three_statuses(self):
        sql = COUNT_SQL_BY_CATEGORY["work_target"]
        assert WORK_TARGET_STATUSES_SQL_LIST in sql
        assert PRESENT_EXISTS_SQL_FRAGMENT in sql

    def test_failed_count_uses_failed_statuses_list(self):
        sql = COUNT_SQL_BY_CATEGORY["failed"]
        assert FAILED_STATUSES_SQL_LIST in sql
        assert PRESENT_EXISTS_SQL_FRAGMENT in sql

    def test_other_count_uses_other_statuses_list(self):
        sql = COUNT_SQL_BY_CATEGORY["other"]
        assert OTHER_STATUSES_SQL_LIST in sql
        assert PRESENT_EXISTS_SQL_FRAGMENT in sql

    def test_missing_count_uses_missing_exists(self):
        sql = COUNT_SQL_BY_CATEGORY["missing"]
        assert MISSING_EXISTS_SQL_FRAGMENT in sql
        # missing 카테고리는 present_exists 를 사용하지 않음 (반대 의미)
        assert PRESENT_EXISTS_SQL_FRAGMENT not in sql

    def test_warning_key_removed_from_count(self):
        assert "warning" not in COUNT_SQL_BY_CATEGORY


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
        for status in [
            "'file_write_failed'", "'convert_failed'", "'metadata_write_failed'",
            "'db_update_failed'", "'needs_reindex'",
        ]:
            assert status in FAILED_STATUSES_SQL_LIST, (
                f"FAILED_STATUSES_SQL_LIST 에 {status} 누락"
            )

    def test_work_target_statuses_list_has_three_quoted_statuses(self):
        for status in ["'full'", "'json_only'", "'xmp_write_failed'"]:
            assert status in WORK_TARGET_STATUSES_SQL_LIST, (
                f"WORK_TARGET_STATUSES_SQL_LIST 에 {status} 누락"
            )

    def test_other_statuses_list_has_three_quoted_statuses(self):
        for status in ["'pending'", "'out_of_sync'", "'source_unavailable'"]:
            assert status in OTHER_STATUSES_SQL_LIST, (
                f"OTHER_STATUSES_SQL_LIST 에 {status} 누락"
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
        CREATE TABLE no_metadata_queue (
            queue_id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            detected_at TEXT
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


def _enqueue(conn, *, qid, resolved=0):
    conn.execute(
        "INSERT INTO no_metadata_queue (queue_id, file_path, resolved, detected_at) "
        "VALUES (?, ?, ?, '2026-01-01')",
        (qid, f"/tmp/{qid}.jpg", resolved),
    )
    conn.commit()


class TestSQLExecutes:
    def test_count_all_returns_present_only(self, conn):
        _add(conn, gid="g1", file_status="present")
        _add(conn, gid="g2", file_status="missing")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["all"]).fetchone()[0]
        assert n == 1

    def test_count_work_target_matches_three_statuses(self, conn):
        _add(conn, gid="g_full", sync="full")
        _add(conn, gid="g_json", sync="json_only")
        _add(conn, gid="g_xmp", sync="xmp_write_failed")
        _add(conn, gid="g_missing_meta", sync="metadata_missing")
        _add(conn, gid="g_failed", sync="file_write_failed")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["work_target"]).fetchone()[0]
        assert n == 3

    def test_count_unregistered_matches_metadata_missing(self, conn):
        _add(conn, gid="g_um1", sync="metadata_missing")
        _add(conn, gid="g_um2", sync="metadata_missing")
        _add(conn, gid="g_full", sync="full")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["unregistered"]).fetchone()[0]
        assert n == 2

    def test_count_failed_matches_five_failure_statuses(self, conn):
        for s in ["file_write_failed", "convert_failed", "metadata_write_failed",
                  "db_update_failed", "needs_reindex"]:
            _add(conn, gid=f"g_{s}", sync=s)
        _add(conn, gid="g_full", sync="full")
        _add(conn, gid="g_xmp", sync="xmp_write_failed")  # work_target
        n = conn.execute(COUNT_SQL_BY_CATEGORY["failed"]).fetchone()[0]
        assert n == 5

    def test_count_other_matches_three_passive_statuses(self, conn):
        for s in ["pending", "out_of_sync", "source_unavailable"]:
            _add(conn, gid=f"g_{s}", sync=s)
        _add(conn, gid="g_full", sync="full")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["other"]).fetchone()[0]
        assert n == 3

    def test_count_no_metadata_uses_queue(self, conn):
        # no_metadata 카운트는 큐 기반 — artwork_groups 와 무관하게 동작한다.
        _enqueue(conn, qid="q1", resolved=0)
        _enqueue(conn, qid="q2", resolved=0)
        _enqueue(conn, qid="q3", resolved=1)  # 해소됨 — 카운트 제외
        n = conn.execute(COUNT_SQL_BY_CATEGORY["no_metadata"]).fetchone()[0]
        assert n == 2

    def test_count_missing_uses_separate_path(self, conn):
        _add(conn, gid="g_present", file_status="present")
        _add(conn, gid="g_missing", file_status="missing")
        n = conn.execute(COUNT_SQL_BY_CATEGORY["missing"]).fetchone()[0]
        assert n == 1

    def test_gallery_base_with_work_target_where_returns_only_three(self, conn):
        _add(conn, gid="g_full", sync="full")
        _add(conn, gid="g_xmp", sync="xmp_write_failed")
        _add(conn, gid="g_json", sync="json_only")
        _add(conn, gid="g_pending", sync="pending")
        _add(conn, gid="g_failed", sync="file_write_failed")
        sql = (
            f"{GALLERY_BASE} {GALLERY_WHERE_BY_CATEGORY['work_target']} "
            "ORDER BY g.indexed_at DESC"
        )
        rows = conn.execute(sql).fetchall()
        gids = {r["group_id"] for r in rows}
        assert gids == {"g_full", "g_xmp", "g_json"}

    def test_gallery_base_with_other_where_returns_only_passive(self, conn):
        _add(conn, gid="g_pending", sync="pending")
        _add(conn, gid="g_oos", sync="out_of_sync")
        _add(conn, gid="g_su", sync="source_unavailable")
        _add(conn, gid="g_full", sync="full")
        sql = (
            f"{GALLERY_BASE} {GALLERY_WHERE_BY_CATEGORY['other']} "
            "ORDER BY g.indexed_at DESC"
        )
        rows = conn.execute(sql).fetchall()
        gids = {r["group_id"] for r in rows}
        assert gids == {"g_pending", "g_oos", "g_su"}

    def test_gallery_missing_sql_returns_missing_files(self, conn):
        _add(conn, gid="g_present", file_status="present")
        _add(conn, gid="g_missing", file_status="missing")
        rows = conn.execute(GALLERY_MISSING_SQL).fetchall()
        gids = {r["group_id"] for r in rows}
        assert gids == {"g_missing"}
