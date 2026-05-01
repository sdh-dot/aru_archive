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


class TestIntegrityRestoreCompletionMessage:
    def test_completion_message_contains_restored_keyword(self):
        """완료 메시지에 '다시 확인됨' 키워드가 포함되는지 확인."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "다시 확인됨" in src

    def test_completion_message_uses_restore_updated_key(self):
        """완료 메시지가 restore_updated 키를 참조하는지 확인."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "restore_updated" in src

    def test_scanner_exports_find_restored_files(self):
        """find_restored_files가 모듈에서 임포트 가능한지 확인."""
        from core.integrity_scanner import find_restored_files
        assert callable(find_restored_files)

    def test_scanner_exports_mark_files_as_present(self):
        """mark_files_as_present가 모듈에서 임포트 가능한지 확인."""
        from core.integrity_scanner import mark_files_as_present
        assert callable(mark_files_as_present)

    def test_run_integrity_scan_returns_restore_keys(self):
        """run_integrity_scan 반환 dict에 신규 키가 있는지 source 확인."""
        import core.integrity_scanner as mod
        src = inspect.getsource(mod.run_integrity_scan)
        assert "restored_files" in src
        assert "restored_count" in src
        assert "restore_updated" in src


class TestHashMismatchCompletionMessage:
    def test_completion_message_includes_hash_mismatch_count_when_nonzero(self):
        """hash mismatch 1건 이상일 때 완료 메시지에 '해시 불일치' 문구 포함."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "해시 불일치" in src
        assert "restore_skipped_hash_mismatch" in src

    def test_completion_message_unchanged_when_hash_mismatch_zero(self):
        """hash mismatch 0건 분기가 존재하고 기존 문구를 그대로 사용한다."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        # 기존 키워드가 여전히 존재해야 함
        assert "누락으로 표시" in src
        assert "다시 확인됨" in src
        # mismatch_count 조건 분기가 있어야 함
        assert "mismatch_count" in src


class TestHashMismatchReviewDialogIntegration:
    """MainWindow._on_integrity_check()가 hash mismatch 결과에 따라
    IntegrityRestoreHoldDialog를 호출(또는 호출하지 않음)하는지 source-inspection으로 확인."""

    def test_no_mismatch_skips_review_dialog(self):
        """hash_mismatch_files 키를 확인하는 조건 분기가 존재한다 (빈 list면 dialog 미표시 경로)."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        # 조건 분기 존재 확인
        assert "hash_mismatch_files" in src
        # 조건이 비어 있을 때를 처리하는 if 분기 (빈 list → falsy)
        assert "if mismatch_files" in src or "if len(mismatch_files)" in src

    def test_mismatch_present_invokes_review_dialog(self):
        """hash_mismatch_files가 있을 때 IntegrityRestoreHoldDialog를 호출한다."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "IntegrityRestoreHoldDialog" in src
        assert "hash_mismatch_files" in src

    def test_completion_message_unchanged_when_mismatch(self):
        """완료 메시지 문구 자체는 변경되지 않았다 — 기존 키워드가 그대로 존재."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "누락으로 표시" in src
        assert "다시 확인됨" in src
        assert "해시 불일치로 복원 보류" in src

    def test_main_window_connects_view_missing_signal(self):
        """_on_integrity_check 소스에 view_missing_files_requested signal connect가 있다."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._on_integrity_check)
        assert "view_missing_files_requested" in src
        assert "_navigate_to_missing_category" in src

    def test_navigate_to_missing_category_method_exists(self):
        """MainWindow에 _navigate_to_missing_category 메서드가 존재한다."""
        from app.main_window import MainWindow
        assert hasattr(MainWindow, "_navigate_to_missing_category")
        assert callable(MainWindow._navigate_to_missing_category)

    def test_navigate_method_calls_sidebar_select(self):
        """_navigate_to_missing_category가 sidebar.select_category('missing')를 호출한다."""
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._navigate_to_missing_category)
        assert "select_category" in src
        assert '"missing"' in src or "'missing'" in src


class TestSidebarSelectCategoryAPI:
    """SidebarWidget.select_category() 공개 API 검증."""

    def test_sidebar_has_select_category(self):
        """SidebarWidget에 select_category 메서드가 있다."""
        from app.widgets.sidebar import SidebarWidget
        assert hasattr(SidebarWidget, "select_category")
        assert callable(SidebarWidget.select_category)
