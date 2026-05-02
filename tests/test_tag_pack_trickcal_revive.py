"""tests/test_tag_pack_trickcal_revive.py

Trickcal Re:VIVE tag pack 회귀 테스트 (확장판).

본 테스트는 PR #95 의 최소 세트와 본 PR 의 확장 세트 양쪽을 한 곳에서 lock 한다.

확장 항목 (본 PR):
  - Series alias: "Trickcal: Chibi Go" / "Trickcal Chibi Go" (같은 IP 다른 SKU
    를 같은 canonical 로 흡수)
  - 신규 KR character 12명: 다야/이프리트/마에스트로 2호/림/스피키/실라/벨벳/
    빅우드/제이드/벨리타/벨라/교주
  - 보조 출처 기반 EN/JA alias: 에르핀/네르/버터/요미/클로에/이드/아멜리아/티그/
    헤일리 (안정 세트만)
  - 코스튬 변형 alias (별도 entry 가 아니라 base 의 alias):
    헤일리(멀쩡)/네르(빡침)/에르핀(왕도)/아멜리아(R41)/티그(Hero)

여전히 보류 (이번 PR 미포함):
  - 에슈르/코미/하이디/델리아/아라그니아/리코타/시저 EN 표기
  - 일부 EN/JA 흔들림 표기 (Haley / Asher / Eshur / Ashur / Heidi / Kommy / Comi)
  - 중문 alias
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from core.autocomplete_provider import suggest_tag_completions
from core.classification_inference import infer_character_series_candidates
from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database


PACK_PATH = (
    Path(__file__).parent.parent / "resources" / "tag_packs" / "trickcal_revive.json"
)

CANONICAL_SERIES = "Trickcal Re:VIVE"

# 확장 후 등록되는 30명. 변경 시 의도된 결정이어야 한다.
EXPECTED_CHARACTERS_KO: list[str] = [
    # 최소 세트 (PR #95) — 18명
    "에르핀", "에슈르", "네르", "버터", "코미",
    "요미", "클로에", "델리아", "아라그니아", "리코타",
    "이드", "아멜리아", "티그", "하이디", "시저", "헤일리",
    "아사나", "뮤트",
    # 본 PR 확장 — 보조 출처 단독 KR 12명 (교주 포함)
    "다야", "이프리트", "마에스트로 2호", "림", "스피키", "실라",
    "벨벳", "빅우드", "제이드", "벨리타", "벨라", "교주",
]

# 공식 EN 또는 안정 보조 EN 이 확보된 캐릭터 → 해당 KR canonical 의 EN alias.
# 흔들림이 큰 항목 (에슈르/코미/하이디/델리아/아라그니아/리코타/시저 EN, 헤일리 EN) 은 추가 안 함.
EXPECTED_EN_BY_KO: dict[str, str] = {
    "아사나":   "Asana",     # 공식 (보도자료 본문)
    "뮤트":     "Mute",      # 공식 (보도자료 본문)
    "에르핀":   "Erpin",     # 보조 안정
    "네르":     "Ner",       # 보조 안정
    "버터":     "Butter",    # 보조 안정
    "요미":     "Yomi",      # 보조 안정
    "클로에":   "Chloe",     # 보조 안정
    "아멜리아": "Amelia",    # 보조 안정
    "티그":     "Tig",       # 보조 안정
}

# 보조 안정 JA 표기. 헤일리 도 JA 만 추가 (EN Haley 는 보류).
EXPECTED_JA_BY_KO: dict[str, str] = {
    "에르핀":   "エルフィン",
    "네르":     "ネル",
    "버터":     "バター",
    "요미":     "ヨミ",
    "클로에":   "クロエ",
    "이드":     "イード",
    "아멜리아": "アメリア",
    "티그":     "ティグ",
    "헤일리":   "ヘイリー",
}

# base canonical → 코스튬 변형 alias 의 매핑. 별도 entry 가 아니라 base alias 로 추가됨.
EXPECTED_COSTUME_ALIASES: dict[str, list[str]] = {
    "에르핀":   ["에르핀(왕도)"],
    "네르":     ["네르(빡침)"],
    "아멜리아": ["아멜리아(R41)"],
    "티그":     ["티그(Hero)"],
    "헤일리":   ["헤일리(멀쩡)"],
}

# 본 PR 에서도 여전히 등록 금지인 EN 표기. (회귀 가드)
PENDING_EN_NAMES: list[str] = [
    "Haley", "Eshur", "Asher", "Ashur", "Heidi",
    "Kommy", "Comi", "Delia", "Aragnia", "Ricotta", "Caesar",
]

# 중문 alias — 보류 유지.
PENDING_SERIES_ALIASES: list[str] = [
    "嘟뚜脸恶作剧",
]


# ---------------------------------------------------------------------------
# Static pack file invariants (DB 무관)
# ---------------------------------------------------------------------------

class TestPackFileShape:
    def test_pack_file_exists(self):
        assert PACK_PATH.exists()

    def test_pack_id_and_canonical(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert pack["pack_id"] == "trickcal_revive"
        assert pack["source"] == "built_in"
        assert pack["series"][0]["canonical"] == CANONICAL_SERIES
        assert pack["series"][0]["media_type"] == "game"

    def test_series_aliases_contain_required_strings(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        aliases = pack["series"][0]["aliases"]
        # Hitomi 호환 lowercase + colon 없는 변형 필수
        assert "trickcal revive" in aliases
        for required in ["트릭컬 리바이브", "트릭컬 RE:VIVE", "트릭컬"]:
            assert required in aliases, f"alias 누락: {required!r}"
        for required in ["トリッカル・もちもちほっペ大作戦", "トリッカル"]:
            assert required in aliases, f"alias 누락: {required!r}"
        for required in ["Trickcal Re:VIVE", "Trickcal", "Trickcal Revive"]:
            assert required in aliases, f"alias 누락: {required!r}"
        # 본 PR 확장 — 같은 IP 다른 SKU alias
        for required in ["Trickcal: Chibi Go", "Trickcal Chibi Go"]:
            assert required in aliases, f"신규 alias 누락: {required!r}"

    def test_series_localizations_per_locale_script_ratio(self):
        """FGO lint fix 와 동일한 invariant — locale-mismatch 회귀 가드."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        locs = pack["series"][0]["localizations"]

        ko = locs["ko"]
        ko_count = sum(1 for ch in ko if "가" <= ch <= "힣")
        assert ko_count / max(len(ko), 1) >= 0.30, (
            f"ko localization 한글 비율 < 30%: {ko!r}"
        )

        ja = locs["ja"]
        ja_count = sum(
            1 for ch in ja
            if ("぀" <= ch <= "ゟ")
            or ("゠" <= ch <= "ヿ")
            or ("一" <= ch <= "鿿")
        )
        assert ja_count / max(len(ja), 1) >= 0.30, (
            f"ja localization 일본어 비율 < 30%: {ja!r}"
        )

    def test_series_localization_en_unchanged(self):
        """Chibi Go alias 추가가 localizations.en 을 덮어쓰지 않는다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert pack["series"][0]["localizations"]["en"] == "Trickcal Re:VIVE"

    def test_no_pending_series_aliases(self):
        """중문 표기 등 보류 alias 가 섞이지 않았다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        aliases = set(pack["series"][0]["aliases"])
        for pending in PENDING_SERIES_ALIASES:
            assert pending not in aliases, f"보류 alias 가 등록됨: {pending!r}"

    def test_character_roster_count_and_canonicals(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        canonicals = [c["canonical"] for c in pack["characters"]]
        assert canonicals == EXPECTED_CHARACTERS_KO, (
            "캐릭터 목록이 의도와 다름. 추가/삭제는 명시적 결정이어야 함."
        )
        assert len(canonicals) == 30

    def test_no_costume_canonical_entries(self):
        """코스튬 변형은 canonical entry 가 아니라 base 의 alias 여야 한다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        canonicals = {c["canonical"] for c in pack["characters"]}
        for costumes in EXPECTED_COSTUME_ALIASES.values():
            for variant in costumes:
                assert variant not in canonicals, (
                    f"코스튬 변형이 별도 canonical 로 등록됨: {variant!r}"
                )

    def test_costume_aliases_attached_to_base(self):
        """각 코스튬 변형이 base canonical 의 aliases 에 들어 있다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for base, variants in EXPECTED_COSTUME_ALIASES.items():
            entry = char_by_canonical[base]
            for variant in variants:
                assert variant in entry["aliases"], (
                    f"{base!r} 의 aliases 에 {variant!r} 누락"
                )

    def test_every_character_has_parent_series(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        for char in pack["characters"]:
            assert char["parent_series"] == CANONICAL_SERIES, (
                f"parent_series 누락 또는 불일치: {char['canonical']!r}"
            )

    def test_character_en_localization_only_for_expected(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        for char in pack["characters"]:
            ko_canonical = char["canonical"]
            locs = char["localizations"]
            if ko_canonical in EXPECTED_EN_BY_KO:
                assert locs.get("en") == EXPECTED_EN_BY_KO[ko_canonical], (
                    f"{ko_canonical!r} en localization 불일치: "
                    f"{locs.get('en')!r} != {EXPECTED_EN_BY_KO[ko_canonical]!r}"
                )
            else:
                assert "en" not in locs, (
                    f"보류 EN 항목에 en localization 등록됨: "
                    f"{ko_canonical} → {locs.get('en')!r}"
                )

    def test_character_ja_localization_only_for_expected(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        for char in pack["characters"]:
            ko_canonical = char["canonical"]
            locs = char["localizations"]
            if ko_canonical in EXPECTED_JA_BY_KO:
                assert locs.get("ja") == EXPECTED_JA_BY_KO[ko_canonical], (
                    f"{ko_canonical!r} ja localization 불일치: "
                    f"{locs.get('ja')!r} != {EXPECTED_JA_BY_KO[ko_canonical]!r}"
                )
            else:
                assert "ja" not in locs, (
                    f"보류 JA 항목에 ja localization 등록됨: "
                    f"{ko_canonical} → {locs.get('ja')!r}"
                )

    def test_no_pending_en_aliases(self):
        """본 PR 에서도 등록 금지인 EN 표기가 alias 에 섞이지 않았다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        all_aliases: set[str] = set()
        for char in pack["characters"]:
            all_aliases.update(char["aliases"])
        for pending in PENDING_EN_NAMES:
            assert pending not in all_aliases, (
                f"보류 EN alias 가 등록됨: {pending!r}"
            )

    def test_official_en_preserved_for_asana_mute(self):
        """공식 EN 이 이미 있는 Asana / Mute 는 보조 표기로 덮어쓰지 않는다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        asana = char_by_canonical["아사나"]
        assert asana["localizations"]["en"] == "Asana"
        assert "Asana" in asana["aliases"]
        mute = char_by_canonical["뮤트"]
        assert mute["localizations"]["en"] == "Mute"
        assert "Mute" in mute["aliases"]


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


class TestLoaderEmitsNoLintWarning:
    def test_no_locale_mismatch_warning(self, tmp_path, caplog):
        db = str(tmp_path / "lint.db")
        c = initialize_database(db)
        try:
            pack = load_tag_pack(PACK_PATH)
            with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
                seed_tag_pack(c, pack)
            offending = [
                rec for rec in caplog.records
                if "trickcal_revive" in rec.getMessage()
                and "locale-mismatch" in rec.getMessage()
            ]
            assert not offending, (
                f"locale-mismatch warning 발생: "
                f"{[r.getMessage() for r in offending]}"
            )
        finally:
            c.close()


class TestSeriesAliasesRegistered:
    def test_hitomi_compat_alias_registered(self, conn):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("trickcal revive",),
        ).fetchone()
        assert row is not None
        assert row["canonical"] == CANONICAL_SERIES

    def test_korean_aliases_registered(self, conn):
        for alias in ["트릭컬", "트릭컬 리바이브", "트릭컬 RE:VIVE"]:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert row is not None, f"alias 미등록: {alias!r}"
            assert row["canonical"] == CANONICAL_SERIES

    def test_japanese_aliases_registered(self, conn):
        for alias in ["トリッカル・もちもちほっペ大作戦", "トリッカル"]:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert row is not None, f"JA alias 미등록: {alias!r}"
            assert row["canonical"] == CANONICAL_SERIES

    def test_chibi_go_aliases_registered_to_same_canonical(self, conn):
        """본 PR 신규 — Trickcal: Chibi Go / Trickcal Chibi Go 가 같은 canonical 로."""
        for alias in ["Trickcal: Chibi Go", "Trickcal Chibi Go"]:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert row is not None, f"신규 alias 미등록: {alias!r}"
            assert row["canonical"] == CANONICAL_SERIES, (
                f"{alias!r} 가 별도 canonical 로 등록됨: {row['canonical']!r}"
            )

    def test_chibi_go_does_not_create_separate_series_canonical(self, conn):
        """Chibi Go 가 별도 series canonical 로 등록되지 않았다."""
        rows = conn.execute(
            "SELECT DISTINCT canonical FROM tag_aliases "
            "WHERE tag_type = 'series' AND alias LIKE '%Chibi Go%'"
        ).fetchall()
        assert len(rows) >= 1
        for row in rows:
            assert row["canonical"] == CANONICAL_SERIES


class TestSeriesLocalizationsRegistered:
    def test_ko_localization(self, conn):
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'series' AND locale = 'ko'",
            (CANONICAL_SERIES,),
        ).fetchone()
        assert row is not None
        assert row["display_name"] == "트릭컬 리바이브"

    def test_ja_localization(self, conn):
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'series' AND locale = 'ja'",
            (CANONICAL_SERIES,),
        ).fetchone()
        assert row is not None
        assert row["display_name"] == "トリッカル・もちもちほっペ大作戦"

    def test_en_localization_unchanged_after_chibi_go_addition(self, conn):
        """Chibi Go alias 추가 후에도 en localization 은 'Trickcal Re:VIVE'."""
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'series' AND locale = 'en'",
            (CANONICAL_SERIES,),
        ).fetchone()
        assert row is not None
        assert row["display_name"] == "Trickcal Re:VIVE"


