"""Sidebar 카테고리 라벨 + 키 + tooltip 회귀 테스트.

이번 sidebar semantic refactor 의 invariant 을 lock 한다:
- 9개 카테고리 키 — task spec 순서 (all → work_target → unregistered → failed →
  other → no_metadata → inbox → managed → missing)
- ``warning`` 키는 제거됨
- 새 라벨 3건 (작업 대상 / 메타데이터 미등록 / 기타 파일) + 기존 라벨 보존
- 모든 카테고리에 tooltip 이 설정됨
- 기존 회귀 테스트 (``test_sidebar_missing_category.py``) 호환을 위해
  missing 라벨 (``⚠ 누락 파일``) 은 보존
- 모든 라벨은 한국어 (영어 알파벳 미포함)
"""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6", reason="PyQt6 필요")


EXPECTED_KEYS_IN_ORDER: list[str] = [
    "all", "work_target", "unregistered", "failed", "other",
    "no_metadata", "inbox", "managed", "missing",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# CATEGORIES key invariant
# ---------------------------------------------------------------------------

class TestCategoryKeysSemanticOrder:
    def test_nine_keys_in_spec_order(self):
        from app.widgets.sidebar import CATEGORIES
        keys = [k for k, _ in CATEGORIES]
        assert keys == EXPECTED_KEYS_IN_ORDER

    def test_total_count_is_nine(self):
        from app.widgets.sidebar import CATEGORIES
        assert len(CATEGORIES) == 9

    def test_no_duplicate_keys(self):
        from app.widgets.sidebar import CATEGORIES
        keys = [k for k, _ in CATEGORIES]
        assert len(keys) == len(set(keys))

    def test_warning_key_removed(self):
        """``warning`` 키는 의미 분할 결과 제거되었다 — work_target / other 로 흡수."""
        from app.widgets.sidebar import CATEGORIES
        keys = [k for k, _ in CATEGORIES]
        assert "warning" not in keys


# ---------------------------------------------------------------------------
# Label semantics
# ---------------------------------------------------------------------------

class TestLabels:
    def test_new_semantic_labels(self):
        from app.widgets.sidebar import CATEGORIES
        label_map = dict(CATEGORIES)
        assert label_map["work_target"] == "작업 대상"
        assert label_map["unregistered"] == "메타데이터 미등록"
        assert label_map["other"] == "기타 파일"

    def test_preserved_labels(self):
        """all / inbox / managed / failed / no_metadata / missing 라벨은 보존."""
        from app.widgets.sidebar import CATEGORIES
        label_map = dict(CATEGORIES)
        assert label_map["all"] == "전체 파일"
        assert label_map["inbox"] == "수신함"
        assert label_map["managed"] == "관리 중"
        assert label_map["failed"] == "등록 실패"
        assert label_map["no_metadata"] == "재시도 큐"
        # missing 은 기존 ⚠ prefix 보존 — 회귀 테스트 호환
        assert label_map["missing"] == "⚠ 누락 파일"

    def test_no_english_in_user_facing_labels(self):
        """visible 라벨에 영어 알파벳이 섞이지 않는다."""
        from app.widgets.sidebar import CATEGORIES
        for key, label in CATEGORIES:
            for ch in label:
                assert not (ch.isalpha() and ch.isascii()), (
                    f"카테고리 {key!r} 라벨에 영어 알파벳: {label!r}"
                )


# ---------------------------------------------------------------------------
# Tooltip 모든 카테고리 보유
# ---------------------------------------------------------------------------

class TestTooltipsForAllCategories:
    def test_every_category_has_tooltip_in_constant(self):
        from app.widgets.sidebar import CATEGORIES, _CATEGORY_TOOLTIPS
        for key, _ in CATEGORIES:
            assert key in _CATEGORY_TOOLTIPS, f"카테고리 {key!r} 에 tooltip 누락"
            assert _CATEGORY_TOOLTIPS[key].strip(), (
                f"카테고리 {key!r} tooltip 이 빈 문자열"
            )

    def test_no_orphan_tooltips(self):
        """tooltip dict 에 sidebar 가 모르는 키가 남아있지 않아야 한다."""
        from app.widgets.sidebar import CATEGORIES, _CATEGORY_TOOLTIPS
        sidebar_keys = {k for k, _ in CATEGORIES}
        extra = set(_CATEGORY_TOOLTIPS.keys()) - sidebar_keys
        assert not extra, f"tooltip dict 에 unknown 키: {extra}"

    def test_tooltips_rendered_to_widget_items(self, qapp):
        from PyQt6.QtCore import Qt
        from app.widgets.sidebar import SidebarWidget
        s = SidebarWidget()
        for i in range(s._list.count()):
            item = s._list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            tooltip = item.toolTip()
            assert tooltip, f"sidebar item {key!r} 에 tooltip 없음"


# ---------------------------------------------------------------------------
# Widget-level rendering — 새 라벨이 실제 표시되는지
# ---------------------------------------------------------------------------

class TestWidgetRendersNewLabels:
    def test_widget_items_use_new_labels(self, qapp):
        from PyQt6.QtCore import Qt
        from app.widgets.sidebar import SidebarWidget
        s = SidebarWidget()
        text_by_key: dict[str, str] = {}
        for i in range(s._list.count()):
            item = s._list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            text_by_key[key] = item.text()
        # update_counts 호출 전 — 라벨 그대로 표시
        assert text_by_key["work_target"] == "작업 대상"
        assert text_by_key["unregistered"] == "메타데이터 미등록"
        assert text_by_key["other"] == "기타 파일"
        assert text_by_key["failed"] == "등록 실패"
        assert text_by_key["no_metadata"] == "재시도 큐"
        assert text_by_key["all"] == "전체 파일"
        assert text_by_key["missing"] == "⚠ 누락 파일"

    def test_update_counts_appends_count_to_new_labels(self, qapp):
        from PyQt6.QtCore import Qt
        from app.widgets.sidebar import SidebarWidget
        s = SidebarWidget()
        s.update_counts({
            "all": 100, "work_target": 30, "unregistered": 8, "failed": 1,
            "other": 4, "no_metadata": 2, "inbox": 5, "managed": 3,
            "missing": 4,
        })
        text_by_key: dict[str, str] = {}
        for i in range(s._list.count()):
            item = s._list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            text_by_key[key] = item.text()
        # 새 라벨 + 카운트 형식 그대로
        assert text_by_key["work_target"] == "작업 대상  (30)"
        assert text_by_key["unregistered"] == "메타데이터 미등록  (8)"
        assert text_by_key["other"] == "기타 파일  (4)"
        assert text_by_key["failed"] == "등록 실패  (1)"
        assert text_by_key["no_metadata"] == "재시도 큐  (2)"
        assert text_by_key["missing"] == "⚠ 누락 파일  (4)"


# ---------------------------------------------------------------------------
# Behavior invariant — sidebar 의 동작 / category_selected emit 등 미변경
# ---------------------------------------------------------------------------

class TestSidebarBehaviorUnchanged:
    def test_select_category_emits_signal_with_key(self, qapp):
        from app.widgets.sidebar import SidebarWidget
        captured: list[str] = []
        s = SidebarWidget()
        s.category_selected.connect(lambda k: captured.append(k))
        s.select_category("work_target")
        assert "work_target" in captured

    def test_current_category_returns_key_not_label(self, qapp):
        from app.widgets.sidebar import SidebarWidget
        s = SidebarWidget()
        s.select_category("failed")
        # current_category 는 항상 key 반환 (라벨 아님)
        assert s.current_category() == "failed"

    def test_select_unknown_category_is_noop(self, qapp):
        """``warning`` 같이 제거된 키를 선택해도 예외 없이 무시되어야 한다."""
        from app.widgets.sidebar import SidebarWidget
        s = SidebarWidget()
        s.select_category("warning")  # 제거된 키
        # current_category 는 변경되지 않음 (초기 setCurrentRow(0) 이후 'all')
        assert s.current_category() == "all"
