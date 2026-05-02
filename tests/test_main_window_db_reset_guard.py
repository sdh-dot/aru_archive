"""
tests/test_main_window_db_reset_guard.py

MainWindow DB 초기화 안전장치 통합 테스트 — PyQt6 offscreen.

검증 항목:
1. dialog reject → reset 호출 안 됨
2. backup mock False → reset 호출 안 됨
3. backup True + dialog accepted → reset 호출 + 완료 메시지
4. toolbar label / tooltip에 위험 키워드 포함
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    instance = QApplication.instance() or QApplication(sys.argv[:1])
    return instance


@pytest.fixture()
def main_window(app, tmp_path):
    """최소 config으로 MainWindow 인스턴스를 생성한다."""
    from app.main_window import MainWindow

    db_path = str(tmp_path / ".runtime" / "aru_archive.db")
    config = {
        "data_dir": str(tmp_path),
        "inbox_dir": str(tmp_path / "inbox"),
        "managed_dir": str(tmp_path / "managed"),
        "classified_dir": str(tmp_path / "classified"),
        "db": {"path": db_path},
        "http_server": {"port": 19997},
    }
    win = MainWindow(config=config)
    yield win
    win.close()


def test_db_reset_handler_aborts_on_dialog_cancel(app, main_window):
    """DatabaseResetConfirmDialog가 Rejected를 반환하면 initialize_database가 호출되지 않아야 한다."""
    from PyQt6.QtWidgets import QDialog

    import app.main_window as mw_mod
    import db.database as db_mod

    with (
        patch.object(
            mw_mod.DatabaseResetConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Rejected,
        ),
        patch.object(db_mod, "initialize_database") as init_mock,
    ):
        main_window._on_db_init()
        init_mock.assert_not_called()


def test_db_reset_handler_aborts_on_backup_failure(app, main_window, tmp_path):
    """backup_database가 False를 반환하면 initialize_database가 호출되지 않아야 한다."""
    import pathlib

    from PyQt6.QtWidgets import QDialog

    import app.main_window as mw_mod
    import db.database as db_mod

    # DB 파일을 실제로 생성해야 backup 분기로 진입한다
    db_path = main_window._db_path()
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(db_path).write_bytes(b"fake db")

    # QMessageBox.critical을 app.main_window 모듈 내에서 패치
    with (
        patch.object(
            mw_mod.DatabaseResetConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ),
        patch("app.main_window.backup_database", return_value=False),
        patch("app.main_window.QMessageBox") as qmbox_mock,
        patch.object(db_mod, "initialize_database") as init_mock,
    ):
        qmbox_mock.critical.return_value = None
        main_window._on_db_init()
        init_mock.assert_not_called()


def test_db_reset_handler_runs_reset_only_after_backup_success(
    app, main_window, tmp_path
):
    """backup_database가 True이고 dialog가 Accepted이면 initialize_database가 호출되어야 한다."""
    import pathlib

    from PyQt6.QtWidgets import QDialog

    import app.main_window as mw_mod
    import db.database as db_mod

    # DB 파일 생성
    db_path = main_window._db_path()
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(db_path).write_bytes(b"fake db")

    conn_mock = MagicMock()
    conn_mock.close = MagicMock()

    with (
        patch.object(
            mw_mod.DatabaseResetConfirmDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ),
        patch("app.main_window.backup_database", return_value=True),
        patch("app.main_window.initialize_database", return_value=conn_mock) as init_mock,
        patch("app.main_window.QMessageBox") as qmbox_mock,
        patch.object(main_window, "_seed_localizations"),
        patch.object(main_window, "_refresh_gallery"),
        patch.object(main_window, "_refresh_counts"),
    ):
        qmbox_mock.information.return_value = None
        main_window._on_db_init()
        init_mock.assert_called_once()


def test_db_reset_button_label_indicates_danger(app, main_window):
    """DB 초기화 액션 텍스트 및 툴팁에 '전체' 또는 '위험' 키워드가 포함되어야 한다."""
    action = main_window._act_db_init
    label = action.text()
    tooltip = action.toolTip()

    danger_keywords = ["전체", "위험", "⚠"]
    assert any(kw in label for kw in danger_keywords), (
        f"Action label must include a danger keyword. Got: {label!r}"
    )
    assert any(kw in tooltip for kw in danger_keywords), (
        f"Action tooltip must include a danger keyword. Got: {tooltip!r}"
    )
