"""
Windows 경로 안전화 유틸리티.
파일명/폴더명 컴포넌트에 사용할 수 없는 문자를 치환한다.
"""
from __future__ import annotations

import re

# Windows에서 파일명에 금지된 문자 및 제어 문자
_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 파일명 끝에 올 수 없는 공백/점
_TRAILING_RE  = re.compile(r'[\s.]+$')


def sanitize_path_component(name: str, fallback: str = "_unknown") -> str:
    """
    Windows 경로 컴포넌트에 사용할 수 없는 문자를 제거/치환한다.

    금지 문자: < > : " / \\ | ? *  및 ASCII 제어 문자(0x00-0x1f)
    앞뒤 공백 및 끝의 점(.) 제거.
    빈 문자열이면 fallback 반환.
    """
    result = _FORBIDDEN_RE.sub("_", str(name))
    result = _TRAILING_RE.sub("", result).strip()
    return result if result else fallback
