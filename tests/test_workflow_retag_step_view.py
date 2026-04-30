"""
_Step6Retag UI 테스트.

1. 결과 그리드에 8개 컬럼(파일명/제목/이전 시리즈/이전 캐릭터/새 시리즈/새 캐릭터/상태/비고)이 있어야 한다.
2. _populate_result_grid 호출 시 전달된 데이터가 테이블에 표시된다.
3. 결과가 없으면 empty state 레이블이 보이고 그리드는 숨겨진다.
4. _RetagThread의 done 시그널 타입이 list(int 아님)이어야 한다.
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_wizard(tmp_path):
    """_StepPanel이 요구하는 최소 wizard 인터페이스를 가진 mock 객체."""
    from db.database import initialize_database

    db_path = str(tmp_path / "aru.db")
    conn = initialize_database(db_path)
    conn.close()

    config = {
        "classified_dir": str(tmp_path / "Classified"),
        "classification": {"folder_locale": "ko"},
    }

    class _MockWizard:
        _config = config

        def _conn_factory(self):
            return initialize_database(db_path)

        def _db_path(self):
            return db_path

    return _MockWizard()


@pytest.fixture()
def step6(qapp, tmp_path):
    from app.views.workflow_wizard_view import _Step6Retag
    wizard = _make_wizard(tmp_path)
    step = _Step6Retag(wizard)
    step.show()
    return step


class TestStep6RetagGridColumns:
    def test_result_grid_has_eight_columns(self, step6):
        assert step6._result_grid.columnCount() == 8

    def test_column_headers(self, step6):
        headers = [
            step6._result_grid.horizontalHeaderItem(i).text()
            for i in range(step6._result_grid.columnCount())
        ]
        assert headers[0] == "파일명"
        assert headers[1] == "제목"
        assert headers[2] == "이전 시리즈"
        assert headers[3] == "이전 캐릭터"
        assert headers[4] == "새 시리즈"
        assert headers[5] == "새 캐릭터"
        assert headers[6] == "상태"
        assert headers[7] == "비고"

    def test_empty_state_visible_initially(self, step6):
        step6._populate_result_grid([])
        assert step6._empty_lbl.isVisible()
        assert not step6._result_grid.isVisible()

    def test_results_populate_grid_and_hide_empty_label(self, step6):
        results = [
            {
                "group_id": "aaa",
                "filename": "foo.jpg",
                "title": "Test Art",
                "before_series": "Blue Archive",
                "before_character": "キサキ",
                "after_series": "Blue Archive",
                "after_character": "키사키",
                "changed": True,
                "status": "변경됨",
                "note": "",
            }
        ]
        step6._populate_result_grid(results)
        assert step6._result_grid.isVisible()
        assert not step6._empty_lbl.isVisible()
        assert step6._result_grid.rowCount() == 1
        assert step6._result_grid.item(0, 0).text() == "foo.jpg"
        assert step6._result_grid.item(0, 1).text() == "Test Art"
        assert step6._result_grid.item(0, 6).text() == "변경됨"

    def test_summary_labels_updated(self, step6):
        results = [
            {"filename": "a.jpg", "title": "A", "before_series": "X", "before_character": "Y",
             "after_series": "X", "after_character": "Z", "changed": True, "status": "변경됨", "note": ""},
            {"filename": "b.jpg", "title": "B", "before_series": "", "before_character": "",
             "after_series": "", "after_character": "", "changed": False, "status": "변경 없음", "note": ""},
            {"filename": "c.jpg", "title": "C", "before_series": "", "before_character": "",
             "after_series": "", "after_character": "", "changed": False, "status": "오류", "note": "DB err"},
        ]
        step6._populate_result_grid(results)
        assert "3" in step6._lbl_total.text()
        assert "1" in step6._lbl_failed.text()
        assert "1" in step6._lbl_changed.text()

    def test_has_retag_and_refresh_buttons(self, step6):
        assert hasattr(step6, "_btn_retag")
        assert hasattr(step6, "_btn_refresh")


class TestRetagThreadSignalType:
    def test_done_signal_emits_list(self, qapp):
        """_RetagThread.done 시그널이 Signal(list)로 선언됐어야 한다."""
        import inspect
        from app.views.workflow_wizard_view import _RetagThread
        src = inspect.getsource(_RetagThread)
        assert "Signal(list)" in src, "_RetagThread.done이 Signal(list)여야 함"
