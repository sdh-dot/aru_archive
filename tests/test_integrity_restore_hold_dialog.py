"""IntegrityRestoreHoldDialog smoke 테스트.

offscreen 모드에서 실행.
DB 변경 없음, 강제 복원 버튼 없음, 표시 항목 정확성을 검증한다.

PyQt6 전용. PySide6 사용 금지.
"""
from __future__ import annotations

import inspect
import os
import re
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "") == "",
    reason="QT_QPA_PLATFORM=offscreen 필요",
)

pytest.importorskip("PyQt6", reason="PyQt6 필요")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _module_source() -> str:
    """모듈 소스를 UTF-8로 직접 읽어 반환 (inspect.getsource의 Windows 인코딩 문제 우회)."""
    import app.views.integrity_restore_hold_dialog as mod
    with open(mod.__file__, encoding="utf-8") as f:
        return f.read()


def _sample_mismatch_items(n: int = 2) -> list[dict]:
    return [
        {
            "file_id": f"file-id-{i}",
            "group_id": f"group-{i}",
            "file_path": f"/managed/art_{i}.jpg",
            "file_role": "original",
            "db_hash": f"sha256:aabbcc{i:02d}...",
            "current_hash": f"sha256:ddeeff{i:02d}...",
        }
        for i in range(n)
    ]


class TestIntegrityRestoreHoldDialogImport:
    def test_module_imports_cleanly(self):
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog
        assert isinstance(IntegrityRestoreHoldDialog, type)

    def test_no_pyside6_import(self):
        raw = _module_source()
        # "from PySide6" 또는 "import PySide6" import 문만 금지 (주석 언급은 허용)
        assert not re.search(r"^(?:from|import)\s+PySide6", raw, re.MULTILINE)

    def test_no_db_operations_in_module(self):
        raw = _module_source()
        assert "sqlite3" not in raw
        assert "os.remove" not in raw
        assert ".unlink(" not in raw
        assert "shutil" not in raw


class TestIntegrityRestoreHoldDialogRender:
    def test_dialog_renders_with_empty_list(self, app):
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog
        dlg = IntegrityRestoreHoldDialog([])
        dlg.show()
        dlg.hide()

    def test_dialog_renders_with_items(self, app):
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog
        items = _sample_mismatch_items(3)
        dlg = IntegrityRestoreHoldDialog(items)
        dlg.show()
        dlg.hide()

    def test_dialog_title_contains_restore_hold(self, app):
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog
        dlg = IntegrityRestoreHoldDialog([])
        assert "복원 보류" in dlg.windowTitle()

    def test_dialog_notice_text_in_source(self):
        """안내 문구에 '복원 보류' 또는 '자동 복원을 보류' 키워드가 포함된다."""
        raw = _module_source()
        assert "복원 보류" in raw or "자동 복원을 보류" in raw


class TestIntegrityRestoreHoldDialogTableContents:
    def test_dialog_displays_provided_items(self, app):
        """제공된 mismatch dict 항목이 표에 모두 표시된다."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QTableWidget
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog

        items = _sample_mismatch_items(2)
        dlg = IntegrityRestoreHoldDialog(items)

        table = dlg.findChild(QTableWidget)
        assert table is not None
        assert table.rowCount() == 2

        # 첫 번째 행 — file_path
        path_item = table.item(0, 0)
        assert path_item is not None
        assert path_item.text() == items[0]["file_path"]

        # group_id
        group_item = table.item(0, 1)
        assert group_item is not None
        assert group_item.text() == items[0]["group_id"]

        # file_role
        role_item = table.item(0, 2)
        assert role_item is not None
        assert role_item.text() == items[0]["file_role"]

        # db_hash
        db_hash_item = table.item(0, 3)
        assert db_hash_item is not None
        assert db_hash_item.text() == items[0]["db_hash"]

        # current_hash
        cur_hash_item = table.item(0, 4)
        assert cur_hash_item is not None
        assert cur_hash_item.text() == items[0]["current_hash"]

    def test_file_id_stored_in_user_role(self, app):
        """file_id는 첫 컬럼의 UserRole에 저장되고 표시 텍스트에 없다."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QTableWidget
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog

        items = _sample_mismatch_items(1)
        dlg = IntegrityRestoreHoldDialog(items)

        table = dlg.findChild(QTableWidget)
        assert table is not None
        path_item = table.item(0, 0)
        assert path_item is not None

        stored_id = path_item.data(Qt.ItemDataRole.UserRole)
        assert stored_id == items[0]["file_id"]
        # 표시 텍스트에는 file_id가 없어야 함
        assert items[0]["file_id"] not in path_item.text()

    def test_empty_list_renders_zero_rows(self, app):
        from PyQt6.QtWidgets import QTableWidget
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog

        dlg = IntegrityRestoreHoldDialog([])
        table = dlg.findChild(QTableWidget)
        assert table is not None
        assert table.rowCount() == 0


class TestIntegrityRestoreHoldDialogSafety:
    def test_dialog_no_db_update_on_close(self, app):
        """dialog에 conn 인자가 없음 — DB를 직접 변경할 수 없다."""
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog
        sig = inspect.signature(IntegrityRestoreHoldDialog.__init__)
        param_names = list(sig.parameters.keys())
        assert "conn" not in param_names
        assert "db" not in param_names
        assert "session" not in param_names

    def test_dialog_no_force_restore_button(self, app):
        """강제 복원 버튼이 없다 — QDialogButtonBox에 Close 이외의 버튼이 없다."""
        from PyQt6.QtWidgets import QDialogButtonBox
        from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog

        dlg = IntegrityRestoreHoldDialog([])
        btn_box = dlg.findChild(QDialogButtonBox)
        assert btn_box is not None
        # StandardButtons에 Close만 있어야 한다 (Ok/Apply/Reset 등 없음)
        std = btn_box.standardButtons()
        assert std == QDialogButtonBox.StandardButton.Close

    def test_dialog_close_button_in_source(self):
        """닫기 버튼이 소스에 존재한다."""
        raw = _module_source()
        assert "닫기" in raw
