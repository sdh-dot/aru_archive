"""
_Step7Preview 미리보기 그리드 컬럼 테스트.

1. 컬럼이 6개(파일/제목/분류대상/분류규칙/분류사유·비고/분류 경로)
2. 상단 kv_table(_tbl)이 없어야 한다
3. 분류 경로(col 5) 컬럼이 Stretch 모드
4. will_copy=True → "분류됨", False → "제외"
5. artwork_title이 제목 컬럼에 표시된다
6. 행마다 toolTip이 설정된다
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication, QHeaderView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_wizard(tmp_path):
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
def step7(qapp, tmp_path):
    from app.views.workflow_wizard_view import _Step7Preview
    wizard = _make_wizard(tmp_path)
    step = _Step7Preview(wizard)
    step.show()
    return step


def _make_preview(source_path="/inbox/art.jpg", title="Test Title",
                  will_copy=True, rule_type="series_character",
                  dest_path="/classified/Blue Archive/키사키/art.jpg") -> dict:
    return {
        "source_path": source_path,
        "artwork_title": title,
        "fallback_tags": [],
        "classification_info": None,
        "destinations": [
            {
                "will_copy": will_copy,
                "rule_type": rule_type,
                "dest_path": dest_path,
                "conflict": None,
                "used_fallback": False,
            }
        ],
    }


class TestStep7ColumnStructure:
    def test_six_columns(self, step7):
        assert step7._preview_table.columnCount() == 6

    def test_column_header_names(self, step7):
        headers = [
            step7._preview_table.horizontalHeaderItem(i).text()
            for i in range(6)
        ]
        assert headers[0] == "파일"
        assert headers[1] == "제목"
        assert headers[2] == "분류대상"
        assert headers[3] == "분류규칙"
        assert headers[4] == "분류사유·비고"
        assert headers[5] == "분류 경로"

    def test_last_column_stretch_mode(self, step7):
        hdr = step7._preview_table.horizontalHeader()
        mode = hdr.sectionResizeMode(5)
        assert mode == QHeaderView.ResizeMode.Stretch

    def test_no_kv_table_attribute(self, step7):
        """상단 kv_table(_tbl)이 제거됐어야 한다."""
        assert not hasattr(step7, "_tbl"), "_tbl(kv_table)이 아직 존재함 — 제거해야 함"


class TestStep7ColumnValues:
    def test_will_copy_true_shows_classified(self, step7):
        step7._populate_preview_table([_make_preview(will_copy=True)])
        assert step7._preview_table.item(0, 2).text() == "분류됨"

    def test_will_copy_false_shows_excluded(self, step7):
        step7._populate_preview_table([_make_preview(will_copy=False)])
        assert step7._preview_table.item(0, 2).text() == "제외"

    def test_artwork_title_in_column_1(self, step7):
        step7._populate_preview_table([_make_preview(title="키사키의 봄")])
        assert step7._preview_table.item(0, 1).text() == "키사키의 봄"

    def test_dest_path_in_column_5(self, step7):
        dest = "/classified/Blue Archive/키사키/art.jpg"
        step7._populate_preview_table([_make_preview(dest_path=dest)])
        assert step7._preview_table.item(0, 5).text() == dest

    def test_rule_type_in_column_3(self, step7):
        step7._populate_preview_table([_make_preview(rule_type="series_character")])
        assert step7._preview_table.item(0, 3).text() == "series_character"

    def test_row_tooltip_contains_path(self, step7):
        dest = "/classified/X/Y/art.jpg"
        step7._populate_preview_table([_make_preview(dest_path=dest)])
        tip = step7._preview_table.item(0, 5).toolTip()
        assert dest in tip

    def test_row_tooltip_contains_title(self, step7):
        step7._populate_preview_table([_make_preview(title="어떤 제목")])
        tip = step7._preview_table.item(0, 0).toolTip()
        assert "어떤 제목" in tip

    def test_preview_rows_tracked_per_row(self, step7):
        """_preview_rows가 테이블 행과 동기화되어야 한다."""
        step7._populate_preview_table([
            _make_preview(source_path="/inbox/a.jpg"),
            _make_preview(source_path="/inbox/b.jpg"),
        ])
        assert len(step7._preview_rows) == step7._preview_table.rowCount()
        assert step7._preview_rows[0]["source_path"] == "/inbox/a.jpg"
        assert step7._preview_rows[1]["source_path"] == "/inbox/b.jpg"
