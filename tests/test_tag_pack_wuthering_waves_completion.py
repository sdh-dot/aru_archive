"""Wuthering Waves tag pack 정책 검증 테스트.

Gap A seed: 기존 28인 + 신규 5인 (Youhu + Roccia + Brant + Zani + Ciaccona) = 총 33인

검증 범위:
1. series ko display → "명조"
2. Gap A 신규 5인 ko display_name 등록
3. 신규 캐릭터 parent_series = "Wuthering Waves"
4. 미 seed 확인 (Rover, v2.5+ 후보, hold 대상)
5. 속성/무기/지역명은 character로 등록되지 않음
6. JSON 구조: 33인, version 1.1.0
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database

PACK_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"
WW_PACK = PACK_DIR / "wuthering_waves.json"

CANONICAL_SERIES = "Wuthering Waves"

# Gap A 신규 5인
NEW_SEEDED_KO = ["유호", "로코코", "브렌트", "젠니", "샤콘"]
NEW_SEEDED_CANONICAL = ["Youhu", "Roccia", "Brant", "Zani", "Ciaccona"]

# 기존 28인 대표 샘플 (전체 회귀)
EXISTING_SEEDED_KO = [
    "양양", "치샤", "백지", "기염", "벨리나",
    "앙코", "카카루", "음림", "감심", "능양",
    "산화", "모르테피", "단근", "알토", "도기",
    "연무", "금희", "장리", "절지", "상리요",
    "파수인", "카멜리아", "루미", "카를로타", "피비",
    "칸타렐라", "카르티시아", "루파",
]
EXISTING_SEEDED_CANONICAL = [
    "Yangyang", "Chixia", "Baizhi", "Jiyan", "Verina",
    "Encore", "Calcharo", "Yinlin", "Jianxin", "Lingyang",
    "Sanhua", "Mortefi", "Danjin", "Aalto", "Taoqi",
    "Yuanwu", "Jinhsi", "Changli", "Zhezhi", "Xiangli Yao",
    "Shorekeeper", "Camellya", "Lumi", "Carlotta", "Phoebe",
    "Cantarella", "Cartethyia", "Lupa",
]

ALL_SEEDED_KO = EXISTING_SEEDED_KO + NEW_SEEDED_KO
ALL_SEEDED_CANONICAL = EXISTING_SEEDED_CANONICAL + NEW_SEEDED_CANONICAL

# 미 seed 확인 (hold / needs_review)
NOT_SEEDED_ALIASES = [
    "Rover", "방랑자", "漂泊者",
    "Phrolova", "플로로",
    "Augusta", "아우구스타",
    "Iuno", "유노",
    "Galbrena", "갈브레나",
]

# 비캐릭터 태그 (속성/무기/지역 등)
NON_CHARACTER_TAGS = [
    "명조", "Wuthering Waves", "WuWa",
    "Glacio", "Fusion", "Electro", "Aero", "Havoc", "Spectro",
    "Sword", "Broadblade", "Pistols", "Gauntlets", "Rectifier",
]


@pytest.fixture()
def db(tmp_path):
    conn = initialize_database(str(tmp_path / "test.db"))
    seed_tag_pack(conn, load_tag_pack(WW_PACK))
    yield conn
    conn.close()


# ---------- 1. series ko display ----------

def test_ww_series_ko_display(db):
    """Wuthering Waves series ko display는 '명조'여야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE canonical=? AND tag_type='series' AND locale='ko'",
        (CANONICAL_SERIES,),
    ).fetchone()
    assert row is not None, "Wuthering Waves series ko localization 없음"
    assert row[0] == "명조", f"ko display 불일치: {row[0]!r}"


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
    """seeded 캐릭터의 parent_series는 'Wuthering Waves'여야 한다."""
    row = db.execute(
        "SELECT parent_series FROM tag_aliases "
        "WHERE canonical=? AND tag_type='character' AND enabled=1 LIMIT 1",
        (char_canonical,),
    ).fetchone()
    assert row is not None, f"{char_canonical!r} 가 tag_aliases에 없음"
    assert row[0] == CANONICAL_SERIES, (
        f"{char_canonical!r} parent_series={row[0]!r}, 기대값={CANONICAL_SERIES!r}"
    )


