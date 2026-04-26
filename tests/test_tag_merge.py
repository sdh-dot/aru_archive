"""
core/tag_merge.py 테스트.

DB 없이 pytest in-memory SQLite로 실행.
"""
from __future__ import annotations

import sqlite3
import pytest


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE tag_aliases (
            alias         TEXT NOT NULL,
            canonical     TEXT NOT NULL,
            tag_type      TEXT NOT NULL DEFAULT 'general',
            parent_series TEXT NOT NULL DEFAULT '',
            source        TEXT,
            confidence_score REAL,
            enabled       INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL,
            updated_at    TEXT,
            PRIMARY KEY (alias, tag_type, parent_series)
        );
    """)
    yield db
    db.close()


def _insert_alias(db, alias, canonical, tag_type="character", parent_series="", enabled=1):
    db.execute(
        "INSERT INTO tag_aliases (alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 'test', ?, '2024-01-01')",
        (alias, canonical, tag_type, parent_series, enabled),
    )
    db.commit()


# ---------------------------------------------------------------------------
# list_existing_canonicals
# ---------------------------------------------------------------------------

class TestListExistingCanonicals:
    def test_empty_db_returns_empty(self, conn) -> None:
        from core.tag_merge import list_existing_canonicals
        assert list_existing_canonicals(conn) == []

    def test_returns_distinct_canonicals(self, conn) -> None:
        from core.tag_merge import list_existing_canonicals
        _insert_alias(conn, "ワカモ", "狐坂ワカモ", "character", "Blue Archive")
        _insert_alias(conn, "Wakamo", "狐坂ワカモ", "character", "Blue Archive")
        result = list_existing_canonicals(conn)
        canonicals = [r["canonical"] for r in result]
        assert canonicals.count("狐坂ワカモ") == 1

    def test_filters_by_tag_type(self, conn) -> None:
        from core.tag_merge import list_existing_canonicals
        _insert_alias(conn, "ブルアカ", "Blue Archive", "series")
        _insert_alias(conn, "アル", "陸八魔アル", "character", "Blue Archive")
        series_only = list_existing_canonicals(conn, tag_type="series")
        assert all(r["tag_type"] == "series" for r in series_only)
        assert len(series_only) == 1

    def test_ignores_disabled_aliases(self, conn) -> None:
        from core.tag_merge import list_existing_canonicals
        _insert_alias(conn, "古いAlias", "古いCanonical", "character", enabled=0)
        result = list_existing_canonicals(conn, tag_type="character")
        assert result == []

    def test_result_has_canonical_tag_type_parent_series(self, conn) -> None:
        from core.tag_merge import list_existing_canonicals
        _insert_alias(conn, "ワカモ", "狐坂ワカモ", "character", "Blue Archive")
        result = list_existing_canonicals(conn)
        assert result[0]["canonical"] == "狐坂ワカモ"
        assert result[0]["tag_type"] == "character"
        assert result[0]["parent_series"] == "Blue Archive"


# ---------------------------------------------------------------------------
# find_canonical_alias_conflicts
# ---------------------------------------------------------------------------

class TestFindCanonicalAliasConflicts:
    def test_no_conflicts_when_same_canonical(self, conn) -> None:
        from core.tag_merge import find_canonical_alias_conflicts
        _insert_alias(conn, "ワカモ", "狐坂ワカモ", "character")
        conflicts = find_canonical_alias_conflicts(
            conn, ["ワカモ"], "狐坂ワカモ", "character"
        )
        assert conflicts == []

    def test_detects_conflict_with_different_canonical(self, conn) -> None:
        from core.tag_merge import find_canonical_alias_conflicts
        _insert_alias(conn, "ワカモ", "Other Character", "character")
        conflicts = find_canonical_alias_conflicts(
            conn, ["ワカモ"], "狐坂ワカモ", "character"
        )
        assert len(conflicts) == 1
        assert conflicts[0]["alias"] == "ワカモ"
        assert conflicts[0]["existing_canonical"] == "Other Character"

    def test_multiple_aliases_multiple_conflicts(self, conn) -> None:
        from core.tag_merge import find_canonical_alias_conflicts
        _insert_alias(conn, "A", "Other1", "character")
        _insert_alias(conn, "B", "Other2", "character")
        conflicts = find_canonical_alias_conflicts(
            conn, ["A", "B"], "Target", "character"
        )
        assert len(conflicts) == 2

    def test_unknown_alias_no_conflict(self, conn) -> None:
        from core.tag_merge import find_canonical_alias_conflicts
        conflicts = find_canonical_alias_conflicts(
            conn, ["NewAlias"], "Target", "character"
        )
        assert conflicts == []


# ---------------------------------------------------------------------------
# merge_alias_into_canonical
# ---------------------------------------------------------------------------

class TestMergeAliasIntoCanonical:
    def test_inserts_new_aliases(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical, list_existing_canonicals
        result = merge_alias_into_canonical(
            conn, ["ワカモ", "Wakamo"], "狐坂ワカモ", "character", "Blue Archive"
        )
        assert result["merged"] == 2
        assert result["skipped"] == 0
        row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias='ワカモ'"
        ).fetchone()
        assert row["canonical"] == "狐坂ワカモ"

    def test_overwrites_same_canonical(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical
        _insert_alias(conn, "ワカモ", "狐坂ワカモ", "character", "Blue Archive")
        result = merge_alias_into_canonical(
            conn, ["ワカモ"], "狐坂ワカモ", "character", "Blue Archive"
        )
        assert result["merged"] == 1
        assert result["skipped"] == 0

    def test_skips_conflict_by_default(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical
        _insert_alias(conn, "ワカモ", "別キャラ", "character")
        result = merge_alias_into_canonical(
            conn, ["ワカモ"], "狐坂ワカモ", "character"
        )
        assert result["merged"] == 0
        assert result["skipped"] == 1
        assert result["conflicts"][0]["existing_canonical"] == "別キャラ"

    def test_overwrites_conflict_when_flag_set(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical
        _insert_alias(conn, "ワカモ", "別キャラ", "character")
        result = merge_alias_into_canonical(
            conn, ["ワカモ"], "狐坂ワカモ", "character",
            overwrite_conflicts=True
        )
        assert result["merged"] == 1
        assert result["skipped"] == 0
        row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias='ワカモ'"
        ).fetchone()
        assert row["canonical"] == "狐坂ワカモ"

    def test_partial_merge_some_conflict(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical
        _insert_alias(conn, "ワカモ", "別キャラ", "character")
        result = merge_alias_into_canonical(
            conn, ["ワカモ", "Wakamo"], "狐坂ワカモ", "character"
        )
        assert result["merged"] == 1
        assert result["skipped"] == 1

    def test_source_written_as_user_merge(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical
        merge_alias_into_canonical(conn, ["ワカモ"], "狐坂ワカモ", "character")
        row = conn.execute(
            "SELECT source FROM tag_aliases WHERE alias='ワカモ'"
        ).fetchone()
        assert row["source"] == "user_merge"

    def test_custom_source(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical
        merge_alias_into_canonical(
            conn, ["ワカモ"], "狐坂ワカモ", "character",
            source="pack_import"
        )
        row = conn.execute(
            "SELECT source FROM tag_aliases WHERE alias='ワカモ'"
        ).fetchone()
        assert row["source"] == "pack_import"

    def test_empty_aliases_returns_zero(self, conn) -> None:
        from core.tag_merge import merge_alias_into_canonical
        result = merge_alias_into_canonical(conn, [], "狐坂ワカモ", "character")
        assert result["merged"] == 0
        assert result["skipped"] == 0
