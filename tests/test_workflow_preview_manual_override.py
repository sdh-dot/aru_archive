"""
Step 7 Preview — 수동 분류 지정(manual override) smoke 테스트.

PyQt6 전용. PySide6 사용 금지.

검증 항목:
- _Step7Preview에 컨텍스트 메뉴 정책이 설정되어 있음
- _preview_rows에 group_id가 포함됨
- _open_manual_override_dialog가 group_id 없는 row에서 조기 반환
- ManualClassifyOverrideDialog OK 시 set_override_for_group + apply_override_to_preview_item 호출
- override 적용 후 테이블 셀이 갱신됨 (rule_type = "manual_override")
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from db.database import initialize_database


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "override_test.db")


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
    """_Step7Preview 패널 반환."""
    from app.views.workflow_wizard_view import _Step7Preview
    for panel in wizard._panels:
        if isinstance(panel, _Step7Preview):
            return panel
    pytest.fail("_Step7Preview 패널을 찾을 수 없음")


# ---------------------------------------------------------------------------
# 1. 컨텍스트 메뉴 정책 확인
# ---------------------------------------------------------------------------

def test_preview_table_has_custom_context_menu_policy(step7):
    """_preview_table에 CustomContextMenu 정책이 설정되어야 한다."""
    assert (
        step7._preview_table.contextMenuPolicy()
        == Qt.ContextMenuPolicy.CustomContextMenu
    ), "CustomContextMenu 정책이 설정되어 있지 않음"


# ---------------------------------------------------------------------------
# 2. _preview_rows에 group_id 포함 여부
# ---------------------------------------------------------------------------

def _make_fake_preview(group_id: str, source_path: str = "/tmp/test.jpg") -> dict:
    return {
        "group_id":     group_id,
        "artwork_title": "테스트 작품",
        "source_path":  source_path,
        "destinations": [
            {
                "rule_type":  "author_fallback",
                "dest_path":  f"/Classified/ByAuthor/artist/{source_path.split('/')[-1]}",
                "conflict":   "none",
                "will_copy":  True,
                "used_fallback": False,
            }
        ],
        "classification_info": {
            "classification_reason": "series_and_character_missing",
        },
    }


def test_preview_rows_contain_group_id(step7):
    """_populate_preview_table 후 _preview_rows에 group_id가 포함되어야 한다."""
    fake = _make_fake_preview("group-abc-001")
    step7._populate_preview_table([fake])

    assert len(step7._preview_rows) >= 1
    assert step7._preview_rows[0].get("group_id") == "group-abc-001"


# ---------------------------------------------------------------------------
# 3. _preview_items에 group_id 인덱싱 확인
# ---------------------------------------------------------------------------

def test_preview_items_indexed_by_group_id(step7):
    """_populate_preview_table 후 _preview_items에 group_id가 key로 들어가야 한다."""
    fake = _make_fake_preview("group-xyz-002")
    step7._populate_preview_table([fake])

    assert "group-xyz-002" in step7._preview_items
    assert step7._preview_items["group-xyz-002"]["artwork_title"] == "테스트 작품"


# ---------------------------------------------------------------------------
# 4. group_id 없는 row에서 _open_manual_override_dialog 조기 반환
# ---------------------------------------------------------------------------

def test_open_override_dialog_noop_when_no_group_id(step7):
    """
    _preview_rows에 group_id가 없으면 dialog를 열지 않고 조기 반환해야 한다.
    예외 없이 반환되면 통과.
    """
    # group_id 없는 row 직접 삽입
    step7._preview_rows.clear()
    step7._preview_rows.append({"source_path": "/tmp/x.jpg"})  # group_id 없음

    # 예외 없이 조기 반환되는지 확인
    try:
        step7._open_manual_override_dialog(0)
    except Exception as exc:
        pytest.fail(f"예외 발생: {exc}")


# ---------------------------------------------------------------------------
# 5. _refresh_preview_rows_for_group — 테이블 셀 갱신
# ---------------------------------------------------------------------------

def test_refresh_preview_rows_updates_rule_type_cell(step7):
    """
    override 적용 후 _refresh_preview_rows_for_group을 호출하면
    테이블의 rule_type 컬럼이 "manual_override"로 갱신되어야 한다.
    """
    group_id = "group-refresh-003"
    fake = _make_fake_preview(group_id, "/tmp/refresh.jpg")
    step7._populate_preview_table([fake])

    # override 적용된 preview item 구성 (rule_type = manual_override)
    updated_item = {
        "group_id":      group_id,
        "artwork_title": "테스트 작품",
        "source_path":   "/tmp/refresh.jpg",
        "destinations":  [
            {
                "rule_type":           "manual_override",
                "dest_path":           "/Classified/BySeries/BlueArchive/Mari/refresh.jpg",
                "conflict":            "none",
                "will_copy":           True,
                "used_fallback":       False,
                "override_note":       "manual_override",
                "series_canonical":    "Blue Archive",
                "character_canonical": "伊落マリー",
            }
        ],
    }

    step7._refresh_preview_rows_for_group(group_id, updated_item)

    # rule_type 컬럼(3번)이 갱신되었는지 확인
    row_idx = None
    for i, rd in enumerate(step7._preview_rows):
        if rd.get("group_id") == group_id:
            row_idx = i
            break
    assert row_idx is not None

    rule_item = step7._preview_table.item(row_idx, 3)
    assert rule_item is not None
    assert rule_item.text() == "manual_override", (
        f"Expected 'manual_override', got '{rule_item.text()}'"
    )
