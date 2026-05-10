"""Idolmaster tag pack 정책 검증 테스트.

대표 IP canonical = 'Idolmaster' 단일화 정책 (Option B) 적용 후
아래 사항을 보장한다:

1. series ko display → "아이돌 마스터"
2. 하위 브랜드 alias → canonical Idolmaster로 resolve
3. 하위 작품명이 별도 series canonical로 존재하지 않음
4. 765 캐릭터 13명 parent_series = Idolmaster
5. 765 캐릭터 ko locale display_name 정확성
6. 双海亜美 / 双海真美는 full-name resolve, 단일명 "아미"/"마미" 전역 alias 미포함
7. 하위 작품명이 series folder로 직접 사용되지 않음 (series alias → Idolmaster)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database

PACK_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"

IDOLMASTER_PACK = PACK_DIR / "idolmaster.json"
PACKS_765 = PACK_DIR / "idolmaster_765.json"
BRAND_PACKS = [
    PACK_DIR / "idolmaster_cinderella_girls.json",
    PACK_DIR / "idolmaster_million_live.json",
    PACK_DIR / "idolmaster_shiny_colors.json",
    PACK_DIR / "idolmaster_sidem.json",
    PACK_DIR / "idolmaster_gakuen.json",
]

CANONICAL_SERIES = "Idolmaster"

SUB_BRAND_CANONICALS = [
    "THE iDOLM@STER",
    "THE iDOLM@STER Cinderella Girls",
    "THE iDOLM@STER Million Live!",
    "THE iDOLM@STER SideM",
    "THE iDOLM@STER Shiny Colors",
    "Gakuen iDOLM@STER",
]

# 하위 브랜드 alias 목록 (idolmaster.json에 포함되어야 함)
BRAND_ALIASES = [
    "Cinderella Girls",
    "THE iDOLM@STER Cinderella Girls",
    "Million Live!",
    "THE iDOLM@STER Million Live!",
    "SideM",
    "THE iDOLM@STER SideM",
    "Shiny Colors",
    "THE iDOLM@STER Shiny Colors",
    "Gakuen iDOLM@STER",
    "Gakuen Idolmaster",
    "학원 아이돌마스터",
    "샤이니 컬러즈",
    "샤니마스",
    "신데렐라 걸즈",
    "밀리언 라이브!",
    "사이드M",
]

CHARS_765_KO = [
    "아마미 하루카",
    "키사라기 치하야",
    "호시이 미키",
    "타카츠키 야요이",
    "미나세 이오리",
    "키쿠치 마코토",
    "하기와라 유키호",
    "후타미 아미",
    "후타미 마미",
    "미우라 아즈사",
    "아키즈키 리츠코",
    "시죠 타카네",
    "가나하 히비키",
]

CHARS_765_CANONICAL = [
    "天海春香", "如月千早", "星井美希", "高槻やよい", "水瀬伊織",
    "菊地真", "萩原雪歩", "双海亜美", "双海真美", "三浦あずさ",
    "秋月律子", "四条貴音", "我那覇響",
]


@pytest.fixture()
def db(tmp_path):
    conn = initialize_database(str(tmp_path / "test.db"))
    for pack_path in [IDOLMASTER_PACK, PACKS_765] + BRAND_PACKS:
        seed_tag_pack(conn, load_tag_pack(pack_path))
    yield conn
    conn.close()


# ---------- 1. series ko display ----------

def test_idolmaster_series_ko_display(db):
    """Idolmaster series ko display는 '아이돌 마스터'여야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE canonical=? AND tag_type='series' AND locale='ko'",
        (CANONICAL_SERIES,),
    ).fetchone()
    assert row is not None, "Idolmaster series ko localization 없음"
    assert row[0] == "아이돌 마스터", f"ko display 불일치: {row[0]!r}"


# ---------- 2. 하위 브랜드 alias → Idolmaster로 resolve ----------

@pytest.mark.parametrize("alias", BRAND_ALIASES)
def test_brand_alias_resolves_to_idolmaster(db, alias):
    """하위 브랜드 alias는 canonical=Idolmaster series로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='series' AND enabled=1",
        (alias,),
    ).fetchone()
    assert row is not None, f"alias {alias!r} 가 tag_aliases에 없음"
    assert row[0] == CANONICAL_SERIES, (
        f"alias {alias!r} → canonical={row[0]!r}, 기대값={CANONICAL_SERIES!r}"
    )


# ---------- 3. 하위 작품명이 별도 series canonical로 존재하지 않음 ----------

@pytest.mark.parametrize("sub_brand", SUB_BRAND_CANONICALS)
def test_sub_brand_not_separate_series_canonical(db, sub_brand):
    """하위 작품명은 별도 series canonical로 존재해서는 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE canonical=? AND tag_type='series' AND enabled=1",
        (sub_brand,),
    ).fetchone()
    assert row is None, (
        f"{sub_brand!r} 가 별도 series canonical로 존재함 — "
        "Idolmaster 단일 canonical 정책 위반"
    )


