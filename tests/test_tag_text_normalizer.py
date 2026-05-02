"""``core.tag_text_normalizer`` 단위 테스트.

분류 정규화 / 자동완성 두 영역에서 함께 사용되는 helper 의 핵심 약속을 lock 한다.
"""
from __future__ import annotations

import pytest

from core.tag_text_normalizer import (
    LONG_VOWEL_MARK,
    TagTextVariant,
    build_tag_variants,
    detect_input_script,
    looks_mojibake,
    normalize_tag_text,
)


# ---------------------------------------------------------------------------
# normalize_tag_text
# ---------------------------------------------------------------------------

class TestNormalizeTagText:
    def test_empty_input(self):
        assert normalize_tag_text("") == ""
        assert normalize_tag_text(None) == ""

    def test_strip_whitespace(self):
        assert normalize_tag_text("  Blue Archive  ") == "Blue Archive"

    def test_collapses_internal_whitespace(self):
        assert normalize_tag_text("Blue   Archive") == "Blue Archive"

    def test_full_width_ascii_to_half_width(self):
        # NFKC 는 전각 영숫자를 반각으로 정규화한다.
        assert normalize_tag_text("Ｂｌｕｅ") == "Blue"

    def test_full_width_space_collapsed(self):
        # NFKC 는 ideographic space (U+3000) 를 일반 space 로 변환 → collapse 적용
        assert normalize_tag_text("Blue　Archive") == "Blue Archive"

    def test_preserves_korean(self):
        assert normalize_tag_text("블루 아카이브") == "블루 아카이브"

    def test_preserves_japanese(self):
        assert normalize_tag_text("ブルーアーカイブ") == "ブルーアーカイブ"

    def test_preserves_case(self):
        # casefold 는 적용하지 않는다 (그건 lookup-key 용 normalize_tag_key 의 책임).
        assert normalize_tag_text("Blue Archive") == "Blue Archive"
        assert normalize_tag_text("blue archive") == "blue archive"


# ---------------------------------------------------------------------------
# build_tag_variants
# ---------------------------------------------------------------------------

def _values(variants: tuple[TagTextVariant, ...]) -> list[str]:
    return [v.value for v in variants]


def _hint_for(variants: tuple[TagTextVariant, ...], value: str) -> str:
    for v in variants:
        if v.value == value:
            return v.confidence_hint
    raise AssertionError(f"variant value {value!r} 가 없다")


class TestBuildTagVariants:
    def test_empty_input(self):
        assert build_tag_variants("") == ()
        assert build_tag_variants(None) == ()

    def test_simple_ascii(self):
        result = build_tag_variants("Blue Archive")
        values = _values(result)
        assert "Blue Archive" in values
        assert "BlueArchive" in values
        assert _hint_for(result, "Blue Archive") == "exact"
        assert _hint_for(result, "BlueArchive") == "compact"

    def test_padding_collapsed_into_normalized_variant(self):
        result = build_tag_variants("  Blue   Archive  ")
        values = _values(result)
        assert "  Blue   Archive  " in values   # raw 보존
        assert "Blue Archive" in values         # normalized
        assert "BlueArchive" in values          # compact

    def test_no_duplicate_values(self):
        # raw 와 normalized 가 동일하면 한 번만 들어가야 한다.
        result = build_tag_variants("Blue Archive")
        assert len(_values(result)) == len(set(_values(result)))

    def test_trailing_long_vowel_variant(self):
        result = build_tag_variants("ブルー")
        values = _values(result)
        assert "ブルー" in values
        assert "ブル" in values  # trailing ー 제거
        assert _hint_for(result, "ブル") == "trailing_long_vowel_removed"

    def test_all_long_vowels_variant_added_when_internal(self):
        # 내부 ー 가 있으면 all_long_vowels_removed variant 가 trailing 과 별도로 생긴다.
        result = build_tag_variants("ブルーアーカイブ")
        values = _values(result)
        assert "ブルーアーカイブ" in values
        assert "ブルアカイブ" in values  # all ー removed

    def test_no_long_vowel_variant_when_absent(self):
        result = build_tag_variants("Blue Archive")
        for v in result:
            assert v.confidence_hint not in (
                "trailing_long_vowel_removed",
                "all_long_vowels_removed",
            )


# ---------------------------------------------------------------------------
# hyphen vs long vowel mark — 핵심 invariant
# ---------------------------------------------------------------------------

