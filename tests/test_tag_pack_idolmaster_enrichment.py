"""Phase D / Option B: Idolmaster tag pack 구조 회귀 테스트.

Phase D skeleton → Option B 정규화 후 구조:
  - idolmaster.json:         대표 IP 단일 series (canonical='Idolmaster')
  - idolmaster_765:          series=[], 765PRO group, 765 원조 캐릭터 13명
  - idolmaster_cinderella_girls: series=[], 346PRO group
  - idolmaster_million_live:     series=[], 765 MILLIONSTARS group
  - idolmaster_sidem:            series=[], 315PRO group
  - idolmaster_shiny_colors:     series=[], 283PRO group
  - idolmaster_gakuen:           series=[], Hatsuboshi Gakuen group

검증 범위:
  - 모든 brand pack 파일 존재 + 유효 JSON
  - brand pack은 series 배열이 비어 있어야 한다 (Option B 정책)
  - groups 배열 구조 (canonical, parent_series=Idolmaster, aliases, localizations)
  - agency localization (ko/ja)
  - 멱등 seed
  - 대표 series alias 해소는 test_tag_pack_idolmaster_completion.py에서 검증
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

# pack_id → (agency_canonical, ko, ja, en)
AGENCY_LOCALIZATIONS = {
    "idolmaster_765":              ("765PRO",             "765프로",           "765プロ",           "765PRO"),
    "idolmaster_cinderella_girls": ("346PRO",             "346프로",           "346プロ",           "346PRO"),
    "idolmaster_million_live":     ("765 MILLIONSTARS",   "765 밀리언스타즈", "765ミリオンスターズ","765 MILLIONSTARS"),
    "idolmaster_sidem":            ("315PRO",             "315프로",           "315プロ",           "315PRO"),
    "idolmaster_shiny_colors":     ("283PRO",             "283프로",           "283プロ",           "283PRO"),
    "idolmaster_gakuen":           ("Hatsuboshi Gakuen",  "하츠보시 학원",    "初星学園",          "Hatsuboshi Gakuen"),
}

IDOLMASTER_CANONICAL = "Idolmaster"


def _load(pack_id: str) -> dict:
    with open(_PACKS_DIR / f"{pack_id}.json", encoding="utf-8") as f:
        return json.load(f)


def _make_db(*pack_ids: str):
    """idolmaster.json + 지정 brand pack들을 함께 seed한 DB를 반환한다."""
    td = tempfile.mkdtemp()
    c = initialize_database(str(Path(td) / "test.db"))
    # 대표 IP series를 먼저 seed
    seed_tag_pack(c, load_tag_pack(_PACKS_DIR / "idolmaster.json"))
    for pid in pack_ids:
        seed_tag_pack(c, load_tag_pack(_PACKS_DIR / f"{pid}.json"))
    return c


# ---------------------------------------------------------------------------
# Pack 파일 구조 검증 (Option B 기준)
# ---------------------------------------------------------------------------

class TestPackFileStructure:

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_pack_file_exists(self, pack_id):
        assert (_PACKS_DIR / f"{pack_id}.json").exists(), f"{pack_id}.json 없음"

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_pack_valid_json(self, pack_id):
        data = _load(pack_id)
        assert data["pack_id"] == pack_id
        assert data["source"] == "built_in"
        assert data["version"]  # version 존재만 확인 (값은 고정하지 않음)

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_brand_pack_series_is_empty(self, pack_id):
        """Option B: brand 파일은 series 배열이 비어 있어야 한다."""
        data = _load(pack_id)
        assert data.get("series", []) == [], (
            f"{pack_id} 에 series entry가 남아 있음 — "
            "Idolmaster 단일 canonical 정책(Option B) 위반"
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
    def test_groups_parent_series_is_idolmaster(self, pack_id):
        """Option B: 모든 group의 parent_series는 Idolmaster여야 한다."""
        data = _load(pack_id)
        for g in data.get("groups", []):
            assert g["parent_series"] == IDOLMASTER_CANONICAL, (
                f"{pack_id} group '{g['canonical']}' parent_series="
                f"{g['parent_series']!r} — Idolmaster여야 함"
            )

    @pytest.mark.parametrize("pack_id", BRANDS)
    def test_groups_ko_ja(self, pack_id):
        data = _load(pack_id)
        for g in data.get("groups", []):
            locs = g.get("localizations", {})
            assert "ko" in locs and locs["ko"], f"{pack_id} group '{g.get('canonical')}' ko 없음"
            assert "ja" in locs and locs["ja"], f"{pack_id} group '{g.get('canonical')}' ja 없음"

    def test_765_has_13_characters(self):
        """idolmaster_765.json에는 캐릭터가 정확히 13명이어야 한다."""
        data = _load("idolmaster_765")
        assert len(data.get("characters", [])) == 13

    @pytest.mark.parametrize("pack_id", [
        "idolmaster_cinderella_girls",
        "idolmaster_million_live",
        "idolmaster_sidem",
        "idolmaster_shiny_colors",
        "idolmaster_gakuen",
    ])
    def test_non_765_characters_array_empty(self, pack_id):
        """765 외 brand 파일은 아직 캐릭터를 추가하지 않는다."""
        data = _load(pack_id)
        assert data.get("characters", []) == [], (
            f"{pack_id} has characters — 검수 완료 후 단계적 seed 예정"
        )


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
# Locale-mismatch safety (groups only — series는 idolmaster.json에서 검증)
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
            seed_tag_pack(c, load_tag_pack(_PACKS_DIR / "idolmaster.json"))
            seed_tag_pack(c, load_tag_pack(_PACKS_DIR / f"{pack_id}.json"))
            r2 = seed_tag_pack(c, load_tag_pack(_PACKS_DIR / f"{pack_id}.json"))
            c.close()
        assert r2["localizations"] == 0
        assert r2["series_aliases"] == 0

    @pytest.mark.parametrize("pack_id,pack_alias", [
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
    def test_series_nickname_alias_resolves_to_idolmaster(self, pack_id, pack_alias):
        """Option B: 하위 브랜드 별칭은 Idolmaster canonical로 resolve된다."""
        c = _make_db(pack_id)
        cur = c.execute(
            "SELECT canonical FROM tag_aliases WHERE alias=? AND tag_type='series'",
            (pack_alias,),
        )
        row = cur.fetchone()
        assert row is not None, f"alias '{pack_alias}' not in DB (idolmaster.json + {pack_id} seeded)"
        assert row[0] == IDOLMASTER_CANONICAL, (
            f"alias '{pack_alias}' → {row[0]!r}, 기대값={IDOLMASTER_CANONICAL!r}"
        )
        c.close()
