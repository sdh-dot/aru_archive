"""Genshin Impact tag pack 정책 검증 테스트.

보장 사항:
1. series ko display → "원신"
2. 1차 seed (Mondstadt 18인) ko locale resolve 정확성
3. Mondstadt 18인 parent_series = Genshin Impact
4. 단일명 alias 전역 미등록 (Jean '진', Xiao '소')
5. 원소/무기/지역명은 character로 등록되지 않음
6. hold/needs_review 항목(Xiao)은 seed에 없음
7. JSON 파일에 character 수가 25개임
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database

PACK_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"
GENSHIN_PACK = PACK_DIR / "genshin_impact.json"
CANONICAL_SERIES = "Genshin Impact"

MONDSTADT_KO = [
    "앰버", "바바라", "베넷", "딜럭", "디오나", "유라", "피슐",
    "진", "카에야", "클레", "리사", "모나", "노엘", "레이저",
    "로자리아", "슈크로스", "벤티", "알베도",
]

MONDSTADT_CANONICAL = [
    "Amber", "Barbara", "Bennett", "Diluc", "Diona", "Eula", "Fischl",
    "Jean", "Kaeya", "Klee", "Lisa", "Mona", "Noelle", "Razor",
    "Rosaria", "Sucrose", "Venti", "Albedo",
]

# 단일명 alias가 등록되어선 안 되는 값들
FORBIDDEN_SINGLE_ALIASES = [
    "진",   # Jean — 1음절 단일명
    "소",   # Xiao — 1음절 단일명 (hold 상태, 미seed)
]

# character로 등록되어선 안 되는 원소/지역/무기명
NON_CHARACTER_TAGS = [
    "Pyro", "Anemo", "Geo", "Electro", "Hydro", "Cryo", "Dendro",
    "Mondstadt", "Liyue", "Inazuma", "Sumeru", "Fontaine", "Natlan",
    "Sword", "Claymore", "Polearm", "Bow", "Catalyst",
]


@pytest.fixture()
def db(tmp_path):
    conn = initialize_database(str(tmp_path / "test.db"))
    seed_tag_pack(conn, load_tag_pack(GENSHIN_PACK))
    yield conn
    conn.close()


# ---------- 1. Series ko display ----------

def test_genshin_series_ko_display(db):
    """Genshin Impact series ko display는 '원신'이어야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE canonical=? AND tag_type='series' AND locale='ko'",
        (CANONICAL_SERIES,),
    ).fetchone()
    assert row is not None, "Genshin Impact series ko localization 없음"
    assert row[0] == "원신", f"ko display 불일치: {row[0]!r}"


# ---------- 2. Mondstadt 18인 ko locale resolve ----------

@pytest.mark.parametrize("ko_name", MONDSTADT_KO)
def test_mondstadt_character_ko_display(db, ko_name):
    """Mondstadt 캐릭터가 ko locale에서 display_name으로 등록되어야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE display_name=? AND locale='ko'",
        (ko_name,),
    ).fetchone()
    assert row is not None, f"ko display_name {ko_name!r} 가 tag_localizations에 없음"


# ---------- 3. Mondstadt 18인 parent_series = Genshin Impact ----------

@pytest.mark.parametrize("canonical", MONDSTADT_CANONICAL)
def test_mondstadt_character_parent_series(db, canonical):
    """Mondstadt 캐릭터의 parent_series는 Genshin Impact여야 한다."""
    row = db.execute(
        "SELECT parent_series FROM tag_aliases "
        "WHERE canonical=? AND tag_type='character' AND enabled=1 LIMIT 1",
        (canonical,),
    ).fetchone()
    assert row is not None, f"{canonical!r} 가 tag_aliases에 없음"
    assert row[0] == CANONICAL_SERIES, (
        f"{canonical!r} parent_series={row[0]!r}, 기대값={CANONICAL_SERIES!r}"
    )


# ---------- 4. 단일명 alias 전역 미등록 ----------

@pytest.mark.parametrize("single_name", FORBIDDEN_SINGLE_ALIASES)
def test_single_name_not_global_character_alias(db, single_name):
    """단일명은 전역 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (single_name,),
    ).fetchone()
    assert row is None, (
        f"단일명 {single_name!r} 가 character alias로 존재함 → canonical={row[0] if row else None}"
    )


# ---------- 5. 원소/지역/무기명은 character로 미등록 ----------

@pytest.mark.parametrize("non_char", NON_CHARACTER_TAGS)
def test_non_character_tags_not_in_character_aliases(db, non_char):
    """원소/지역/무기명은 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (non_char,),
    ).fetchone()
    assert row is None, f"'{non_char}' 이 character alias로 등록됨 — 정책 위반"


# ---------- 6. hold 항목(Xiao)은 미seed ----------

def test_xiao_not_seeded(db):
    """Xiao(소)는 needs_review 상태로 DB에 없어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE canonical='Xiao' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is None, "Xiao 가 character alias로 seed됨 — needs_review 상태여야 함"


# ---------- 7. JSON 파일 character 수 검증 ----------

def test_genshin_pack_has_25_characters():
    """genshin_impact.json에는 캐릭터가 25명이어야 한다 (기존 7 + Mondstadt 18)."""
    data = json.loads(GENSHIN_PACK.read_text(encoding="utf-8"))
    assert len(data.get("characters", [])) == 25, (
        f"character 수 불일치: {len(data.get('characters', []))} (기대값 25)"
    )


def test_genshin_pack_version():
    """genshin_impact.json 버전은 1.2.0이어야 한다."""
    data = json.loads(GENSHIN_PACK.read_text(encoding="utf-8"))
    assert data["version"] == "1.2.0"


def test_jean_ko_in_localizations_not_aliases():
    """Jean의 KO 이름 '진'은 localizations에 있지만 aliases에는 없어야 한다."""
    data = json.loads(GENSHIN_PACK.read_text(encoding="utf-8"))
    jean = next(c for c in data["characters"] if c["canonical"] == "Jean")
    assert jean["localizations"]["ko"] == "진"
    assert "진" not in jean["aliases"], "'진' 이 Jean aliases에 포함됨 — 단일명 정책 위반"


# ---------- 기존 캐릭터(7인) 유지 확인 ----------

@pytest.mark.parametrize("canonical,ko", [
    ("Hu Tao", "호두"),
    ("Keqing", "각청"),
    ("Ganyu", "감우"),
    ("Zhongli", "종리"),
    ("Raiden Shogun", "라이덴 쇼군"),
    ("Nahida", "나히다"),
    ("Furina", "후리나"),
])
def test_existing_characters_preserved(db, canonical, ko):
    """기존 7인 캐릭터가 DB에 유지되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (ko,),
    ).fetchone()
    assert row is not None, f"기존 캐릭터 alias '{ko}' 없음"
    assert row[0] == canonical
