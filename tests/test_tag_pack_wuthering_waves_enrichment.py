"""Phase C-2: Wuthering Waves tag pack enrichment tests.

Covers:
  - Pack file structure (v1.1.0, 33 characters applied)
  - EN canonical policy (global game → EN canonical)
  - KO/JA localizations for all 33 confirmed characters
  - Locale-mismatch safety (ko=hangul, ja=CJK/kana)
  - DB alias round-trip via seed_tag_pack + initialize_database
  - needs_review characters absent from pack
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database

_PACKS_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"
_WW_PACK = _PACKS_DIR / "wuthering_waves.json"

# EN canonical → (ko, ja)
WW_CHARACTERS = {
    "Yangyang":     ("양양",      "秧秧"),
    "Chixia":       ("치샤",      "熾霞"),
    "Baizhi":       ("백지",      "白芷"),
    "Jiyan":        ("기염",      "忌炎"),
    "Verina":       ("벨리나",    "ヴェリーナ"),
    "Encore":       ("앙코",      "アンコ"),
    "Calcharo":     ("카카루",    "カカロ"),
    "Yinlin":       ("음림",      "吟霖"),
    "Jianxin":      ("감심",      "鑑心"),
    "Lingyang":     ("능양",      "凌陽"),
    "Sanhua":       ("산화",      "散華"),
    "Mortefi":      ("모르테피",  "モルトフィー"),
    "Danjin":       ("단근",      "丹瑾"),
    "Aalto":        ("알토",      "アールト"),
    "Taoqi":        ("도기",      "桃祈"),
    "Yuanwu":       ("연무",      "淵武"),
    "Jinhsi":       ("금희",      "今汐"),
    "Changli":      ("장리",      "長離"),
    "Zhezhi":       ("절지",      "折枝"),
    "Xiangli Yao":  ("상리요",    "相里要"),
    "Shorekeeper":  ("파수인",    "ショアキーパー"),
    "Camellya":     ("카멜리아",  "ツバキ"),
    "Lumi":         ("루미",      "ルミ"),
    "Carlotta":     ("카를로타",  "カルロッタ"),
    "Phoebe":       ("피비",      "フィービー"),
    "Cantarella":   ("칸타렐라",  "カンタレラ"),
    "Cartethyia":   ("카르티시아","カルテジア"),
    "Lupa":         ("루파",      "ルパ"),
    # Gap A v1.1.0
    "Youhu":        ("유호",      "釉瑚"),
    "Roccia":       ("로코코",    "ロココ"),
    "Brant":        ("브렌트",    "ブラント"),
    "Zani":         ("젠니",      "ザンニー"),
    "Ciaccona":     ("샤콘",      "シャコンヌ"),
}

# Characters held as needs_review — must NOT appear in the pack
NEEDS_REVIEW = ["Rover"]


@pytest.fixture(scope="module")
def ww_conn():
    with tempfile.TemporaryDirectory() as td:
        c = initialize_database(str(Path(td) / "ww.db"))
        seed_tag_pack(c, load_tag_pack(_WW_PACK))
        yield c
        c.close()


# ---------------------------------------------------------------------------
# Pack file structure
# ---------------------------------------------------------------------------

class TestWuWaPackFile:

    def test_pack_file_exists(self):
        assert _WW_PACK.exists(), "wuthering_waves.json 파일 없음"

    def test_pack_file_valid_json(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        assert data["pack_id"] == "wuthering_waves"
        assert data["version"] == "1.1.0"
        assert data["source"] == "built_in"

    def test_pack_has_series(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["series"]) == 1
        s = data["series"][0]
        assert s["canonical"] == "Wuthering Waves"

    def test_series_localizations(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        locs = data["series"][0]["localizations"]
        assert locs["ko"] == "명조"
        assert locs["ja"] == "鳴潮"
        assert locs["en"] == "Wuthering Waves"

    def test_pack_has_33_characters(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["characters"]) == 33

    def test_all_characters_have_en_canonical(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        for ch in data["characters"]:
            assert ch["canonical"] in WW_CHARACTERS, (
                f"Unexpected canonical: {ch['canonical']!r}"
            )

    def test_all_characters_have_ko_ja_en_localizations(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        for ch in data["characters"]:
            locs = ch.get("localizations", {})
            assert "ko" in locs, f"{ch['canonical']} missing ko"
            assert "ja" in locs, f"{ch['canonical']} missing ja"
            assert "en" in locs, f"{ch['canonical']} missing en"

    def test_en_localization_matches_canonical(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        for ch in data["characters"]:
            assert ch["localizations"]["en"] == ch["canonical"], (
                f"{ch['canonical']}: en localization != canonical"
            )

    @pytest.mark.parametrize("canonical", NEEDS_REVIEW)
    def test_needs_review_absent(self, canonical):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        canonicals = [ch["canonical"] for ch in data["characters"]]
        assert canonical not in canonicals, (
            f"needs_review character {canonical!r} should not be in pack"
        )

    def test_series_aliases_include_lowercase(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        aliases = data["series"][0]["aliases"]
        assert "wuthering waves" in aliases

    def test_series_aliases_include_wuwa(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        aliases = data["series"][0]["aliases"]
        assert "WuWa" in aliases

    def test_series_aliases_include_ko(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        aliases = data["series"][0]["aliases"]
        assert "명조" in aliases
        assert "워더링 웨이브스" in aliases

    def test_series_aliases_include_cjk(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        aliases = data["series"][0]["aliases"]
        assert "鳴潮" in aliases


# ---------------------------------------------------------------------------
# KO / JA localization correctness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("canonical,expected", [
    (c, ko) for c, (ko, _) in WW_CHARACTERS.items()
])
def test_ko_localization(canonical, expected):
    with open(_WW_PACK, encoding="utf-8") as f:
        data = json.load(f)
    ch = next((x for x in data["characters"] if x["canonical"] == canonical), None)
    assert ch is not None, f"{canonical} not found in pack"
    assert ch["localizations"]["ko"] == expected, (
        f"{canonical} ko: expected={expected!r}, got={ch['localizations']['ko']!r}"
    )


@pytest.mark.parametrize("canonical,expected", [
    (c, ja) for c, (_, ja) in WW_CHARACTERS.items()
])
def test_ja_localization(canonical, expected):
    with open(_WW_PACK, encoding="utf-8") as f:
        data = json.load(f)
    ch = next((x for x in data["characters"] if x["canonical"] == canonical), None)
    assert ch is not None, f"{canonical} not found in pack"
    assert ch["localizations"]["ja"] == expected, (
        f"{canonical} ja: expected={expected!r}, got={ch['localizations']['ja']!r}"
    )


# ---------------------------------------------------------------------------
# Locale-mismatch safety
# ---------------------------------------------------------------------------

class TestNoLocaleMismatch:
    """ko localization must be hangul-dominant; ja must be CJK/kana-dominant."""

    def _hangul_ratio(self, s):
        if not s:
            return 0.0
        hangul = sum(1 for c in s if "가" <= c <= "힣" or "㄰" <= c <= "㆏")
        return hangul / len(s)

    def _cjk_kana_ratio(self, s):
        if not s:
            return 0.0
        cjk_kana = sum(
            1 for c in s
            if "一" <= c <= "鿿"
            or "぀" <= c <= "ヿ"
            or "ㇰ" <= c <= "ㇿ"
            or "･" <= c <= "ﾟ"
        )
        return cjk_kana / len(s)

    def test_ko_fields_are_hangul(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        for ch in data["characters"]:
            ko = ch["localizations"]["ko"]
            assert self._hangul_ratio(ko) >= 0.3, (
                f"{ch['canonical']} ko={ko!r} hangul ratio < 30%"
            )

    def test_ja_fields_are_cjk_or_kana(self):
        with open(_WW_PACK, encoding="utf-8") as f:
            data = json.load(f)
        for ch in data["characters"]:
            ja = ch["localizations"]["ja"]
            assert self._cjk_kana_ratio(ja) >= 0.3, (
                f"{ch['canonical']} ja={ja!r} CJK/kana ratio < 30%"
            )


# ---------------------------------------------------------------------------
# DB alias round-trip
# ---------------------------------------------------------------------------

class TestWuWaDB:

    def test_seed_returns_nonzero_aliases(self, ww_conn):
        cur = ww_conn.execute(
            "SELECT COUNT(*) FROM tag_aliases WHERE parent_series='Wuthering Waves'"
        )
        count = cur.fetchone()[0]
        assert count > 0

    def test_seed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            c = initialize_database(str(Path(td) / "ww2.db"))
            seed_tag_pack(c, load_tag_pack(_WW_PACK))
            r2 = seed_tag_pack(c, load_tag_pack(_WW_PACK))
            c.close()
        assert r2["localizations"] == 0
        assert r2["series_aliases"] == 0

    @pytest.mark.parametrize("alias,canonical", [
        ("양양",          "Yangyang"),
        ("秧秧",          "Yangyang"),
        ("파수인",        "Shorekeeper"),
        ("ショアキーパー", "Shorekeeper"),
        ("ツバキ",        "Camellya"),
        ("カメリア",      "Camellya"),
        ("카멜리아",      "Camellya"),
        ("명조",          "Wuthering Waves"),
        ("WuWa",          "Wuthering Waves"),
        ("鳴潮",          "Wuthering Waves"),
    ])
    def test_alias_resolves(self, ww_conn, alias, canonical):
        cur = ww_conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias=?", (alias,)
        )
        row = cur.fetchone()
        assert row is not None, f"alias {alias!r} not found in DB"
        assert row[0] == canonical, (
            f"alias {alias!r}: expected canonical={canonical!r}, got={row[0]!r}"
        )

    @pytest.mark.parametrize("canonical,locale,expected", [
        ("Yangyang",       "ko", "양양"),
        ("Yangyang",       "ja", "秧秧"),
        ("Shorekeeper",    "ko", "파수인"),
        ("Shorekeeper",    "ja", "ショアキーパー"),
        ("Camellya",       "ko", "카멜리아"),
        ("Camellya",       "ja", "ツバキ"),
        ("Xiangli Yao",    "ko", "상리요"),
        ("Xiangli Yao",    "ja", "相里要"),
        ("Wuthering Waves","ko", "명조"),
        ("Wuthering Waves","ja", "鳴潮"),
    ])
    def test_localization_in_db(self, ww_conn, canonical, locale, expected):
        cur = ww_conn.execute(
            "SELECT display_name FROM tag_localizations WHERE canonical=? AND locale=?",
            (canonical, locale),
        )
        row = cur.fetchone()
        assert row is not None, f"localization ({canonical!r}, {locale!r}) not in DB"
        assert row[0] == expected, (
            f"({canonical!r}, {locale!r}): expected={expected!r}, got={row[0]!r}"
        )

    @pytest.mark.parametrize("canonical", NEEDS_REVIEW)
    def test_needs_review_not_in_db(self, ww_conn, canonical):
        cur = ww_conn.execute(
            "SELECT canonical FROM tag_aliases WHERE canonical=? AND parent_series='Wuthering Waves'",
            (canonical,),
        )
        assert cur.fetchone() is None, (
            f"needs_review {canonical!r} should not be seeded into DB"
        )


# ---------------------------------------------------------------------------
# Special character notes
# ---------------------------------------------------------------------------

class TestSpecialCases:

    def test_camellya_has_both_ja_aliases(self, ww_conn):
        """Camellya JA: ツバキ (official) and カメリア (phonetic) both aliased."""
        for alias in ("ツバキ", "カメリア"):
            cur = ww_conn.execute(
                "SELECT canonical FROM tag_aliases WHERE alias=?", (alias,)
            )
            row = cur.fetchone()
            assert row is not None and row[0] == "Camellya", (
                f"Camellya alias {alias!r} not found"
            )

    def test_shorekeeper_ko_is_pasu_in(self, ww_conn):
        """Shorekeeper KO 파수인 — valid under parent_series scoping."""
        cur = ww_conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias='파수인' AND parent_series='Wuthering Waves'"
        )
        row = cur.fetchone()
        assert row is not None and row[0] == "Shorekeeper"

    def test_rover_absent(self, ww_conn):
        """Rover (방랑자) excluded entirely due to general-noun collision."""
        for alias in ("Rover", "방랑자", "명조 방랑자"):
            cur = ww_conn.execute(
                "SELECT canonical FROM tag_aliases WHERE alias=? AND parent_series='Wuthering Waves'",
                (alias,),
            )
            assert cur.fetchone() is None, (
                f"Rover alias {alias!r} must not appear in WW pack"
            )
