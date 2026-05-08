"""tests/test_tag_pack_hoyoverse_enrichment.py

Phase C-1 HoYoverse enrichment 회귀 테스트.

대상 시리즈:
  - Genshin Impact   (v1.1.0): 시리즈 alias 보강 + 7캐릭터 seed
  - Honkai: Star Rail (v1.1.0): 시리즈 alias 보강 + 5캐릭터 seed
  - Zenless Zone Zero (v1.1.0): 시리즈 alias 보강 + 4캐릭터 seed

캐릭터 canonical 정책: EN canonical (시리즈 canonical 언어와 일치).
KO localization: 게임 한국어 클라이언트 표기 기준.
JA localization: 게임 일본어 클라이언트 표기 기준.

보류 (needs_review, 미등록):
  - GI: 루미네/에테르(형/공 KO 표기 혼동 위험), 카즈하, 야에 미코 등
  - HSR: Seele, Firefly, Ruan Mei 등 KO 표기 불확실
  - ZZZ: Zhu Yuan, Rina 등 KO 표기 불확실
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database


_PACKS_DIR = Path(__file__).parent.parent / "resources" / "tag_packs"

GI_PACK_PATH  = _PACKS_DIR / "genshin_impact.json"
HSR_PACK_PATH = _PACKS_DIR / "honkai_star_rail.json"
ZZZ_PACK_PATH = _PACKS_DIR / "zenless_zone_zero.json"

GI_SERIES  = "Genshin Impact"
HSR_SERIES = "Honkai: Star Rail"
ZZZ_SERIES = "Zenless Zone Zero"

# ---------------------------------------------------------------------------
# 시드된 캐릭터 목록 (EN canonical → (KO, JA))
# ---------------------------------------------------------------------------

GI_CHARACTERS: dict[str, tuple[str, str]] = {
    "Hu Tao":        ("호두",        "胡桃"),
    "Keqing":        ("각청",        "刻晴"),
    "Ganyu":         ("감우",        "甘雨"),
    "Zhongli":       ("종리",        "鍾離"),
    "Raiden Shogun": ("라이덴 쇼군", "雷電将軍"),
    "Nahida":        ("나히다",      "ナヒーダ"),
    "Furina":        ("후리나",      "フリーナ"),
}

HSR_CHARACTERS: dict[str, tuple[str, str]] = {
    "Kafka":      ("카프카",   "カフカ"),
    "Blade":      ("블레이드", "刃"),
    "Bronya":     ("브로냐",   "ブローニャ"),
    "Black Swan": ("블랙 스완","ブラックスワン"),
    "Jingliu":    ("경류",     "鏡流"),
}

ZZZ_CHARACTERS: dict[str, tuple[str, str]] = {
    "Nicole Demara": ("니콜 드마라", "ニコル・デマーラ"),
    "Ellen Joe":     ("엘런 조",     "エレン・ジョー"),
    "Yanagi":        ("야나기",      "柳"),
    "Jane Doe":      ("제인",        "ジェーン"),
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gi_conn(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("gi") / "gi.db")
    c = initialize_database(db)
    seed_tag_pack(c, load_tag_pack(GI_PACK_PATH))
    yield c
    c.close()


@pytest.fixture(scope="module")
def hsr_conn(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("hsr") / "hsr.db")
    c = initialize_database(db)
    seed_tag_pack(c, load_tag_pack(HSR_PACK_PATH))
    yield c
    c.close()


@pytest.fixture(scope="module")
def zzz_conn(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("zzz") / "zzz.db")
    c = initialize_database(db)
    seed_tag_pack(c, load_tag_pack(ZZZ_PACK_PATH))
    yield c
    c.close()


# ===========================================================================
# 1. Pack 파일 구조 및 버전 확인
# ===========================================================================

class TestPackVersions:
    def test_genshin_version(self):
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        assert pack["version"] == "1.1.0", f"GI version: {pack['version']}"

    def test_hsr_version(self):
        pack = json.loads(HSR_PACK_PATH.read_text(encoding="utf-8"))
        assert pack["version"] == "1.1.0", f"HSR version: {pack['version']}"

    def test_zzz_version(self):
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        assert pack["version"] == "1.1.0", f"ZZZ version: {pack['version']}"

    def test_genshin_character_count(self):
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        assert len(pack["characters"]) == len(GI_CHARACTERS)

    def test_hsr_character_count(self):
        pack = json.loads(HSR_PACK_PATH.read_text(encoding="utf-8"))
        assert len(pack["characters"]) == len(HSR_CHARACTERS)

    def test_zzz_character_count(self):
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        assert len(pack["characters"]) == len(ZZZ_CHARACTERS)


# ===========================================================================
# 2. 시리즈 alias 추가 확인 (Hitomi lowercase compat)
# ===========================================================================

class TestSeriesAliasAdditions:
    def test_genshin_lowercase_alias(self):
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        aliases = pack["series"][0]["aliases"]
        assert "genshin impact" in aliases, "genshin impact (소문자) alias 누락"

    def test_genshin_short_ko_alias(self):
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        aliases = pack["series"][0]["aliases"]
        assert "겐신" in aliases, "겐신 (단축 KO) alias 누락"

    def test_hsr_lowercase_alias(self):
        pack = json.loads(HSR_PACK_PATH.read_text(encoding="utf-8"))
        aliases = pack["series"][0]["aliases"]
        assert "honkai star rail" in aliases, "honkai star rail (소문자) alias 누락"

    def test_hsr_no_colon_ko_alias(self):
        pack = json.loads(HSR_PACK_PATH.read_text(encoding="utf-8"))
        aliases = pack["series"][0]["aliases"]
        assert "붕괴 스타레일" in aliases, "붕괴 스타레일 (콜론 없음) alias 누락"

    def test_zzz_lowercase_alias(self):
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        aliases = pack["series"][0]["aliases"]
        assert "zenless zone zero" in aliases, "zenless zone zero (소문자) alias 누락"


# ===========================================================================
# 3. Pack 파일 캐릭터 localizations 검증
# ===========================================================================

class TestGenshinCharacterLocalizations:
    @pytest.mark.parametrize("canonical,ko_ja", list(GI_CHARACTERS.items()))
    def test_ko_localization(self, canonical, ko_ja):
        expected_ko, _ = ko_ja
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char is not None, f"캐릭터 없음: {canonical}"
        assert char["localizations"].get("ko") == expected_ko, (
            f"{canonical} ko: {char['localizations'].get('ko')!r} != {expected_ko!r}"
        )

    @pytest.mark.parametrize("canonical,ko_ja", list(GI_CHARACTERS.items()))
    def test_ja_localization(self, canonical, ko_ja):
        _, expected_ja = ko_ja
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char is not None, f"캐릭터 없음: {canonical}"
        assert char["localizations"].get("ja") == expected_ja, (
            f"{canonical} ja: {char['localizations'].get('ja')!r} != {expected_ja!r}"
        )

    @pytest.mark.parametrize("canonical", list(GI_CHARACTERS.keys()))
    def test_parent_series(self, canonical):
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char["parent_series"] == GI_SERIES


class TestHSRCharacterLocalizations:
    @pytest.mark.parametrize("canonical,ko_ja", list(HSR_CHARACTERS.items()))
    def test_ko_localization(self, canonical, ko_ja):
        expected_ko, _ = ko_ja
        pack = json.loads(HSR_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char is not None, f"캐릭터 없음: {canonical}"
        assert char["localizations"].get("ko") == expected_ko

    @pytest.mark.parametrize("canonical,ko_ja", list(HSR_CHARACTERS.items()))
    def test_ja_localization(self, canonical, ko_ja):
        _, expected_ja = ko_ja
        pack = json.loads(HSR_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char is not None, f"캐릭터 없음: {canonical}"
        assert char["localizations"].get("ja") == expected_ja

    @pytest.mark.parametrize("canonical", list(HSR_CHARACTERS.keys()))
    def test_parent_series(self, canonical):
        pack = json.loads(HSR_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char["parent_series"] == HSR_SERIES


class TestZZZCharacterLocalizations:
    @pytest.mark.parametrize("canonical,ko_ja", list(ZZZ_CHARACTERS.items()))
    def test_ko_localization(self, canonical, ko_ja):
        expected_ko, _ = ko_ja
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char is not None, f"캐릭터 없음: {canonical}"
        assert char["localizations"].get("ko") == expected_ko

    @pytest.mark.parametrize("canonical,ko_ja", list(ZZZ_CHARACTERS.items()))
    def test_ja_localization(self, canonical, ko_ja):
        _, expected_ja = ko_ja
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char is not None, f"캐릭터 없음: {canonical}"
        assert char["localizations"].get("ja") == expected_ja

    @pytest.mark.parametrize("canonical", list(ZZZ_CHARACTERS.keys()))
    def test_parent_series(self, canonical):
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        char = next((c for c in pack["characters"] if c["canonical"] == canonical), None)
        assert char["parent_series"] == ZZZ_SERIES


# ===========================================================================
# 4. 특수 alias 확인 (pack 파일 레벨)
# ===========================================================================

class TestSpecialAliases:
    def test_raiden_ei_alias(self):
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        raiden = next(c for c in pack["characters"] if c["canonical"] == "Raiden Shogun")
        assert "Ei" in raiden["aliases"], "Raiden Shogun alias에 Ei 누락"
        assert "에이" in raiden["aliases"], "Raiden Shogun alias에 에이(KO) 누락"

    def test_furina_focalors_alias(self):
        pack = json.loads(GI_PACK_PATH.read_text(encoding="utf-8"))
        furina = next(c for c in pack["characters"] if c["canonical"] == "Furina")
        assert "Focalors" in furina["aliases"], "Furina alias에 Focalors 누락"
        assert "포칼로스" in furina["aliases"], "Furina alias에 포칼로스(KO) 누락"

    def test_nicole_short_alias(self):
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        nicole = next(c for c in pack["characters"] if c["canonical"] == "Nicole Demara")
        assert "Nicole" in nicole["aliases"], "Nicole Demara alias에 Nicole 누락"

    def test_ellen_short_alias(self):
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        ellen = next(c for c in pack["characters"] if c["canonical"] == "Ellen Joe")
        assert "Ellen" in ellen["aliases"], "Ellen Joe alias에 Ellen 누락"

    def test_jane_doe_short_alias(self):
        pack = json.loads(ZZZ_PACK_PATH.read_text(encoding="utf-8"))
        jane = next(c for c in pack["characters"] if c["canonical"] == "Jane Doe")
        assert "Jane" in jane["aliases"], "Jane Doe alias에 Jane 누락"


# ===========================================================================
# 5. Loader locale-mismatch 경고 없음
# ===========================================================================

class TestNoLocaleMismatch:
    @pytest.mark.parametrize("pack_path,pack_id", [
        (GI_PACK_PATH,  "genshin_impact"),
        (HSR_PACK_PATH, "honkai_star_rail"),
        (ZZZ_PACK_PATH, "zenless_zone_zero"),
    ])
    def test_no_locale_mismatch_warning(self, pack_path, pack_id, tmp_path, caplog):
        from db.database import initialize_database as init_db
        db = str(tmp_path / f"{pack_id}_lint.db")
        c = init_db(db)
        try:
            pack = load_tag_pack(pack_path)
            with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
                seed_tag_pack(c, pack)
            offending = [
                r for r in caplog.records
                if pack_id in r.getMessage() and "locale-mismatch" in r.getMessage()
            ]
            assert not offending, (
                f"{pack_id} locale-mismatch 경고 발생: "
                f"{[r.getMessage() for r in offending]}"
            )
        finally:
            c.close()


# ===========================================================================
# 6. DB 레벨 — alias 해석 및 localization 등록 확인
# ===========================================================================

class TestGenshinDB:
    @pytest.mark.parametrize("alias,expected_canonical", [
        ("호두",        "Hu Tao"),
        ("胡桃",        "Hu Tao"),
        ("각청",        "Keqing"),
        ("刻晴",        "Keqing"),
        ("감우",        "Ganyu"),
        ("종리",        "Zhongli"),
        ("라이덴 쇼군", "Raiden Shogun"),
        ("雷電将軍",    "Raiden Shogun"),
        ("Ei",          "Raiden Shogun"),
        ("에이",        "Raiden Shogun"),
        ("나히다",      "Nahida"),
        ("ナヒーダ",    "Nahida"),
        ("후리나",      "Furina"),
        ("Focalors",    "Furina"),
        ("포칼로스",    "Furina"),
    ])
    def test_alias_resolves_to_canonical(self, gi_conn, alias, expected_canonical):
        row = gi_conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (alias,),
        ).fetchone()
        assert row is not None, f"alias 미등록: {alias!r}"
        assert row["canonical"] == expected_canonical, (
            f"{alias!r} → {row['canonical']!r} (기대: {expected_canonical!r})"
        )

    @pytest.mark.parametrize("canonical,expected_ko", [
        ("Hu Tao",        "호두"),
        ("Raiden Shogun", "라이덴 쇼군"),
        ("Nahida",        "나히다"),
        ("Furina",        "후리나"),
    ])
    def test_ko_localization_in_db(self, gi_conn, canonical, expected_ko):
        row = gi_conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'character' AND locale = 'ko'",
            (canonical,),
        ).fetchone()
        assert row is not None, f"KO localization 미등록: {canonical}"
        assert row["display_name"] == expected_ko

    def test_genshin_lowercase_series_alias_in_db(self, gi_conn):
        row = gi_conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("genshin impact",),
        ).fetchone()
        assert row is not None, "genshin impact (소문자) alias 미등록"
        assert row["canonical"] == GI_SERIES


class TestHSRDB:
    @pytest.mark.parametrize("alias,expected_canonical", [
        ("카프카",   "Kafka"),
        ("カフカ",   "Kafka"),
        ("블레이드", "Blade"),
        ("刃",       "Blade"),
        ("브로냐",   "Bronya"),
        ("ブローニャ","Bronya"),
        ("블랙 스완","Black Swan"),
        ("ブラックスワン","Black Swan"),
        ("경류",     "Jingliu"),
        ("鏡流",     "Jingliu"),
    ])
    def test_alias_resolves_to_canonical(self, hsr_conn, alias, expected_canonical):
        row = hsr_conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (alias,),
        ).fetchone()
        assert row is not None, f"alias 미등록: {alias!r}"
        assert row["canonical"] == expected_canonical, (
            f"{alias!r} → {row['canonical']!r} (기대: {expected_canonical!r})"
        )

    def test_hsr_lowercase_series_alias_in_db(self, hsr_conn):
        row = hsr_conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("honkai star rail",),
        ).fetchone()
        assert row is not None, "honkai star rail (소문자) alias 미등록"
        assert row["canonical"] == HSR_SERIES

    def test_hsr_no_colon_ko_alias_in_db(self, hsr_conn):
        row = hsr_conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("붕괴 스타레일",),
        ).fetchone()
        assert row is not None, "붕괴 스타레일 alias 미등록"
        assert row["canonical"] == HSR_SERIES


class TestZZZDB:
    @pytest.mark.parametrize("alias,expected_canonical", [
        ("니콜 드마라",   "Nicole Demara"),
        ("ニコル・デマーラ","Nicole Demara"),
        ("Nicole",        "Nicole Demara"),
        ("엘런 조",       "Ellen Joe"),
        ("エレン・ジョー", "Ellen Joe"),
        ("Ellen",         "Ellen Joe"),
        ("야나기",        "Yanagi"),
        ("柳",            "Yanagi"),
        ("제인",          "Jane Doe"),
        ("ジェーン",      "Jane Doe"),
        ("Jane",          "Jane Doe"),
    ])
    def test_alias_resolves_to_canonical(self, zzz_conn, alias, expected_canonical):
        row = zzz_conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (alias,),
        ).fetchone()
        assert row is not None, f"alias 미등록: {alias!r}"
        assert row["canonical"] == expected_canonical, (
            f"{alias!r} → {row['canonical']!r} (기대: {expected_canonical!r})"
        )

    def test_zzz_lowercase_series_alias_in_db(self, zzz_conn):
        row = zzz_conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("zenless zone zero",),
        ).fetchone()
        assert row is not None, "zenless zone zero (소문자) alias 미등록"
        assert row["canonical"] == ZZZ_SERIES
