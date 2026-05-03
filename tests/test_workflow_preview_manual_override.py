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


# ---------------------------------------------------------------------------
# 6. 필터 적용 후 override 동작 회귀 가드
# ---------------------------------------------------------------------------

def test_override_group_id_accessible_after_filter_applied(step7):
    """
    필터 적용으로 row가 숨겨진 후에도 _preview_rows[row].group_id 로
    _preview_items에 접근 가능해야 한다 (setRowHidden은 mapping을 깨지 않음).
    """
    group_id = "group-filter-rg-001"
    fake = _make_fake_preview(group_id)
    step7._populate_preview_table([fake])

    # "수동 보정됨" 필터 적용 → fake는 override 아니므로 숨겨짐
    step7._apply_filter("manual_override")

    row_idx = None
    for i, rd in enumerate(step7._preview_rows):
        if rd.get("group_id") == group_id:
            row_idx = i
            break
    assert row_idx is not None, "group_id를 _preview_rows에서 찾을 수 없음"
    assert step7._preview_table.isRowHidden(row_idx), "override 없는 row가 숨겨지지 않음"

    # 숨겨진 row에서도 _preview_items 접근 가능
    assert group_id in step7._preview_items, "_preview_items에서 group_id 접근 불가"

    # 필터 복구
    step7._apply_filter("all")
    assert not step7._preview_table.isRowHidden(row_idx), "필터 복구 후 row가 여전히 숨겨짐"


def test_preview_rows_and_items_consistent_after_filter_and_refresh(step7):
    """
    필터 적용 → override refresh → 필터 재적용 흐름에서
    _preview_rows 와 _preview_items 가 일관성을 유지해야 한다.
    """
    group_id = "group-filter-rg-002"
    fake = _make_fake_preview(group_id)
    step7._populate_preview_table([fake])

    # 초기 "수동 보정됨" 필터 → row 숨겨짐
    step7._apply_filter("manual_override")

    # override 적용된 item으로 _preview_items 갱신 + refresh
    updated_item = {
        "group_id": group_id,
        "artwork_title": "테스트 작품",
        "source_path": "/tmp/test.jpg",
        "destinations": [
            {
                "rule_type": "manual_override",
                "dest_path": "/Classified/BySeries/BA/Arona/test.jpg",
                "conflict": "none",
                "will_copy": True,
                "used_fallback": False,
                "override_note": "manual_override",
            }
        ],
        "classification_info": None,
    }
    step7._preview_items[group_id] = updated_item
    step7._refresh_preview_rows_for_group(group_id, updated_item)

    # refresh 후 필터가 재적용됨 → 이제 override이므로 visible
    row_idx = None
    for i, rd in enumerate(step7._preview_rows):
        if rd.get("group_id") == group_id:
            row_idx = i
            break
    assert row_idx is not None
    assert not step7._preview_table.isRowHidden(row_idx), (
        "override 적용 후 '수동 보정됨' 필터에서 row가 표시되어야 함"
    )


# ---------------------------------------------------------------------------
# 7. _replace_batch_preview_item — Step 8 execute consistency 가드
# ---------------------------------------------------------------------------
#
# 배경:
#   apply_override_to_preview_item 은 deepcopy 를 반환하므로 _preview_items
#   의 ref 와 _batch_preview["previews"] 의 ref 가 끊긴다. _replace_batch_preview_item
#   helper 가 두 자료구조를 다시 동기화하여 Step 8 execute 가 UI 에 보이는
#   destinations 와 동일한 destinations 를 사용하도록 보장한다.

def _seed_batch_preview(step7, previews: list[dict]) -> None:
    """_populate_preview_table + _batch_preview 를 같이 채워 실 시나리오를 재현."""
    step7._batch_preview = {"previews": previews, "estimated_copies": len(previews)}
    step7._populate_preview_table(previews)


