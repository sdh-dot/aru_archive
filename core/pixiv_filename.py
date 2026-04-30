"""
Pixiv 파일명 파서 — 개선판.

지원 패턴:
  106586263_p0_master1200.jpg       → artwork_id=106586263, page_index=0
  106586263_p0.jpg                  → artwork_id=106586263, page_index=0
  106586263_p0_master1200 (1).jpg   → artwork_id=106586263, page_index=0
  106586263_p0 (2).webp             → artwork_id=106586263, page_index=0
  106586263_P0_master1200.jpg       → artwork_id=106586263, page_index=0
  106586263-p1-master1200.png       → artwork_id=106586263, page_index=1
  pixiv_106586263_p2.jpg            → artwork_id=106586263, page_index=2
  141100516_ugoira.zip              → artwork_id=141100516, page_index=0

인식 불가 파일명이면 None 반환.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PIXIV_BASE_URL = "https://www.pixiv.net/artworks/"

# Windows duplicate suffix: "name (1)" → "name"
_DUP_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")

# artwork_id: 5–12 digits (짧은 ID는 초창기 작품)
# separator : _ 또는 -
# page      : p / P 대소문자 무관, 뒤에 _suffix 또는 -suffix 허용
# ugoira    : _ugoira 또는 -ugoira 로 시작하는 변형
_PATTERN = re.compile(
    r"^(?:pixiv_)?"                    # optional "pixiv_" prefix
    r"(\d{5,12})"                      # artwork_id
    r"[_-]"                            # separator: _ or -
    r"(?:"
    r"[Pp](\d+)(?:[_-]\w+)*"          # p/P + page_index [+ suffix(es)]
    r"|ugoira(?:[_-]\w+)*"             # or ugoira variant
    r")$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PixivFilenameInfo:
    artwork_id:      str
    page_index:      int
    normalized_stem: str            # "{artwork_id}_p{page_index}"
    confidence:      str            # "high" | "medium"
    source:          str = field(default="filename")


def parse_pixiv_filename(filename: str | Path) -> PixivFilenameInfo | None:
    """
    Pixiv 파일명에서 artwork_id / page_index를 추출한다.

    - 전체 경로를 전달해도 basename만 사용한다.
    - Windows duplicate suffix "(1)", "(2)" 를 무시한다.
    - 구분자는 _ 또는 - 모두 허용한다.
    - p / P 대소문자를 무시한다.
    - 인식 불가이면 None 반환한다.
    """
    path = Path(filename)
    if not path.suffix:
        return None

    stem = path.stem

    # Windows duplicate suffix 제거: "name (1)" → "name"
    stem = _DUP_SUFFIX.sub("", stem)

    m = _PATTERN.match(stem)
    if m is None:
        return None

    artwork_id: str = m.group(1)
    page_str = m.group(2)                      # None for ugoira branch
    page_index = int(page_str) if page_str is not None else 0

    # pixiv_ 접두사가 있으면 medium 신뢰도
    confidence = "medium" if stem.lower().startswith("pixiv_") else "high"

    return PixivFilenameInfo(
        artwork_id=artwork_id,
        page_index=page_index,
        normalized_stem=f"{artwork_id}_p{page_index}",
        confidence=confidence,
    )
