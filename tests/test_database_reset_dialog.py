"""
tests/test_database_reset_dialog.py

DatabaseResetConfirmDialog smoke tests — PyQt6 offscreen.
"""
from __future__ import annotations

import os
import sys

import pytest

# PyQt6 offscreen은 환경 변수로 설정 (conftest 또는 fixture에 없을 경우 직접 설정)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    instance = QApplication.instance() or QApplication(sys.argv[:1])
    return instance


def test_dialog_cancel_returns_rejected(app):
    """취소 버튼 클릭(reject)은 Rejected 코드를 반환해야 한다."""
    from PyQt6.QtWidgets import QDialog, QDialogButtonBox

    from app.views.database_reset_confirm_dialog import DatabaseResetConfirmDialog

    dlg = DatabaseResetConfirmDialog(
        db_path="/tmp/test.db",
        backup_path="/tmp/test_before_reset_20250502_120000.db",
    )
    # 취소 버튼으로 reject 호출
    cancel_btn = dlg._btn_box.button(QDialogButtonBox.StandardButton.Cancel)
    assert cancel_btn is not None
    cancel_btn.click()
    assert dlg.result() == QDialog.DialogCode.Rejected


def test_dialog_invalid_confirmation_keeps_ok_disabled(app):
    """잘못된 확인 문구 입력 시 OK 버튼이 비활성 상태를 유지해야 한다."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from app.views.database_reset_confirm_dialog import (
        CONFIRM_PHRASE,
        DatabaseResetConfirmDialog,
    )

    dlg = DatabaseResetConfirmDialog(
        db_path="/tmp/test.db",
        backup_path="/tmp/test_before_reset_20250502_120000.db",
    )
    ok_btn = dlg._btn_box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None

    for bad_input in ["", "전체", "초기화", "reset", CONFIRM_PHRASE + " "]:
        dlg._confirm_edit.setText(bad_input)
        assert not ok_btn.isEnabled(), f"OK should be disabled for input: {bad_input!r}"


def test_dialog_correct_confirmation_enables_ok(app):
    """정확한 확인 문구 입력 시 OK 버튼이 활성화되어야 한다."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from app.views.database_reset_confirm_dialog import (
        CONFIRM_PHRASE,
        DatabaseResetConfirmDialog,
    )

    dlg = DatabaseResetConfirmDialog(
        db_path="/tmp/test.db",
        backup_path="/tmp/test_before_reset_20250502_120000.db",
    )
    ok_btn = dlg._btn_box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None

    dlg._confirm_edit.setText(CONFIRM_PHRASE)
    assert ok_btn.isEnabled(), "OK button should be enabled for correct confirmation phrase"


def test_dialog_does_not_modify_db_directly(app, tmp_path):
    """dialog 인스턴스 생성 및 취소 시 DB 파일을 수정하지 않아야 한다."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from app.views.database_reset_confirm_dialog import DatabaseResetConfirmDialog

    db_file = tmp_path / "test.db"
    db_file.write_bytes(b"fake db content")
    mtime_before = db_file.stat().st_mtime

    dlg = DatabaseResetConfirmDialog(
        db_path=str(db_file),
        backup_path=str(tmp_path / "test_before_reset.db"),
    )
    cancel_btn = dlg._btn_box.button(QDialogButtonBox.StandardButton.Cancel)
    assert cancel_btn is not None
    cancel_btn.click()

    assert db_file.exists(), "DB file must not be deleted by dialog"
    assert db_file.stat().st_mtime == mtime_before, "DB file must not be modified by dialog"
    assert not (tmp_path / "test_before_reset.db").exists(), "Backup must not be created by dialog"
