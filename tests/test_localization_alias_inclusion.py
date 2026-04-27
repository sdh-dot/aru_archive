"""
Localization → Alias 포함 검증 테스트.

모든 character entry에서 localizations.ko/ja/en 값이 aliases에 포함되어야 한다.
canonical이 변경된 경우 old canonical도 aliases에 보존되어야 한다.
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


# ---------------------------------------------------------------------------
# localizations → aliases 포함 검증
# ---------------------------------------------------------------------------

class TestLocalizationAliasInclusion:
    def test_all_localization_values_are_in_aliases(self, enriched_pack):
        """localizations.ko/ja/en 값이 모두 aliases에 포함되어야 한다."""
        violations: list[str] = []
        for char in enriched_pack["characters"]:
            canonical = char.get("canonical", "")
            aliases = set(char.get("aliases", []))
            locs = char.get("localizations", {})
            for locale, display_name in locs.items():
                if display_name and display_name not in aliases:
                    violations.append(
                        f"[{canonical}] localizations.{locale}='{display_name}' not in aliases"
                    )
        assert not violations, "\n".join(violations)

    def test_canonical_itself_is_in_aliases(self, enriched_pack):
        """canonical 값이 aliases에 포함되어야 한다."""
        violations: list[str] = []
        for char in enriched_pack["characters"]:
            canonical = char.get("canonical", "")
            aliases = char.get("aliases", [])
            if canonical and canonical not in aliases:
                violations.append(f"canonical '{canonical}' not in its own aliases")
        assert not violations, "\n".join(violations)

    def test_toki_old_canonical_preserved_in_aliases(self, enriched_pack):
        """Toki → 飛鳥馬トキ 변경 후 'Toki'가 aliases에 보존."""
        toki_entry = next(
            (c for c in enriched_pack["characters"] if c["canonical"] == "飛鳥馬トキ"),
            None,
        )
        assert toki_entry is not None
        assert "Toki" in toki_entry["aliases"]

    def test_tsubasa_old_canonical_preserved_in_aliases(self, enriched_pack):
        """Tsubasa → 小鳥遊ツバサ 변경 후 'Tsubasa'가 aliases에 보존."""
        tsubasa_entry = next(
            (c for c in enriched_pack["characters"] if c["canonical"] == "小鳥遊ツバサ"),
            None,
        )
        assert tsubasa_entry is not None
        assert "Tsubasa" in tsubasa_entry["aliases"]


# ---------------------------------------------------------------------------
# canonical 변경 보고서 검증
# ---------------------------------------------------------------------------

class TestCanonicalChangeReport:
    def test_canonical_changes_have_from_to(self, enriched_report):
        for cc in enriched_report["canonical_changes"]:
            assert "from" in cc and "to" in cc
            assert cc["from"] != cc["to"], "self-merge는 report에 기록하면 안 됨"

    def test_no_self_merges_in_report(self, enriched_report):
        for cc in enriched_report["canonical_changes"]:
            assert cc["from"] != cc["to"]

    def test_all_changed_canonicals_in_enriched_pack(self, enriched_pack, enriched_report):
        """report의 canonical_changes 모두 enriched pack에 존재해야 함."""
        char_canonicals = {c["canonical"] for c in enriched_pack["characters"]}
        for cc in enriched_report["canonical_changes"]:
            assert cc["to"] in char_canonicals, \
                f"New canonical '{cc['to']}' not found in enriched pack"

    def test_old_canonicals_are_in_aliases(self, enriched_pack, enriched_report):
        """report에 기록된 old canonical이 new canonical의 aliases에 있어야 함."""
        char_by_canonical = {c["canonical"]: c for c in enriched_pack["characters"]}
        for cc in enriched_report["canonical_changes"]:
            new_entry = char_by_canonical.get(cc["to"])
            if new_entry:
                assert cc["from"] in new_entry["aliases"], \
                    f"Old canonical '{cc['from']}' missing from aliases of '{cc['to']}'"


# ---------------------------------------------------------------------------
# 기존 완전히 정규화된 캐릭터 회귀 확인
# ---------------------------------------------------------------------------

class TestExistingNormalizedCharactersRegression:
    FULLY_NORMALIZED = [
        ("アロナ", {"en": "Arona", "ko": "아로나", "ja": "アロナ"}),
        ("空崎ヒナ", {"en": "Hina", "ko": "소라사키 히나", "ja": "空崎ヒナ"}),
        ("小鳥遊ホシノ", {"en": "Takanashi Hoshino", "ko": "타카나시 호시노", "ja": "小鳥遊ホシノ"}),
    ]

    def test_existing_characters_localizations_unchanged(self, enriched_pack):
        char_by_canonical = {c["canonical"]: c for c in enriched_pack["characters"]}
        for canonical, expected_locs in self.FULLY_NORMALIZED:
            entry = char_by_canonical.get(canonical)
            assert entry is not None, f"{canonical} not found"
            locs = entry.get("localizations", {})
            for locale, display_name in expected_locs.items():
                assert locs.get(locale) == display_name, \
                    f"{canonical}: localizations.{locale} changed unexpectedly"

    def test_existing_characters_aliases_superset(self, enriched_pack):
        """보강 후 aliases 수가 줄지 않아야 한다."""
        source_pack = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
        source_by_canonical = {c["canonical"]: c for c in source_pack["characters"]}
        enriched_by_canonical = {c["canonical"]: c for c in enriched_pack["characters"]}

        for canonical, source_entry in source_by_canonical.items():
            # canonical이 변경되지 않은 항목만 비교
            if canonical not in enriched_by_canonical:
                continue
            enriched_entry = enriched_by_canonical[canonical]
            source_aliases = set(source_entry.get("aliases", []))
            enriched_aliases = set(enriched_entry.get("aliases", []))
            missing = source_aliases - enriched_aliases
            assert not missing, \
                f"{canonical}: aliases 손실 {missing}"
