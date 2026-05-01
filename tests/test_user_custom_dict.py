"""core.user_custom_dict 단위 테스트.

DB schema는 변경하지 않는다. 합성 in-memory SQLite + bootstrap으로
tag_aliases 테이블만 만들고 검증한다.

schema.sql:290-308 의 CREATE TABLE 정의를 그대로 사용한다.
PRIMARY KEY: (alias, tag_type, parent_series)
"""
from __future__ import annotations

import sqlite3

import pytest

from core.user_custom_dict import (
    add_user_alias,
    list_user_aliases,
    remove_user_alias,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CREATE_TAG_ALIASES = """
CREATE TABLE IF NOT EXISTS tag_aliases (
    alias            TEXT NOT NULL,
    canonical        TEXT NOT NULL,
    tag_type         TEXT NOT NULL DEFAULT 'general',
    parent_series    TEXT NOT NULL DEFAULT '',
    media_type       TEXT,
    source           TEXT,
    confidence_score REAL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_by       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT,
    PRIMARY KEY (alias, tag_type, parent_series)
)
"""


def _bootstrap(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TAG_ALIASES)
    conn.commit()


def _insert_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    tag_type: str,
    source: str,
    parent_series: str = "",
    enabled: int = 1,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (alias, canonical, tag_type, parent_series, source, enabled),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _bootstrap(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# TestAddUserAlias
# ---------------------------------------------------------------------------


class TestAddUserAlias:
    def test_inserts_with_user_confirmed_source(self, conn):
        result = add_user_alias(conn, "아루", "陸八魔アル", "character")
        assert result["action"] == "inserted"
        assert isinstance(result["rowid"], int)

        row = conn.execute(
            "SELECT * FROM tag_aliases WHERE alias = '아루'"
        ).fetchone()
        assert row is not None
        assert row["canonical"] == "陸八魔アル"
        assert row["tag_type"] == "character"
        assert row["source"] == "user_confirmed"
        assert row["enabled"] == 1

    def test_validates_empty_alias(self, conn):
        with pytest.raises(ValueError, match="alias"):
            add_user_alias(conn, "", "陸八魔アル", "character")

    def test_validates_whitespace_only_alias(self, conn):
        with pytest.raises(ValueError, match="alias"):
            add_user_alias(conn, "   ", "陸八魔アル", "character")

    def test_validates_empty_canonical(self, conn):
        with pytest.raises(ValueError, match="canonical"):
            add_user_alias(conn, "아루", "", "character")

    def test_validates_invalid_tag_type(self, conn):
        with pytest.raises(ValueError, match="tag_type"):
            add_user_alias(conn, "아루", "陸八魔アル", "invalid")

    def test_validates_none_alias(self, conn):
        with pytest.raises((ValueError, AttributeError)):
            add_user_alias(conn, None, "陸八魔アル", "character")  # type: ignore[arg-type]

    def test_strips_whitespace_from_alias_and_canonical(self, conn):
        add_user_alias(conn, "  아루  ", "  陸八魔アル  ", "character")
        row = conn.execute(
            "SELECT alias, canonical FROM tag_aliases WHERE source='user_confirmed'"
        ).fetchone()
        assert row["alias"] == "아루"
        assert row["canonical"] == "陸八魔アル"

    def test_idempotent_second_call_returns_updated(self, conn):
        r1 = add_user_alias(conn, "아루", "陸八魔アル", "character")
        r2 = add_user_alias(conn, "아루", "陸八魔アル", "character")
        assert r1["action"] == "inserted"
        assert r2["action"] == "updated"
        # 행이 하나만 있어야 함
        count = conn.execute(
            "SELECT COUNT(*) FROM tag_aliases "
            "WHERE alias='아루' AND source='user_confirmed'"
        ).fetchone()[0]
        assert count == 1

    def test_idempotent_update_changes_canonical(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        r2 = add_user_alias(conn, "아루", "NewCanonical", "character")
        assert r2["action"] == "updated"
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias='아루' AND source='user_confirmed'"
        ).fetchone()
        assert row["canonical"] == "NewCanonical"

    def test_re_enables_soft_deleted_row(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        remove_user_alias(conn, "아루", "character")

        # soft-deleted 상태에서 재추가
        r = add_user_alias(conn, "아루", "陸八魔アル", "character")
        assert r["action"] == "updated"
        row = conn.execute(
            "SELECT enabled FROM tag_aliases "
            "WHERE alias='아루' AND source='user_confirmed'"
        ).fetchone()
        assert row["enabled"] == 1

    def test_does_not_disturb_other_source_aliases(self, conn):
        # 먼저 built_in source로 같은 alias/tag_type은 PK가 충돌하므로
        # parent_series를 달리 해서 공존 테스트
        _insert_alias(
            conn, "블루아카", "Blue Archive", "series", "built_in", parent_series=""
        )
        # user_confirmed를 별도 parent_series로 삽입 (PK 다름)
        add_user_alias(
            conn, "블루아카2", "Blue Archive", "series"
        )
        # built_in 행 보존 확인
        bi_row = conn.execute(
            "SELECT source FROM tag_aliases WHERE alias='블루아카'"
        ).fetchone()
        assert bi_row is not None
        assert bi_row["source"] == "built_in"

    def test_series_alias_stored_correctly(self, conn):
        result = add_user_alias(conn, "블아", "Blue Archive", "series")
        assert result["action"] == "inserted"
        row = conn.execute(
            "SELECT * FROM tag_aliases WHERE alias='블아'"
        ).fetchone()
        assert row["tag_type"] == "series"
        assert row["source"] == "user_confirmed"
        assert row["canonical"] == "Blue Archive"

    def test_general_alias_stored_correctly(self, conn):
        result = add_user_alias(conn, "수영복", "swimsuit", "general")
        assert result["action"] == "inserted"
        row = conn.execute(
            "SELECT tag_type FROM tag_aliases WHERE alias='수영복'"
        ).fetchone()
        assert row["tag_type"] == "general"

    def test_parent_series_stored_for_character(self, conn):
        add_user_alias(
            conn, "아루", "陸八魔アル", "character",
            parent_series="Blue Archive"
        )
        row = conn.execute(
            "SELECT parent_series FROM tag_aliases WHERE alias='아루'"
        ).fetchone()
        assert row["parent_series"] == "Blue Archive"

    def test_media_type_stored(self, conn):
        add_user_alias(
            conn, "아루", "陸八魔アル", "character",
            media_type="game"
        )
        row = conn.execute(
            "SELECT media_type FROM tag_aliases WHERE alias='아루'"
        ).fetchone()
        assert row["media_type"] == "game"

    def test_returns_rowid_int(self, conn):
        result = add_user_alias(conn, "아루", "陸八魔アル", "character")
        assert isinstance(result["rowid"], int)
        assert result["rowid"] > 0


# ---------------------------------------------------------------------------
# TestListUserAliases
# ---------------------------------------------------------------------------


class TestListUserAliases:
    def test_returns_only_user_confirmed(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        _insert_alias(conn, "블루아카", "Blue Archive", "series", "built_in")
        _insert_alias(conn, "ba_alias", "Blue Archive", "series", "import")

        result = list_user_aliases(conn)
        assert len(result) == 1
        assert result[0]["alias"] == "아루"
        assert result[0]["source"] == "user_confirmed"

    def test_returns_all_types_when_no_filter(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        add_user_alias(conn, "블아", "Blue Archive", "series")
        add_user_alias(conn, "수영복", "swimsuit", "general")

        result = list_user_aliases(conn)
        aliases = {r["alias"] for r in result}
        assert aliases == {"아루", "블아", "수영복"}

    def test_filters_by_tag_type_character(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        add_user_alias(conn, "블아", "Blue Archive", "series")

        result = list_user_aliases(conn, tag_type="character")
        assert len(result) == 1
        assert result[0]["alias"] == "아루"

    def test_filters_by_tag_type_series(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        add_user_alias(conn, "블아", "Blue Archive", "series")

        result = list_user_aliases(conn, tag_type="series")
        assert len(result) == 1
        assert result[0]["alias"] == "블아"

    def test_excludes_soft_deleted_by_default(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        remove_user_alias(conn, "아루", "character")

        result = list_user_aliases(conn)
        assert result == []

    def test_include_disabled_shows_soft_deleted(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        remove_user_alias(conn, "아루", "character")

        result = list_user_aliases(conn, include_disabled=True)
        assert len(result) == 1
        assert result[0]["enabled"] == 0

    def test_result_contains_expected_keys(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        result = list_user_aliases(conn)
        assert len(result) == 1
        row = result[0]
        for key in ("alias", "canonical", "tag_type", "parent_series",
                    "media_type", "source", "enabled", "created_at", "updated_at"):
            assert key in row, f"missing key: {key}"

    def test_invalid_tag_type_filter_raises(self, conn):
        with pytest.raises(ValueError, match="tag_type"):
            list_user_aliases(conn, tag_type="invalid")

    def test_sorted_by_tag_type_then_alias(self, conn):
        add_user_alias(conn, "z_char", "Z", "character")
        add_user_alias(conn, "a_char", "A", "character")
        add_user_alias(conn, "a_series", "AS", "series")

        result = list_user_aliases(conn)
        # character < series 알파벳순
        types = [r["tag_type"] for r in result]
        assert types == sorted(types)
        # character 내에서 alias 정렬
        char_aliases = [r["alias"] for r in result if r["tag_type"] == "character"]
        assert char_aliases == sorted(char_aliases)

    def test_empty_returns_empty_list(self, conn):
        assert list_user_aliases(conn) == []


# ---------------------------------------------------------------------------
# TestRemoveUserAlias
# ---------------------------------------------------------------------------


class TestRemoveUserAlias:
    def test_soft_deletes_user_confirmed(self, conn):
        add_user_alias(conn, "아루", "陸八魔アル", "character")
        count = remove_user_alias(conn, "아루", "character")
        assert count == 1

        row = conn.execute(
            "SELECT enabled FROM tag_aliases "
            "WHERE alias='아루' AND source='user_confirmed'"
        ).fetchone()
        assert row["enabled"] == 0

    def test_does_not_remove_built_in_source(self, conn):
        # built_in alias는 PK가 충돌하므로 parent_series 다르게
        _insert_alias(
            conn, "아루_bi", "陸八魔アル", "character",
            "built_in", parent_series=""
        )
        count = remove_user_alias(conn, "아루_bi", "character")
        # user_confirmed 행이 없으므로 0
        assert count == 0
        # built_in 행은 그대로
        row = conn.execute(
            "SELECT enabled, source FROM tag_aliases WHERE alias='아루_bi'"
        ).fetchone()
        assert row["enabled"] == 1
        assert row["source"] == "built_in"

    def test_does_not_remove_pack_source(self, conn):
        _insert_alias(
            conn, "pack_alias", "SomeCanon", "series", "pack"
        )
        count = remove_user_alias(conn, "pack_alias")
        assert count == 0

    def test_does_not_remove_import_source(self, conn):
        _insert_alias(
            conn, "imp_alias", "SomeCanon", "series", "import"
        )
        count = remove_user_alias(conn, "imp_alias")
        assert count == 0

    def test_returns_zero_when_no_match(self, conn):
        count = remove_user_alias(conn, "nonexistent", "character")
        assert count == 0

    def test_remove_without_tag_type_removes_all_types(self, conn):
        add_user_alias(conn, "multi", "C1", "character")
        add_user_alias(conn, "multi", "S1", "series")
        count = remove_user_alias(conn, "multi")
        assert count == 2

    def test_remove_with_tag_type_only_removes_that_type(self, conn):
        add_user_alias(conn, "multi", "C1", "character")
        add_user_alias(conn, "multi", "S1", "series")
        count = remove_user_alias(conn, "multi", "character")
        assert count == 1

        # series 행은 여전히 enabled=1
        row = conn.execute(
            "SELECT enabled FROM tag_aliases "
            "WHERE alias='multi' AND tag_type='series' AND source='user_confirmed'"
        ).fetchone()
        assert row["enabled"] == 1

    def test_validates_empty_alias(self, conn):
        with pytest.raises(ValueError, match="alias"):
            remove_user_alias(conn, "")

    def test_validates_invalid_tag_type(self, conn):
        with pytest.raises(ValueError, match="tag_type"):
            remove_user_alias(conn, "아루", "invalid_type")

    def test_remove_with_parent_series(self, conn):
        add_user_alias(
            conn, "아루", "陸八魔アル", "character",
            parent_series="Blue Archive"
        )
        add_user_alias(
            conn, "아루", "AnotherCharacter", "character",
            parent_series="Other Series"
        )
        # parent_series 지정해서 하나만 soft-delete
        count = remove_user_alias(
            conn, "아루", "character", parent_series="Blue Archive"
        )
        assert count == 1

        rows = conn.execute(
            "SELECT parent_series, enabled FROM tag_aliases "
            "WHERE alias='아루' AND source='user_confirmed'"
        ).fetchall()
        by_series = {r["parent_series"]: r["enabled"] for r in rows}
        assert by_series["Blue Archive"] == 0
        assert by_series["Other Series"] == 1


# ---------------------------------------------------------------------------
# TestPriorityOverHardcoded
# ---------------------------------------------------------------------------


class TestPriorityOverHardcoded:
    """user_confirmed alias가 load_db_aliases에 포함되는지 확인.

    classify_pixiv_tags에서 DB alias는 hardcoded dict.update() 이후
    적용되므로, DB에 있는 user_confirmed 항목은 hardcoded를 덮어쓴다
    (series의 경우) 또는 char_alias_groups에 병합된다 (character의 경우).

    신규 alias(hardcoded에 없는 것)는 DB에서 정상 로드되는 것을 검증한다.
    """

    def test_load_db_aliases_returns_user_confirmed_series(self, conn):
        from core.tag_classifier import load_db_aliases

        add_user_alias(conn, "유저시리즈", "UserSeries", "series")
        series, _ = load_db_aliases(conn)
        assert "유저시리즈" in series
        assert series["유저시리즈"] == "UserSeries"

    def test_load_db_aliases_returns_user_confirmed_character(self, conn):
        from core.tag_classifier import load_db_aliases

        add_user_alias(
            conn, "유저캐릭", "UserCharacter", "character",
            parent_series="UserSeries"
        )
        _, chars = load_db_aliases(conn)
        assert "유저캐릭" in chars
        assert chars["유저캐릭"][0]["canonical"] == "UserCharacter"
        assert chars["유저캐릭"][0]["series"] == "UserSeries"

    def test_user_confirmed_series_overrides_hardcoded_via_classify(self, conn):
        """series_aliases.update(db_series) 이므로 DB가 hardcoded를 덮어쓴다."""
        from core.tag_classifier import classify_pixiv_tags, SERIES_ALIASES

        # hardcoded에 존재하는 alias를 user_confirmed로 다른 canonical로 지정
        # SERIES_ALIASES에 "ブルーアーカイブ" → "Blue Archive" 있음
        original_canonical = SERIES_ALIASES.get("ブルーアーカイブ")
        assert original_canonical is not None, "테스트 전제: hardcoded alias 존재 확인"

        add_user_alias(conn, "ブルーアーカイブ", "Blue Archive Override", "series")
        result = classify_pixiv_tags(["ブルーアーカイブ"], conn=conn)
        assert "Blue Archive Override" in result["series_tags"]

    def test_new_user_confirmed_alias_classified_correctly(self, conn):
        """hardcoded에 없는 신규 user_confirmed alias가 분류에 반영된다."""
        from core.tag_classifier import classify_pixiv_tags

        add_user_alias(conn, "완전히새로운별칭", "NewCanonicalSeries", "series")
        result = classify_pixiv_tags(["완전히새로운별칭"], conn=conn)
        assert "NewCanonicalSeries" in result["series_tags"]
        assert "완전히새로운별칭" not in result["tags"]

    def test_soft_deleted_alias_not_classified(self, conn):
        """soft-delete된 user_confirmed alias는 분류에 반영되지 않는다."""
        from core.tag_classifier import classify_pixiv_tags

        add_user_alias(conn, "사라질별칭", "GoneCanonical", "series")
        remove_user_alias(conn, "사라질별칭", "series")

        result = classify_pixiv_tags(["사라질별칭"], conn=conn)
        assert "GoneCanonical" not in result["series_tags"]
        assert "사라질별칭" in result["tags"]

    def test_user_confirmed_character_classified_correctly(self, conn):
        """user_confirmed character alias가 classify_pixiv_tags에 반영된다."""
        from core.tag_classifier import classify_pixiv_tags

        add_user_alias(
            conn, "커스텀캐릭", "CustomCharacter", "character",
            parent_series="CustomSeries"
        )
        result = classify_pixiv_tags(["커스텀캐릭"], conn=conn)
        assert "CustomCharacter" in result["character_tags"]
        assert "CustomSeries" in result["series_tags"]