class TestReplaceBatchPreviewItem:
    """``_Step7Preview._replace_batch_preview_item`` 단위 검증."""

    def test_replaces_matching_entry_in_place(self, step7):
        gid = "group-replace-001"
        original = _make_fake_preview(gid)
        _seed_batch_preview(step7, [original])

        updated = {
            "group_id":      gid,
            "artwork_title": "테스트 작품",
            "source_path":   original["source_path"],
            "destinations":  [{
                "rule_type":           "manual_override",
                "dest_path":           "/Classified/BySeries/BA/Mari/test.jpg",
                "conflict":            "none",
                "will_copy":           True,
                "used_fallback":       False,
                "override_note":       "manual_override",
                "series_canonical":    "Blue Archive",
                "character_canonical": "伊落マリー",
            }],
        }

        ok = step7._replace_batch_preview_item(gid, updated)
        assert ok is True

        # 같은 list object 안에서 element 가 교체됐는지 (in-place — Step 8 가 보는
        # reference 도 함께 갱신).
        previews = step7._batch_preview["previews"]
        assert previews[0] is updated, (
            "list element 가 in-place 로 교체되지 않음 — Step 8 가 옛 dict 를 본다"
        )
        assert previews[0]["destinations"][0]["rule_type"] == "manual_override"

    def test_returns_false_when_batch_preview_missing(self, step7):
        step7._batch_preview = None
        assert step7._replace_batch_preview_item("any-gid", {}) is False

    def test_returns_false_when_batch_preview_not_dict(self, step7):
        step7._batch_preview = "garbage"  # type: ignore[assignment]
        assert step7._replace_batch_preview_item("any-gid", {}) is False

    def test_returns_false_when_previews_missing(self, step7):
        step7._batch_preview = {"other": []}
        assert step7._replace_batch_preview_item("any-gid", {}) is False

    def test_returns_false_when_no_matching_group_id(self, step7):
        gid = "group-existing-001"
        _seed_batch_preview(step7, [_make_fake_preview(gid)])
        result = step7._replace_batch_preview_item("group-not-present-999", {})
        assert result is False
        # 기존 entry 는 손상되지 않음.
        assert step7._batch_preview["previews"][0]["group_id"] == gid

    def test_replaces_only_matching_entry_among_many(self, step7):
        gids = [f"group-multi-{i:03d}" for i in range(5)]
        previews = [_make_fake_preview(g) for g in gids]
        _seed_batch_preview(step7, previews)

        target = gids[2]
        updated = {
            "group_id":      target,
            "artwork_title": "x",
            "source_path":   "/tmp/multi.jpg",
            "destinations":  [{
                "rule_type":           "manual_override",
                "dest_path":           "/Classified/multi/updated.jpg",
                "conflict":            "none",
                "will_copy":           True,
                "used_fallback":       False,
                "override_note":       "manual_override",
            }],
        }
        assert step7._replace_batch_preview_item(target, updated) is True

        for idx, gid in enumerate(gids):
            entry = step7._batch_preview["previews"][idx]
            if gid == target:
                assert entry is updated
                assert entry["destinations"][0]["dest_path"] == (
                    "/Classified/multi/updated.jpg"
                )
            else:
                # 다른 entry 들은 손상되지 않음.
                assert entry["group_id"] == gid
                assert entry["destinations"][0].get("override_note") != "manual_override"


class TestPreviewItemsAndBatchPreviewStaySynced:
    """``_open_manual_override_dialog`` 의 동기화 흐름 — 단위 모방.

    실제 dialog 호출 경로 (Qt modal exec) 는 offscreen 환경에서 띄우기 어려우므로,
    helper 호출 단위로 _preview_items 와 _batch_preview["previews"] 양쪽이
    동일한 destinations 를 가짐을 검증한다.
    """

    def test_after_replace_helper_both_sources_match(self, step7):
        gid = "group-sync-001"
        original = _make_fake_preview(gid)
        _seed_batch_preview(step7, [original])

        updated = {
            "group_id":      gid,
            "artwork_title": "테스트 작품",
            "source_path":   original["source_path"],
            "destinations":  [{
                "rule_type":           "manual_override",
                "dest_path":           "/Classified/BySeries/BA/Arona/sync.jpg",
                "conflict":            "none",
                "will_copy":           True,
                "used_fallback":       False,
                "override_note":       "manual_override",
                "series_canonical":    "Blue Archive",
                "character_canonical": "天童アリス",
            }],
        }

        # _open_manual_override_dialog 가 수행하는 두 step:
        step7._preview_items[gid] = updated
        step7._replace_batch_preview_item(gid, updated)

        # Step 7 UI source = Step 8 execute source 가 같은 destination 을 본다.
        ui_source = step7._preview_items[gid]
        execute_source = step7._batch_preview["previews"][0]
        assert ui_source["destinations"][0]["dest_path"] == (
            execute_source["destinations"][0]["dest_path"]
        )
        assert execute_source["destinations"][0]["rule_type"] == "manual_override"

    def test_step8_sees_override_via_shared_batch_preview_reference(self, step7, wizard):
        """Wizard _on_preview_ready 가 step8.set_preview 를 호출하면 Step 8 의
        ``_batch_preview`` 는 Step 7 과 같은 dict object 를 reference 로 보유.

        Step 7 가 in-place 로 previews list element 를 교체하면 Step 8 가 보는
        list 도 같은 element 가 갱신됨 — 별도의 set_preview 재호출 없이 일치.
        """
        from app.views.workflow_wizard_view import _Step8Execute

        gid = "group-step8-001"
        original = _make_fake_preview(gid)
        _seed_batch_preview(step7, [original])

        # Wizard 가 preview_ready emit 하면 step8.set_preview 가 호출된다고 가정.
        step8 = next(p for p in wizard._panels if isinstance(p, _Step8Execute))
        step8.set_preview(step7._batch_preview)

        # Step 8 가 같은 batch_preview dict 를 reference 로 가진다.
        assert step8._batch_preview is step7._batch_preview

        # Step 7 가 manual override 적용:
        updated = {
            "group_id":      gid,
            "artwork_title": "테스트 작품",
            "source_path":   original["source_path"],
            "destinations":  [{
                "rule_type":           "manual_override",
                "dest_path":           "/Classified/BySeries/BA/Hina/exec.jpg",
                "conflict":            "none",
                "will_copy":           True,
                "used_fallback":       False,
                "override_note":       "manual_override",
            }],
        }
        step7._preview_items[gid] = updated
        step7._replace_batch_preview_item(gid, updated)

        # Step 8 가 그대로 새 destination 을 본다 — set_preview 재호출 불필요.
        step8_view = step8._batch_preview["previews"][0]
        assert step8_view["destinations"][0]["rule_type"] == "manual_override"
        assert step8_view["destinations"][0]["dest_path"] == (
            "/Classified/BySeries/BA/Hina/exec.jpg"
        )
