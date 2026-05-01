"""파일 무결성 검사 UI 회귀 테스트.

source-inspection 기반 — GUI 부팅 최소.
"""
from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")


class TestMainWindowIntegrityAction:
    def test_main_window_has_on_integrity_check_handler(self):
        from app.main_window import MainWindow
        assert hasattr(MainWindow, "_on_integrity_check")
        assert callable(MainWindow._on_integrity_check)

    def test_handler_uses_dry_run_first(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        # dry_run=True 또는 dry_run = True 모두 매치
        assert "dry_run=True" in src or "dry_run = True" in src
        assert "dry_run=False" in src or "dry_run = False" in src

    def test_handler_calls_run_integrity_scan(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "run_integrity_scan" in src

    def test_handler_uses_confirm_dialog(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "IntegrityConfirmDialog" in src

    def test_handler_calls_refresh_after_apply(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "_on_refresh" in src or "_refresh_gallery" in src

    def test_handler_does_not_use_unlink_or_remove(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "os.remove" not in src
        assert "os.unlink" not in src
        assert ".unlink(" not in src
        assert "shutil.rmtree" not in src


class TestIntegrityConfirmDialog:
    def test_dialog_module_import(self):
        from app.views.integrity_confirm_dialog import IntegrityConfirmDialog
        assert IntegrityConfirmDialog is not None

    def test_dialog_source_says_no_real_delete(self):
        import app.views.integrity_confirm_dialog as mod
        src = inspect.getsource(mod)
        assert "실제 파일을 삭제하지 않습니다" in src

    def test_dialog_does_not_use_delete_apis(self):
        import app.views.integrity_confirm_dialog as mod
        src = inspect.getsource(mod)
        assert "os.remove" not in src
        assert ".unlink(" not in src
        assert "shutil.rmtree" not in src


class TestIntegrityScannerNoDeletion:
    def test_scanner_module_does_not_use_delete_apis(self):
        import core.integrity_scanner as mod
        src = inspect.getsource(mod)
        assert "os.remove" not in src
        assert "os.unlink" not in src
        assert ".unlink(" not in src
        assert "shutil.rmtree" not in src