class TestCharactersRegistered:
    def test_all_30_characters_have_parent_series(self, conn):
        for ko in EXPECTED_CHARACTERS_KO:
            row = conn.execute(
                "SELECT parent_series FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (ko,),
            ).fetchone()
            assert row is not None, f"character alias 미등록: {ko!r}"
            assert row["parent_series"] == CANONICAL_SERIES, (
                f"parent_series 불일치: {ko!r} → {row['parent_series']!r}"
            )

    @pytest.mark.parametrize("ko_name", [
        "다야", "이프리트", "마에스트로 2호", "림", "스피키", "실라",
        "벨벳", "빅우드", "제이드", "벨리타", "벨라", "교주",
    ])
    def test_new_namuwiki_kr_character_registered(self, conn, ko_name):
        """본 PR 신규 — 보조 출처 단독 KR 12명 등록."""
        row = conn.execute(
            "SELECT canonical, parent_series FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (ko_name,),
        ).fetchone()
        assert row is not None, f"신규 KR character 미등록: {ko_name!r}"
        assert row["canonical"] == ko_name
        assert row["parent_series"] == CANONICAL_SERIES

    def test_kyoju_has_disambiguating_parent_series(self, conn):
        """교주 (일반명사 충돌 위험) — parent_series 로 disambiguation 보장."""
        row = conn.execute(
            "SELECT canonical, parent_series FROM tag_aliases "
            "WHERE alias = '교주' AND tag_type = 'character' AND enabled = 1"
        ).fetchone()
        assert row is not None
        assert row["parent_series"] == CANONICAL_SERIES
        assert row["parent_series"] != "", (
            "교주 entry 의 parent_series 가 비어있음 — disambiguation 실패"
        )


