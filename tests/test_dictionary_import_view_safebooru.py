"""
DictionaryImportView Safebooru source GUI smoke test.

Safebooru source가 source combo에 존재하고,
staged safebooru 후보가 테이블에 표시되는지 확인한다.
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
def view(qt_app, tmp_path):
    from db.database import initialize_database, get_connection
    db_path = str(tmp_path / "view_safe_test.db")
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
    """view fixture와 같은 DB에 직접 접근하기 위한 conn."""
    from db.database import initialize_database
    db_path = str(tmp_path / "view_safe_test.db")
    c = initialize_database(db_path)
    yield c
    c.close()


class TestDictionaryImportViewSafebooruSource:
    def test_source_combo_contains_safebooru(self, view) -> None:
        items = [view._source_combo.itemText(i)
                 for i in range(view._source_combo.count())]
        assert any("Safebooru" in item or "safebooru" in item for item in items)

    def test_source_combo_still_contains_danbooru(self, view) -> None:
        items = [view._source_combo.itemText(i)
                 for i in range(view._source_combo.count())]
        assert any("Danbooru" in item or "danbooru" in item for item in items)

    def test_safebooru_data_value_selectable(self, view) -> None:
        """source combo에서 data='safebooru' 항목을 선택할 수 있어야 한다."""
        found = False
        for i in range(view._source_combo.count()):
            if view._source_combo.itemData(i) == "safebooru":
                view._source_combo.setCurrentIndex(i)
                found = True
                break
        assert found, "safebooru data value가 combo에 없음"
        assert view._source_combo.currentData() == "safebooru"

    def test_danbooru_data_value_selectable(self, view) -> None:
        for i in range(view._source_combo.count()):
            if view._source_combo.itemData(i) == "danbooru":
                view._source_combo.setCurrentIndex(i)
                break
        assert view._source_combo.currentData() == "danbooru"

    def test_fallback_checkbox_exists(self, view) -> None:
        assert hasattr(view, "_fallback_checkbox")

    def test_fallback_checkbox_unchecked_by_default(self, view) -> None:
        assert not view._fallback_checkbox.isChecked()


class TestDictionaryImportViewSafebooruTable:
    def test_load_staged_shows_safebooru_entry(self, view, view_conn) -> None:
        from core.external_dictionary import import_external_entries
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        import_external_entries(view_conn, [{
            "source":            "safebooru",
            "danbooru_tag":      "wakamo_(blue_archive)",
            "danbooru_category": "character",
            "canonical":         "Wakamo",
            "tag_type":          "character",
            "parent_series":     "Blue Archive",
            "alias":             "wakamo_(blue_archive)",
            "locale":            None,
            "display_name":      None,
            "confidence_score":  0.60,
            "evidence_json":     None,
            "imported_at":       now,
        }])
        view._load_staged()
        assert view._table.rowCount() == 1
        # 소스 컬럼(0)이 "safebooru"인지 확인
        source_item = view._table.item(0, 0)
        assert source_item is not None
        assert source_item.text() == "safebooru"

    def test_safebooru_and_danbooru_entries_both_visible(self, view, view_conn) -> None:
        from core.external_dictionary import import_external_entries
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        import_external_entries(view_conn, [
            {
                "source": "danbooru", "danbooru_tag": "aru_(blue_archive)",
                "danbooru_category": "character", "canonical": "Aru",
                "tag_type": "character", "parent_series": "Blue Archive",
                "alias": "aru_(blue_archive)", "locale": None, "display_name": None,
                "confidence_score": 0.75, "evidence_json": None, "imported_at": now,
            },
            {
                "source": "safebooru", "danbooru_tag": "shiroko_(blue_archive)",
                "danbooru_category": "character", "canonical": "Shiroko",
                "tag_type": "character", "parent_series": "Blue Archive",
                "alias": "shiroko_(blue_archive)", "locale": None, "display_name": None,
                "confidence_score": 0.60, "evidence_json": None, "imported_at": now,
            },
        ])
        view._load_staged()
        assert view._table.rowCount() == 2
        sources = {
            view._table.item(r, 0).text()
            for r in range(view._table.rowCount())
            if view._table.item(r, 0)
        }
        assert "danbooru" in sources
        assert "safebooru" in sources