# ---------- 4. 미 seed 확인 ----------

@pytest.mark.parametrize("alias", NOT_SEEDED_ALIASES)
def test_hold_nr_not_seeded(db, alias):
    """hold/needs_review 항목은 character alias로 등록되지 않아야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (alias,),
    ).fetchone()
    assert row is None, (
        f"미seed 항목 {alias!r} 가 등록됨 → canonical={row[0] if row else None}"
    )


# ---------- 5. 비캐릭터 태그 character 미등록 ----------

@pytest.mark.parametrize("tag", NON_CHARACTER_TAGS)
def test_non_character_tags_not_in_character_aliases(db, tag):
    """속성/무기/지역/시리즈명은 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (tag,),
    ).fetchone()
    assert row is None, (
        f"비캐릭터 태그 {tag!r} 가 character alias로 존재함"
    )


# ---------- 6. JSON 구조 검증 ----------

def test_ww_pack_has_33_characters():
    """wuthering_waves.json에는 캐릭터가 정확히 33명이어야 한다."""
    data = json.loads(WW_PACK.read_text(encoding="utf-8"))
    assert len(data.get("characters", [])) == 33, (
        f"캐릭터 수 불일치: {len(data.get('characters', []))}"
    )


def test_ww_pack_version():
    """wuthering_waves.json version은 1.1.0이어야 한다."""
    data = json.loads(WW_PACK.read_text(encoding="utf-8"))
    assert data["version"] == "1.1.0", f"version 불일치: {data['version']!r}"


def test_ww_pack_has_one_series():
    """wuthering_waves.json에는 series entry가 정확히 1개여야 한다."""
    data = json.loads(WW_PACK.read_text(encoding="utf-8"))
    assert len(data.get("series", [])) == 1
    assert data["series"][0]["canonical"] == CANONICAL_SERIES


# ---------- Gap A 신규 캐릭터 alias 검증 ----------

def test_youhu_alias_resolves(db):
    """'유호' alias는 canonical='Youhu'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='유호' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'유호' alias 없음"
    assert row[0] == "Youhu"


def test_roccia_ko_is_rocooco(db):
    """'로코코' alias는 canonical='Roccia'로 resolve되어야 한다 (Rococo 테마)."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='로코코' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'로코코' alias 없음"
    assert row[0] == "Roccia"


def test_ciaccona_ko_is_shakon(db):
    """'샤콘' alias는 canonical='Ciaccona'로 resolve되어야 한다 (Chaconne 테마)."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='샤콘' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'샤콘' alias 없음"
    assert row[0] == "Ciaccona"


def test_rover_not_seeded(db):
    """Rover(방랑자)는 needs_review 상태로 아직 seed되지 않아야 한다."""
    for alias in ("Rover", "방랑자", "漂泊者"):
        row = db.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias=? AND tag_type='character' AND enabled=1",
            (alias,),
        ).fetchone()
        assert row is None, f"Rover alias {alias!r} 가 등록됨"


# ---------- Phase 2: Cartethyia KO 교정 ----------

def test_cartethyia_ko_display_is_kartisia(db):
    """'카르티시아'(교정된 나무위키 표기)가 Cartethyia의 ko display_name이어야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE canonical='Cartethyia' AND locale='ko'",
    ).fetchone()
    assert row is not None, "Cartethyia ko localization 없음"
    assert row[0] == "카르티시아", f"Cartethyia ko display={row[0]!r}, 기대값='카르티시아'"


def test_cartethyia_old_ko_alias_preserved(db):
    """'카르테시아'(구 표기)는 하위 호환 alias로 Cartethyia에 계속 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='카르테시아' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'카르테시아' 하위 호환 alias 없음"
    assert row[0] == "Cartethyia", f"alias '카르테시아' → {row[0]!r}"


def test_cartethyia_new_ko_alias_resolves(db):
    """'카르티시아' alias는 canonical='Cartethyia'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='카르티시아' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'카르티시아' alias 없음"
    assert row[0] == "Cartethyia", f"alias '카르티시아' → {row[0]!r}"