class TestEnAliasesMapToKoCanonical:
    @pytest.mark.parametrize("en_alias,expected_canonical", [
        ("Erpin",   "에르핀"),
        ("Ner",     "네르"),
        ("Butter",  "버터"),
        ("Yomi",    "요미"),
        ("Chloe",   "클로에"),
        ("Amelia",  "아멜리아"),
        ("Tig",     "티그"),
        # 기존 공식 EN 보존
        ("Asana",   "아사나"),
        ("Mute",    "뮤트"),
    ])
    def test_en_alias_resolves_to_kr_canonical(
        self, conn, en_alias, expected_canonical
    ):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (en_alias,),
        ).fetchone()
        assert row is not None, f"EN alias 미등록: {en_alias!r}"
        assert row["canonical"] == expected_canonical


class TestJaAliasesMapToKoCanonical:
    @pytest.mark.parametrize("ja_alias,expected_canonical", [
        ("エルフィン", "에르핀"),
        ("ネル",       "네르"),
        ("バター",     "버터"),
        ("ヨミ",       "요미"),
        ("クロエ",     "클로에"),
        ("イード",     "이드"),
        ("アメリア",   "아멜리아"),
        ("ティグ",     "티그"),
        ("ヘイリー",   "헤일리"),
    ])
    def test_ja_alias_resolves_to_kr_canonical(
        self, conn, ja_alias, expected_canonical
    ):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (ja_alias,),
        ).fetchone()
        assert row is not None, f"JA alias 미등록: {ja_alias!r}"
        assert row["canonical"] == expected_canonical


