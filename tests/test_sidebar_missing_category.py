"""Sidebar "⚠ 누락 파일" 카테고리 smoke test.

실행:
  $env:QT_QPA_PLATFORM = "offscreen"
  pytest tests/test_sidebar_missing_category.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6가 설치되어 있지 않음")


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# sidebar.CATEGORIES
# ---------------------------------------------------------------------------

def test_missing_category_in_categories():
    """CATEGORIES 리스트에 missing 키와 올바른 레이블이 있어야 한다."""
    from app.widgets.sidebar import CATEGORIES
    keys = [k for k, _ in CATEGORIES]
    assert "missing" in keys, "CATEGORIES에 missing 키가 없습니다."
    label_map = dict(CATEGORIES)
    assert label_map["missing"] == "⚠ 누락 파일"


def test_existing_category_keys_unchanged():
    """기존 카테고리 key가 변경되지 않아야 한다."""
    from app.widgets.sidebar import CATEGORIES
    keys = [k for k, _ in CATEGORIES]
    for expected in ("all", "inbox", "managed", "no_metadata", "failed"):
        assert expected in keys, f"기존 key '{expected}'가 사라졌습니다."


# ---------------------------------------------------------------------------
# SidebarWidget — 위젯 초기화
# ---------------------------------------------------------------------------

def test_sidebar_missing_item_exists(qt_app):
    """SidebarWidget에 missing 카테고리 아이템이 렌더링되어야 한다."""
    from app.widgets.sidebar import SidebarWidget
    s = SidebarWidget()
    keys_in_widget = []
    from PyQt6.QtCore import Qt
    for i in range(s._list.count()):
        item = s._list.item(i)
        keys_in_widget.append(item.data(Qt.ItemDataRole.UserRole))
    assert "missing" in keys_in_widget


def test_sidebar_missing_item_has_tooltip(qt_app):
    """missing 아이템에 툴팁이 설정되어 있어야 한다."""
    from app.widgets.sidebar import SidebarWidget
    from PyQt6.QtCore import Qt
    s = SidebarWidget()
    for i in range(s._list.count()):
        item = s._list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == "missing":
            assert item.toolTip(), "missing 아이템에 툴팁이 없습니다."
            return
    pytest.fail("missing 아이템을 찾지 못했습니다.")


def test_sidebar_update_counts_with_missing(qt_app):
    """update_counts에 missing 키가 포함되어도 예외 없이 처리되어야 한다."""
    from app.widgets.sidebar import SidebarWidget
    s = SidebarWidget()
    s.update_counts({
        "all": 20, "inbox": 5, "managed": 3,
        "no_metadata": 2, "failed": 1,
        "missing": 4,
    })
    # missing 아이템 텍스트에 카운트가 반영되었는지 확인
    from PyQt6.QtCore import Qt
    for i in range(s._list.count()):
        item = s._list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == "missing":
            assert "4" in item.text(), f"카운트 미반영: {item.text()!r}"
            return
    pytest.fail("missing 아이템을 찾지 못했습니다.")


def test_sidebar_update_counts_missing_zero(qt_app):
    """counts에 missing 키가 없으면 0으로 표시되어야 한다 (예외 없음)."""
    from app.widgets.sidebar import SidebarWidget
    s = SidebarWidget()
    # missing 키를 counts에 포함하지 않음
    s.update_counts({"all": 10, "inbox": 5})
    from PyQt6.QtCore import Qt
    for i in range(s._list.count()):
        item = s._list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == "missing":
            assert "(0)" in item.text(), f"0 표시 누락: {item.text()!r}"
            return
    pytest.fail("missing 아이템을 찾지 못했습니다.")


# ---------------------------------------------------------------------------
# main_window 상수 — SQL fragment 검사
# ---------------------------------------------------------------------------

def test_missing_exists_fragment_defined():
    """_MISSING_EXISTS_FRAGMENT 상수가 정의되어 있어야 한다."""
    from app.main_window import _MISSING_EXISTS_FRAGMENT
    assert "file_status = 'missing'" in _MISSING_EXISTS_FRAGMENT


def test_gallery_missing_sql_defined():
    """_GALLERY_MISSING_SQL 이 present 조건 없이 missing 조건만 포함해야 한다."""
    from app.main_window import _GALLERY_MISSING_SQL
    assert "file_status = 'missing'" in _GALLERY_MISSING_SQL
    # present 필터가 섞이면 안 됨
    assert "file_status = 'present'" not in _GALLERY_MISSING_SQL


def test_count_sql_has_missing_key():
    """_COUNT_SQL에 missing 키가 있어야 한다."""
    from app.main_window import _COUNT_SQL
    assert "missing" in _COUNT_SQL
    assert "file_status = 'missing'" in _COUNT_SQL["missing"]
