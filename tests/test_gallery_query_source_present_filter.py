"""Gallery present filter source-inspection 회귀 테스트.

_GALLERY_BASE / _GALLERY_WHERE / _COUNT_SQL의 형태가 정책에 맞는지 잠근다.
"""
from __future__ import annotations
import inspect
import pytest


class TestGalleryBaseHasPresentFilter:
    def test_gallery_base_contains_file_status_present(self):
        from app.main_window import _GALLERY_BASE
        assert "file_status = 'present'" in _GALLERY_BASE
        assert "EXISTS" in _GALLERY_BASE

    def test_gallery_base_filters_at_group_level(self):
        from app.main_window import _GALLERY_BASE
        # WHERE가 base 끝부분에 존재해야 함
        assert "FROM artwork_groups g" in _GALLERY_BASE
        assert "WHERE EXISTS" in _GALLERY_BASE


class TestGalleryWhereUsesAnd:
    def test_gallery_where_entries_use_and_or_empty(self):
        from app.main_window import _GALLERY_WHERE
        for cat, where in _GALLERY_WHERE.items():
            if where == "":
                continue
            # WHERE 단어 시작 금지, AND로 시작해야 함
            stripped = where.strip()
            assert stripped.startswith("AND "), (
                f"_GALLERY_WHERE['{cat}'] must start with AND or be empty, "
                f"got: {where!r}"
            )


class TestCountSqlAppliesPresentFragment:
    def test_count_sql_entries_reference_present_filter(self):
        from app.main_window import _COUNT_SQL, _PRESENT_EXISTS_FRAGMENT
        # 모든 카운터에 fragment가 포함되어야 함
        for cat, sql in _COUNT_SQL.items():
            assert (
                _PRESENT_EXISTS_FRAGMENT in sql
                or "file_status = 'present'" in sql
            ), f"_COUNT_SQL['{cat}'] missing present filter"


class TestRefreshGalleryItemUsesAndClause:
    def test_refresh_gallery_item_uses_and_group_id(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._refresh_gallery_item)
        assert "AND g.group_id = ?" in src

    def test_refresh_gallery_item_does_not_use_where_group_id(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow._refresh_gallery_item)
        assert "WHERE g.group_id = ?" not in src


class TestPresentFragmentDefinition:
    def test_present_fragment_is_module_level(self):
        from app import main_window
        assert hasattr(main_window, "_PRESENT_EXISTS_FRAGMENT")
        frag = main_window._PRESENT_EXISTS_FRAGMENT
        assert "EXISTS" in frag
        assert "file_status = 'present'" in frag
