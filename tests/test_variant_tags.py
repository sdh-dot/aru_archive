"""
core/tag_variant.py 테스트.
"""
from __future__ import annotations

import pytest

from core.tag_variant import split_variant_suffix, is_variant_of, base_tag


class TestSplitVariantSuffix:
    def test_japanese_variant_with_season(self) -> None:
        assert split_variant_suffix("ワカモ(正月)") == ("ワカモ", "正月")

    def test_japanese_variant_swimsuit(self) -> None:
        assert split_variant_suffix("ワカモ(水着)") == ("ワカモ", "水着")

    def test_no_suffix_returns_none(self) -> None:
        base, suffix = split_variant_suffix("ワカモ")
        assert base == "ワカモ"
        assert suffix is None

    def test_latin_variant(self) -> None:
        base, suffix = split_variant_suffix("Wakamo(New Year)")
        assert base == "Wakamo"
        assert suffix == "New Year"

    def test_danbooru_style_not_split(self) -> None:
        """wakamo_(blue_archive) — base는 소문자+밑줄이므로 분리 안 함."""
        tag = "wakamo_(blue_archive)"
        base, suffix = split_variant_suffix(tag)
        assert base == tag
        assert suffix is None

    def test_danbooru_style_with_number_not_split(self) -> None:
        tag = "arona_(blue_archive)"
        base, suffix = split_variant_suffix(tag)
        assert base == tag
        assert suffix is None

    def test_mixed_case_not_treated_as_danbooru(self) -> None:
        base, suffix = split_variant_suffix("狐坂ワカモ(クリスマス)")
        assert base == "狐坂ワカモ"
        assert suffix == "クリスマス"

    def test_plain_english_no_paren(self) -> None:
        base, suffix = split_variant_suffix("Blue Archive")
        assert base == "Blue Archive"
        assert suffix is None

    def test_trailing_spaces_stripped(self) -> None:
        base, suffix = split_variant_suffix("  ワカモ(正月)  ")
        assert base == "ワカモ"
        assert suffix == "正月"

    def test_empty_suffix_not_split(self) -> None:
        """ワカモ() — 빈 괄호는 분리하지 않는다 (regex가 1+ 문자 요구)."""
        base, suffix = split_variant_suffix("ワカモ()")
        assert base == "ワカモ()"
        assert suffix is None


class TestIsVariantOf:
    def test_variant_is_variant(self) -> None:
        assert is_variant_of("ワカモ(正月)", "ワカモ") is True

    def test_non_variant_is_not(self) -> None:
        assert is_variant_of("ワカモ", "ワカモ") is False

    def test_different_base_is_not_variant(self) -> None:
        assert is_variant_of("アル(正月)", "ワカモ") is False

    def test_danbooru_style_is_not_variant(self) -> None:
        assert is_variant_of("wakamo_(blue_archive)", "wakamo") is False


class TestBaseTag:
    def test_strips_variant(self) -> None:
        assert base_tag("ワカモ(正月)") == "ワカモ"

    def test_no_variant_unchanged(self) -> None:
        assert base_tag("ワカモ") == "ワカモ"

    def test_danbooru_style_unchanged(self) -> None:
        assert base_tag("wakamo_(blue_archive)") == "wakamo_(blue_archive)"
