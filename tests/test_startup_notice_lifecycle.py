"""Startup notice lifecycle source-inspection 회귀 가드.

main.py에 helper가 정의되어 있고 run_gui가 적절한 시점에 호출하는지
잠근다. 실제 GUI exec 호출 없이 source 토큰만 검증.
"""
from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")


class TestHelperExists:
    def test_main_has_show_startup_notice_helper(self):
        from main import _show_startup_notice_if_needed
        assert callable(_show_startup_notice_if_needed)


class TestHelperBehaviorSource:
    def test_helper_compares_seen_version_with_app_version(self):
        from main import _show_startup_notice_if_needed
        src = inspect.getsource(_show_startup_notice_if_needed)
        assert "applicationVersion()" in src
        assert "startup_notice_seen_version" in src

    def test_helper_uses_startup_notice_dialog(self):
        from main import _show_startup_notice_if_needed
        src = inspect.getsource(_show_startup_notice_if_needed)
        assert "StartupNoticeDialog" in src

    def test_helper_calls_save_config(self):
        from main import _show_startup_notice_if_needed
        src = inspect.getsource(_show_startup_notice_if_needed)
        assert "save_config" in src

    def test_helper_checks_dont_show_again_for_version(self):
        from main import _show_startup_notice_if_needed
        src = inspect.getsource(_show_startup_notice_if_needed)
        assert "dont_show_again_for_version" in src

    def test_helper_has_silent_fallback(self):
        from main import _show_startup_notice_if_needed
        src = inspect.getsource(_show_startup_notice_if_needed)
        assert "try:" in src
        assert "except Exception" in src


class TestRunGuiLifecycle:
    def test_run_gui_calls_show_startup_notice(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        assert "_show_startup_notice_if_needed(window, config, config_path)" in src

    def test_show_startup_notice_called_after_splash_finish(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        finish_idx = src.find("splash.finish(window)")
        notice_idx = src.find("_show_startup_notice_if_needed(window, config, config_path)")
        assert finish_idx >= 0 and notice_idx >= 0
        assert finish_idx < notice_idx, (
            "splash.finish(window)가 _show_startup_notice_if_needed보다 먼저여야 함"
        )

    def test_show_startup_notice_called_before_app_exec(self):
        from main import run_gui
        src = inspect.getsource(run_gui)
        notice_idx = src.find("_show_startup_notice_if_needed(window, config, config_path)")
        exec_idx = src.find("app.exec()")
        assert notice_idx >= 0 and exec_idx >= 0
        assert notice_idx < exec_idx

    def test_run_headless_does_not_call_startup_notice(self):
        from main import run_headless
        src = inspect.getsource(run_headless)
        assert "_show_startup_notice_if_needed" not in src
        assert "StartupNoticeDialog" not in src


class TestVersionUnchanged:
    def test_main_keeps_application_version_0_1_0(self):
        """본 PR은 setApplicationVersion 변경하지 않음."""
        from main import run_gui
        src = inspect.getsource(run_gui)
        assert 'setApplicationVersion("0.1.0")' in src
