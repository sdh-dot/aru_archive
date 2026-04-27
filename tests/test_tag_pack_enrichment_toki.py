"""
Tag Pack Alias Enrichment — Toki 보강 검증 테스트.

enrich_pack()을 직접 호출하여 in-memory로 검증한다.
docs/tag_pack_export_localized_ko_ja.json 파일이 있어야 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_JSON = ROOT / "docs" / "tag_pack_export_localized_ko_ja.json"


@pytest.fixture(scope="module")
def source_pack():
    if not SOURCE_JSON.exists():
        pytest.skip(f"Source JSON not found: {SOURCE_JSON}")
    return json.loads(SOURCE_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def enriched_result(source_pack):
    from tools.enrich_tag_pack_aliases import enrich_pack
    return enrich_pack(source_pack, use_danbooru=False)


@pytest.fixture(scope="module")
def enriched_pack(enriched_result):
    return enriched_result[0]


@pytest.fixture(scope="module")
def enriched_report(enriched_result):
    return enriched_result[1]


@pytest.fixture(scope="module")
def char_by_canonical(enriched_pack):
    return {c["canonical"]: c for c in enriched_pack["characters"]}


# ---------------------------------------------------------------------------
# Toki canonical 정규화
# ---------------------------------------------------------------------------

class TestTokiCanonicalNormalization:
    def test_toki_canonical_is_japanese(self, char_by_canonical):
        assert "飛鳥馬トキ" in char_by_canonical, "飛鳥馬トキ가 canonical로 존재해야 함"

    def test_old_canonical_toki_not_present_as_canonical(self, char_by_canonical):
        assert "Toki" not in char_by_canonical, "'Toki'는 더 이상 canonical이 아니어야 함"

    def test_canonical_change_recorded_in_report(self, enriched_report):
        changes = enriched_report["canonical_changes"]
        toki_change = next((c for c in changes if c["from"] == "Toki"), None)
        assert toki_change is not None, "Toki canonical 변경이 report에 기록되어야 함"
        assert toki_change["to"] == "飛鳥馬トキ"
        assert toki_change["confidence"] == "high"


# ---------------------------------------------------------------------------
# Toki aliases 보강
# ---------------------------------------------------------------------------

class TestTokiAliases:
    REQUIRED_ALIASES = [
        "Toki",
        "toki_(blue_archive)",
        "トキ",
        "飛鳥馬トキ",
        "아스마 토키",
        "토키",
        "Asuma Toki",
    ]

    def test_toki_has_all_required_aliases(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        aliases = set(toki["aliases"])
        for expected in self.REQUIRED_ALIASES:
            assert expected in aliases, f"'{expected}'이 aliases에 없음"

    def test_toki_danbooru_tag_preserved(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        assert "toki_(blue_archive)" in toki["aliases"]

    def test_toki_katakana_short_alias(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        assert "トキ" in toki["aliases"]

    def test_toki_korean_aliases(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        aliases = set(toki["aliases"])
        assert "토키" in aliases
        assert "아스마 토키" in aliases


# ---------------------------------------------------------------------------
# Toki variant 병합
# ---------------------------------------------------------------------------

class TestTokiVariantMerge:
    def test_school_uniform_not_separate_canonical(self, char_by_canonical):
        assert "Toki (school Uniform)" not in char_by_canonical, \
            "'Toki (school Uniform)'은 별도 canonical로 남으면 안 됨"

    def test_school_uniform_aliases_absorbed_into_toki(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        aliases = set(toki["aliases"])
        assert "toki_(school_uniform)_(blue_archive)" in aliases
        assert "Toki (school Uniform)" in aliases

    def test_merged_variants_recorded_in_review(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        review = toki.get("_review", {})
        merged = review.get("merged_variants", [])
        assert any(
            m["source_canonical"] == "Toki (school Uniform)" for m in merged
        ), "merged_variants에 'Toki (school Uniform)' 기록이 있어야 함"

    def test_merge_recorded_in_report(self, enriched_report):
        merges = enriched_report["merges"]
        toki_merge = next(
            (m for m in merges if m["from"] == "Toki (school Uniform)"), None
        )
        assert toki_merge is not None
        assert toki_merge["into"] == "飛鳥馬トキ"

    def test_unconfirmed_new_year_variant_is_suggestion_only(self, enriched_report):
        warnings = enriched_report["warnings"]
        suggestion_aliases = {
            w["suggestion"] for w in warnings
            if w.get("type") == "unconfirmed_variant_alias_suggestion"
        }
        assert "toki_(new_year)_(blue_archive)" in suggestion_aliases
        assert "Toki (new year)" in suggestion_aliases

    def test_unconfirmed_new_year_not_in_toki_aliases(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        aliases = set(toki["aliases"])
        assert "toki_(new_year)_(blue_archive)" not in aliases
        assert "Toki (new year)" not in aliases


# ---------------------------------------------------------------------------
# Toki localizations
# ---------------------------------------------------------------------------

class TestTokiLocalizations:
    def test_toki_ko_localization(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        assert toki["localizations"].get("ko") == "아스마 토키"

    def test_toki_ja_localization(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        assert toki["localizations"].get("ja") == "飛鳥馬トキ"

    def test_toki_en_localization(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        assert toki["localizations"].get("en") == "Asuma Toki"

    def test_toki_localizations_in_aliases(self, char_by_canonical):
        toki = char_by_canonical["飛鳥馬トキ"]
        aliases = set(toki["aliases"])
        locs = toki["localizations"]
        for locale, display_name in locs.items():
            assert display_name in aliases, \
                f"localizations.{locale}={display_name} not in aliases"


# ---------------------------------------------------------------------------
# Tsubasa 보강 확인 (HIGH confidence second case)
# ---------------------------------------------------------------------------

class TestTsubasaEnrichment:
    def test_tsubasa_canonical_is_japanese(self, char_by_canonical):
        assert "小鳥遊ツバサ" in char_by_canonical

    def test_tsubasa_old_canonical_preserved(self, char_by_canonical):
        tsubasa = char_by_canonical["小鳥遊ツバサ"]
        assert "Tsubasa" in tsubasa["aliases"]

    def test_tsubasa_localizations_complete(self, char_by_canonical):
        tsubasa = char_by_canonical["小鳥遊ツバサ"]
        locs = tsubasa["localizations"]
        assert locs.get("en") == "Takanashi Tsubasa"
        assert locs.get("ja") == "小鳥遊ツバサ"
        assert locs.get("ko") == "타카나시 츠바사"