class TestCostumeAliasesMapToBaseCanonical:
    @pytest.mark.parametrize("variant,base_canonical", [
        ("헤일리(멀쩡)",   "헤일리"),
        ("네르(빡침)",     "네르"),
        ("에르핀(왕도)",   "에르핀"),
        ("아멜리아(R41)",  "아멜리아"),
        ("티그(Hero)",     "티그"),
    ])
    def test_costume_alias_maps_to_base(self, conn, variant, base_canonical):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (variant,),
        ).fetchone()
        assert row is not None, f"코스튬 alias 미등록: {variant!r}"
        assert row["canonical"] == base_canonical, (
            f"{variant!r} → {row['canonical']!r} (기대: {base_canonical!r})"
        )

    def test_costume_variants_not_separate_canonical(self, conn):
        """코스튬 변형이 별도 canonical 로 등록되지 않았다 (DB 차원 확인)."""
        for variants in EXPECTED_COSTUME_ALIASES.values():
            for variant in variants:
                rows = conn.execute(
                    "SELECT canonical FROM tag_aliases "
                    "WHERE canonical = ? AND tag_type = 'character'",
                    (variant,),
                ).fetchall()
                assert not rows, (
                    f"코스튬 변형이 별도 canonical 로 등록됨: {variant!r}"
                )


