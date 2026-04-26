"""
태그 alias 매칭용 정규화.

normalize_tag_key(): alias lookup key를 만든다.
실제 canonical 확정은 alias 등록된 값에 한정하며,
이 함수는 lookup key 생성 목적으로만 사용한다.
"""
from __future__ import annotations

import unicodedata


def normalize_tag_key(tag: str) -> str:
    """
    alias 매칭용 key를 만든다.

    정책:
    - Unicode NFKC 정규화 (전각→반각, 합성 문자 분해·재결합)
    - 앞뒤 공백 제거
    - 대소문자 fold (casefold)
    - 내부 공백 / 구분자 제거: space, _, ·, ・ (중점), -, /
    """
    if not tag:
        return ""
    normalized = unicodedata.normalize("NFKC", tag)
    normalized = normalized.casefold()
    normalized = normalized.strip()
    for ch in (" ", "_", "·", "・", "-", "/"):
        normalized = normalized.replace(ch, "")
    return normalized
