"""Zenless Zone Zero tag pack 정책 검증 테스트.

Phase A seed: 기존 4인 정리 + 신규 18인 = 총 22인

검증 범위:
1. series ko display → "젠레스 존 제로"
2. v1.0 표준 캐릭터 + v1.1~v1.5 캐릭터 ko display_name 등록
3. 신규 캐릭터 parent_series = "Zenless Zone Zero"
4. 단일명 alias(Nicole/Ellen/Jane) 전역 character 등록 금지
5. 나무위키 KO 교정 확인: 엔비 데마라, 본 리카온, 앤톤 이바노프
6. Nekomata / Soldier 11 / Belle / Wise 미 seed 확인
7. faction명이 character로 등록되지 않음
8. JSON 구조: 22인, version 1.2.0
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database

PACK_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"
ZZZ_PACK = PACK_DIR / "zenless_zone_zero.json"

CANONICAL_SERIES = "Zenless Zone Zero"

# Phase A 신규 seed 18인 (기존 4인 제외)
NEW_SEEDED_KO = [
    "엔비 데마라", "빌리 키드", "코린 위크스", "벤 비거",
    "그레이스 하워드", "앤톤 이바노프", "주연", "본 리카온",
    "세스 로웰", "청의", "소우카쿠", "버니스 화이트",
    "카이사르 킹", "라이터", "호시미 미야비", "아사바 하루마사",
    "아스트라 야오", "이블린 슈발리에",
]
NEW_SEEDED_CANONICAL = [
    "Anby Demara", "Billy Kid", "Corin Wickes", "Ben Bigger",
    "Grace Howard", "Anton Ivanov", "Zhu Yuan", "Von Lycaon",
    "Seth Lowell", "Qingyi", "Soukaku", "Burnice White",
    "Caesar King", "Lighter", "Miyabi", "Harumasa",
    "Astra Yao", "Evelyn Chevalier",
]

# 기존 4인 (Phase A 이전부터 seed)
EXISTING_SEEDED_KO = ["니콜 드마라", "엘런 조", "야나기", "제인"]
EXISTING_SEEDED_CANONICAL = ["Nicole Demara", "Ellen Joe", "Yanagi", "Jane Doe"]

# Phase 2 seed: hold/needs_review 검증 후 확정 7인
PHASE2_SEEDED_KO = [
    "파이퍼 휠", "콜레다 벨로보그", "11호",
    "루시아나 드 몬테피오", "알렉산드리나 세바스티안",
    "트리거", "비비안 밴시",
]
PHASE2_SEEDED_CANONICAL = [
    "Piper Wheel", "Koleda Belobog", "Soldier 11",
    "Luciana de Montefio", "Alexandrina Sebastiane",
    "Trigger", "Vivian Banshee",
]

ALL_SEEDED_KO = EXISTING_SEEDED_KO + NEW_SEEDED_KO + PHASE2_SEEDED_KO
ALL_SEEDED_CANONICAL = EXISTING_SEEDED_CANONICAL + NEW_SEEDED_CANONICAL + PHASE2_SEEDED_CANONICAL

# 단일명 alias — 전역 character 등록 금지
FORBIDDEN_SINGLE_NAME_ALIASES = ["Nicole", "Ellen", "Jane", "Billy", "Anby", "Piper"]

# faction/속성명 — character 등록 금지
NON_CHARACTER_TAGS = [
    "젠레스 존 제로", "Zenless Zone Zero", "ZZZ",
    "Cunning Hares", "Belobog Heavy Industries",
    "Victoria Housekeeping Co.", "Sons of Calydon",
    "CIST", "Section 6", "Yunkui Summit",
    "Obol Squad", "Mockingbird",
]

# 미 seed 확인 대상 (needs_review — canonical_en 정책 미결 / 주인공 쌍 정책 미결)
NOT_SEEDED_ALIASES = [
    "Nekomata", "네코마타", "네코미야 마나",
    "솔저 11",           # 나무위키 KO는 '11호'이므로 '솔저 11'은 alias 없음
    "Belle", "벨", "Wise", "와이즈",
    "Piper", "파이퍼",   # Piper Wheel의 단일명 — 전역 등록 금지
]


@pytest.fixture()
def db(tmp_path):
    conn = initialize_database(str(tmp_path / "test.db"))
    seed_tag_pack(conn, load_tag_pack(ZZZ_PACK))
    yield conn
    conn.close()


# ---------- 1. series ko display ----------

def test_zzz_series_ko_display(db):
    """Zenless Zone Zero series ko display는 '젠레스 존 제로'여야 한다."""
    row = db.execute(
        "SELECT display_name FROM tag_localizations "
        "WHERE canonical=? AND tag_type='series' AND locale='ko'",
        (CANONICAL_SERIES,),
    ).fetchone()
    assert row is not None, "Zenless Zone Zero series ko localization 없음"
    assert row[0] == "젠레스 존 제로", f"ko display 불일치: {row[0]!r}"


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
    """seeded 캐릭터의 parent_series는 'Zenless Zone Zero'여야 한다."""
    row = db.execute(
        "SELECT parent_series FROM tag_aliases "
        "WHERE canonical=? AND tag_type='character' AND enabled=1 LIMIT 1",
        (char_canonical,),
    ).fetchone()
    assert row is not None, f"{char_canonical!r} 가 tag_aliases에 없음"
    assert row[0] == CANONICAL_SERIES, (
        f"{char_canonical!r} parent_series={row[0]!r}, 기대값={CANONICAL_SERIES!r}"
    )


# ---------- 4. 단일명 alias 전역 등록 금지 ----------

@pytest.mark.parametrize("alias", FORBIDDEN_SINGLE_NAME_ALIASES)
def test_single_name_not_global_character_alias(db, alias):
    """단일명/짧은 이름은 전역 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (alias,),
    ).fetchone()
    assert row is None, (
        f"단일명 {alias!r} 가 character alias로 존재함 → canonical={row[0] if row else None}"
    )


