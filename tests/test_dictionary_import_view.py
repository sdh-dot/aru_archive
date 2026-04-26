"""
app/views/dictionary_import_view.py GUI smoke test.

PyQt6 QApplication이 필요하므로 pytest-qt 또는 QApplication 직접 생성.
"""
from __future__ import annotations

import sys

import pytest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_QT = True
except ImportError:
    _HAS_QT = False

pytestmark = pytest.mark.skipif(not _HAS_QT, reason="PyQt6 not available")


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


@pytest.fixture
def view(qt_app, tmp_path):
    from db.database import initialize_database, get_connection
    db_path = str(tmp_path / "view_test.db")
    # 스키마 초기화
    _init_conn = initialize_database(db_path)
    _init_conn.close()

    def factory():
        return get_connection(db_path)

    from app.views.dictionary_import_view import DictionaryImportView
    dlg = DictionaryImportView(factory)
    yield dlg
    dlg.close()


@pytest.fixture
def view_conn(tmp_path):
    """view fixture와 같은 DB를 직접 접근하기 위한 conn."""
    from db.database import initialize_database
    db_path = str(tmp_path / "view_test.db")
    c = initialize_database(db_path)
    yield c
    c.close()


class TestDictionaryImportViewCreation:
    def test_dialog_creates(self, view) -> None:
        assert view is not None

    def test_source_combo_exists(self, view) -> None:
        assert hasattr(view, "_source_combo")
        assert view._source_combo.count() >= 1

    def test_series_input_exists(self, view) -> None:
        assert hasattr(view, "_series_input")

    def test_query_input_exists(self, view) -> None:
        assert hasattr(view, "_query_input")

    def test_candidate_table_exists(self, view) -> None:
        assert hasattr(view, "_table")
        from PyQt6.QtWidgets import QTableWidget
        assert isinstance(view._table, QTableWidget)

    def test_table_has_correct_columns(self, view) -> None:
        assert view._table.columnCount() == 10

    def test_approve_button_exists(self, view) -> None:
        assert hasattr(view, "_btn_accept")

    def test_reject_button_exists(self, view) -> None:
        assert hasattr(view, "_btn_reject")

    def test_ignore_button_exists(self, view) -> None:
        assert hasattr(view, "_btn_ignore")

    def test_fetch_button_exists(self, view) -> None:
        assert hasattr(view, "_btn_fetch")

    def test_bulk_select_button_exists(self, view) -> None:
        assert hasattr(view, "_btn_bulk_select")

    def test_status_filter_exists(self, view) -> None:
        assert hasattr(view, "_status_filter")
        items = [view._status_filter.itemText(i)
                 for i in range(view._status_filter.count())]
        assert "staged" in items
        assert "accepted" in items

    def test_source_combo_contains_danbooru(self, view) -> None:
        items = [view._source_combo.itemText(i)
                 for i in range(view._source_combo.count())]
        assert any("Danbooru" in item or "danbooru" in item for item in items)

    def test_retag_checkbox_exists(self, view) -> None:
        assert hasattr(view, "_retag_checkbox")


class TestDictionaryImportViewLogic:
    def test_load_staged_with_no_data(self, view) -> None:
        view._load_staged()
        assert view._table.rowCount() == 0

    def test_load_staged_shows_entries(self, view, view_conn) -> None:
        from core.external_dictionary import import_external_entries
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        import_external_entries(view_conn, [{
            "source": "danbooru",
            "danbooru_tag": "wakamo_(blue_archive)",
            "danbooru_category": "character",
            "canonical": "Wakamo",
            "tag_type": "character",
            "parent_series": "Blue Archive",
            "alias": "ワカモ",
            "locale": None,
            "display_name": None,
            "confidence_score": 0.75,
            "evidence_json": None,
            "imported_at": now,
        }])
        view._load_staged()
        assert view._table.rowCount() == 1

    def test_fetch_without_series_shows_warning(self, view, qt_app) -> None:
        from PyQt6.QtWidgets import QMessageBox
        # series 입력 없이 fetch 시도
        view._series_input.setText("")
        # QMessageBox.warning이 호출되면 즉시 닫기
        import unittest.mock as mock
        with mock.patch.object(QMessageBox, "warning", return_value=None):
            view._on_fetch()
        # 스레드가 시작되지 않아야 함
        assert view._fetch_thread is None or not view._fetch_thread.isRunning()

    def test_bulk_select_selects_above_threshold(self, view, view_conn) -> None:
        from core.external_dictionary import import_external_entries
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        import_external_entries(view_conn, [
            {"source": "danbooru", "danbooru_tag": "a", "danbooru_category": "character",
             "canonical": "Low", "tag_type": "character", "parent_series": "BA",
             "alias": "low_tag", "locale": None, "display_name": None,
             "confidence_score": 0.3, "evidence_json": None, "imported_at": now},
            {"source": "danbooru", "danbooru_tag": "b", "danbooru_category": "character",
             "canonical": "High", "tag_type": "character", "parent_series": "BA",
             "alias": "high_tag", "locale": None, "display_name": None,
             "confidence_score": 0.9, "evidence_json": None, "imported_at": now},
        ])
        view._load_staged()
        view._bulk_threshold.setValue(0.85)
        view._on_bulk_select()
        selected = view._table.selectedItems()
        assert len(selected) > 0
        # 선택된 행의 confidence가 0.85 이상이어야 함
        selected_rows = {item.row() for item in selected}
        for r in selected_rows:
            conf_item = view._table.item(r, 8)
            if conf_item:
                assert float(conf_item.text()) >= 0.85
