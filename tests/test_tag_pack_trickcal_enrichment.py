"""tests/test_tag_pack_trickcal_enrichment.py

Trickcal Re:VIVE Phase B enrichment 회귀 테스트.

대상:
  - EN hold 8건 해소: 에슈르(Ashur)/코미(Kommy)/하이디(Heidi)/델리아(Delia)/
    아라그니아(Aragnia)/리코타(Ricotta)/시저(Caesar)/헤일리(Haley)
  - KR-only EN 추가 9건: 다야(Daya)/이프리트(Ifrit)/마에스트로 2호(Maestro MK2)/
    림(Rim)/스피키(Speaki)/벨벳(Velvet)/빅우드(Bigwood)/제이드(Jade)/벨리타(Belita)
  - 잘못된 표기 미등록 보장: Eshur/Asher/Comi
  - EN 미확인 3건 보류 유지: 실라/벨라/교주
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database


PACK_PATH = (
    Path(__file__).parent.parent / "resources" / "tag_packs" / "trickcal_revive.json"
)

CANONICAL_SERIES = "Trickcal Re:VIVE"

# Phase B 에서 EN hold 가 해소된 8건
EN_HOLD_RESOLVED: dict[str, str] = {
    "에슈르":     "Ashur",
    "코미":       "Kommy",
    "하이디":     "Heidi",
    "델리아":     "Delia",
    "아라그니아": "Aragnia",
    "리코타":     "Ricotta",
    "시저":       "Caesar",
    "헤일리":     "Haley",
}

# Phase B 에서 EN 이 새로 확인된 KR-only 9건
EN_NEWLY_CONFIRMED: dict[str, str] = {
    "다야":         "Daya",
    "이프리트":     "Ifrit",
    "마에스트로 2호": "Maestro MK2",
    "림":           "Rim",
    "스피키":       "Speaki",
    "벨벳":         "Velvet",
    "빅우드":       "Bigwood",
    "제이드":       "Jade",
    "벨리타":       "Belita",
}

# Phase B 이후에도 등록 금지인 잘못된 EN 표기
WRONG_EN_ALIASES: list[str] = ["Eshur", "Asher", "Comi"]

# EN 미확인 — 보류 유지
EN_UNCONFIRMED_KO: list[str] = ["실라", "벨라", "교주"]


# ---------------------------------------------------------------------------
# Pack file invariants
# ---------------------------------------------------------------------------

class TestPhaseB_PackFile:
    def test_version_bumped_to_1_2_0(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert pack["version"] == "1.2.0", (
            f"Phase B 반영 후 version 이 1.2.0 이어야 함: {pack['version']!r}"
        )

    @pytest.mark.parametrize("ko_name,expected_en", list(EN_HOLD_RESOLVED.items()))
    def test_en_hold_resolved_in_localizations(self, ko_name, expected_en):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        assert ko_name in char_by_canonical, f"캐릭터 누락: {ko_name!r}"
        locs = char_by_canonical[ko_name]["localizations"]
        assert locs.get("en") == expected_en, (
            f"{ko_name!r} en localization 불일치: {locs.get('en')!r} != {expected_en!r}"
        )

    @pytest.mark.parametrize("ko_name,expected_en", list(EN_HOLD_RESOLVED.items()))
    def test_en_hold_resolved_in_aliases(self, ko_name, expected_en):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        aliases = char_by_canonical[ko_name]["aliases"]
        assert expected_en in aliases, (
            f"{ko_name!r} aliases 에 {expected_en!r} 누락"
        )

    @pytest.mark.parametrize("ko_name,expected_en", list(EN_NEWLY_CONFIRMED.items()))
    def test_kr_only_en_confirmed_in_localizations(self, ko_name, expected_en):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        assert ko_name in char_by_canonical, f"캐릭터 누락: {ko_name!r}"
        locs = char_by_canonical[ko_name]["localizations"]
        assert locs.get("en") == expected_en, (
            f"{ko_name!r} en localization 불일치: {locs.get('en')!r} != {expected_en!r}"
        )

    @pytest.mark.parametrize("ko_name,expected_en", list(EN_NEWLY_CONFIRMED.items()))
    def test_kr_only_en_confirmed_in_aliases(self, ko_name, expected_en):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        aliases = char_by_canonical[ko_name]["aliases"]
        assert expected_en in aliases, (
            f"{ko_name!r} aliases 에 {expected_en!r} 누락"
        )

    @pytest.mark.parametrize("wrong_en", WRONG_EN_ALIASES)
    def test_wrong_en_not_in_any_alias(self, wrong_en):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        all_aliases: set[str] = set()
        for char in pack["characters"]:
            all_aliases.update(char["aliases"])
        assert wrong_en not in all_aliases, (
            f"잘못된 EN 표기가 alias 에 등록됨: {wrong_en!r}"
        )

    @pytest.mark.parametrize("ko_name", EN_UNCONFIRMED_KO)
    def test_unconfirmed_has_no_en(self, ko_name):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        assert ko_name in char_by_canonical, f"캐릭터 누락: {ko_name!r}"
        locs = char_by_canonical[ko_name]["localizations"]
        assert "en" not in locs, (
            f"EN 미확인 캐릭터에 en localization 등록됨: {ko_name!r} → {locs.get('en')!r}"
        )


# ---------------------------------------------------------------------------
# Loader 동작 검증 (in-memory SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    pack = load_tag_pack(PACK_PATH)
    seed_tag_pack(c, pack)
    yield c
    c.close()


class TestPhaseB_Loader:
    @pytest.mark.parametrize("en_alias,expected_canonical", [
        ("Ashur",   "에슈르"),
        ("Kommy",   "코미"),
        ("Heidi",   "하이디"),
        ("Delia",   "델리아"),
        ("Aragnia", "아라그니아"),
        ("Ricotta", "리코타"),
        ("Caesar",  "시저"),
        ("Haley",   "헤일리"),
    ])
    def test_en_hold_resolved_alias_in_db(self, conn, en_alias, expected_canonical):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (en_alias,),
        ).fetchone()
        assert row is not None, f"EN alias 미등록: {en_alias!r}"
        assert row["canonical"] == expected_canonical, (
            f"{en_alias!r} → {row['canonical']!r} (기대: {expected_canonical!r})"
        )

    @pytest.mark.parametrize("en_alias,expected_canonical", [
        ("Daya",        "다야"),
        ("Ifrit",       "이프리트"),
        ("Maestro MK2", "마에스트로 2호"),
        ("Rim",         "림"),
        ("Speaki",      "스피키"),
        ("Velvet",      "벨벳"),
        ("Bigwood",     "빅우드"),
        ("Jade",        "제이드"),
        ("Belita",      "벨리타"),
    ])
    def test_kr_only_en_alias_in_db(self, conn, en_alias, expected_canonical):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (en_alias,),
        ).fetchone()
        assert row is not None, f"KR-only EN alias 미등록: {en_alias!r}"
        assert row["canonical"] == expected_canonical, (
            f"{en_alias!r} → {row['canonical']!r} (기대: {expected_canonical!r})"
        )

    @pytest.mark.parametrize("wrong_en", WRONG_EN_ALIASES)
    def test_wrong_en_not_in_db(self, conn, wrong_en):
        row = conn.execute(
            "SELECT 1 FROM tag_aliases WHERE alias = ? AND tag_type = 'character'",
            (wrong_en,),
        ).fetchone()
        assert row is None, f"잘못된 EN alias 가 DB 에 등록됨: {wrong_en!r}"

    @pytest.mark.parametrize("ko_name", EN_UNCONFIRMED_KO)
    def test_unconfirmed_character_has_no_en_localization_in_db(
        self, conn, ko_name
    ):
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'character' AND locale = 'en'",
            (ko_name,),
        ).fetchone()
        assert row is None, (
            f"EN 미확인 캐릭터에 en localization 이 DB 에 등록됨: "
            f"{ko_name!r} → {row['display_name'] if row else None!r}"
        )

    def test_haley_has_ja_alias_preserved(self, conn):
        """헤일리에 EN(Haley) 추가 후 JA(ヘイリー) alias 도 유지된다."""
        for alias in ["Haley", "ヘイリー"]:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert row is not None, f"헤일리 alias 미등록: {alias!r}"
            assert row["canonical"] == "헤일리"
