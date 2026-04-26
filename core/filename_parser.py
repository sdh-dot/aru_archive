"""
Pixiv 파일명 파서.

지원 패턴:
  141100516_p0_master1200.jpg  → artwork_id=141100516, page_index=0
  141100516_p0.jpg             → artwork_id=141100516, page_index=0
  141100516_p1.png             → artwork_id=141100516, page_index=1
  141100516_ugoira.zip         → artwork_id=141100516, page_index=0

인식 불가 파일명이면 None 반환.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PIXIV_BASE_URL = "https://www.pixiv.net/artworks/"

# {5,12} digits — artwork_id, then _p{n}[_{quality}] or _ugoira[_{suffix}]
_PATTERN = re.compile(
    r"^(\d{5,12})_"
    r"(?:p(\d+)(?:_\w+)*"   # _p{page}[_quality...]
    r"|ugoira(?:_\w+)*)"     # or _ugoira[_suffix...]
    r"\.\w+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PixivFilenameResult:
    artwork_id: str
    page_index: int
    artwork_url: str


def parse_pixiv_filename(filename: str) -> Optional[PixivFilenameResult]:
    """
    Pixiv 저장 파일명에서 artwork_id / page_index를 추출한다.

    파일 전체 경로를 전달해도 basename만 사용한다.
    인식 불가이면 None 반환.
    """
    name = Path(filename).name
    m = _PATTERN.match(name)
    if m is None:
        return None

    artwork_id: str = m.group(1)
    page_str: Optional[str] = m.group(2)   # None for ugoira branch
    page_index = int(page_str) if page_str is not None else 0

    return PixivFilenameResult(
        artwork_id=artwork_id,
        page_index=page_index,
        artwork_url=f"{PIXIV_BASE_URL}{artwork_id}",
    )
