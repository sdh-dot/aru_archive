"""Honkai: Star Rail tag pack 정책 검증 테스트.

Phase B1 seed: Astral Express 5 + Belobog 10 = 15인 (기존 5인 포함 총 20인)

검증 범위:
1. series ko display → "붕괴: 스타레일"
2. 15 seeded chars ko display_name 등록
3. 15 seeded chars parent_series = "Honkai: Star Rail"
4. 삼칠이 / 단항 alias resolve
5. 훅(Hook) 1음절 KO → aliases 미포함, localizations.ko에만 보존
6. Trailblazer(개척자) 미 seed 확인
7. 비캐릭터 태그가 character alias로 등록되지 않음
8. JSON 구조: 캐릭터 20인, version 1.2.0
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database

PACK_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"
HSR_PACK = PACK_DIR / "honkai_star_rail.json"

CANONICAL_SERIES = "Honkai: Star Rail"

ASTRAL_SEEDED_KO = ["삼칠이", "단항", "히메코", "웰트", "아스타"]
ASTRAL_SEEDED_CANONICAL = ["March 7th", "Dan Heng", "Himeko", "Welt", "Asta"]

BELOBOG_SEEDED_KO = ["게파르트", "펠라", "세르발", "나타샤", "삼포", "루카", "수상", "아를란", "린스"]
BELOBOG_SEEDED_CANONICAL = ["Gepard", "Pela", "Serval", "Natasha", "Sampo", "Luka", "Sushang", "Arlan", "Lynx"]

ALL_SEEDED_KO = ASTRAL_SEEDED_KO + BELOBOG_SEEDED_KO
ALL_SEEDED_CANONICAL = ASTRAL_SEEDED_CANONICAL + BELOBOG_SEEDED_CANONICAL

NON_CHARACTER_TAGS = [
    "붕괴: 스타레일",
    "Honkai: Star Rail",
    "스타레일",
    "Astral Express",
    "Belobog",
]


@pytest.fixture()
def db(tmp_path):
    conn = initialize_database(str(tmp_path / "test.db"))
    seed_tag_pack(conn, load_tag_pack(HSR_PACK))
    yield conn
    conn.close()


# ---------- 1. series ko display ----------

def test_hsr_series_ko_display(db):
    """Honkai: Star Rail series ko display는 '붕괴: 스타레일'이어야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE canonical=? AND tag_type='series' AND locale='ko'",
        (CANONICAL_SERIES,),
    ).fetchone()
    assert row is not None, "Honkai: Star Rail series ko localization 없음"
    assert row[0] == "붕괴: 스타레일", f"ko display 불일치: {row[0]!r}"


# ---------- 2. ko display_name 등록 ----------

@pytest.mark.parametrize("ko_name", ALL_SEEDED_KO)
def test_seeded_character_ko_display(db, ko_name):
    """seeded 캐릭터가 ko locale에서 display_name으로 등록되어야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE display_name=? AND locale='ko'",
        (ko_name,),
    ).fetchone()
    assert row is not None, f"ko display_name {ko_name!r} 가 tag_localizations에 없음"


# ---------- 3. parent_series ----------

@pytest.mark.parametrize("char_canonical", ALL_SEEDED_CANONICAL)
def test_seeded_character_parent_series(db, char_canonical):
    """seeded 캐릭터의 parent_series는 'Honkai: Star Rail'이어야 한다."""
    row = db.execute(
        "SELECT parent_series FROM tag_aliases "
        "WHERE canonical=? AND tag_type='character' AND enabled=1 LIMIT 1",
        (char_canonical,),
    ).fetchone()
    assert row is not None, f"{char_canonical!r} 가 tag_aliases에 없음"
    assert row[0] == CANONICAL_SERIES, (
        f"{char_canonical!r} parent_series={row[0]!r}, 기대값={CANONICAL_SERIES!r}"
    )


# ---------- 4. 삼칠이 / 단항 alias resolve ----------

def test_march7th_ko_alias_resolves(db):
    """'삼칠이' alias는 canonical='March 7th'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='삼칠이' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'삼칠이' alias 없음"
    assert row[0] == "March 7th", f"alias '삼칠이' → {row[0]!r}"


def test_danheng_ko_alias_resolves(db):
    """'단항' alias는 canonical='Dan Heng'으로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='단항' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'단항' alias 없음"
    assert row[0] == "Dan Heng", f"alias '단항' → {row[0]!r}"


# ---------- 5. 훅(Hook) 1음절 처리 ----------

def test_hook_ko_in_localizations(db):
    """'훅'은 localizations.ko에 등록되어 있어야 한다 (display_name)."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE canonical='Hook' AND locale='ko'",
    ).fetchone()
    assert row is not None, "Hook ko localization 없음"
    assert row[0] == "훅", f"Hook ko display={row[0]!r}"


def test_hook_ko_not_in_aliases(db):
    """'훅'(1음절)은 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='훅' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is None, f"'훅' 가 character alias로 존재함 → canonical={row[0] if row else None}"


# ---------- 6. Trailblazer 미 seed ----------

def test_trailblazer_not_seeded(db):
    """개척자(Trailblazer)는 needs_review 상태로 아직 seed되지 않아야 한다."""
    for alias in ("Trailblazer", "개척자", "開拓者"):
        row = db.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias=? AND tag_type='character' AND enabled=1",
            (alias,),
        ).fetchone()
        assert row is None, f"Trailblazer alias {alias!r} 가 등록됨 — needs_review 항목"


# ---------- 7. 비캐릭터 태그 character alias 미포함 ----------

@pytest.mark.parametrize("non_char_tag", NON_CHARACTER_TAGS)
def test_non_character_tags_not_in_character_aliases(db, non_char_tag):
    """series/그룹명 등 비캐릭터 태그는 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (non_char_tag,),
    ).fetchone()
    assert row is None, (
        f"비캐릭터 태그 {non_char_tag!r} 가 character alias로 존재함 → canonical={row[0] if row else None}"
    )


# ---------- 8. JSON 구조 검증 ----------

def test_hsr_pack_has_20_characters():
    """honkai_star_rail.json에는 캐릭터가 정확히 20명이어야 한다."""
    data = json.loads(HSR_PACK.read_text(encoding="utf-8"))
    assert len(data.get("characters", [])) == 20, (
        f"캐릭터 수 불일치: {len(data.get('characters', []))}"
    )


def test_hsr_pack_version():
    """honkai_star_rail.json version은 1.2.0이어야 한다."""
    data = json.loads(HSR_PACK.read_text(encoding="utf-8"))
    assert data["version"] == "1.2.0", f"version 불일치: {data['version']!r}"


def test_hook_aliases_exclude_ko_in_json():
    """JSON에서 Hook의 aliases에 '훅'이 포함되지 않아야 한다."""
    data = json.loads(HSR_PACK.read_text(encoding="utf-8"))
    hook = next((c for c in data["characters"] if c["canonical"] == "Hook"), None)
    assert hook is not None, "Hook 캐릭터 없음"
    assert "훅" not in hook["aliases"], f"Hook aliases에 '훅' 포함됨: {hook['aliases']}"
    assert hook["localizations"]["ko"] == "훅", "Hook localizations.ko != '훅'"


def test_hsr_pack_has_one_series():
    """honkai_star_rail.json에는 series entry가 정확히 1개여야 한다."""
    data = json.loads(HSR_PACK.read_text(encoding="utf-8"))
    assert len(data.get("series", [])) == 1
    assert data["series"][0]["canonical"] == CANONICAL_SERIES
