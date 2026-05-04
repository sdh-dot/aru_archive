"""
분류 완료 폴더 하위의 카테고리 폴더명을 ko / ja / en 으로 로컬라이즈한다 (PR #122).

내부 category key (`by_author`, `by_series`, `by_character`, `by_tag`) 는 절대
변하지 않는 안정 식별자이다. DB / consistency report / preview rule_type 매칭은
모두 내부 key 기준으로 이루어지며, 화면 표시명과 실제 파일시스템 폴더명만
``folder_name_language`` 에 따라 바뀐다.

언어 정책:
- ``ko`` / ``ja`` / ``en`` 만 정식 지원.
- ``canonical`` 또는 빈 문자열은 영어 (``en``) 와 동일하게 라벨을 반환.
- 그 외 알 수 없는 값은 영어로 안전 fallback — 예외를 던지지 않는다.

기존 정책:
- 이미 생성된 폴더는 자동으로 rename 되지 않는다.
- 새 preview / 새 destination 생성에서만 선택 언어가 적용된다.

PR #125 변경:
- category folder label 단순화: "시리즈 기준" → "시리즈", "캐릭터 기준" → "캐릭터",
  "작가 기준" → "작가", 영어 "BySeries" → "Series" 등.
- UNCATEGORIZED_FOLDER_LABELS + resolve_uncategorized_folder() 추가:
  `_uncategorized` 내부 폴더명이 사용자 폴더명으로 직접 노출되지 않도록 한다.
"""
from __future__ import annotations

from typing import Mapping

# category key → locale → folder name (실제 파일시스템 컴포넌트로 사용됨)
# 내부 key (by_author / by_series / by_character / by_tag) 는 변경하지 않는다.
CATEGORY_FOLDER_LABELS: Mapping[str, Mapping[str, str]] = {
    "by_author": {
        "ko": "작가",
        "ja": "作者",
        "en": "Author",
    },
    "by_series": {
        "ko": "시리즈",
        "ja": "シリーズ",
        "en": "Series",
    },
    "by_character": {
        "ko": "캐릭터",
        "ja": "キャラクター",
        "en": "Character",
    },
    "by_tag": {
        "ko": "태그",
        "ja": "タグ",
        "en": "Tag",
    },
}

# `_uncategorized` 내부 폴더명 대신 사용자에게 보일 localized label.
# series_only 모드에서 series 미식별 시, 또는 series_character Tier 2 에서
# character 없이 series만 있을 때 사용된다.
UNCATEGORIZED_FOLDER_LABELS: Mapping[str, str] = {
    "ko": "미분류",
    "ja": "未分類",
    "en": "Uncategorized",
}

# Aru Archive 가 정식 지원하는 폴더명 언어 코드.
SUPPORTED_FOLDER_NAME_LANGS: frozenset[str] = frozenset({"ko", "ja", "en"})

# canonical 표시는 영어 라벨과 동일하게 처리한다.
_FALLBACK_LANG = "en"


def _normalize_lang(lang: str | None) -> str:
    """입력 언어 코드를 지원 언어로 안전 매핑한다.

    canonical / '' / None / 알 수 없는 값 → ``en`` (fallback). 예외를 던지지
    않는다 — preview 흐름이 알 수 없는 언어 설정 때문에 끊기지 않도록 한다.
    """
    if not lang:
        return _FALLBACK_LANG
    if lang == "canonical":
        return _FALLBACK_LANG
    if lang in SUPPORTED_FOLDER_NAME_LANGS:
        return lang
    return _FALLBACK_LANG


def resolve_category_folder(category_key: str, lang: str | None) -> str:
    """category_key + 언어로 실제 폴더명을 반환한다.

    Args:
        category_key: ``by_author`` / ``by_series`` / ``by_character`` / ``by_tag``
                      등 안정적인 내부 key. 이 함수의 반환값은 사용자에게 보일
                      폴더명일 뿐, DB 비교 / consistency report 의 키는 절대
                      이 반환값을 쓰지 않는다.
        lang:         ``ko`` / ``ja`` / ``en`` / ``canonical`` / 알 수 없는 값.
                      알 수 없거나 ``canonical`` 이면 영어 라벨로 fallback.

    Returns:
        파일시스템 컴포넌트로 사용 가능한 폴더명 문자열. 알 수 없는
        ``category_key`` 가 들어오면 그 키 자체를 반환 (안전 fallback).
    """
    labels = CATEGORY_FOLDER_LABELS.get(category_key)
    if labels is None:
        return category_key
    return labels.get(_normalize_lang(lang), labels[_FALLBACK_LANG])


def resolve_uncategorized_folder(lang: str | None) -> str:
    """localized uncategorized folder label 을 반환한다.

    `_uncategorized` 가 사용자 폴더명으로 직접 노출되지 않도록 한다.

    Args:
        lang: ``ko`` / ``ja`` / ``en`` / ``canonical`` / None.

    Returns:
        - ko → "미분류"
        - ja → "未分類"
        - en / canonical / 기타 → "Uncategorized"
    """
    normalized = _normalize_lang(lang)
    return UNCATEGORIZED_FOLDER_LABELS.get(normalized, UNCATEGORIZED_FOLDER_LABELS[_FALLBACK_LANG])


def resolve_folder_name_language(config: dict | None) -> str:
    """config dict 에서 folder_name_language 를 읽어 정규화해 반환한다.

    우선순위:
    1. ``config["folder_name_language"]`` (PR #122 신규 top-level key)
    2. ``config["classification"]["folder_locale"]`` (legacy 키)
    3. fallback ``en``

    ``canonical`` / 알 수 없는 값은 ``en`` 으로 정규화된다. classification
    영역의 ``folder_locale`` 의미 (series/character display 언어) 와 동일한
    값을 공유하므로 두 설정이 일관성을 잃지 않는다.
    """
    if not config:
        return _FALLBACK_LANG
    raw = config.get("folder_name_language")
    if not raw:
        cls = config.get("classification") or {}
        raw = cls.get("folder_locale")
    return _normalize_lang(raw)