# ---------- 5. 나무위키 KO 교정 확인 ----------

def test_anby_demara_ko_is_namuiki(db):
    """'엔비 데마라'(나무위키 표기)가 Anby Demara의 KO alias로 등록된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='엔비 데마라' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'엔비 데마라' alias 없음"
    assert row[0] == "Anby Demara"


def test_von_lycaon_ko_is_bon_not_pon(db):
    """'본 리카온'(나무위키, Von=본 B렌더링)이 Von Lycaon의 KO alias로 등록된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='본 리카온' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'본 리카온' alias 없음"
    assert row[0] == "Von Lycaon"


def test_anton_ivanov_ko_is_namuiki(db):
    """'앤톤 이바노프'(나무위키 표기)가 Anton Ivanov의 KO alias로 등록된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='앤톤 이바노프' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'앤톤 이바노프' alias 없음"
    assert row[0] == "Anton Ivanov"


# ---------- 6. 미 seed 확인 (hold / needs_review) ----------

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


# ---------- 7. faction명 character 미등록 ----------

@pytest.mark.parametrize("tag", NON_CHARACTER_TAGS)
def test_non_character_tags_not_in_character_aliases(db, tag):
    """faction/시리즈명은 character alias로 등록되어선 안 된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias=? AND tag_type='character' AND enabled=1",
        (tag,),
    ).fetchone()
    assert row is None, (
        f"비캐릭터 태그 {tag!r} 가 character alias로 존재함"
    )


# ---------- 8. JSON 구조 검증 ----------

def test_zzz_pack_has_29_characters():
    """zenless_zone_zero.json에는 캐릭터가 정확히 29명이어야 한다 (Phase A 22 + Phase 2 7)."""
    data = json.loads(ZZZ_PACK.read_text(encoding="utf-8"))
    assert len(data.get("characters", [])) == 29, (
        f"캐릭터 수 불일치: {len(data.get('characters', []))}"
    )


def test_zzz_pack_version():
    """zenless_zone_zero.json version은 1.3.0이어야 한다."""
    data = json.loads(ZZZ_PACK.read_text(encoding="utf-8"))
    assert data["version"] == "1.3.0", f"version 불일치: {data['version']!r}"


def test_nicole_no_single_name_alias_in_json():
    """JSON에서 Nicole Demara의 aliases에 'Nicole' 단일명이 없어야 한다."""
    data = json.loads(ZZZ_PACK.read_text(encoding="utf-8"))
    nicole = next((c for c in data["characters"] if c["canonical"] == "Nicole Demara"), None)
    assert nicole is not None, "Nicole Demara 없음"
    assert "Nicole" not in nicole["aliases"], f"Nicole aliases에 단일명 포함: {nicole['aliases']}"


def test_ellen_no_single_name_alias_in_json():
    """JSON에서 Ellen Joe의 aliases에 'Ellen' 단일명이 없어야 한다."""
    data = json.loads(ZZZ_PACK.read_text(encoding="utf-8"))
    ellen = next((c for c in data["characters"] if c["canonical"] == "Ellen Joe"), None)
    assert ellen is not None, "Ellen Joe 없음"
    assert "Ellen" not in ellen["aliases"], f"Ellen aliases에 단일명 포함: {ellen['aliases']}"