class TestNegativePendingItems:
    @pytest.mark.parametrize("pending_en", [
        "Haley", "Eshur", "Asher", "Ashur", "Heidi",
        "Kommy", "Comi",
    ])
    def test_pending_en_alias_not_registered(self, conn, pending_en):
        row = conn.execute(
            "SELECT 1 FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character'",
            (pending_en,),
        ).fetchone()
        assert row is None, f"보류 EN alias 가 등록됨: {pending_en!r}"

    def test_chinese_alias_not_registered(self, conn):
        row = conn.execute(
            "SELECT 1 FROM tag_aliases WHERE alias = ?",
            ("嘟뚜脸恶作剧",),
        ).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# Autocomplete provider 통합 (read-only)
# ---------------------------------------------------------------------------

class TestAutocompleteProvider:
    def test_trickcal_revive_lowercase_returns_series(self, conn):
        candidates = suggest_tag_completions(conn, "trickcal revive")
        canonicals = {c.canonical for c in candidates}
        assert CANONICAL_SERIES in canonicals

    def test_korean_short_returns_series(self, conn):
        candidates = suggest_tag_completions(conn, "트릭컬")
        canonicals = {c.canonical for c in candidates}
        assert CANONICAL_SERIES in canonicals

    def test_chibi_go_returns_series(self, conn):
        candidates = suggest_tag_completions(conn, "Trickcal: Chibi Go")
        canonicals = {c.canonical for c in candidates}
        assert CANONICAL_SERIES in canonicals

    def test_erpin_returns_character(self, conn):
        candidates = suggest_tag_completions(conn, "에르핀")
        chars = [c for c in candidates if c.tag_type == "character"]
        assert any(c.canonical == "에르핀" for c in chars)

    def test_kyoju_returns_character(self, conn):
        candidates = suggest_tag_completions(conn, "교주")
        chars = [c for c in candidates if c.tag_type == "character"]
        assert any(
            c.canonical == "교주" and c.parent_series == CANONICAL_SERIES
            for c in chars
        )

    def test_japanese_alias_returns_character(self, conn):
        candidates = suggest_tag_completions(conn, "エルフィン")
        chars = [c for c in candidates if c.tag_type == "character"]
        assert any(c.canonical == "에르핀" for c in chars)

    def test_costume_variant_returns_base_character(self, conn):
        candidates = suggest_tag_completions(conn, "헤일리(멀쩡)")
        chars = [c for c in candidates if c.tag_type == "character"]
        assert any(c.canonical == "헤일리" for c in chars)

    def test_asana_en_still_works(self, conn):
        candidates = suggest_tag_completions(conn, "Asana")
        assert any(
            c.canonical == "아사나" and c.tag_type == "character"
            for c in candidates
        )

    def test_mute_en_still_works(self, conn):
        candidates = suggest_tag_completions(conn, "Mute")
        assert any(
            c.canonical == "뮤트" and c.tag_type == "character"
            for c in candidates
        )


