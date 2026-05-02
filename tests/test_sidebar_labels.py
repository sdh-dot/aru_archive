"""Sidebar 카테고리 라벨 한국어 친화 정리 + tooltip 회귀 테스트.

이번 PR (label-only refactor) 의 핵심 invariant 을 lock 한다:
- category key 7개 모두 동일 (`all`/`inbox`/`managed`/`no_metadata`/`warning`/
  `failed`/`missing`)
- 라벨이 사용자 친화 한국어로 갱신됨 (`재시도 큐`/`주의 필요`/`등록 실패` 등)
- 모든 카테고리에 tooltip 이 설정됨
- 기존 회귀 테스트 (`test_sidebar_missing_category.py`) 가 그대로 통과하도록
  missing 라벨 (`⚠ 누락 파일`) 은 보존
"""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6", reason="PyQt6 필요")


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

class TestCategoryKeysUnchanged:
    def test_all_seven_keys_present(self):
        from app.widgets.sidebar import CATEGORIES
        keys = [k for k, _ in CATEGORIES]
        assert keys == [
            "all", "inbox", "managed", "no_metadata",
            "warning", "failed", "missing",
        ]

    def test_no_extra_keys_added(self):
        from app.widgets.sidebar import CATEGORIES
        assert len(CATEGORIES) == 7

    def test_no_duplicate_keys(self):
        from app.widgets.sidebar import CATEGORIES
        keys = [k for k, _ in CATEGORIES]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# Label refresh
# ---------------------------------------------------------------------------

class TestNewLabels:
    def test_no_metadata_label_renamed_to_retry_queue(self):
        from app.widgets.sidebar import CATEGORIES
        label_map = dict(CATEGORIES)
        assert label_map["no_metadata"] == "재시도 큐"

    def test_warning_label_renamed_to_caution(self):
        from app.widgets.sidebar import CATEGORIES
        label_map = dict(CATEGORIES)
        assert label_map["warning"] == "주의 필요"

    def test_failed_label_renamed_to_registration_failure(self):
        from app.widgets.sidebar import CATEGORIES
        label_map = dict(CATEGORIES)
        assert label_map["failed"] == "등록 실패"

    def test_unchanged_labels_preserved(self):
        """all / inbox / managed / missing 라벨은 변경되지 않는다."""
        from app.widgets.sidebar import CATEGORIES
        label_map = dict(CATEGORIES)
        assert label_map["all"] == "전체 파일"
        assert label_map["inbox"] == "수신함"
        assert label_map["managed"] == "관리 중"
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
        assert text_by_key["no_metadata"] == "재시도 큐"
        assert text_by_key["warning"] == "주의 필요"
        assert text_by_key["failed"] == "등록 실패"
        assert text_by_key["all"] == "전체 파일"
        assert text_by_key["missing"] == "⚠ 누락 파일"

    def test_update_counts_appends_count_to_new_labels(self, qapp):
        from PyQt6.QtCore import Qt
        from app.widgets.sidebar import SidebarWidget
        s = SidebarWidget()
        s.update_counts({
            "all": 100, "inbox": 5, "managed": 3,
            "no_metadata": 2, "warning": 7, "failed": 1, "missing": 4,
        })
        text_by_key: dict[str, str] = {}
        for i in range(s._list.count()):
            item = s._list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            text_by_key[key] = item.text()
        # 새 라벨 + 카운트 형식 그대로
        assert text_by_key["no_metadata"] == "재시도 큐  (2)"
        assert text_by_key["warning"] == "주의 필요  (7)"
        assert text_by_key["failed"] == "등록 실패  (1)"
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
        s.select_category("warning")
        assert "warning" in captured

    def test_current_category_returns_key_not_label(self, qapp):
        from app.widgets.sidebar import SidebarWidget
        s = SidebarWidget()
        s.select_category("failed")
        # current_category 는 항상 key 반환 (라벨 아님)
        assert s.current_category() == "failed"
