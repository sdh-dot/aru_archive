"""app/resources 패키지. 번들(PyInstaller)과 개발 모드 양쪽에서 아이콘 경로를 반환한다."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def icon_path() -> str:
    """
    aru_archive_icon.ico의 절대 경로를 반환한다.
    - 개발 모드: assets/icon/ 기준
    - PyInstaller 번들: sys._MEIPASS/assets/icon/ 기준
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent.parent  # aru_archive 루트
    return str(base / "assets" / "icon" / "aru_archive_icon.ico")


def splash_path() -> Optional[str]:
    """assets/splash/splash.png 경로. 부재 시 None.

    개발 모드: assets/splash/ 기준
    PyInstaller 번들: sys._MEIPASS/assets/splash/ 기준

    splash 자산이 없으면 None 반환 (앱은 splash 없이 정상 기동).
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent.parent  # aru_archive 루트
    p = base / "assets" / "splash" / "splash.png"
    return str(p) if p.exists() else None
