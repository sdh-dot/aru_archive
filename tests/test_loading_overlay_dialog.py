"""
LoadingOverlayDialog smoke + asset resolution 회귀 테스트.

목적:
- assets/loading/ 자산이 release build에서 누락된 사고 (v0.6.3 이후) 재발 방지
- frozen-aware 경로 helper (loading_image_path / loading_icon_path) 의 resolver 검증
- pixmap 누락 시 dialog가 crash 없이 fallback text를 보여주는지 검증
- PyInstaller spec datas에 assets/loading/ 가 포함되어 있는지 source-inspection 가드
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6가 설치되어 있지 않음")


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_loading_assets_present_in_repo():
    main_image = REPO_ROOT / "assets" / "loading" / "loading_01.png"
    mini_icon = REPO_ROOT / "assets" / "loading" / "icon_05.png"
    assert main_image.exists(), f"누락된 release asset: {main_image}"
    assert mini_icon.exists(), f"누락된 release asset: {mini_icon}"


def test_loading_image_path_helper_resolves_in_dev():
    from app.resources import loading_image_path

    resolved = loading_image_path()
    assert resolved is not None, "dev 환경에서 loading_image_path()가 None을 반환했다."
    assert Path(resolved).exists(), f"resolver가 가리킨 파일이 실제로 없다: {resolved}"
    assert Path(resolved).name == "loading_01.png"


def test_loading_icon_path_helper_resolves_in_dev():
    from app.resources import loading_icon_path

    resolved = loading_icon_path()
    assert resolved is not None, "dev 환경에서 loading_icon_path()가 None을 반환했다."
    assert Path(resolved).exists(), f"resolver가 가리킨 파일이 실제로 없다: {resolved}"
    assert Path(resolved).name == "icon_05.png"


def test_loading_overlay_dialog_initializes_with_assets(qt_app):
    from app.views.loading_overlay_dialog import LoadingOverlayDialog

    dlg = LoadingOverlayDialog()
    try:
        assert dlg._main_image_path is not None
        assert dlg._mini_icon_path is not None
        assert dlg._main_image.pixmap() is not None
        assert not dlg._main_image.pixmap().isNull(), (
            "메인 이미지 pixmap이 null. release asset이 정상적으로 로드되지 않음."
        )
    finally:
        dlg.deleteLater()


def test_loading_overlay_dialog_falls_back_when_assets_missing(qt_app, monkeypatch):
    """assets/loading 자산이 없을 때 (예: spec 누락) crash 없이 fallback text를 표시."""
    from app.views import loading_overlay_dialog as mod

    monkeypatch.setattr(mod, "loading_image_path", lambda: None)
    monkeypatch.setattr(mod, "loading_icon_path", lambda: None)

    dlg = mod.LoadingOverlayDialog()
    try:
        assert dlg._main_image_path is None
        assert dlg._mini_icon_path is None
        assert dlg._main_image.pixmap().isNull()
        assert "불러오지 못했습니다" in dlg._main_image.text()
    finally:
        dlg.deleteLater()


def test_pyinstaller_spec_includes_loading_assets():
    spec_path = REPO_ROOT / "build" / "aru_archive.spec"
    text = spec_path.read_text(encoding="utf-8")
    assert re.search(r'"assets"\s*/\s*"loading"', text), (
        "build/aru_archive.spec datas에 assets/loading 디렉터리가 포함되어 있지 않다. "
        "release build에서 LoadingOverlayDialog 이미지가 누락된다."
    )