def test_jane_no_single_name_alias_in_json():
    """JSON에서 Jane Doe의 aliases에 'Jane' 단일명이 없어야 한다."""
    data = json.loads(ZZZ_PACK.read_text(encoding="utf-8"))
    jane = next((c for c in data["characters"] if c["canonical"] == "Jane Doe"), None)
    assert jane is not None, "Jane Doe 없음"
    assert "Jane" not in jane["aliases"], f"Jane aliases에 단일명 포함: {jane['aliases']}"


def test_zzz_pack_has_one_series():
    """zenless_zone_zero.json에는 series entry가 정확히 1개여야 한다."""
    data = json.loads(ZZZ_PACK.read_text(encoding="utf-8"))
    assert len(data.get("series", [])) == 1
    assert data["series"][0]["canonical"] == CANONICAL_SERIES


# ---------- Phase 2: hold/needs_review 검증 후 확정 7인 ----------

def test_piper_wheel_full_name_seeded(db):
    """'파이퍼 휠' alias는 canonical='Piper Wheel'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='파이퍼 휠' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'파이퍼 휠' alias 없음"
    assert row[0] == "Piper Wheel"


def test_piper_short_name_not_alias(db):
    """'Piper'(단일명)은 character alias로 등록되어선 안 된다 (Piper Wheel의 단축명)."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='Piper' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is None, f"단일명 'Piper' 가 character alias로 존재함 → canonical={row[0] if row else None}"


def test_koleda_belobog_ko_alias_resolves(db):
    """'콜레다 벨로보그' alias는 canonical='Koleda Belobog'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='콜레다 벨로보그' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'콜레다 벨로보그' alias 없음"
    assert row[0] == "Koleda Belobog"


def test_koleda_short_alias_resolves(db):
    """'콜레다' 단축 alias는 canonical='Koleda Belobog'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='콜레다' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'콜레다' alias 없음"
    assert row[0] == "Koleda Belobog"


def test_koleda_ja_is_kureta_not_koreda(db):
    """Koleda Belobog의 JA alias는 'クレタ・ベロボーグ'이어야 한다 (NOT コレダ)."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='クレタ・ベロボーグ' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'クレタ・ベロボーグ' alias 없음"
    assert row[0] == "Koleda Belobog"


def test_soldier11_ko_is_11ho(db):
    """'11호'(나무위키 표기)가 Soldier 11의 KO alias로 등록된다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='11호' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'11호' alias 없음"
    assert row[0] == "Soldier 11"


def test_soldier11_ko_not_soljeo11(db):
    """'솔저 11'은 character alias로 등록되지 않아야 한다 (나무위키 KO는 '11호')."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='솔저 11' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is None, f"'솔저 11' 가 character alias로 존재함 → canonical={row[0] if row else None}"


def test_lucy_full_name_resolves(db):
    """'루시아나 드 몬테피오' alias는 canonical='Luciana de Montefio'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='루시아나 드 몬테피오' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'루시아나 드 몬테피오' alias 없음"
    assert row[0] == "Luciana de Montefio"


def test_rina_full_name_resolves(db):
    """'알렉산드리나 세바스티안' alias는 canonical='Alexandrina Sebastiane'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='알렉산드리나 세바스티안' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'알렉산드리나 세바스티안' alias 없음"
    assert row[0] == "Alexandrina Sebastiane"


def test_vivian_surname_is_banshee(db):
    """canonical='Vivian Banshee' (NOT 'Vivian') — 나무위키/HoYoWiki 확인 완료."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='비비안 밴시' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'비비안 밴시' alias 없음"
    assert row[0] == "Vivian Banshee"


def test_trigger_ko_alias_resolves(db):
    """'트리거' alias는 canonical='Trigger'로 resolve되어야 한다."""
    row = db.execute(
        "SELECT canonical FROM tag_aliases "
        "WHERE alias='트리거' AND tag_type='character' AND enabled=1",
    ).fetchone()
    assert row is not None, "'트리거' alias 없음"
    assert row[0] == "Trigger"


def test_nekomata_still_not_seeded(db):
    """Nekomata/네코미야 마나는 canonical_en 정책 미결로 아직 seed되지 않아야 한다."""
    for alias in ("Nekomata", "네코마타", "네코미야 마나"):
        row = db.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias=? AND tag_type='character' AND enabled=1",
            (alias,),
        ).fetchone()
        assert row is None, f"미seed 항목 {alias!r} 가 등록됨"


def test_belle_wise_still_not_seeded(db):
    """Belle/Wise는 주인공 쌍 정책 미결로 아직 seed되지 않아야 한다."""
    for alias in ("Belle", "벨", "Wise", "와이즈"):
        row = db.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias=? AND tag_type='character' AND enabled=1",
            (alias,),
        ).fetchone()
        assert row is None, f"미seed 항목 {alias!r} 가 등록됨"
