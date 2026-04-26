"""core/tag_classifier.py 테스트."""
from __future__ import annotations

import pytest

from core.tag_classifier import (
    CHARACTER_ALIASES,
    SERIES_ALIASES,
    classify_pixiv_tags,
)


class TestSeriesAliases:
    def test_known_aliases_present(self) -> None:
        for alias in ("ブルーアーカイブ", "ブルアカ", "BlueArchive", "Blue Archive",
                      "블루 아카이브", "블아"):
            assert alias in SERIES_ALIASES
            assert SERIES_ALIASES[alias] == "Blue Archive"


class TestCharacterAliases:
    def test_canonical_characters_present(self) -> None:
        for char in ("伊落マリー", "水羽ミモリ", "陸八魔アル"):
            assert char in CHARACTER_ALIASES
            assert CHARACTER_ALIASES[char]["series"] == "Blue Archive"

    def test_romaji_alias_maps_to_canonical(self) -> None:
        entry = CHARACTER_ALIASES["Rikuhachima Aru"]
        assert entry["canonical"] == "陸八魔アル"
        assert entry["series"] == "Blue Archive"

    def test_kana_alias_maps_to_canonical(self) -> None:
        entry = CHARACTER_ALIASES["リクハチマ・アル"]
        assert entry["canonical"] == "陸八魔アル"


class TestClassifyPixivTags:
    # ------------------------------------------------------------------
    # 시리즈 태그 분류
    # ------------------------------------------------------------------

    def test_series_alias_extracted(self) -> None:
        result = classify_pixiv_tags(["ブルアカ", "ソロ"])
        assert "Blue Archive" in result["series_tags"]
        assert "ブルアカ" not in result["tags"]
        assert "ソロ" in result["tags"]

    def test_full_series_name_extracted(self) -> None:
        result = classify_pixiv_tags(["ブルーアーカイブ"])
        assert result["series_tags"] == ["Blue Archive"]
        assert result["tags"] == []

    def test_multiple_series_aliases_dedup(self) -> None:
        result = classify_pixiv_tags(["ブルアカ", "ブルーアーカイブ", "BlueArchive"])
        assert result["series_tags"] == ["Blue Archive"]

    # ------------------------------------------------------------------
    # 캐릭터 태그 분류
    # ------------------------------------------------------------------

    def test_character_tag_extracted(self) -> None:
        result = classify_pixiv_tags(["伊落マリー", "水着"])
        assert "伊落マリー" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]
        assert "伊落マリー" not in result["tags"]
        assert "水着" in result["tags"]

    def test_character_alias_maps_to_canonical(self) -> None:
        result = classify_pixiv_tags(["Rikuhachima Aru"])
        assert result["character_tags"] == ["陸八魔アル"]
        assert "Blue Archive" in result["series_tags"]

    def test_character_implies_series(self) -> None:
        result = classify_pixiv_tags(["水羽ミモリ"])
        assert "Blue Archive" in result["series_tags"]

    def test_multiple_characters_same_series(self) -> None:
        result = classify_pixiv_tags(["伊落マリー", "水羽ミモリ"])
        assert sorted(result["character_tags"]) == ["伊落マリー", "水羽ミモリ"]
        assert result["series_tags"] == ["Blue Archive"]

    # ------------------------------------------------------------------
    # 일반 태그
    # ------------------------------------------------------------------

    def test_unknown_tags_become_general(self) -> None:
        result = classify_pixiv_tags(["オリジナル", "風景", "女の子"])
        assert result["tags"] == ["オリジナル", "風景", "女の子"]
        assert result["series_tags"] == []
        assert result["character_tags"] == []

    def test_empty_input(self) -> None:
        result = classify_pixiv_tags([])
        assert result == {"tags": [], "series_tags": [], "character_tags": []}

    def test_general_tags_preserve_order(self) -> None:
        tags = ["Z", "A", "M", "B"]
        result = classify_pixiv_tags(tags)
        assert result["tags"] == ["Z", "A", "M", "B"]

    def test_general_tags_dedup(self) -> None:
        result = classify_pixiv_tags(["ソロ", "ソロ", "ソロ"])
        assert result["tags"] == ["ソロ"]

    # ------------------------------------------------------------------
    # 복합 시나리오
    # ------------------------------------------------------------------

    def test_mixed_series_char_general(self) -> None:
        tags = ["ブルアカ", "伊落マリー", "ソロ", "水着"]
        result = classify_pixiv_tags(tags)
        assert result["series_tags"] == ["Blue Archive"]
        assert result["character_tags"] == ["伊落マリー"]
        assert result["tags"] == ["ソロ", "水着"]

    def test_char_alias_and_direct_both_classified(self) -> None:
        result = classify_pixiv_tags(["陸八魔アル", "リクハチマ・アル"])
        assert result["character_tags"] == ["陸八魔アル"]
        assert result["tags"] == []

    def test_series_dedup_when_char_implies_same_series(self) -> None:
        result = classify_pixiv_tags(["ブルアカ", "伊落マリー"])
        assert result["series_tags"] == ["Blue Archive"]
