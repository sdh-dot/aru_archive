"""tests/test_tag_localizer.py — tag_localizer 모듈 단위 테스트."""
from __future__ import annotations

import sqlite3

import pytest

from core.tag_localizer import (
    BUILTIN_LOCALIZATIONS,
    list_localizations,
    resolve_display_name,
    resolve_display_name_with_info,
    seed_builtin_localizations,
    upsert_localization,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
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
        CREATE INDEX idx_tag_local_canonical ON tag_localizations(canonical, tag_type);
        CREATE INDEX idx_tag_local_locale    ON tag_localizations(locale, enabled);
    """)
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(mem_db):
    seed_builtin_localizations(mem_db)
    return mem_db


# ---------------------------------------------------------------------------
# BUILTIN_LOCALIZATIONS 내용 확인
# ---------------------------------------------------------------------------

def test_builtin_contains_blue_archive_ko():
    series_entries = [
        e for e in BUILTIN_LOCALIZATIONS
        if e["canonical"] == "Blue Archive" and e["locale"] == "ko"
    ]
    assert series_entries, "Blue Archive ko 항목이 없음"
    assert series_entries[0]["display_name"] == "블루 아카이브"


def test_builtin_contains_characters():
    chars = {e["canonical"] for e in BUILTIN_LOCALIZATIONS if e["tag_type"] == "character"}
    assert "陸八魔アル" in chars
    assert "砂狼シロコ" in chars


# ---------------------------------------------------------------------------
# seed_builtin_localizations
# ---------------------------------------------------------------------------

def test_seed_returns_count(mem_db):
    n = seed_builtin_localizations(mem_db)
    assert n > 0


def test_seed_is_idempotent(mem_db):
    n1 = seed_builtin_localizations(mem_db)
    n2 = seed_builtin_localizations(mem_db)
    assert n1 > 0
    assert n2 == 0  # INSERT OR IGNORE → 두 번째엔 0


def test_seed_persists_to_db(seeded_db):
    rows = seeded_db.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]
    assert rows > 0


# ---------------------------------------------------------------------------
# resolve_display_name — canonical locale
# ---------------------------------------------------------------------------

def test_canonical_locale_returns_canonical(seeded_db):
    name = resolve_display_name(
        seeded_db, "Blue Archive", "series",
        parent_series="", locale="canonical", fallback_locale="canonical",
    )
    assert name == "Blue Archive"


def test_canonical_locale_no_db_lookup(seeded_db):
    # canonical이면 DB 조회 없이 바로 canonical 반환
    name = resolve_display_name(
        seeded_db, "NonExistentSeries", "series",
        parent_series="", locale="canonical", fallback_locale="canonical",
    )
    assert name == "NonExistentSeries"


# ---------------------------------------------------------------------------
# resolve_display_name — ko locale (builtin)
# ---------------------------------------------------------------------------

def test_ko_series_from_builtin(seeded_db):
    name = resolve_display_name(
        seeded_db, "Blue Archive", "series",
        parent_series="", locale="ko", fallback_locale="canonical",
    )
    assert name == "블루 아카이브"


def test_ko_character_from_builtin(seeded_db):
    name = resolve_display_name(
        seeded_db, "陸八魔アル", "character",
        parent_series="Blue Archive", locale="ko", fallback_locale="canonical",
    )
    assert name == "리쿠하치마 아루"


def test_ko_missing_falls_back_to_canonical(seeded_db):
    name = resolve_display_name(
        seeded_db, "UnknownChar", "character",
        parent_series="", locale="ko", fallback_locale="canonical",
    )
    assert name == "UnknownChar"


# ---------------------------------------------------------------------------
# resolve_display_name_with_info — fallback 표시
# ---------------------------------------------------------------------------

def test_with_info_no_fallback(seeded_db):
    display, used_fallback = resolve_display_name_with_info(
        seeded_db, "Blue Archive", "series",
        parent_series="", locale="ko", fallback_locale="canonical",
    )
    assert display == "블루 아카이브"
    assert used_fallback is False


def test_with_info_used_fallback(seeded_db):
    display, used_fallback = resolve_display_name_with_info(
        seeded_db, "MissingTag", "character",
        parent_series="", locale="ko", fallback_locale="canonical",
    )
    assert display == "MissingTag"
    assert used_fallback is True


# ---------------------------------------------------------------------------
# DB override — upsert_localization
# ---------------------------------------------------------------------------

def test_db_override_builtin(seeded_db):
    upsert_localization(
        seeded_db, "Blue Archive", "series", "ko", "커스텀 시리즈",
        parent_series="", source="test",
    )
    name = resolve_display_name(
        seeded_db, "Blue Archive", "series",
        parent_series="", locale="ko", fallback_locale="canonical",
    )
    assert name == "커스텀 시리즈"


def test_upsert_new_character(seeded_db):
    upsert_localization(
        seeded_db, "新キャラ", "character", "ko", "신 캐릭터",
        parent_series="Blue Archive", source="test",
    )
    name = resolve_display_name(
        seeded_db, "新キャラ", "character",
        parent_series="Blue Archive", locale="ko", fallback_locale="canonical",
    )
    assert name == "신 캐릭터"


# ---------------------------------------------------------------------------
# list_localizations
# ---------------------------------------------------------------------------

def test_list_all(seeded_db):
    rows = list_localizations(seeded_db)
    assert len(rows) > 0
    assert "canonical" in rows[0]
    assert "display_name" in rows[0]


def test_list_filter_locale(seeded_db):
    rows = list_localizations(seeded_db, locale="ko")
    locales = {r["locale"] for r in rows}
    assert locales == {"ko"}


# ---------------------------------------------------------------------------
# parent_series 매칭
# ---------------------------------------------------------------------------

def test_character_parent_series_match(seeded_db):
    # 같은 canonical이지만 parent_series가 다른 캐릭터를 추가해 분리 확인
    upsert_localization(
        seeded_db, "TestChar", "character", "ko", "시리즈A 캐릭터",
        parent_series="SeriesA", source="test",
    )
    upsert_localization(
        seeded_db, "TestChar", "character", "ko", "시리즈B 캐릭터",
        parent_series="SeriesB", source="test",
    )
    name_a = resolve_display_name(
        seeded_db, "TestChar", "character",
        parent_series="SeriesA", locale="ko", fallback_locale="canonical",
    )
    name_b = resolve_display_name(
        seeded_db, "TestChar", "character",
        parent_series="SeriesB", locale="ko", fallback_locale="canonical",
    )
    assert name_a == "시리즈A 캐릭터"
    assert name_b == "시리즈B 캐릭터"
