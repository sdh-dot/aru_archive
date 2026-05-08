"""Phase D: Idolmaster tag pack skeleton enrichment tests.

Phase D 목표: 구조 설계 + CSV 후보 정리. 대량 캐릭터 applied 금지.

대상 pack 파일 (skeleton, 각 v1.0.0):
  - idolmaster_765:              THE iDOLM@STER        + 765PRO agency
  - idolmaster_cinderella_girls: Cinderella Girls      + 346PRO agency
  - idolmaster_million_live:     Million Live!         + 765 MILLIONSTARS agency
  - idolmaster_sidem:            SideM                 + 315PRO agency
  - idolmaster_shiny_colors:     Shiny Colors          + 283PRO agency
  - idolmaster_gakuen:           Gakuen iDOLM@STER     + Hatsuboshi Gakuen agency

검증 범위:
  - 모든 pack 파일 존재 + 유효 JSON
  - series ko/ja localization 정확성
  - groups 배열 구조 (canonical, parent_series, aliases, localizations)
  - characters 배열 빔 (Phase D는 캐릭터 미추가)
  - 대표 alias 해소 (시리즈 별칭 / 에이전시 한국어·일본어)
  - 로케일 불일치 없음 (ko=한글, ja=CJK/가나)
  - 멱등 seed
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database

_PACKS_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"

BRANDS = [
    "idolmaster_765",
    "idolmaster_cinderella_girls",
    "idolmaster_million_live",
    "idolmaster_sidem",
    "idolmaster_shiny_colors",
    "idolmaster_gakuen",
]

# pack_id → (series_canonical, ko, ja)
SERIES_LOCALIZATIONS = {
    "idolmaster_765":              ("THE iDOLM@STER",                 "아이돌마스터",      "アイドルマスター"),
    "idolmaster_cinderella_girls": ("THE iDOLM@STER Cinderella Girls", "신데렐라 걸즈",    "シンデレラガールズ"),
    "idolmaster_million_live":     ("THE iDOLM@STER Million Live!",    "밀리언 라이브!",   "ミリオンライブ!"),
    "idolmaster_sidem":            ("THE iDOLM@STER SideM",           "사이드M",          "アイドルマスター SideM"),
    "idolmaster_shiny_colors":     ("THE iDOLM@STER Shiny Colors",    "샤이니 컬러즈",   "シャイニーカラーズ"),
    "idolmaster_gakuen":           ("Gakuen iDOLM@STER",              "학원 아이돌마스터","学園アイドルマスター"),
}

# pack_id → (agency_canonical, ko, ja, en)
AGENCY_LOCALIZATIONS = {
    "idolmaster_765":              ("765PRO",             "765프로",           "765プロ",           "765PRO"),
    "idolmaster_cinderella_girls": ("346PRO",             "346프로",           "346プロ",           "346PRO"),
    "idolmaster_million_live":     ("765 MILLIONSTARS",   "765 밀리언스타즈", "765ミリオンスターズ","765 MILLIONSTARS"),
    "idolmaster_sidem":            ("315PRO",             "315프로",           "315プロ",           "315PRO"),
    "idolmaster_shiny_colors":     ("283PRO",             "283프로",           "283プロ",           "283PRO"),
    "idolmaster_gakuen":           ("Hatsuboshi Gakuen",  "하츠보시 학원",    "初星学園",          "Hatsuboshi Gakuen"),
}


def _load(pack_id: str) -> dict:
    with open(_PACKS_DIR / f"{pack_id}.json", encoding="utf-8") as f:
        return json.load(f)


def _make_db(pack_id: str):
    td = tempfile.mkdtemp()
    c = initialize_database(str(Path(td) / f"{pack_id}.db"))
    seed_tag_pack(c, load_tag_pack(_PACKS_DIR / f"{pack_id}.json"))
    return c


# ---------------------------------------------------------------------------
# Pack 파일 구조 검증
# ---------------------------------------------------------------------------

class TestPackFileStructure:

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_pack_file_exists(self, pack_id):
        assert (_PACKS_DIR / f"{pack_id}.json").exists(), f"{pack_id}.json 없음"

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_pack_valid_json(self, pack_id):
        data = _load(pack_id)
        assert data["pack_id"] == pack_id
        assert data["version"] == "1.0.0"
        assert data["source"] == "built_in"

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_series_has_one_entry(self, pack_id):
        data = _load(pack_id)
        assert len(data["series"]) == 1

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_series_ko_ja_en(self, pack_id):
        data = _load(pack_id)
        locs = data["series"][0]["localizations"]
        assert "ko" in locs and locs["ko"]
        assert "ja" in locs and locs["ja"]
        assert "en" in locs and locs["en"]

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_characters_array_empty(self, pack_id):
        """Phase D에서는 캐릭터를 추가하지 않는다."""
        data = _load(pack_id)
        assert data.get("characters", []) == [], (
            f"{pack_id} has characters — Phase D forbids bulk character seeding"
        )

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_groups_array_has_one_agency(self, pack_id):
        data = _load(pack_id)
        groups = data.get("groups", [])
        assert len(groups) >= 1, f"{pack_id} groups 배열이 비어 있음"
        for g in groups:
            assert "canonical" in g
            assert "parent_series" in g
            assert "aliases" in g
            assert "localizations" in g

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_groups_ko_ja(self, pack_id):
        data = _load(pack_id)
        for g in data.get("groups", []):
            locs = g.get("localizations", {})
            assert "ko" in locs and locs["ko"], f"{pack_id} group '{g.get('canonical')}' ko 없음"
            assert "ja" in locs and locs["ja"], f"{pack_id} group '{g.get('canonical')}' ja 없음"


# ---------------------------------------------------------------------------
# Series localization 정확성
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pack_id,canonical,expected_ko,expected_ja", [
    (pid, c, ko, ja) for pid, (c, ko, ja) in SERIES_LOCALIZATIONS.items()
])
def test_series_ko_localization(pack_id, canonical, expected_ko, expected_ja):
    data = _load(pack_id)
    locs = data["series"][0]["localizations"]
    assert locs["ko"] == expected_ko, f"{pack_id} ko: {locs['ko']!r} != {expected_ko!r}"


@pytest.mark.parametrize("pack_id,canonical,expected_ko,expected_ja", [
    (pid, c, ko, ja) for pid, (c, ko, ja) in SERIES_LOCALIZATIONS.items()
])
def test_series_ja_localization(pack_id, canonical, expected_ko, expected_ja):
    data = _load(pack_id)
    locs = data["series"][0]["localizations"]
    assert locs["ja"] == expected_ja, f"{pack_id} ja: {locs['ja']!r} != {expected_ja!r}"


# ---------------------------------------------------------------------------
# Agency localization 정확성
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pack_id,canonical,ko,ja,en", [
    (pid, c, ko, ja, en) for pid, (c, ko, ja, en) in AGENCY_LOCALIZATIONS.items()
])
def test_agency_ko(pack_id, canonical, ko, ja, en):
    data = _load(pack_id)
    agency = next((g for g in data.get("groups", []) if g["canonical"] == canonical), None)
    assert agency is not None, f"{pack_id} agency '{canonical}' 없음"
    assert agency["localizations"]["ko"] == ko


@pytest.mark.parametrize("pack_id,canonical,ko,ja,en", [
    (pid, c, ko, ja, en) for pid, (c, ko, ja, en) in AGENCY_LOCALIZATIONS.items()
])
def test_agency_ja(pack_id, canonical, ko, ja, en):
    data = _load(pack_id)
    agency = next((g for g in data.get("groups", []) if g["canonical"] == canonical), None)
    assert agency is not None, f"{pack_id} agency '{canonical}' 없음"
    assert agency["localizations"]["ja"] == ja


# ---------------------------------------------------------------------------
# Locale-mismatch safety
# ---------------------------------------------------------------------------

class TestNoLocaleMismatch:

    def _hangul_ratio(self, s: str) -> float:
        if not s:
            return 0.0
        n = sum(1 for c in s if "가" <= c <= "힣" or "㄰" <= c <= "㆏")
        return n / len(s)

    def _cjk_kana_ratio(self, s: str) -> float:
        if not s:
            return 0.0
        n = sum(
            1 for c in s
            if "一" <= c <= "鿿"
            or "぀" <= c <= "ヿ"
            or "ㇰ" <= c <= "ㇿ"
            or "･" <= c <= "ﾟ"
        )
        return n / len(s)

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_series_ko_is_hangul(self, pack_id):
        data = _load(pack_id)
        ko = data["series"][0]["localizations"]["ko"]
        assert self._hangul_ratio(ko) >= 0.3, f"{pack_id} series ko={ko!r} hangul<30%"

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_series_ja_is_cjk_kana(self, pack_id):
        data = _load(pack_id)
        ja = data["series"][0]["localizations"]["ja"]
        assert self._cjk_kana_ratio(ja) >= 0.3, f"{pack_id} series ja={ja!r} CJK/kana<30%"

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_groups_ko_is_hangul(self, pack_id):
        data = _load(pack_id)
        for g in data.get("groups", []):
            ko = g["localizations"].get("ko", "")
            assert self._hangul_ratio(ko) >= 0.3, (
                f"{pack_id} group '{g['canonical']}' ko={ko!r} hangul<30%"
            )

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_groups_ja_is_cjk_kana(self, pack_id):
        data = _load(pack_id)
        for g in data.get("groups", []):
            ja = g["localizations"].get("ja", "")
            assert self._cjk_kana_ratio(ja) >= 0.3, (
                f"{pack_id} group '{g['canonical']}' ja={ja!r} CJK/kana<30%"
            )


# ---------------------------------------------------------------------------
# DB seed round-trip
# ---------------------------------------------------------------------------

class TestIdolmasterDB:

    @pytest.mark.parametrize("pack_id,canonical,ko,ja,en", [
        (pid, c, ko, ja, en) for pid, (c, ko, ja, en) in AGENCY_LOCALIZATIONS.items()
    ])
    def test_series_alias_resolves(self, pack_id, canonical, ko, ja, en):
        c = _make_db(pack_id)
        series_canonical, _, _ = SERIES_LOCALIZATIONS[pack_id]
        for alias in (series_canonical,):
            cur = c.execute("SELECT canonical FROM tag_aliases WHERE alias=?", (alias,))
            row = cur.fetchone()
            assert row is not None, f"{pack_id} series alias '{alias}' not in DB"
        c.close()

    @pytest.mark.parametrize("pack_id,canonical,ko,ja,en", [
        (pid, c, ko, ja, en) for pid, (c, ko, ja, en) in AGENCY_LOCALIZATIONS.items()
    ])
    def test_agency_ko_alias_in_db(self, pack_id, canonical, ko, ja, en):
        c = _make_db(pack_id)
        cur = c.execute("SELECT canonical FROM tag_aliases WHERE alias=?", (ko,))
        row = cur.fetchone()
        assert row is not None, f"{pack_id} agency KO alias '{ko}' not in DB"
        assert row[0] == canonical
        c.close()

    @pytest.mark.parametrize("pack_id,canonical,ko,ja,en", [
        (pid, c, ko, ja, en) for pid, (c, ko, ja, en) in AGENCY_LOCALIZATIONS.items()
    ])
    def test_agency_ja_alias_in_db(self, pack_id, canonical, ko, ja, en):
        c = _make_db(pack_id)
        cur = c.execute("SELECT canonical FROM tag_aliases WHERE alias=?", (ja,))
        row = cur.fetchone()
        assert row is not None, f"{pack_id} agency JA alias '{ja}' not in DB"
        assert row[0] == canonical
        c.close()

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_seed_is_idempotent(self, pack_id):
        with tempfile.TemporaryDirectory() as td:
            c = initialize_database(str(Path(td) / f"{pack_id}.db"))
            seed_tag_pack(c, load_tag_pack(_PACKS_DIR / f"{pack_id}.json"))
            r2 = seed_tag_pack(c, load_tag_pack(_PACKS_DIR / f"{pack_id}.json"))
            c.close()
        assert r2["localizations"] == 0
        assert r2["series_aliases"] == 0

    @pytest.mark.parametrize("pack_id,pack_alias", [
        ("idolmaster_765",              "imas"),
        ("idolmaster_765",              "아이돌마스터"),
        ("idolmaster_cinderella_girls", "デレマス"),
        ("idolmaster_cinderella_girls", "신데렐라 걸즈"),
        ("idolmaster_million_live",     "ミリマス"),
        ("idolmaster_million_live",     "밀리마스"),
        ("idolmaster_sidem",            "사이드M"),
        ("idolmaster_shiny_colors",     "シャニマス"),
        ("idolmaster_shiny_colors",     "샤니마스"),
        ("idolmaster_gakuen",           "学マス"),
        ("idolmaster_gakuen",           "학원 아이돌마스터"),
    ])
    def test_series_nickname_alias(self, pack_id, pack_alias):
        c = _make_db(pack_id)
        cur = c.execute("SELECT canonical FROM tag_aliases WHERE alias=?", (pack_alias,))
        row = cur.fetchone()
        assert row is not None, f"alias '{pack_alias}' not in {pack_id} DB"
        c.close()
