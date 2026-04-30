"""
toolbar 그룹 메뉴 구조 테스트.

- 전역 삭제 버튼(_btn_delete_selected)이 툴바에 없음
- 작업 마법사는 독립 버튼으로 존재
- 그룹 메뉴 actions가 연결되어 있음
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication, QToolBar, QToolButton, QPushButton
import sys


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    return app


@pytest.fixture()
def main_window(qapp, tmp_path):
    config = {
        "data_dir": str(tmp_path),
        "inbox_dir": str(tmp_path / "Inbox"),
        "classified_dir": str(tmp_path / "Classified"),
        "managed_dir": str(tmp_path / "Managed"),
        "db": {"path": str(tmp_path / ".runtime" / "aru.db")},
        "duplicates": {"default_scope": "inbox_managed", "confirm_visual_scan": True,
                       "max_visual_files_per_run": 300},
        "classification": {"folder_locale": "ko"},
    }
    from app.main_window import MainWindow
    w = MainWindow(config, config_path=str(tmp_path / "config.json"))
    yield w
    w.close()


class TestToolbarStructure:
    def test_no_global_delete_button(self, main_window):
        """전역 삭제 버튼(_btn_delete_selected)이 툴바에 없어야 한다."""
        assert not hasattr(main_window, "_btn_delete_selected"), (
            "_btn_delete_selected 속성이 남아있음 — 전역 삭제 버튼 제거 필요"
        )

    def test_wizard_button_exists(self, main_window):
        """작업 마법사는 독립 QPushButton으로 존재해야 한다."""
        assert hasattr(main_window, "_btn_wizard")
        assert isinstance(main_window._btn_wizard, QPushButton)

    def test_grouped_menu_actions_exist(self, main_window):
        """그룹 메뉴의 핵심 actions가 존재해야 한다."""
        required_actions = [
            "_act_select_root",
            "_act_inbox_scan",
            "_act_exact_dup",
            "_act_visual_dup",
            "_act_xmp_sel",
            "_act_xmp_all",
            "_act_retag",
            "_act_batch_classify",
            "_act_work_log",
            "_act_db_init",
        ]
        for attr in required_actions:
            assert hasattr(main_window, attr), f"action 없음: {attr}"

    def test_toolbar_has_tool_buttons(self, main_window):
        """툴바에 QToolButton (드롭다운 메뉴용) 이 있어야 한다."""
        tb = main_window.findChild(QToolBar)
        assert tb is not None
        tool_btns = [w for w in tb.children() if isinstance(w, QToolButton)]
        assert len(tool_btns) > 0, "QToolButton이 툴바에 없음"

    def test_menu_actions_connected(self, main_window):
        """주요 action들이 연결(수신자 있음)되어 있어야 한다."""
        from PyQt6.QtGui import QAction
        act = main_window._act_inbox_scan
        assert isinstance(act, QAction)
        # triggered signal에 수신자가 있으면 연결된 것
        assert act.receivers(act.triggered) > 0, "_act_inbox_scan에 handler가 연결되지 않음"