# ---------- 4. 765 캐릭터 parent_series = Idolmaster ----------

@pytest.mark.parametrize("char_canonical", CHARS_765_CANONICAL)
def test_765_character_parent_series(db, char_canonical):
    """765 캐릭터의 parent_series는 Idolmaster여야 한다."""
    row = db.execute(
        "SELECT parent_series FROM tag_aliases "
        "WHERE canonical=? AND tag_type='character' AND enabled=1 LIMIT 1",
        (char_canonical,),
    ).fetchone()
    assert row is not None, f"{char_canonical!r} 가 tag_aliases에 없음"
    assert row[0] == CANONICAL_SERIES, (
        f"{char_canonical!r} parent_series={row[0]!r}, 기대값={CANONICAL_SERIES!r}"
    )


# ---------- 5. 765 캐릭터 ko locale display_name ----------

@pytest.mark.parametrize("ko_name", CHARS_765_KO)
def test_765_character_ko_display(db, ko_name):
    """765 캐릭터가 ko locale에서 display_name으로 등록되어야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE display_name=? AND locale='ko'",
        (ko_name,),
    ).fetchone()
    assert row is not None, f"ko display_name {ko_name!r} 가 tag_localizations에 없음"


# ---------- 6. 双海 twins: full-name ok, 단일명 alias 미포함 ----------

def test_futami_ami_full_name_resolves(db):
    """后타미 아미는 full-name '후타미 아미'로 resolve된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='후타미 아미' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'후타미 아미' alias 없음"
    assert row[0] == "双海亜美"


def test_futami_mami_full_name_resolves(db):
    """후타미 마미는 full-name '후타미 마미'로 resolve된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='후타미 마미' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'후타미 마미' alias 없음"
    assert row[0] == "双海真美"


def test_single_ami_not_global_alias(db):
    """단일명 '아미'는 전역 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='아미' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is None, f"'아미' 가 character alias로 존재함 → canonical={row[0] if row else None}"


def test_single_mami_not_global_alias(db):
    """단일명 '마미'는 전역 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='마미' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is None, f"'마미' 가 character alias로 존재함 → canonical={row[0] if row else None}"


# ---------- 7. 하위 작품명 series folder로 직접 사용 금지 ----------

def test_shiny_colors_alias_points_to_idolmaster_not_self(db):
    """'샤이니 컬러즈' alias는 Idolmaster를 가리켜야 하며 별도 series를 만들지 않는다."""
    rows = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='샤이니 컬러즈' AND tag_type='series' AND enabled=1",
    ).fetchall()
    assert len(rows) == 1, f"'샤이니 컬러즈' series alias 중복 또는 없음: {rows}"
    assert rows[0][0] == CANONICAL_SERIES


def test_cinderella_girls_alias_points_to_idolmaster(db):
    """'신데렐라 걸즈' alias는 Idolmaster를 가리켜야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='신데렐라 걸즈' AND tag_type='series' AND enabled=1",
    ).fetchone()
    assert row is not None
    assert row[0] == CANONICAL_SERIES


# ---------- JSON 구조 검증 (로더 없이) ----------

def test_idolmaster_json_has_exactly_one_series():
    """idolmaster.json에는 series entry가 정확히 1개여야 한다."""
    data = json.loads(IDOLMASTER_PACK.read_text(encoding="utf-8"))
    assert len(data.get("series", [])) == 1
    assert data["series"][0]["canonical"] == CANONICAL_SERIES


@pytest.mark.parametrize("pack_path", BRAND_PACKS)
def test_brand_packs_have_no_series_entries(pack_path):
    """하위 브랜드 파일은 series 배열이 비어 있어야 한다."""
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    assert data.get("series", []) == [], (
        f"{pack_path.name} 에 series entry가 남아 있음: {data['series']}"
    )


def test_765_pack_has_13_characters():
    """idolmaster_765.json에는 캐릭터가 정확히 13명이어야 한다."""
    data = json.loads(PACKS_765.read_text(encoding="utf-8"))
    assert len(data.get("characters", [])) == 13


def test_765_twins_have_no_single_name_alias():
    """双海亜美/双海真美의 aliases에 '아미'/'마미' 단일명이 없어야 한다."""
    data = json.loads(PACKS_765.read_text(encoding="utf-8"))
    for char in data.get("characters", []):
        if char["canonical"] in ("双海亜美", "双海真美"):
            forbidden = {"아미", "마미"}
            overlap = forbidden & set(char.get("aliases", []))
            assert not overlap, (
                f"{char['canonical']} aliases에 단일명 포함됨: {overlap}"
            )
