"""tests/test_tag_pack_trickcal_revive.py

Trickcal Re:VIVE tag pack 회귀 테스트.

검증 대상 (요약):
  1. pack 파일 자체 invariant — canonical / aliases / localizations 보존
  2. seed_tag_pack 실행 시 locale-mismatch warning 0건 (FGO lint fix 회귀)
  3. series alias "trickcal revive" / "트릭컬" / "트릭컬 리바이브" 가
     "Trickcal Re:VIVE" canonical 로 등록
  4. series ja localization 「トリッカル・もちもちほっペ大作戦」 등록
  5. character 18명 모두 parent_series="Trickcal Re:VIVE" 로 등록
  6. 아사나/Asana, 뮤트/Mute alias 가 같은 canonical 로 묶임
  7. 보류 캐릭터 ("다야", "교주", "Erpin", "Ner" 등 보조 출처 단독) 미등록
  8. 보류 series alias ("Trickcal: Chibi Go") 미등록
  9. autocomplete provider 가 "trickcal revive" / "트릭컬" / "에르핀" /
     "Asana" / "Mute" 입력에 후보를 반환
 10. classification inference 가 raw tag "trickcal revive" / "에르핀" /
     "Asana" 에서 후보를 추출
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

# 이번 PR 에서 등록되는 18명. 변경 시 의도된 결정이어야 한다.
EXPECTED_CHARACTERS_KO: list[str] = [
    "에르핀", "에슈르", "네르", "버터", "코미",
    "요미", "클로에", "델리아", "아라그니아", "리코타",
    "이드", "아멜리아", "티그", "하이디", "시저", "헤일리",
    "아사나", "뮤트",
]

# 공식 EN 표기가 확인된 캐릭터만 EN alias 보유. 나머지 EN/JA 표기는 보류.
EXPECTED_EN_BY_KO: dict[str, str] = {
    "아사나": "Asana",
    "뮤트": "Mute",
}

# 보조 출처 단독 — 이번 PR 에 명시적으로 미등록.
PENDING_CHARACTERS_KO: list[str] = [
    "다야", "이프리트", "마에스트로 2호", "림", "스피키", "실라",
    "벨벳", "빅우드", "제이드", "벨리타", "벨라", "교주",
]

# 보조 출처 단독 EN 표기 — 이번 PR 에 미등록.
PENDING_EN_NAMES: list[str] = [
    "Erpin", "Ner", "Butter", "Yomi", "Chloe",
    "Amelia", "Tig", "Haley", "Eshur", "Asher", "Kommy", "Comi",
]

# 같은 IP 다른 SKU — 사용자 결정 전까지 미등록.
PENDING_SERIES_ALIASES: list[str] = [
    "Trickcal: Chibi Go", "Trickcal Chibi Go", "嘟뚜脸恶作剧",
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
        # KR 정식 / 단축 / 한영 혼용
        for required in ["트릭컬 리바이브", "트릭컬 RE:VIVE", "트릭컬"]:
            assert required in aliases, f"alias 누락: {required!r}"
        # JP 정식 / 단축
        for required in ["トリッカル・もちもちほっペ大作戦", "トリッカル"]:
            assert required in aliases, f"alias 누락: {required!r}"
        # EN 변형들
        for required in ["Trickcal Re:VIVE", "Trickcal", "Trickcal Revive"]:
            assert required in aliases, f"alias 누락: {required!r}"

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
            if ("぀" <= ch <= "ゟ")  # hiragana
            or ("゠" <= ch <= "ヿ")  # katakana
            or ("一" <= ch <= "鿿")  # CJK unified
        )
        assert ja_count / max(len(ja), 1) >= 0.30, (
            f"ja localization 일본어 비율 < 30%: {ja!r}"
        )

    def test_no_pending_series_aliases(self):
        """Trickcal: Chibi Go 등 사용자 확인 전 alias 가 섞이지 않았다."""
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

    def test_every_character_has_parent_series(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        for char in pack["characters"]:
            assert char["parent_series"] == CANONICAL_SERIES, (
                f"parent_series 누락 또는 불일치: {char['canonical']!r}"
            )

    def test_character_localizations_only_have_official_locales(self):
        """KR locale 은 모두, EN locale 은 Asana / Mute 만, JA locale 은 0건."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        for char in pack["characters"]:
            ko_canonical = char["canonical"]
            locs = char["localizations"]
            assert "ko" in locs and locs["ko"] == ko_canonical
            assert "ja" not in locs, f"JA localization 은 보류여야 함: {ko_canonical}"
            if ko_canonical in EXPECTED_EN_BY_KO:
                assert locs.get("en") == EXPECTED_EN_BY_KO[ko_canonical]
            else:
                assert "en" not in locs, (
                    f"공식 EN 미확인 캐릭터에 en localization 이 들어감: "
                    f"{ko_canonical} → {locs.get('en')!r}"
                )

    def test_no_pending_characters_present(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        canonicals = {c["canonical"] for c in pack["characters"]}
        for pending in PENDING_CHARACTERS_KO:
            assert pending not in canonicals, (
                f"보류 캐릭터가 등록됨: {pending!r}"
            )

    def test_no_pending_en_aliases(self):
        """보조 출처 단독 EN 표기가 alias 에 섞이지 않았다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        all_aliases = set()
        for char in pack["characters"]:
            all_aliases.update(char["aliases"])
        for pending in PENDING_EN_NAMES:
            assert pending not in all_aliases, (
                f"보조 출처 단독 EN alias 가 등록됨: {pending!r}"
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
        assert row is not None, "Hitomi 호환 alias 'trickcal revive' 미등록"
        assert row["canonical"] == CANONICAL_SERIES

    def test_korean_short_alias_registered(self, conn):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("트릭컬",),
        ).fetchone()
        assert row is not None, "단축 alias '트릭컬' 미등록"
        assert row["canonical"] == CANONICAL_SERIES

    def test_korean_full_alias_registered(self, conn):
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("트릭컬 리바이브",),
        ).fetchone()
        assert row is not None, "정식 alias '트릭컬 리바이브' 미등록"
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

    def test_chibi_go_alias_not_registered(self, conn):
        """보류 alias 'Trickcal: Chibi Go' 가 DB 에 들어가지 않았다."""
        for pending in PENDING_SERIES_ALIASES:
            row = conn.execute(
                "SELECT 1 FROM tag_aliases WHERE alias = ?",
                (pending,),
            ).fetchone()
            assert row is None, f"보류 alias 가 등록됨: {pending!r}"


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

    def test_en_localization(self, conn):
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'series' AND locale = 'en'",
            (CANONICAL_SERIES,),
        ).fetchone()
        assert row is not None
        assert row["display_name"] == "Trickcal Re:VIVE"


class TestCharactersRegistered:
    def test_all_18_characters_have_parent_series(self, conn):
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

    def test_erpin_registered(self, conn):
        row = conn.execute(
            "SELECT canonical, parent_series FROM tag_aliases "
            "WHERE alias = '에르핀' AND tag_type = 'character' AND enabled = 1"
        ).fetchone()
        assert row is not None
        assert row["canonical"] == "에르핀"
        assert row["parent_series"] == CANONICAL_SERIES

    def test_asana_ko_and_en_share_canonical(self, conn):
        ko_row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias = '아사나' "
            "AND tag_type = 'character' AND enabled = 1"
        ).fetchone()
        en_row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias = 'Asana' "
            "AND tag_type = 'character' AND enabled = 1"
        ).fetchone()
        assert ko_row is not None and en_row is not None
        assert ko_row["canonical"] == en_row["canonical"] == "아사나"

    def test_mute_ko_and_en_share_canonical(self, conn):
        ko_row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias = '뮤트' "
            "AND tag_type = 'character' AND enabled = 1"
        ).fetchone()
        en_row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias = 'Mute' "
            "AND tag_type = 'character' AND enabled = 1"
        ).fetchone()
        assert ko_row is not None and en_row is not None
        assert ko_row["canonical"] == en_row["canonical"] == "뮤트"

    def test_pending_characters_not_registered(self, conn):
        for pending in PENDING_CHARACTERS_KO:
            row = conn.execute(
                "SELECT 1 FROM tag_aliases WHERE alias = ? "
                "AND tag_type = 'character'",
                (pending,),
            ).fetchone()
            assert row is None, f"보류 캐릭터가 등록됨: {pending!r}"

    def test_pending_en_aliases_not_registered(self, conn):
        for pending in PENDING_EN_NAMES:
            row = conn.execute(
                "SELECT 1 FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character'",
                (pending,),
            ).fetchone()
            assert row is None, f"보조 출처 단독 EN alias 가 등록됨: {pending!r}"


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

    def test_erpin_returns_character(self, conn):
        candidates = suggest_tag_completions(conn, "에르핀")
        chars = [c for c in candidates if c.tag_type == "character"]
        assert any(c.canonical == "에르핀" for c in chars)
        assert all(
            c.parent_series == CANONICAL_SERIES
            for c in chars if c.canonical == "에르핀"
        )

    def test_asana_en_returns_character(self, conn):
        candidates = suggest_tag_completions(conn, "Asana")
        assert any(
            c.canonical == "아사나" and c.tag_type == "character"
            for c in candidates
        )

    def test_mute_en_returns_character(self, conn):
        candidates = suggest_tag_completions(conn, "Mute")
        assert any(
            c.canonical == "뮤트" and c.tag_type == "character"
            for c in candidates
        )


# ---------------------------------------------------------------------------
# Classification inference 통합 (read-only)
# ---------------------------------------------------------------------------

class TestClassificationInference:
    def test_inference_resolves_hitomi_series_tag(self, conn):
        results = infer_character_series_candidates(conn, ["trickcal revive"])
        canonicals = {r.canonical for r in results}
        assert CANONICAL_SERIES in canonicals

    def test_inference_resolves_korean_character(self, conn):
        results = infer_character_series_candidates(conn, ["에르핀"])
        chars = [r for r in results if r.tag_type == "character"]
        assert any(r.canonical == "에르핀" for r in chars)

    def test_inference_resolves_official_en_character(self, conn):
        results = infer_character_series_candidates(conn, ["Asana"])
        chars = [r for r in results if r.tag_type == "character"]
        assert any(r.canonical == "아사나" for r in chars)
