"""
core/dictionary_sources/matcher.py 테스트.
"""
from __future__ import annotations

import pytest


def _danbooru_char(
    tag: str,
    canonical: str,
    parent_series: str = "Blue Archive",
    confidence: float = 0.75,
) -> dict:
    return {
        "source":            "danbooru",
        "danbooru_tag":      tag,
        "danbooru_category": "character",
        "canonical":         canonical,
        "tag_type":          "character",
        "parent_series":     parent_series,
        "alias":             tag,
        "confidence_score":  confidence,
    }


class TestMatchPixivTagsToDanbooruCandidates:
    def test_exact_match(self) -> None:
        from core.dictionary_sources.matcher import match_pixiv_tags_to_danbooru_candidates
        pixiv = ["wakamo_(blue_archive)"]
        db_cands = [_danbooru_char("wakamo_(blue_archive)", "Wakamo")]
        results = match_pixiv_tags_to_danbooru_candidates(pixiv, db_cands)
        assert len(results) == 1
        assert results[0]["match_type"] == "exact"
        assert results[0]["pixiv_tag"] == "wakamo_(blue_archive)"

    def test_normalized_match_fullwidth(self) -> None:
        """ＷａｋａｍＯ → normalize → 매칭."""
        from core.dictionary_sources.matcher import match_pixiv_tags_to_danbooru_candidates
        from core.tag_normalize import normalize_tag_key
        # 전각 "Ｗａｋａｍｏ" → normalize → "wakamo"
        pixiv = ["Ｗａｋａｍｏ"]
        db_cands = [_danbooru_char("wakamo", "Wakamo")]
        results = match_pixiv_tags_to_danbooru_candidates(pixiv, db_cands)
        assert any(r["match_type"] == "normalized" for r in results)

    def test_no_match_returns_empty(self) -> None:
        from core.dictionary_sources.matcher import match_pixiv_tags_to_danbooru_candidates
        pixiv = ["全然関係ないタグ"]
        db_cands = [_danbooru_char("wakamo_(blue_archive)", "Wakamo")]
        results = match_pixiv_tags_to_danbooru_candidates(pixiv, db_cands)
        assert results == []

    def test_co_occurrence_with_known_series(self) -> None:
        from core.dictionary_sources.matcher import match_pixiv_tags_to_danbooru_candidates
        pixiv = ["wakamo_(blue_archive)", "Blue Archive"]
        db_cands = [_danbooru_char("wakamo_(blue_archive)", "Wakamo")]
        results = match_pixiv_tags_to_danbooru_candidates(
            pixiv, db_cands, known_series=["Blue Archive"]
        )
        assert results[0]["co_occurred"] is True
        assert "Blue Archive" in results[0]["evidence"]["co_occurred_with"]

    def test_multiple_pixiv_tags_multiple_matches(self) -> None:
        from core.dictionary_sources.matcher import match_pixiv_tags_to_danbooru_candidates
        pixiv = ["wakamo_(blue_archive)", "aru_(blue_archive)"]
        db_cands = [
            _danbooru_char("wakamo_(blue_archive)", "Wakamo"),
            _danbooru_char("aru_(blue_archive)", "Aru"),
        ]
        results = match_pixiv_tags_to_danbooru_candidates(pixiv, db_cands)
        assert len(results) == 2


class TestBuildExternalEntriesFromMatches:
    def test_generates_alias_and_localization_entries(self) -> None:
        from core.dictionary_sources.matcher import (
            match_pixiv_tags_to_danbooru_candidates,
            build_external_entries_from_matches,
        )
        pixiv = ["ワカモ(正月)"]
        db_cands = [_danbooru_char("wakamo_(blue_archive)", "Wakamo")]
        # 정규화 매칭을 위해 canonical normalized = "wakamo" 확인
        # ワカモ(正月) normalize → ワカモ(正月) ≠ wakamo_(blue_archive) normalize → "wakamo(bluearchive)"
        # 직접 매칭 없을 수 있으므로 match 결과를 수동 주입
        matches = [{
            "pixiv_tag": "ワカモ(正月)",
            "danbooru_candidate": db_cands[0],
            "match_type": "normalized",
            "co_occurred": True,
            "evidence": {"match_type": "normalized"},
        }]
        entries = build_external_entries_from_matches(matches)
        # 2 entries: alias + ja localization
        assert len(entries) == 2
        alias_e = next(e for e in entries if e["alias"] == "ワカモ(正月)")
        loc_e   = next(e for e in entries if e.get("locale") == "ja")
        assert alias_e["canonical"] == "Wakamo"
        assert alias_e["tag_type"] == "character"
        assert loc_e["display_name"] == "ワカモ(正月)"

    def test_short_alias_has_lower_confidence(self) -> None:
        from core.dictionary_sources.matcher import build_external_entries_from_matches
        short_match = [{
            "pixiv_tag": "アル",  # 3자 이하
            "danbooru_candidate": _danbooru_char("aru_(blue_archive)", "Aru"),
            "match_type": "normalized",
            "co_occurred": False,
            "evidence": {},
        }]
        long_match = [{
            "pixiv_tag": "陸八魔アル",
            "danbooru_candidate": _danbooru_char("aru_(blue_archive)", "Aru"),
            "match_type": "normalized",
            "co_occurred": False,
            "evidence": {},
        }]
        short_entries = build_external_entries_from_matches(short_match)
        long_entries  = build_external_entries_from_matches(long_match)
        short_conf = next(e["confidence_score"] for e in short_entries if e.get("alias"))
        long_conf  = next(e["confidence_score"] for e in long_entries  if e.get("alias"))
        assert short_conf < long_conf

    def test_evidence_json_in_entry(self) -> None:
        from core.dictionary_sources.matcher import build_external_entries_from_matches
        import json
        match = [{
            "pixiv_tag": "ワカモ",
            "danbooru_candidate": _danbooru_char("wakamo_(blue_archive)", "Wakamo"),
            "match_type": "exact",
            "co_occurred": True,
            "evidence": {"match_type": "exact", "pixiv_tag": "ワカモ"},
        }]
        entries = build_external_entries_from_matches(match)
        alias_entry = next(e for e in entries if e.get("alias"))
        evidence = json.loads(alias_entry["evidence_json"])
        assert evidence["match_type"] == "exact"