class TestHyphenLongVowelDistinct:
    """ASCII hyphen ``"-"`` 과 일본어 장음 ``"ー"`` 는 절대 같은 문자로 취급되지 않는다."""

    def test_long_vowel_mark_is_not_hyphen(self):
        assert LONG_VOWEL_MARK == "ー"
        assert LONG_VOWEL_MARK != "-"
        assert ord(LONG_VOWEL_MARK) == 0x30FC

    def test_hyphen_preserved_through_normalize(self):
        # 폴더 separator "시리즈 - 캐릭터" 에서 "-" 보존 필수.
        assert normalize_tag_text("Blue Archive - Aru") == "Blue Archive - Aru"

    def test_hyphen_does_not_trigger_long_vowel_variants(self):
        result = build_tag_variants("Blue Archive - Aru")
        for v in result:
            assert v.confidence_hint not in (
                "trailing_long_vowel_removed",
                "all_long_vowels_removed",
            )

    def test_long_vowel_variant_does_not_strip_hyphen(self):
        # 동일 입력에 hyphen 과 ー 가 함께 있을 때, ー 만 제거되고 - 는 남는다.
        result = build_tag_variants("ブルー - Aru")
        values = _values(result)
        # all-long-vowels-removed variant 에서도 "-" 는 남아 있어야 한다.
        long_removed = [
            v.value for v in result
            if v.confidence_hint in (
                "trailing_long_vowel_removed",
                "all_long_vowels_removed",
            )
        ]
        assert long_removed
        for value in long_removed:
            assert "-" in value
            assert "ー" not in value


# ---------------------------------------------------------------------------
# detect_input_script
# ---------------------------------------------------------------------------

class TestDetectInputScript:
    def test_empty(self):
        assert detect_input_script("") == "unknown"
        assert detect_input_script(None) == "unknown"
        assert detect_input_script("   ") == "unknown"

    def test_korean(self):
        assert detect_input_script("블루 아카이브") == "ko"
        assert detect_input_script("아루") == "ko"

    def test_japanese_hiragana(self):
        assert detect_input_script("あるはちょっとつかれた") == "ja"

    def test_japanese_katakana(self):
        assert detect_input_script("ブルーアーカイブ") == "ja"

    def test_ascii(self):
        assert detect_input_script("Blue Archive") == "ascii"
        assert detect_input_script("aru_p0") == "ascii"

    def test_mixed_korean_and_kana(self):
        assert detect_input_script("블루 アーカイブ") == "mixed"

    def test_kanji_only_is_unknown(self):
        # 한자만 (가나 없음) → 한국어/중국어/일본어 구분 불가 → 보수적으로 unknown.
        assert detect_input_script("青色档案") == "unknown"

    def test_punctuation_only_is_unknown(self):
        assert detect_input_script("!!??") == "unknown"


# ---------------------------------------------------------------------------
# looks_mojibake
# ---------------------------------------------------------------------------

class TestLooksMojibake:
    def test_empty_is_not_mojibake(self):
        assert looks_mojibake("") is False
        assert looks_mojibake(None) is False

    def test_replacement_char_detected(self):
        assert looks_mojibake("Blue�Archive") is True

    def test_question_run_detected(self):
        assert looks_mojibake("???") is True
        assert looks_mojibake("Blue ?? Archive") is True

    def test_single_question_not_flagged(self):
        # 하나짜리 ? 는 정상 입력 (검색어 등) 에서도 흔하다.
        assert looks_mojibake("Blue Archive?") is False

    def test_normal_korean_not_flagged(self):
        assert looks_mojibake("블루 아카이브") is False
        assert looks_mojibake("아루") is False

    def test_normal_japanese_not_flagged(self):
        assert looks_mojibake("ブルーアーカイブ") is False
        assert looks_mojibake("白上フブキ") is False

    def test_normal_ascii_not_flagged(self):
        assert looks_mojibake("Blue Archive") is False

    def test_punctuation_heavy_short_input_flagged(self):
        # 의미 있는 가시 문자 비율 < 30% 면 mojibake 로 간주.
        assert looks_mojibake("@@@@@") is True
        assert looks_mojibake("...!!!...") is True

    def test_mixed_normal_text_with_some_punctuation_not_flagged(self):
        # 정상 한글 + 약간의 구두점 → 가시 문자 중 한글 비율이 충분히 높음.
        assert looks_mojibake("아루 (Blue Archive)") is False


# ---------------------------------------------------------------------------
# 데이터클래스 형태 / immutability
# ---------------------------------------------------------------------------

class TestTagTextVariantDataclass:
    def test_is_frozen(self):
        v = TagTextVariant(value="Blue", kind="raw", confidence_hint="exact")
        with pytest.raises((AttributeError, Exception)):
            v.value = "Other"  # type: ignore[misc]

    def test_equality(self):
        a = TagTextVariant(value="Blue", kind="raw", confidence_hint="exact")
        b = TagTextVariant(value="Blue", kind="raw", confidence_hint="exact")
        assert a == b

    def test_hashable(self):
        v = TagTextVariant(value="Blue", kind="raw", confidence_hint="exact")
        assert hash(v) is not None
        assert {v} == {v, v}
