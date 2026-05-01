"""Startup Splash 회귀 테스트.

helper 단위 테스트 + run_gui source-inspection.
asset relocation 후 assets/splash/splash.png 경로를 사용한다.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication


REPO_ROOT = Path(__file__).resolve().parents[1]
SPLASH_PATH = REPO_ROOT / "assets" / "splash" / "splash.png"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class TestSplashAsset:
    def test_splash_asset_present_at_assets_splash(self):
        assert SPLASH_PATH.exists(), f"assets/splash/splash.png 누락: {SPLASH_PATH}"

    def test_splash_asset_is_non_empty(self):
        assert SPLASH_PATH.stat().st_size > 0


class TestSplashPathHelper:
    def test_splash_path_returns_string_when_asset_present(self):
        from app.resources import splash_path
        result = splash_path()
        assert result is not None
        assert "assets" in result
        assert "splash" in result

    def test_splash_path_resolves_to_existing_file(self):
        from app.resources import splash_path
        result = splash_path()
        assert result is not None
        assert Path(result).exists()


class TestCreateStartupSplash:
    def test_returns_qsplashscreen_when_asset_present(self, qapp):
        from main import _create_startup_splash
        from PyQt6.QtWidgets import QSplashScreen
        splash = _create_startup_splash(qapp)
        assert isinstance(splash, QSplashScreen)

    def test_uses_keep_aspect_ratio_scaling(self, qapp):
        from main import _create_startup_splash
        src = inspect.getsource(_create_startup_splash)
        assert "KeepAspectRatio" in src
        assert "0.72" in src

    def test_does_not_raise_on_failure(self, qapp):
        from main import _create_startup_splash
        src = inspect.getsource(_create_startup_splash)
        assert "try:" in src
        assert "except Exception" in src
        assert "return None" in src

    def test_uses_splash_path_helper(self):
        from main import _create_startup_splash
        src = inspect.getsource(_create_startup_splash)
        assert "splash_path" in src

    def test_uses_isnull_guard(self):
        from main import _create_startup_splash
        src = inspect.getsource(_create_startup_splash)
        assert "isNull()" in src


class TestRunGuiLifecycle:
    def test_run_gui_calls_create_startup_splash(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        assert "_create_startup_splash(app)" in src

    def test_run_gui_shows_splash_before_main_window(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        splash_show = src.find("splash.show()")
        mw_create = src.find("MainWindow(config")
        assert splash_show >= 0 and mw_create >= 0
        assert splash_show < mw_create

    def test_run_gui_calls_process_events(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        assert "processEvents()" in src

    def test_run_gui_calls_finish_after_window_show(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        finish_idx = src.find("splash.finish(window)")
        window_show = src.find("window.show()")
        assert finish_idx >= 0 and window_show >= 0
        assert window_show < finish_idx

    def test_run_gui_uses_none_safe_pattern(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        assert "splash is not None" in src or "if splash:" in src

    def test_run_headless_does_not_create_splash(self):
        from main import run_headless
        src = inspect.getsource(run_headless)
        assert "_create_startup_splash" not in src
        assert "QSplashScreen" not in src
