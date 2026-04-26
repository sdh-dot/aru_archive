"""app/resources 패키지. 번들(PyInstaller)과 개발 모드 양쪽에서 아이콘 경로를 반환한다."""
from __future__ import annotations

import sys
from pathlib import Path


def icon_path() -> str:
    """
    aru_archive_icon.ico의 절대 경로를 반환한다.
    - 개발 모드: app/resources/icons/ 기준
    - PyInstaller 번들: sys._MEIPASS/app/resources/icons/ 기준
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent.parent  # aru_archive 루트
    return str(base / "app" / "resources" / "icons" / "aru_archive_icon.ico")
