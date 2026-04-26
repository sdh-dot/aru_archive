"""
Variant tag 분리 유틸리티.

Pixiv에서 계절/이벤트 코스튬 variant를 별도 canonical로 취급하지 않도록
괄호 suffix를 분리한다.

  ワカモ(正月)       → ("ワカモ",  "正月")
  ワカモ(水着)       → ("ワカモ",  "水着")
  Blue Archive       → ("Blue Archive", None)
  wakamo_(blue_archive) → ("wakamo_(blue_archive)", None)  ← Danbooru 스타일 유지

Danbooru 스타일 character_(series) 패턴 (소문자+밑줄)은 분리하지 않는다.
"""
from __future__ import annotations

import re

# 괄호 하나로 끝나는 패턴 (Danbooru 스타일은 base가 소문자+밑줄이므로 구분 가능)
_PAREN_PATTERN = re.compile(r'^(.+?)\(([^)]+)\)\s*$')


def split_variant_suffix(tag: str) -> tuple[str, str | None]:
    """
    태그에서 variant suffix를 분리한다.

    Danbooru 스타일 character_(series) 패턴은 분리하지 않는다.
    그 외 괄호 suffix는 variant로 간주한다.

    반환:
        (base, suffix)  — suffix=None이면 variant 없음
    """
    m = _PAREN_PATTERN.match(tag.strip())
    if not m:
        return tag, None

    base = m.group(1).strip()
    suffix = m.group(2).strip()

    # Danbooru 스타일: base가 소문자+밑줄로만 구성 → series suffix → 분리 안 함
    if base == base.lower() and '_' in base:
        return tag, None

    return base, suffix


def is_variant_of(tag: str, base_tag: str) -> bool:
    """tag가 base_tag의 variant인지 확인한다."""
    base, suffix = split_variant_suffix(tag)
    return suffix is not None and base == base_tag


def base_tag(tag: str) -> str:
    """variant suffix를 제거한 base tag를 반환한다."""
    base, _ = split_variant_suffix(tag)
    return base
