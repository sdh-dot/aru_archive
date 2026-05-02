"""``core.autocomplete_provider`` 단위 테스트.

다국어 자동완성 candidate provider 가:
- alias / localized_name 양쪽에서 후보를 수집하는지
- 한국어 / 일본어 / 영어 입력 모두에 후보를 반환하는지
- source / locale 우선순위가 confidence 에 반영되는지
- 같은 canonical 후보를 dedupe 하는지
- ``-`` (U+002D) 와 ``ー`` (U+30FC) 를 절대 혼동하지 않는지
- mojibake 의심 후보가 강하게 감점되는지
- DB 에 어떤 write 도 가하지 않는지
- limit / tag_type 필터가 동작하는지
를 lock 한다.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from core.autocomplete_provider import (
    TagAutocompleteCandidate,
    suggest_tag_completions,
)


_NOW = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE tag_aliases (
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
);

CREATE TABLE tag_localizations (
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
);
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    c.commit()
    yield c
    c.close()


def _add_alias(c, alias, canonical, *, tag_type="character", parent_series="",
               source="built_in_pack:test", enabled=1):
    c.execute(
        "INSERT INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (alias, canonical, tag_type, parent_series, source, enabled, _NOW),
    )
    c.commit()


def _add_loc(c, canonical, display_name, locale, *, tag_type="character",
             parent_series="", source="built_in_pack:test", enabled=1):
    c.execute(
        "INSERT INTO tag_localizations "
        "(localization_id, canonical, tag_type, parent_series, locale, display_name, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), canonical, tag_type, parent_series, locale,
         display_name, source, enabled, _NOW),
    )
    c.commit()


# ---------------------------------------------------------------------------
# 기본 매칭 — alias / localized
# ---------------------------------------------------------------------------

class TestBasicMatching:
    def test_korean_localized_prefix_returns_candidates(self, conn):
        _add_loc(conn, "陸八魔アル", "리쿠하치마 아루", "ko", parent_series="Blue Archive")
        result = suggest_tag_completions(conn, "리쿠")
        assert result
        assert any(c.canonical == "陸八魔アル" and c.locale == "ko" for c in result)

    def test_japanese_localized_prefix_returns_candidates(self, conn):
        _add_loc(conn, "Blue Archive", "ブルーアーカイブ", "ja", tag_type="series")
        result = suggest_tag_completions(conn, "ブルー")
        assert result
        assert any(c.canonical == "Blue Archive" and c.locale == "ja" for c in result)

    def test_english_canonical_alias_returns_candidates(self, conn):
        _add_alias(conn, "Blue Archive", "Blue Archive", tag_type="series")
        result = suggest_tag_completions(conn, "Blue")
        assert result
        assert any(c.canonical == "Blue Archive" for c in result)

    def test_english_alias_partial_returns_candidates(self, conn):
        _add_alias(conn, "BlueArchive", "Blue Archive", tag_type="series")
        result = suggest_tag_completions(conn, "Blue")
        assert any(c.canonical == "Blue Archive" for c in result)

    def test_no_match_returns_empty(self, conn):
        result = suggest_tag_completions(conn, "totally_unknown_xyz")
        assert result == ()

    def test_disabled_rows_skipped(self, conn):
        _add_alias(conn, "DisabledAlias", "DisabledCanon", enabled=0)
        result = suggest_tag_completions(conn, "Disabled")
        assert result == ()


# ---------------------------------------------------------------------------
# tag_type 필터
# ---------------------------------------------------------------------------

class TestTagTypeFilter:
    def test_tag_type_filter_keeps_only_requested(self, conn):
        _add_alias(conn, "BlueArchive", "Blue Archive", tag_type="series")
        _add_alias(conn, "BlueChar", "BlueChar", tag_type="character")
        result = suggest_tag_completions(conn, "Blue", tag_type="series")
        assert result
        assert all(c.tag_type == "series" for c in result)

    def test_tag_type_none_returns_all(self, conn):
        _add_alias(conn, "BlueArchive", "Blue Archive", tag_type="series")
        _add_alias(conn, "BlueChar", "BlueChar", tag_type="character")
        result = suggest_tag_completions(conn, "Blue")
        types = {c.tag_type for c in result}
        assert {"series", "character"}.issubset(types)

    def test_invalid_tag_type_returns_empty(self, conn):
        _add_alias(conn, "Blue", "Blue", tag_type="series")
        result = suggest_tag_completions(conn, "Blue", tag_type="invalid_type")
        assert result == ()


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------

class TestDedupe:
    def test_same_canonical_dedupe_to_one(self, conn):
        # 동일 canonical 을 alias + localization 양쪽에 등록.
        _add_alias(conn, "陸八魔アル", "陸八魔アル", parent_series="Blue Archive")
        _add_loc(conn, "陸八魔アル", "陸八魔アル", "ja", parent_series="Blue Archive")
        result = suggest_tag_completions(conn, "陸八魔アル")
        # 같은 (canonical, tag_type, parent_series) 는 1개만 남는다.
        same = [c for c in result if c.canonical == "陸八魔アル"]
        assert len(same) == 1

    def test_dedupe_keeps_highest_confidence(self, conn):
        # 두 source 가 같은 canonical 을 가리키면 source 우선순위 높은 게 보존.
        _add_alias(conn, "陸八魔アル", "陸八魔アル", parent_series="Blue Archive",
                   source="user_confirmed")
        _add_loc(conn, "陸八魔アル", "陸八魔アル", "ja", parent_series="Blue Archive",
                 source="some_unknown_source")
        result = suggest_tag_completions(conn, "陸八魔アル")
        same = [c for c in result if c.canonical == "陸八魔アル"]
        assert len(same) == 1
        assert same[0].source == "user_confirmed"


# ---------------------------------------------------------------------------
# Locale priority
# ---------------------------------------------------------------------------

class TestLocalePriority:
    def test_korean_query_prefers_ko_display(self, conn):
        # 같은 canonical, ko 와 ja 양쪽 localization 등록.
        _add_loc(conn, "陸八魔アル", "리쿠하치마 아루", "ko", parent_series="Blue Archive")
        _add_loc(conn, "陸八魔アル", "リクハチマアル", "ja", parent_series="Blue Archive")
        # 사용자가 한국어로 입력 — 매칭은 ko 만 되지만, locale bonus 까지 검증.
        result = suggest_tag_completions(conn, "리쿠")
        assert result
        top = result[0]
        assert top.locale == "ko"

    def test_japanese_query_prefers_ja_display(self, conn):
        _add_loc(conn, "陸八魔アル", "리쿠하치마 아루", "ko", parent_series="Blue Archive")
        _add_loc(conn, "陸八魔アル", "リクハチマアル", "ja", parent_series="Blue Archive")
        result = suggest_tag_completions(conn, "リクハチマ")
        assert result
        top = result[0]
        assert top.locale == "ja"

    def test_ascii_query_prefers_alias_canonical(self, conn):
        # 같은 canonical 에 ko localization + alias 등록.
        _add_alias(conn, "Rikuhachima Aru", "陸八魔アル", parent_series="Blue Archive")
        _add_loc(conn, "陸八魔アル", "리쿠하치마 아루", "ko", parent_series="Blue Archive")
        result = suggest_tag_completions(conn, "Rikuhachima")
        assert result
        top = result[0]
        assert top.locale == "alias"


# ---------------------------------------------------------------------------
# Source priority
# ---------------------------------------------------------------------------

class TestSourcePriority:
    def test_user_confirmed_outranks_built_in(self, conn):
        # 같은 입력을 두 alias 가 정확 매칭 — user_confirmed 가 위에 와야 한다.
        _add_alias(conn, "Blue Archive", "Blue ArchiveA", tag_type="series",
                   source="built_in")
        _add_alias(conn, "Blue Archive", "Blue ArchiveB", tag_type="series",
                   source="user_confirmed", parent_series="dummy")
        result = suggest_tag_completions(conn, "Blue Archive")
        # user_confirmed 가 더 높은 confidence
        sources_in_order = [c.source for c in result]
        assert sources_in_order.index("user_confirmed") < sources_in_order.index("built_in")

    def test_built_in_pack_outranks_imported_localized_pack(self, conn):
        _add_loc(conn, "X", "Aname", "en", source="imported_localized_pack")
        _add_loc(conn, "Y", "Aname", "en", source="built_in_pack:test",
                 parent_series="other")
        result = suggest_tag_completions(conn, "Aname")
        sources = [c.source for c in result]
        # built_in_pack 이 imported_localized_pack 보다 위에 있어야 한다.
        assert sources.index("built_in_pack:test") < sources.index("imported_localized_pack")

    def test_unknown_source_lowest(self, conn):
        _add_alias(conn, "Aone", "OneCanon", source="some_unknown_source")
        _add_alias(conn, "Aone", "OneCanon2", source="user_confirmed", parent_series="x")
        result = suggest_tag_completions(conn, "Aone")
        sources = [c.source for c in result]
        assert sources[0] == "user_confirmed"


# ---------------------------------------------------------------------------
# Mojibake 후보
# ---------------------------------------------------------------------------

class TestMojibakeFiltering:
    def test_mojibake_canonical_pushed_to_bottom(self, conn):
        _add_alias(conn, "MojiPrefix", "??? broken ???", parent_series="X",
                   source="built_in_pack:test")
        _add_alias(conn, "MojiPrefix2", "Clean Canon", parent_series="X",
                   source="built_in_pack:test")
        result = suggest_tag_completions(conn, "MojiPrefix")
        # mojibake canonical 후보는 정상 후보보다 아래.
        canon_order = [c.canonical for c in result]
        clean_idx = canon_order.index("Clean Canon")
        moji_idx = canon_order.index("??? broken ???")
        assert clean_idx < moji_idx


# ---------------------------------------------------------------------------
# 일본어 장음부호 variant
# ---------------------------------------------------------------------------

class TestLongVowelVariant:
    def test_trailing_long_vowel_variant_match(self, conn):
        # alias 에는 ー 없이 등록, 입력은 끝에 ー.
        _add_alias(conn, "ブル", "Blue Archive", tag_type="series")
        result = suggest_tag_completions(conn, "ブルー")
        assert any(c.canonical == "Blue Archive" for c in result)

    def test_long_vowel_variant_kind_marked(self, conn):
        _add_alias(conn, "ブル", "Blue Archive", tag_type="series")
        result = suggest_tag_completions(conn, "ブルー")
        match = next(c for c in result if c.canonical == "Blue Archive")
        assert match.match_kind == "long_vowel"


# ---------------------------------------------------------------------------
# hyphen ↔ long vowel mark invariant
# ---------------------------------------------------------------------------

class TestHyphenLongVowelInvariant:
    def test_hyphen_query_does_not_match_long_vowel_alias(self, conn):
        # alias 에 ー (U+30FC), 입력에 - (U+002D).
        _add_alias(conn, "ブルー", "Blue Archive", tag_type="series")
        result = suggest_tag_completions(conn, "ブル-")
        # hyphen 입력으로는 long-vowel alias 매칭 불가.
        assert all(c.canonical != "Blue Archive" for c in result)

    def test_long_vowel_query_does_not_match_hyphen_alias(self, conn):
        _add_alias(conn, "ブル-", "Blue Dash", tag_type="series")
        result = suggest_tag_completions(conn, "ブルー")
        assert all(c.canonical != "Blue Dash" for c in result)


# ---------------------------------------------------------------------------
# Match kind ordering — exact > prefix > contains
# ---------------------------------------------------------------------------

class TestMatchKindOrdering:
    def test_exact_outranks_prefix(self, conn):
        # alias "Blue" 정확 매칭 + alias "Bluebird" prefix 매칭.
        _add_alias(conn, "Blue", "Blue Canon", tag_type="series",
                   source="built_in_pack:test")
        _add_alias(conn, "Bluebird", "Bluebird Canon", tag_type="series",
                   source="built_in_pack:test")
        result = suggest_tag_completions(conn, "Blue")
        # 정확 매칭 (Blue Canon) 이 위.
        canon_order = [c.canonical for c in result]
        assert canon_order.index("Blue Canon") < canon_order.index("Bluebird Canon")

    def test_prefix_outranks_contains(self, conn):
        # prefix 매칭 후보 vs contains 만 매칭되는 후보.
        _add_alias(conn, "ArchiveBlue", "ContainsCanon", tag_type="series",
                   source="built_in_pack:test")
        _add_alias(conn, "BlueChar", "PrefixCanon", tag_type="series",
                   source="built_in_pack:test")
        result = suggest_tag_completions(conn, "Blue")
        canon_order = [c.canonical for c in result]
        assert canon_order.index("PrefixCanon") < canon_order.index("ContainsCanon")


# ---------------------------------------------------------------------------
# Limit / empty
# ---------------------------------------------------------------------------

class TestLimitAndEmpty:
    def test_limit_applied(self, conn):
        for i in range(10):
            _add_alias(conn, f"BlueA{i}", f"Canon{i}", tag_type="series",
                       source="built_in_pack:test", parent_series=f"P{i}")
        result = suggest_tag_completions(conn, "Blue", limit=3)
        assert len(result) == 3

    def test_zero_limit_returns_empty(self, conn):
        _add_alias(conn, "Blue", "Blue Canon")
        assert suggest_tag_completions(conn, "Blue", limit=0) == ()

    def test_empty_query_returns_empty(self, conn):
        _add_alias(conn, "Blue", "Blue Canon")
        assert suggest_tag_completions(conn, "") == ()
        assert suggest_tag_completions(conn, "   ") == ()
        assert suggest_tag_completions(conn, None) == ()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Read-only / metadata 보존
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_no_db_writes(self, conn):
        _add_alias(conn, "Blue", "Blue Canon", tag_type="series")
        _add_loc(conn, "Blue Canon", "블루", "ko", tag_type="series")

        before_aliases = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        before_locs = conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]

        suggest_tag_completions(conn, "Blue", limit=10)
        suggest_tag_completions(conn, "블루", limit=10)
        suggest_tag_completions(conn, "ブルー", limit=10)

        after_aliases = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        after_locs = conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]
        assert after_aliases == before_aliases
        assert after_locs == before_locs

    def test_returns_frozen_dataclass(self, conn):
        _add_alias(conn, "Blue", "Blue Canon", tag_type="series")
        result = suggest_tag_completions(conn, "Blue")
        assert isinstance(result[0], TagAutocompleteCandidate)
        with pytest.raises((AttributeError, Exception)):
            result[0].canonical = "X"  # type: ignore[misc]

    def test_metadata_preserved(self, conn):
        _add_alias(conn, "陸八魔アル", "陸八魔アル", tag_type="character",
                   parent_series="Blue Archive", source="built_in_pack:test")
        result = suggest_tag_completions(conn, "陸八魔アル")
        c = result[0]
        assert c.canonical == "陸八魔アル"
        assert c.tag_type == "character"
        assert c.parent_series == "Blue Archive"
        assert c.source == "built_in_pack:test"
        # secondary_text 에 위 정보가 모두 들어 있어야 한다.
        assert "陸八魔アル" in c.secondary_text
        assert "character" in c.secondary_text
        assert "Blue Archive" in c.secondary_text
        assert "built_in_pack:test" in c.secondary_text

    def test_row_factory_restored_after_call(self, conn):
        # 호출자가 다른 row_factory 를 쓰고 있었다면 그대로 복원돼야 한다.
        sentinel = lambda cursor, row: dict(zip([d[0] for d in cursor.description], row))
        conn.row_factory = sentinel
        _add_alias(conn, "Blue", "Blue Canon")
        suggest_tag_completions(conn, "Blue")
        assert conn.row_factory is sentinel
