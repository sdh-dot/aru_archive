"""
apply_failure_tag_patch 테스트.

parse_failure_txt, apply_failure_patch, analyze_failure_report를 검증한다.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SAMPLE_TXT = """\
# Aru Archive Classification Failure Tags

## Summary
- failed groups: 3
- unique raw tags: 12
- generated_at: 2026-04-27T10:51:00Z

## Frequent Unknown Tags
1. ブルーアーカイブ5000users入り — 3 files
2. 羽川ハスミ — 2 files

## Failed Files

### file_a.jpg
rule_type: author_fallback
title: ハスミ
artist: TestArtist
raw_tags:
- 羽川ハスミ
- ブルーアーカイブ5000users入り
- 体操服

### file_b.jpg
rule_type: series_uncategorized
title: サツキ
artist: TestArtist2
raw_tags:
- サツキ(ブルーアーカイブ)
- 京極サツキ
- 巨乳
debug_notes:
- 'サツキ(ブルーアーカイブ)': possible series disambiguator (inner='ブルーアーカイブ')

### file_c.jpg
rule_type: author_fallback
title: ヒビキ
artist: TestArtist3
raw_tags:
- 猫塚ヒビキ
- 猫塚ヒビキ(応援団)
- ブルーアーカイブ5000users入り
debug_notes:
- '猫塚ヒビキ(応援団)': possible parenthetical variant tag (inner='応援団')
"""

_MINIMAL_PACK: dict = {
    "pack_id": "test_pack",
    "name": "Test Pack",
    "version": "1.0.0",
    "series": [],
    "characters": [],
}


def _pack_with_existing(canonical: str) -> dict:
    """Pack that already contains one character entry."""
    return {
        **_MINIMAL_PACK,
        "characters": [
            {
                "canonical": canonical,
                "aliases": [canonical],
                "localizations": {"en": canonical},
                "parent_series": "Blue Archive",
            }
        ],
    }


# ---------------------------------------------------------------------------
# 1. parse_failure_txt
# ---------------------------------------------------------------------------

class TestParseFailureTxt:
    def test_summary_fields(self):
        from tools.apply_failure_tag_patch import parse_failure_txt
        result = parse_failure_txt(_SAMPLE_TXT)
        s = result["summary"]
        assert s["failed_groups"] == 3
        assert s["unique_raw_tags"] == 12
        assert "2026-04-27" in s["generated_at"]

    def test_frequent_tags(self):
        from tools.apply_failure_tag_patch import parse_failure_txt
        result = parse_failure_txt(_SAMPLE_TXT)
        freq = {e["tag"]: e["count"] for e in result["frequent_tags"]}
        assert freq["ブルーアーカイブ5000users入り"] == 3
        assert freq["羽川ハスミ"] == 2

    def test_failed_files_count(self):
        from tools.apply_failure_tag_patch import parse_failure_txt
        result = parse_failure_txt(_SAMPLE_TXT)
        assert len(result["failed_files"]) == 3

    def test_file_raw_tags(self):
        from tools.apply_failure_tag_patch import parse_failure_txt
        result = parse_failure_txt(_SAMPLE_TXT)
        fa = result["failed_files"][0]
        assert fa["file_name"] == "file_a.jpg"
        assert fa["rule_type"] == "author_fallback"
        assert "羽川ハスミ" in fa["raw_tags"]
        assert "ブルーアーカイブ5000users入り" in fa["raw_tags"]

    def test_debug_notes_parsed(self):
        from tools.apply_failure_tag_patch import parse_failure_txt
        result = parse_failure_txt(_SAMPLE_TXT)
        fb = result["failed_files"][1]
        assert any("サツキ(ブルーアーカイブ)" in note for note in fb["debug_notes"])

    def test_empty_raw_tags_section_allowed(self):
        from tools.apply_failure_tag_patch import parse_failure_txt
        txt = "## Failed Files\n\n### file_x.jpg\nrule_type: author_fallback\ntitle: T\n"
        result = parse_failure_txt(txt)
        assert result["failed_files"][0]["raw_tags"] == []


# ---------------------------------------------------------------------------
# 2. ブルーアーカイブ5000users入り not added as character alias
# ---------------------------------------------------------------------------

class TestPopularityTagNotCharacterAlias:
    def test_popularity_tag_not_in_any_aliases(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        for entry in patched["characters"]:
            assert "ブルーアーカイブ5000users入り" not in entry.get("aliases", [])
            assert "ブルーアーカイブ1000users入り" not in entry.get("aliases", [])

    def test_popularity_tag_not_as_canonical(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        canonicals = {e["canonical"] for e in patched["characters"]}
        assert "ブルーアーカイブ5000users入り" not in canonicals


# ---------------------------------------------------------------------------
# 3. 羽川ハスミ processed as character candidate
# ---------------------------------------------------------------------------

class TestHasumiCharacterCandidate:
    def test_hasumi_added_to_pack(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, report = apply_failure_patch(_MINIMAL_PACK, {})
        canonicals = {e["canonical"] for e in patched["characters"]}
        assert "羽川ハスミ" in canonicals

    def test_hasumi_has_expected_aliases(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        hasumi = next(e for e in patched["characters"] if e["canonical"] == "羽川ハスミ")
        aliases = set(hasumi["aliases"])
        assert "ハスミ" in aliases
        assert "Hasumi" in aliases
        assert "hanekawa_hasumi_(blue_archive)" in aliases

    def test_hasumi_parent_series(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        hasumi = next(e for e in patched["characters"] if e["canonical"] == "羽川ハスミ")
        assert hasumi["parent_series"] == "Blue Archive"

    def test_hasumi_skipped_when_existing(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        pack = _pack_with_existing("羽川ハスミ")
        _, report = apply_failure_patch(pack, {})
        skipped = [s["canonical"] for s in report["skipped"]]
        assert "羽川ハスミ" in skipped


# ---------------------------------------------------------------------------
# 4. 猫塚ヒビキ(応援団) merged as variant of 猫塚ヒビキ
# ---------------------------------------------------------------------------

class TestVariantMergeHibiki:
    def test_cheerleader_variant_added_to_aliases(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, report = apply_failure_patch(_MINIMAL_PACK, {})
        hibiki = next(e for e in patched["characters"] if e["canonical"] == "猫塚ヒビキ")
        assert "猫塚ヒビキ(応援団)" in hibiki["aliases"]

    def test_variant_in_review_merged_variants(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        hibiki = next(e for e in patched["characters"] if e["canonical"] == "猫塚ヒビキ")
        merged = hibiki.get("_review", {}).get("merged_variants", [])
        variants = [mv["source_tag"] for mv in merged]
        assert "猫塚ヒビキ(応援団)" in variants

    def test_variant_in_report(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        _, report = apply_failure_patch(_MINIMAL_PACK, {})
        merges = {mv["variant_tag"] for mv in report["variant_merges"]}
        assert "猫塚ヒビキ(応援団)" in merges

    def test_hibiki_no_ambiguous_short_alias(self):
        """猫塚ヒビキ は ヒビキ / Hibiki の単独 alias を持たない（日下部ヒビキと衝突回避）."""
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        hibiki = next(e for e in patched["characters"] if e["canonical"] == "猫塚ヒビキ")
        assert "ヒビキ" not in hibiki["aliases"]
        assert "Hibiki" not in hibiki["aliases"]


# ---------------------------------------------------------------------------
# 5. サツキ(ブルーアーカイブ) → 京極サツキ + Blue Archive
# ---------------------------------------------------------------------------

class TestSeriesDisambiguatorSatsuki:
    def test_satsuki_disambiguator_in_aliases(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        satsuki = next(e for e in patched["characters"] if e["canonical"] == "京極サツキ")
        assert "サツキ(ブルーアーカイブ)" in satsuki["aliases"]

    def test_satsuki_parent_series(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        satsuki = next(e for e in patched["characters"] if e["canonical"] == "京極サツキ")
        assert satsuki["parent_series"] == "Blue Archive"

    def test_disambiguator_in_report(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        _, report = apply_failure_patch(_MINIMAL_PACK, {})
        recorded = {d["tag"] for d in report["series_disambiguators"]}
        assert "サツキ(ブルーアーカイブ)" in recorded


# ---------------------------------------------------------------------------
# 6. ヘイロー(ブルーアーカイブ) NOT added as character alias
# ---------------------------------------------------------------------------

class TestGroupTagNotCharacterAlias:
    def test_halo_tag_not_character_alias(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        for entry in patched["characters"]:
            assert "ヘイロー(ブルーアーカイブ)" not in entry.get("aliases", [])
            assert "ヘイロー" not in entry.get("aliases", [])

    def test_tea_party_not_character_alias(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        for entry in patched["characters"]:
            assert "ティーパーティー(ブルーアーカイブ)" not in entry.get("aliases", [])

    def test_problem_solver_68_not_character_alias(self):
        from tools.apply_failure_tag_patch import apply_failure_patch
        patched, _ = apply_failure_patch(_MINIMAL_PACK, {})
        for entry in patched["characters"]:
            assert "便利屋68" not in entry.get("aliases", [])


# ---------------------------------------------------------------------------
# 7. Title-only candidate not auto-confirmed
# ---------------------------------------------------------------------------

class TestTitleOnlyCandidateNotConfirmed:
    def test_title_only_detected_in_analysis(self):
        from tools.apply_failure_tag_patch import parse_failure_txt, analyze_failure_report
        txt = (
            "## Failed Files\n\n"
            "### 999999_p0.jpg\n"
            "rule_type: author_fallback\n"
            "title: ハスミちゃん\n"
            "artist: someone\n"
        )
        parsed = parse_failure_txt(txt)
        analysis = analyze_failure_report(parsed)
        candidates = [c["file_name"] for c in analysis["title_only_candidates"]]
        assert "999999_p0.jpg" in candidates

    def test_title_only_candidate_not_in_pack(self):
        """title-only 후보는 pack에 자동으로 추가되지 않는다."""
        from tools.apply_failure_tag_patch import apply_failure_patch
        # patch applies _PATCH_CHARACTERS — but does NOT inspect titles at all
        # Verify that no spurious character is added beyond the defined list
        patched, report = apply_failure_patch(_MINIMAL_PACK, {})
        expected_canonicals = {c["canonical"] for c in __import__(
            "tools.apply_failure_tag_patch", fromlist=["_PATCH_CHARACTERS"]
        )._PATCH_CHARACTERS}
        actual_canonicals = {e["canonical"] for e in patched["characters"]}
        # Only characters from _PATCH_CHARACTERS should be present (pack was empty)
        assert actual_canonicals == expected_canonicals
