"""다국어 태그 텍스트 정규화 / variant 생성 helper.

분류 정규화 (시리즈 역추론, 일본어 장음 차이 대응) 와 자동완성 (한국어/일본어
localized_name 매칭) 두 영역에서 공통으로 사용되는 유틸리티를 모은다.

이 모듈의 책임:
- ``normalize_tag_text(text)``      — Unicode NFKC + 공백 정리 후 단일 문자열 반환
- ``build_tag_variants(text)``      — exact / normalized / compact / 일본어 장음
                                      변형 등 매칭 후보 variant tuple 반환
- ``detect_input_script(text)``     — ko / ja / ascii / mixed / unknown 분류
- ``looks_mojibake(text)``          — 자동완성 후보 필터용 가벼운 wrapper
                                      (정밀 진단은 ``core.mojibake_heuristics`` 참조)

이 모듈이 절대 하지 않는 것:
- 폴더 경로 sanitize (``core.path_utils.sanitize_path_component`` 와 분리)
- alias DB 등록 / DB write
- ASCII hyphen ``"-"`` 와 일본어 장음 부호 ``"ー"`` (U+30FC) 를 같은 문자로
  치환. 두 문자는 의미가 다르며 폴더 separator 보존을 위해 반드시 구분된다.
- 자동완성 source priority 결정 (호출자가 결정)

신뢰도 hint (``TagTextVariant.confidence_hint``) 의미:
- ``"exact"``                       — 입력 원문 그대로
- ``"normalized"``                  — NFKC + 공백 정리만 적용
- ``"compact"``                     — 공백 제거된 검색 키
- ``"trailing_long_vowel_removed"`` — 끝의 ``ー`` 한 글자 제거
- ``"all_long_vowels_removed"``     — 모든 ``ー`` 제거 (낮은 신뢰도)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# 기본 정규화
# ---------------------------------------------------------------------------

_WHITESPACE_RUN = re.compile(r"\s+")

# Japanese long vowel mark (U+30FC). ASCII hyphen (U+002D) 과 의도적으로 다른 문자다.
LONG_VOWEL_MARK = "ー"


def normalize_tag_text(text: Optional[str]) -> str:
    """Unicode NFKC + 양끝 공백 trim + 연속 공백 단일 space 로 축약.

    빈 입력 / None → 빈 문자열 반환. 대소문자는 보존한다 (한국어/일본어 텍스트는
    casefold 와 무관하므로 매칭 키 생성은 ``compact`` variant 또는 별도
    ``core.tag_normalize.normalize_tag_key`` 를 사용한다).
    """
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text)
    trimmed = nfkc.strip()
    return _WHITESPACE_RUN.sub(" ", trimmed)


def _compact(text: str) -> str:
    """모든 공백 제거. matching key 생성 보조."""
    return _WHITESPACE_RUN.sub("", text)


# ---------------------------------------------------------------------------
# Variant 생성
# ---------------------------------------------------------------------------

ConfidenceHint = Literal[
    "exact",
    "normalized",
    "compact",
    "trailing_long_vowel_removed",
    "all_long_vowels_removed",
]


@dataclass(frozen=True)
class TagTextVariant:
    """매칭 후보 1개. ``value`` 가 실제 비교 대상 문자열이다.

    ``kind`` 는 디버그/로깅용 짧은 라벨, ``confidence_hint`` 는 호출자가
    score 가중치를 결정할 때 사용한다.
    """
    value: str
    kind: str
    confidence_hint: ConfidenceHint


def build_tag_variants(text: Optional[str]) -> tuple[TagTextVariant, ...]:
    """매칭 후보 variant 를 생성한다. 빈 입력 → 빈 tuple.

    생성 규칙:
    1. exact          — 입력 원문 (단, 빈 문자열이면 skip)
    2. normalized     — NFKC + 공백 정리
    3. compact        — normalized 에서 모든 공백 제거 (값이 normalized 와 같으면 skip)
    4. trailing_long_vowel_removed — 끝의 ``ー`` 한 글자 제거 (있을 때만)
    5. all_long_vowels_removed     — 모든 ``ー`` 제거 (낮은 신뢰도, trailing 과
                                      값이 같으면 skip — 중복 후보 방지)

    중복 value 는 후행 variant 가 무시된다 (앞 순위 confidence 를 우선).
    ASCII hyphen ``"-"`` 은 어떤 단계에서도 ``ー`` 와 호환 처리되지 않는다.
    """
    if not text:
        return ()

    seen: set[str] = set()
    out: list[TagTextVariant] = []

    def _push(value: str, kind: str, hint: ConfidenceHint) -> None:
        if not value or value in seen:
            return
        seen.add(value)
        out.append(TagTextVariant(value=value, kind=kind, confidence_hint=hint))

    raw = text
    normalized = normalize_tag_text(raw)

    _push(raw, "raw", "exact")
    _push(normalized, "nfkc_trimmed", "normalized")
    _push(_compact(normalized), "no_whitespace", "compact")

    if normalized.endswith(LONG_VOWEL_MARK):
        _push(
            normalized.rstrip(LONG_VOWEL_MARK),
            "trailing_long_vowel_removed",
            "trailing_long_vowel_removed",
        )

    if LONG_VOWEL_MARK in normalized:
        _push(
            normalized.replace(LONG_VOWEL_MARK, ""),
            "all_long_vowels_removed",
            "all_long_vowels_removed",
        )

    return tuple(out)


# ---------------------------------------------------------------------------
# Script detection
# ---------------------------------------------------------------------------

InputScript = Literal["ko", "ja", "ascii", "mixed", "unknown"]


def _is_hangul(ch: str) -> bool:
    code = ord(ch)
    return (
        0xAC00 <= code <= 0xD7A3      # Hangul Syllables
        or 0x1100 <= code <= 0x11FF   # Hangul Jamo
        or 0x3130 <= code <= 0x318F   # Hangul Compatibility Jamo
        or 0xA960 <= code <= 0xA97F   # Hangul Jamo Extended-A
        or 0xD7B0 <= code <= 0xD7FF   # Hangul Jamo Extended-B
    )


def _is_kana(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x309F       # Hiragana
        or 0x30A0 <= code <= 0x30FF    # Katakana
        or 0x31F0 <= code <= 0x31FF    # Katakana Phonetic Extensions
    )


def _is_cjk_ideograph(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400  <= code <= 0x4DBF      # CJK Extension A
        or 0x4E00  <= code <= 0x9FFF   # CJK Unified Ideographs
        or 0x20000 <= code <= 0x2A6DF  # CJK Extension B
        or 0xF900  <= code <= 0xFAFF   # CJK Compatibility Ideographs
    )


def _classify_char(ch: str) -> str:
    """문자 1개를 ``hangul``/``kana``/``cjk``/``ascii_alnum``/``other`` 로 분류.

    공백은 호출자가 사전 필터링한다.
    """
    if _is_hangul(ch):
        return "hangul"
    if _is_kana(ch):
        return "kana"
    if _is_cjk_ideograph(ch):
        return "cjk"
    if ord(ch) < 0x80:
        return "ascii_alnum" if (ch.isalpha() or ch.isdigit()) else "ascii_punct"
    return "other"


def detect_input_script(text: Optional[str]) -> InputScript:
    """입력 문자열의 주요 스크립트를 반환한다.

    분류 규칙:
    - 비어 있음 / None / 모두 공백 → ``"unknown"``
    - 한글과 일본어 가나가 동시에 발견 → ``"mixed"``
    - 한글만 → ``"ko"``
    - 일본어 가나 (히라가나/가타카나) 포함 → ``"ja"``
      (한자만 있고 가나가 없는 입력은 한국어/중국어 구분이 모호하므로 보수적으로
       ``"unknown"`` 반환. 호출자가 추가 컨텍스트로 결정)
    - 영문/숫자 가시 문자가 있고, 비-ASCII 가시 문자가 없으면 → ``"ascii"``
    - 위 어디에도 해당 안 됨 → ``"unknown"``
    """
    if not text:
        return "unknown"

    categories = {_classify_char(ch) for ch in text if not ch.isspace()}
    if not categories:
        return "unknown"

    has_hangul = "hangul" in categories
    has_kana = "kana" in categories
    has_non_ascii_visible = "cjk" in categories or "other" in categories
    has_ascii_letter = "ascii_alnum" in categories

    if has_hangul and has_kana:
        return "mixed"
    if has_hangul:
        return "ko"
    if has_kana:
        return "ja"
    if has_ascii_letter and not has_non_ascii_visible:
        return "ascii"
    return "unknown"


# ---------------------------------------------------------------------------
# 가벼운 mojibake 감지 (자동완성 후보 필터링용)
# ---------------------------------------------------------------------------

# U+FFFD REPLACEMENT CHARACTER. core.mojibake_heuristics 와 동일.
_REPLACEMENT_CHAR = "�"

_QUESTION_RUN = re.compile(r"\?{2,}")


def looks_mojibake(text: Optional[str]) -> bool:
    """자동완성 후보 표시 전 빠르게 거를 mojibake 여부를 판별한다.

    이 함수는 **lightweight** 다 — 정밀 진단 / DB lint 가 필요하면
    ``core.mojibake_heuristics.is_suspected_mojibake`` 를 직접 사용하라.

    True 를 반환하는 조건:
    - U+FFFD (replacement char) 포함
    - "??" 이상 연속한 question mark
    - 문자가 거의 punctuation/symbol 로만 채워진 짧은 입력 (정상 텍스트의
      가독성 임계값 — 가시 문자 중 알파벳/한글/가나/한자 비율 < 30%)

    빈 입력 → False (필터하지 않음, 호출자가 별도 처리).
    """
    if not text:
        return False

    if _REPLACEMENT_CHAR in text:
        return True

    if _QUESTION_RUN.search(text):
        return True

    visible = [ch for ch in text if not ch.isspace()]
    if not visible:
        return False

    meaningful = sum(
        1
        for ch in visible
        if (
            _is_hangul(ch)
            or _is_kana(ch)
            or _is_cjk_ideograph(ch)
            or ch.isalpha()
            or ch.isdigit()
        )
    )
    if meaningful / len(visible) < 0.30:
        return True

    return False
