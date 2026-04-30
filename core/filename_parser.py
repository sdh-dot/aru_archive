"""
Pixiv 파일명 파서 — 하위 호환 레이어.

내부 구현은 core.pixiv_filename으로 이전됐다.
기존 코드가 parse_pixiv_filename() / PixivFilenameResult를 참조하는 경우
이 모듈을 계속 사용할 수 있다.

신규 코드는 core.pixiv_filename을 직접 import할 것.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.pixiv_filename import (
    PIXIV_BASE_URL,
    PixivFilenameInfo,
    parse_pixiv_filename as _parse_new,
)

__all__ = [
    "PIXIV_BASE_URL",
    "PixivFilenameResult",
    "parse_pixiv_filename",
]


@dataclass(frozen=True)
class PixivFilenameResult:
    """하위 호환 결과 타입. 신규 코드는 PixivFilenameInfo를 사용할 것."""
    artwork_id:  str
    page_index:  int
    artwork_url: str


def parse_pixiv_filename(filename: str | Path) -> Optional[PixivFilenameResult]:
    """
    Pixiv 파일명에서 artwork_id / page_index를 추출한다.

    하위 호환 레이어: 내부적으로 core.pixiv_filename.parse_pixiv_filename()에 위임한다.
    인식 불가이면 None 반환.
    """
    info: Optional[PixivFilenameInfo] = _parse_new(filename)
    if info is None:
        return None
    return PixivFilenameResult(
        artwork_id=info.artwork_id,
        page_index=info.page_index,
        artwork_url=f"{PIXIV_BASE_URL}{info.artwork_id}",
    )
