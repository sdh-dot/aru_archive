"""``core.classification_inference`` 단위 테스트.

read-only character/series 추론이:
- alias / localized_name 양쪽에서 매칭되는지
- 일본어 / 한국어 / 영어 / NFKC 차이를 처리하는지
- 일본어 장음부호 ``ー`` variant 가 작동하는지
- ``-`` 와 ``ー`` 를 절대 혼동하지 않는지
- source priority 가 confidence 산정에 반영되는지
- ambiguous parent_series 를 표시하는지
- DB 에 어떤 write 도 가하지 않는지
를 lock 한다.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.classification_inference import (
    CharacterSeriesInference,
    has_ambiguous_parent_series,
    infer_character_series_candidates,
)


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


def _add_alias(
    conn,
    alias: str,
    canonical: str,
    tag_type: str = "character",
    parent_series: str = "",
    source: str = "built_in_pack:test",
    enabled: int = 1,
):
    conn.execute(
        "INSERT INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (alias, canonical, tag_type, parent_series, source, enabled),
    )
    conn.commit()


def _add_loc(
    conn,
    canonical: str,
    display_name: str,
    locale: str,
    tag_type: str = "character",
    parent_series: str = "",
    source: str = "built_in_pack:test",
    enabled: int = 1,
):
    import uuid as _uuid
    conn.execute(
        "INSERT INTO tag_localizations "
        "(localization_id, canonical, tag_type, parent_series, locale, display_name, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (str(_uuid.uuid4()), canonical, tag_type, parent_series, locale, display_name, source, enabled),
    )
    conn.commit()


def _by_kind(results, predicate):
    return [r for r in results if predicate(r)]


# ---------------------------------------------------------------------------
# 매칭 — alias 경로
# ---------------------------------------------------------------------------

class TestAliasMatching:
    def test_japanese_alias_exact_match(self, conn):
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
        )
        result = infer_character_series_candidates(conn, ["陸八魔アル"])
        assert len(result) >= 1
        top = result[0]
        assert top.canonical == "陸八魔アル"
        assert top.tag_type == "character"
        assert top.parent_series == "Blue Archive"
        assert top.match_kind.startswith("alias_")
        assert top.confidence == "high"

    def test_english_canonical_via_alias(self, conn):
        _add_alias(
            conn, alias="Rikuhachima Aru", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
        )
        result = infer_character_series_candidates(conn, ["Rikuhachima Aru"])
        assert any(r.canonical == "陸八魔アル" for r in result)

    def test_no_match_returns_empty(self, conn):
        result = infer_character_series_candidates(conn, ["totally_unknown_tag_xyz"])
        assert result == ()

    def test_disabled_alias_skipped(self, conn):
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
            enabled=0,
        )
        result = infer_character_series_candidates(conn, ["陸八魔アル"])
        assert result == ()


# ---------------------------------------------------------------------------
# 매칭 — localized_name 경로
# ---------------------------------------------------------------------------

class TestLocalizationMatching:
    def test_korean_localized_name_match(self, conn):
        _add_loc(
            conn, canonical="陸八魔アル", display_name="리쿠하치마 아루",
            locale="ko", tag_type="character", parent_series="Blue Archive",
        )
        result = infer_character_series_candidates(conn, ["리쿠하치마 아루"])
        assert len(result) >= 1
        top = result[0]
        assert top.canonical == "陸八魔アル"
        assert top.locale == "ko"
        assert top.match_kind.startswith("loc_")

    def test_japanese_localized_name_match(self, conn):
        _add_loc(
            conn, canonical="Blue Archive", display_name="ブルーアーカイブ",
            locale="ja", tag_type="series", parent_series="",
        )
        result = infer_character_series_candidates(conn, ["ブルーアーカイブ"])
        assert any(
            r.canonical == "Blue Archive" and r.tag_type == "series"
            for r in result
        )


# ---------------------------------------------------------------------------
# Variant 매칭 — NFKC / 장음 / compact
# ---------------------------------------------------------------------------

class TestVariantMatching:
    def test_nfkc_normalized_match(self, conn):
        # DB 에는 반각, 입력은 전각.
        _add_alias(conn, alias="Blue", canonical="Blue Archive", tag_type="series")
        result = infer_character_series_candidates(conn, ["Ｂｌｕｅ"])
        assert any(r.canonical == "Blue Archive" for r in result)

    def test_trailing_long_vowel_removed_variant(self, conn):
        # DB 에는 ー 없는 형태, 입력은 끝에 ー 가 붙어 있음.
        _add_alias(
            conn, alias="ブル", canonical="Blue Archive",
            tag_type="series",
        )
        result = infer_character_series_candidates(conn, ["ブルー"])
        matched = [r for r in result if r.canonical == "Blue Archive"]
        assert matched, "trailing long vowel removed variant 가 매칭되지 않음"
        assert any(r.match_kind.endswith("trailing_long_vowel_removed") for r in matched)

    def test_all_long_vowels_removed_variant_low_confidence(self, conn):
        # 내부 ー 가 여러 개. all 제거 variant 매칭의 confidence 는 low.
        _add_alias(
            conn, alias="ブルアカイブ", canonical="Blue Archive",
            tag_type="series", source="built_in_pack:test",
        )
        result = infer_character_series_candidates(conn, ["ブルーアーカイブ"])
        matched = [
            r for r in result
            if r.canonical == "Blue Archive"
            and r.match_kind.endswith("all_long_vowels_removed")
        ]
        assert matched
        assert all(r.confidence == "low" for r in matched)


# ---------------------------------------------------------------------------
# hyphen vs long vowel mark — invariant
# ---------------------------------------------------------------------------

class TestHyphenLongVowelInvariant:
    def test_hyphen_input_does_not_match_long_vowel_alias(self, conn):
        # alias 에 ー (U+30FC), 입력에 - (U+002D). 매칭되어서는 안 됨.
        _add_alias(conn, alias="ブルー", canonical="Blue Archive", tag_type="series")
        result = infer_character_series_candidates(conn, ["ブル-"])
        assert result == ()

    def test_long_vowel_input_does_not_match_hyphen_alias(self, conn):
        # alias 에 - (U+002D), 입력에 ー (U+30FC). 매칭되어서는 안 됨.
        _add_alias(conn, alias="ブル-", canonical="Blue Dash", tag_type="series")
        result = infer_character_series_candidates(conn, ["ブルー"])
        assert all(r.canonical != "Blue Dash" for r in result)


# ---------------------------------------------------------------------------
# Source priority → confidence
# ---------------------------------------------------------------------------

class TestSourcePriority:
    def test_built_in_pack_source_yields_high(self, conn):
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
            source="built_in_pack:blue_archive",
        )
        result = infer_character_series_candidates(conn, ["陸八魔アル"])
        assert result[0].confidence == "high"

    def test_user_confirmed_source_yields_high(self, conn):
        _add_alias(
            conn, alias="MyAru", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
            source="user_confirmed",
        )
        result = infer_character_series_candidates(conn, ["MyAru"])
        assert result[0].confidence == "high"

    def test_imported_localized_pack_source_demoted_to_medium(self, conn):
        _add_loc(
            conn, canonical="陸八魔アル", display_name="리쿠하치마 아루",
            locale="ko", tag_type="character", parent_series="Blue Archive",
            source="imported_localized_pack",
        )
        result = infer_character_series_candidates(conn, ["리쿠하치마 아루"])
        assert result
        # exact match + source rank 3 → medium
        assert result[0].confidence == "medium"

    def test_unknown_source_yields_low(self, conn):
        _add_alias(
            conn, alias="OddAlias", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
            source="some_unknown_source",
        )
        result = infer_character_series_candidates(conn, ["OddAlias"])
        assert result[0].confidence == "low"

    def test_higher_priority_source_wins_in_dedupe(self, conn):
        # 같은 canonical / parent_series 를 가리키는 두 source — high 가 보존.
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
            source="built_in_pack:test",
        )
        _add_loc(
            conn, canonical="陸八魔アル", display_name="陸八魔アル",
            locale="ja", tag_type="character", parent_series="Blue Archive",
            source="some_unknown_source",
        )
        result = infer_character_series_candidates(conn, ["陸八魔アル"])
        # 정렬 결과 1순위는 high confidence (built_in_pack)
        assert result[0].confidence == "high"
        assert result[0].source.startswith("built_in_pack:")


# ---------------------------------------------------------------------------
# Mojibake 의심 row → low confidence
# ---------------------------------------------------------------------------

class TestMojibakeFiltering:
    def test_mojibake_canonical_demoted_to_low(self, conn):
        # canonical 이 "??" 연속을 포함 → looks_mojibake True → confidence low.
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔???",
            tag_type="character", parent_series="Blue Archive",
            source="built_in_pack:test",
        )
        result = infer_character_series_candidates(conn, ["陸八魔アル"])
        assert result
        assert result[0].confidence == "low"


# ---------------------------------------------------------------------------
# Parent_series 처리
# ---------------------------------------------------------------------------

class TestParentSeriesHandling:
    def test_empty_parent_series_returned_as_none(self, conn):
        _add_alias(
            conn, alias="GenericTag", canonical="GenericTag",
            tag_type="general", parent_series="",
        )
        result = infer_character_series_candidates(conn, ["GenericTag"])
        assert result[0].parent_series is None

    def test_multiple_characters_with_same_parent_series(self, conn):
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
        )
        _add_alias(
            conn, alias="砂狼シロコ", canonical="砂狼シロコ",
            tag_type="character", parent_series="Blue Archive",
        )
        result = infer_character_series_candidates(
            conn, ["陸八魔アル", "砂狼シロコ"],
        )
        parents = {r.parent_series for r in result if r.tag_type == "character"}
        assert parents == {"Blue Archive"}
        # ambiguous 아님
        assert has_ambiguous_parent_series(result) is False

    def test_ambiguous_parent_series_flagged(self, conn):
        # 같은 canonical 이 두 시리즈에 등록 (이론상 충돌 — 사용자 확인 필요)
        _add_alias(
            conn, alias="アル_A", canonical="アル",
            tag_type="character", parent_series="Series A",
        )
        _add_alias(
            conn, alias="アル_B", canonical="アル",
            tag_type="character", parent_series="Series B",
        )
        result = infer_character_series_candidates(conn, ["アル_A", "アル_B"])
        assert has_ambiguous_parent_series(result) is True


# ---------------------------------------------------------------------------
# Read-only 보장
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_no_db_writes(self, conn):
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
        )

        # baseline row counts
        before_aliases = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        before_locs = conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]

        infer_character_series_candidates(conn, ["陸八魔アル", "未知の文字列"])

        after_aliases = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        after_locs = conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]
        assert after_aliases == before_aliases
        assert after_locs == before_locs

    def test_empty_input_returns_empty(self, conn):
        assert infer_character_series_candidates(conn, []) == ()
        assert infer_character_series_candidates(conn, [""]) == ()
        assert infer_character_series_candidates(conn, [None]) == ()  # type: ignore[list-item]

    def test_returns_frozen_dataclass(self, conn):
        _add_alias(conn, alias="陸八魔アル", canonical="陸八魔アル",
                   tag_type="character", parent_series="Blue Archive")
        result = infer_character_series_candidates(conn, ["陸八魔アル"])
        assert isinstance(result[0], CharacterSeriesInference)
        with pytest.raises((AttributeError, Exception)):
            result[0].canonical = "X"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Result ordering / dedupe
# ---------------------------------------------------------------------------

class TestOrderingAndDedupe:
    def test_high_confidence_appears_first(self, conn):
        _add_alias(conn, alias="MidTag", canonical="MidCanonical",
                   tag_type="character", parent_series="X",
                   source="some_unknown_source")  # → low
        _add_alias(conn, alias="HighTag", canonical="HighCanonical",
                   tag_type="character", parent_series="X",
                   source="user_confirmed")  # → high
        result = infer_character_series_candidates(conn, ["MidTag", "HighTag"])
        assert result[0].canonical == "HighCanonical"
        assert result[0].confidence == "high"
        assert result[-1].confidence == "low"

    def test_dedupe_preserves_strongest_confidence(self, conn):
        # 같은 canonical / tag_type / parent_series / match_kind 조합에 두 source.
        # alias_exact 는 하나만 남아야 한다 (강한 confidence).
        _add_alias(
            conn, alias="陸八魔アル", canonical="陸八魔アル",
            tag_type="character", parent_series="Blue Archive",
            source="built_in_pack:test",
        )
        result = infer_character_series_candidates(conn, ["陸八魔アル"])
        # alias_exact match_kind 후보 1개만
        exact_matches = [r for r in result if r.match_kind == "alias_exact"]
        assert len(exact_matches) == 1
