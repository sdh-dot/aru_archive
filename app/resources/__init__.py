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


def _assets_base() -> Path:
    """frozen / source 양쪽에서 동일하게 동작하는 assets 루트."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.parent.parent  # aru_archive 루트


def loading_image_path() -> Optional[str]:
    """LoadingOverlayDialog 좌측 메인 이미지 경로. 부재 시 None."""
    p = _assets_base() / "assets" / "loading" / "loading_01.png"
    return str(p) if p.exists() else None


def loading_icon_path() -> Optional[str]:
    """LoadingOverlayDialog 하단 mini icon 경로. 부재 시 None."""
    p = _assets_base() / "assets" / "loading" / "icon_05.png"
    return str(p) if p.exists() else None
