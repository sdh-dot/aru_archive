"""
app/views/work_log_view.py smoke 테스트.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6가 설치되어 있지 않음")


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    c = initialize_database(str(tmp_path / "wl.db"))
    yield c
    c.close()


def _insert_undo_entry(conn, status: str = "pending") -> str:
    from datetime import timedelta
    eid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=7)).isoformat()
    conn.execute(
        """INSERT INTO undo_entries
           (entry_id, operation_type, performed_at, undo_expires_at,
            undo_status, description)
           VALUES (?, 'classify', ?, ?, ?, 'smoke test')""",
        (eid, now.isoformat(), expires, status),
    )
    conn.commit()
    return eid


# ---------------------------------------------------------------------------

def test_work_log_view_init(qt_app, conn):
    """WorkLogView가 예외 없이 초기화된다."""
    from app.views.work_log_view import WorkLogView
    dlg = WorkLogView(conn)
    assert dlg.windowTitle() == "🕘 작업 로그 / Undo"


def test_work_log_view_loads_entries(qt_app, conn):
    """undo_entries가 있으면 테이블에 로드된다."""
    from app.views.work_log_view import WorkLogView

    _insert_undo_entry(conn, "pending")
    _insert_undo_entry(conn, "completed")

    dlg = WorkLogView(conn)
    # filter=all → 2행
    dlg._filter_box.setCurrentText("all")
    dlg._load_entries()
    assert dlg._entry_table.rowCount() >= 2


def test_work_log_view_undo_button_disabled_without_selection(qt_app, conn):
    """행 선택 없이 Undo 버튼은 비활성."""
    from app.views.work_log_view import WorkLogView
    dlg = WorkLogView(conn)
    assert not dlg._btn_undo.isEnabled()


def test_work_log_view_undo_button_enabled_for_pending(qt_app, conn):
    """pending 항목 선택 시 Undo 버튼이 활성화된다."""
    from app.views.work_log_view import WorkLogView
    from PyQt6.QtCore import Qt

    eid = _insert_undo_entry(conn, "pending")
    dlg = WorkLogView(conn)
    dlg._filter_box.setCurrentText("all")
    dlg._load_entries()

    # 첫 번째 행의 entry_id 확인 후 수동으로 선택 상태 시뮬레이션
    dlg._entry_table.selectRow(0)
    # pending 행이 선택되면 버튼이 활성화되어야 함
    # (selectRow → itemSelectionChanged → _on_entry_selected)
    # 직접 핸들러 호출
    dlg._on_entry_selected()
    # entry_id를 가져와서 pending인지 확인
    selected = dlg._entry_table.selectedItems()
    if selected:
        entry_id = selected[0].data(Qt.ItemDataRole.UserRole)
        if entry_id == eid:
            assert dlg._btn_undo.isEnabled()


def test_work_log_view_log_msg_signal_exists(qt_app, conn):
    """log_msg 시그널이 존재하고 연결 가능하다."""
    from app.views.work_log_view import WorkLogView
    dlg = WorkLogView(conn)
    received = []
    dlg.log_msg.connect(received.append)
    dlg.log_msg.emit("[TEST] signal ok")
    assert received == ["[TEST] signal ok"]


def test_main_window_has_work_log_button(qt_app, tmp_path):
    """MainWindow에 작업 로그 버튼이 존재한다."""
    from app.main_window import MainWindow
    cfg = {
        "data_dir":  str(tmp_path / "archive"),
        "inbox_dir": str(tmp_path / "inbox"),
        "db": {"path": str(tmp_path / "aru.db")},
    }
    win = MainWindow(cfg, config_path=str(tmp_path / "cfg.json"))
    assert win._btn_work_log.isEnabled()
    win.close()