# ---------------------------------------------------------------------------
# Classification inference 통합 (read-only)
# ---------------------------------------------------------------------------

class TestClassificationInference:
    def test_inference_hitomi_series_tag(self, conn):
        results = infer_character_series_candidates(conn, ["trickcal revive"])
        canonicals = {r.canonical for r in results}
        assert CANONICAL_SERIES in canonicals

    def test_inference_chibi_go_series_tag(self, conn):
        results = infer_character_series_candidates(conn, ["Trickcal: Chibi Go"])
        canonicals = {r.canonical for r in results}
        assert CANONICAL_SERIES in canonicals

    def test_inference_kyoju_character(self, conn):
        results = infer_character_series_candidates(conn, ["교주"])
        chars = [r for r in results if r.tag_type == "character"]
        assert any(r.canonical == "교주" for r in chars)

    def test_inference_japanese_character_alias(self, conn):
        results = infer_character_series_candidates(conn, ["エルフィン"])
        chars = [r for r in results if r.tag_type == "character"]
        assert any(r.canonical == "에르핀" for r in chars)

    def test_inference_costume_alias_resolves_to_base(self, conn):
        results = infer_character_series_candidates(conn, ["에르핀(왕도)"])
        chars = [r for r in results if r.tag_type == "character"]
        assert any(r.canonical == "에르핀" for r in chars)

    def test_inference_official_en_preserved(self, conn):
        results = infer_character_series_candidates(conn, ["Asana"])
        chars = [r for r in results if r.tag_type == "character"]
        assert any(r.canonical == "아사나" for r in chars)
