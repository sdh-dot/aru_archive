"""
Step 7 Preview 필터 + 확인 필요 강조 회귀 테스트.

PyQt6 전용. PySide6 사용 금지.

검증 항목:
- _is_preview_item_needs_review helper 판정 로직
- _is_preview_item_manual_override helper 판정 로직
- 필터 ComboBox 존재 및 기본값 "all"
- 필터 "needs_review" 적용 시 정상 row가 숨겨짐 (setRowHidden)
- 필터 "manual_override" 적용 시 비-override row가 숨겨짐
- 필터 적용 후에도 _preview_items dict mapping 유지
- 상태 컬럼(6번) 텍스트 확인
- Wizard Step 수 9 유지
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QComboBox

from app.views.workflow_wizard_view import (
    _is_preview_item_manual_override,
    _is_preview_item_needs_review,
)
from db.database import initialize_database


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "filter_test.db")


@pytest.fixture
def conn_factory(db_path):
    def factory():
        return initialize_database(db_path)
    return factory


@pytest.fixture
def wizard(qapp, conn_factory):
    from app.views.workflow_wizard_view import WorkflowWizardView
    config = {
        "data_dir": "", "inbox_dir": "", "classified_dir": "/Classified",
        "managed_dir": "", "db": {"path": ""},
    }
    w = WorkflowWizardView(conn_factory, config, "config.json")
    yield w
    w.close()


@pytest.fixture
def step7(wizard):
    from app.views.workflow_wizard_view import _Step7Preview
    for panel in wizard._panels:
        if isinstance(panel, _Step7Preview):
            return panel
    pytest.fail("_Step7Preview 패널을 찾을 수 없음")


# ---------------------------------------------------------------------------
# preview item 공장 함수
# ---------------------------------------------------------------------------

def _make_normal_item(group_id: str = "gid-normal-001") -> dict:
    """정상 분류 완료 preview item."""
    return {
        "group_id": group_id,
        "artwork_title": "정상 작품",
        "source_path": f"/tmp/{group_id}.jpg",
        "destinations": [
            {
                "rule_type": "series_character",
                "dest_path": f"/Classified/BySeries/BA/Arona/{group_id}.jpg",
                "conflict": "none",
                "will_copy": True,
                "used_fallback": False,
            }
        ],
        "classification_info": None,
    }


def _make_needs_review_series_missing_char(group_id: str = "gid-nr-001") -> dict:
    """시리즈 감지, 캐릭터 없음 → 확인 필요."""
    return {
        "group_id": group_id,
        "artwork_title": "시리즈만 있는 작품",
        "source_path": f"/tmp/{group_id}.jpg",
        "destinations": [
            {
                "rule_type": "series_uncategorized",
                "dest_path": f"/Classified/BySeries/BA/_uncategorized/{group_id}.jpg",
                "conflict": "none",
                "will_copy": True,
                "used_fallback": False,
            }
        ],
        "classification_info": {
            "classification_reason": "series_detected_but_character_missing",
            "missing_parts": ["character"],
        },
    }


def _make_needs_review_all_missing(group_id: str = "gid-nr-002") -> dict:
    """시리즈/캐릭터 모두 없음 → 확인 필요."""
    return {
        "group_id": group_id,
        "artwork_title": "폴백 작품",
        "source_path": f"/tmp/{group_id}.jpg",
        "destinations": [
            {
                "rule_type": "author_fallback",
                "dest_path": f"/Classified/ByAuthor/artist/{group_id}.jpg",
                "conflict": "none",
                "will_copy": True,
                "used_fallback": False,
            }
        ],
        "classification_info": {
            "classification_reason": "series_and_character_missing",
            "missing_parts": ["series", "character"],
        },
    }


def _make_needs_review_used_fallback(group_id: str = "gid-nr-003") -> dict:
    """used_fallback=True → 확인 필요."""
    return {
        "group_id": group_id,
        "artwork_title": "표시명 fallback 작품",
        "source_path": f"/tmp/{group_id}.jpg",
        "destinations": [
            {
                "rule_type": "series_character",
                "dest_path": f"/Classified/BySeries/SomeSeries/SomeChar/{group_id}.jpg",
                "conflict": "none",
                "will_copy": True,
                "used_fallback": True,
                "series_canonical": "SomeSeries",
                "series_display": "SomeSeries",  # canonical == display → fallback
            }
        ],
        "classification_info": None,
    }


def _make_manual_override_item(group_id: str = "gid-mo-001") -> dict:
    """manual override 적용된 preview item."""
    return {
        "group_id": group_id,
        "artwork_title": "수동 보정 작품",
        "source_path": f"/tmp/{group_id}.jpg",
        "destinations": [
            {
                "rule_type": "manual_override",
                "dest_path": f"/Classified/BySeries/BlueArchive/Arona/{group_id}.jpg",
                "conflict": "none",
                "will_copy": True,
                "used_fallback": False,
                "override_note": "manual_override",
                "series_canonical": "Blue Archive",
                "character_canonical": "アロナ",
            }
        ],
        "classification_info": None,
    }


# ---------------------------------------------------------------------------
# TestNeedsReviewHelper
# ---------------------------------------------------------------------------

class TestNeedsReviewHelper:
    def test_series_detected_but_character_missing_is_needs_review(self):
        item = _make_needs_review_series_missing_char()
        assert _is_preview_item_needs_review(item) is True

    def test_series_and_character_missing_is_needs_review(self):
        item = _make_needs_review_all_missing()
        assert _is_preview_item_needs_review(item) is True

    def test_used_fallback_dest_is_needs_review(self):
        item = _make_needs_review_used_fallback()
        assert _is_preview_item_needs_review(item) is True

    def test_normal_item_is_not_needs_review(self):
        item = _make_normal_item()
        assert _is_preview_item_needs_review(item) is False

    def test_manual_override_item_without_fallback_is_not_needs_review(self):
        """override 적용 후 정상 분류 → needs_review 아님."""
        item = _make_manual_override_item()
        assert _is_preview_item_needs_review(item) is False

    def test_empty_destinations_no_fallback_is_not_needs_review(self):
        item = {"group_id": "g", "destinations": [], "classification_info": None}
        assert _is_preview_item_needs_review(item) is False

    def test_classification_info_none_no_fallback_is_not_needs_review(self):
        item = _make_normal_item()
        item["classification_info"] = None
        assert _is_preview_item_needs_review(item) is False


# ---------------------------------------------------------------------------
# TestManualOverrideHelper
# ---------------------------------------------------------------------------

class TestManualOverrideHelper:
    def test_override_note_marker_detected(self):
        item = _make_manual_override_item()
        assert _is_preview_item_manual_override(item) is True

    def test_rule_type_manual_override_detected(self):
        """override_note 없어도 rule_type 만으로도 감지."""
        item = {
            "group_id": "g",
            "destinations": [
                {"rule_type": "manual_override", "override_note": None, "will_copy": True}
            ],
            "classification_info": None,
        }
        assert _is_preview_item_manual_override(item) is True

    def test_no_override_marker_returns_false(self):
        item = _make_normal_item()
        assert _is_preview_item_manual_override(item) is False

    def test_needs_review_item_is_not_manual_override(self):
        item = _make_needs_review_all_missing()
        assert _is_preview_item_manual_override(item) is False

    def test_empty_destinations_returns_false(self):
        item = {"group_id": "g", "destinations": [], "classification_info": None}
        assert _is_preview_item_manual_override(item) is False


# ---------------------------------------------------------------------------
# TestStep7FilterUI
# ---------------------------------------------------------------------------

class TestStep7FilterUI:
    def test_filter_combo_exists(self, step7):
        """_filter_combo 속성이 QComboBox여야 한다."""
        assert hasattr(step7, "_filter_combo"), "_filter_combo 없음"
        assert isinstance(step7._filter_combo, QComboBox)

    def test_filter_combo_has_three_options(self, step7):
        assert step7._filter_combo.count() == 3

    def test_filter_default_is_all(self, step7):
        assert step7._filter_combo.currentData() == "all"

    def test_filter_mode_default_is_all(self, step7):
        assert step7._filter_mode == "all"

    def test_filter_combo_option_labels(self, step7):
        labels = [step7._filter_combo.itemText(i) for i in range(step7._filter_combo.count())]
        assert "전체" in labels
        assert "확인 필요" in labels
        assert "수동 보정됨" in labels

    def test_filter_combo_option_data(self, step7):
        data_values = [step7._filter_combo.itemData(i) for i in range(step7._filter_combo.count())]
        assert "all" in data_values
        assert "needs_review" in data_values
        assert "manual_override" in data_values


# ---------------------------------------------------------------------------
# TestFilterApply
# ---------------------------------------------------------------------------

class TestFilterApply:
    def _populate(self, step7):
        """normal + needs_review + manual_override 각 1개씩 채운다."""
        previews = [
            _make_normal_item("gid-n"),
            _make_needs_review_all_missing("gid-nr"),
            _make_manual_override_item("gid-mo"),
        ]
        step7._populate_preview_table(previews)
        return previews

    def test_filter_all_shows_all_rows(self, step7):
        self._populate(step7)
        step7._apply_filter("all")
        visible = sum(
            0 if step7._preview_table.isRowHidden(r) else 1
            for r in range(step7._preview_table.rowCount())
        )
        assert visible == 3

    def test_filter_needs_review_shows_only_review_rows(self, step7):
        self._populate(step7)
        step7._apply_filter("needs_review")
        hidden_count = sum(
            1 if step7._preview_table.isRowHidden(r) else 0
            for r in range(step7._preview_table.rowCount())
        )
        # normal(1) + manual_override(1) = 2개 숨겨져야 함
        assert hidden_count == 2

    def test_filter_manual_override_shows_only_override_rows(self, step7):
        self._populate(step7)
        step7._apply_filter("manual_override")
        hidden_count = sum(
            1 if step7._preview_table.isRowHidden(r) else 0
            for r in range(step7._preview_table.rowCount())
        )
        # normal(1) + needs_review(1) = 2개 숨겨져야 함
        assert hidden_count == 2

    def test_filter_needs_review_visible_row_is_needs_review_item(self, step7):
        """needs_review 필터 후 보이는 row의 group_id는 needs_review item이어야 한다."""
        self._populate(step7)
        step7._apply_filter("needs_review")
        visible_group_ids = []
        for r in range(step7._preview_table.rowCount()):
            if not step7._preview_table.isRowHidden(r):
                group_id = step7._preview_rows[r].get("group_id", "")
                visible_group_ids.append(group_id)
        assert visible_group_ids == ["gid-nr"]

    def test_filter_combo_change_updates_filter_mode(self, step7):
        """ComboBox 변경 시 _filter_mode가 갱신되어야 한다."""
        self._populate(step7)
        idx = step7._filter_combo.findData("needs_review")
        step7._filter_combo.setCurrentIndex(idx)
        assert step7._filter_mode == "needs_review"

        idx_all = step7._filter_combo.findData("all")
        step7._filter_combo.setCurrentIndex(idx_all)
        assert step7._filter_mode == "all"


# ---------------------------------------------------------------------------
# TestFilterMappingSafety
# ---------------------------------------------------------------------------

class TestFilterMappingSafety:
    def _populate(self, step7):
        previews = [
            _make_normal_item("gid-safety-n"),
            _make_needs_review_all_missing("gid-safety-nr"),
            _make_manual_override_item("gid-safety-mo"),
        ]
        step7._populate_preview_table(previews)
        return previews

    def test_filter_does_not_alter_preview_items_dict(self, step7):
        """필터 적용 후에도 _preview_items의 key set이 변하지 않아야 한다."""
        self._populate(step7)
        keys_before = set(step7._preview_items.keys())

        step7._apply_filter("needs_review")
        keys_after = set(step7._preview_items.keys())

        assert keys_before == keys_after

    def test_filter_does_not_alter_preview_rows_list(self, step7):
        """필터 적용 후에도 _preview_rows의 길이와 내용이 변하지 않아야 한다."""
        self._populate(step7)
        rows_before = list(step7._preview_rows)

        step7._apply_filter("manual_override")
        rows_after = list(step7._preview_rows)

        assert rows_before == rows_after

    def test_hidden_row_group_id_still_accessible_via_preview_rows(self, step7):
        """숨겨진 row의 group_id도 _preview_rows로 접근 가능해야 한다."""
        self._populate(step7)
        step7._apply_filter("needs_review")

        # normal item은 숨겨져 있어야 함
        hidden_rows = [
            r for r in range(step7._preview_table.rowCount())
            if step7._preview_table.isRowHidden(r)
        ]
        assert len(hidden_rows) >= 1
        for r in hidden_rows:
            group_id = step7._preview_rows[r].get("group_id", "")
            assert group_id in step7._preview_items, (
                f"hidden row {r} group_id={group_id} not in _preview_items"
            )

    def test_filter_reverts_to_all_shows_all_rows(self, step7):
        """'확인 필요' 필터 적용 후 '전체'로 되돌리면 모든 row가 표시되어야 한다."""
        self._populate(step7)
        step7._apply_filter("needs_review")
        step7._apply_filter("all")
        visible = sum(
            0 if step7._preview_table.isRowHidden(r) else 1
            for r in range(step7._preview_table.rowCount())
        )
        assert visible == 3


# ---------------------------------------------------------------------------
# TestStatusColumn
# ---------------------------------------------------------------------------

class TestStatusColumn:
    def _populate(self, step7):
        previews = [
            _make_normal_item("gid-st-n"),
            _make_needs_review_all_missing("gid-st-nr"),
            _make_manual_override_item("gid-st-mo"),
        ]
        step7._populate_preview_table(previews)
        # row 순서: 0=normal, 1=needs_review, 2=manual_override
        return previews

    def _status_cell(self, step7, row: int):
        it = step7._preview_table.item(row, 6)
        return it.text() if it else None

    def test_table_has_seven_columns(self, step7):
        assert step7._preview_table.columnCount() == 7

    def test_status_header_label(self, step7):
        header = step7._preview_table.horizontalHeaderItem(6)
        assert header is not None
        assert header.text() == "상태"

    def test_normal_row_status_is_empty(self, step7):
        self._populate(step7)
        assert self._status_cell(step7, 0) == ""

    def test_needs_review_row_status_text(self, step7):
        self._populate(step7)
        assert self._status_cell(step7, 1) == "확인 필요"

    def test_manual_override_row_status_text(self, step7):
        self._populate(step7)
        assert self._status_cell(step7, 2) == "수동 보정"

    def test_needs_review_row_status_tooltip(self, step7):
        self._populate(step7)
        it = step7._preview_table.item(1, 6)
        assert it is not None
        assert it.toolTip() != ""

    def test_manual_override_row_status_tooltip(self, step7):
        self._populate(step7)
        it = step7._preview_table.item(2, 6)
        assert it is not None
        assert "사용자 지정" in it.toolTip()

    def test_refresh_after_override_updates_status_column(self, step7):
        """override 적용 후 _refresh_preview_rows_for_group이 상태 컬럼을 갱신해야 한다."""
        previews = [_make_needs_review_all_missing("gid-refresh")]
        step7._populate_preview_table(previews)

        # override 적용된 item으로 갱신
        updated = _make_manual_override_item("gid-refresh")
        step7._preview_items["gid-refresh"] = updated
        step7._refresh_preview_rows_for_group("gid-refresh", updated)

        it = step7._preview_table.item(0, 6)
        assert it is not None
        assert it.text() == "수동 보정"


# ---------------------------------------------------------------------------
# TestPanelStructure
# ---------------------------------------------------------------------------

class TestPanelStructure:
    def test_wizard_still_has_nine_panels(self, wizard):
        assert wizard._stack.count() == 9

    def test_step7_has_filter_combo_attribute(self, step7):
        assert hasattr(step7, "_filter_combo")

    def test_step7_has_filter_mode_attribute(self, step7):
        assert hasattr(step7, "_filter_mode")
