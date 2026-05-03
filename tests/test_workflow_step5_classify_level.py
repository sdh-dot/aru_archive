"""Step 5 분류 기준 선택 패널 회귀 테스트."""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_wizard(tmp_path, classification_level="series_character"):
    from db.database import initialize_database
    from app.views.workflow_wizard_view import WorkflowWizardView
    import os

    db_path = str(tmp_path / "aru.db")
    conn = initialize_database(db_path)
    conn.close()

    config = {
        "data_dir": "",
        "inbox_dir": "",
        "classified_dir": "",
        "managed_dir": "",
        "db": {"path": db_path},
        "classification": {"classification_level": classification_level},
    }
    config_path = str(tmp_path / "config.json")
    w = WorkflowWizardView(
        lambda: initialize_database(db_path),
        config,
        config_path,
    )
    return w


@pytest.fixture
def wizard(qapp, tmp_path):
    w = _make_wizard(tmp_path)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# Step 5 패널 구조 테스트
# ---------------------------------------------------------------------------

class TestStep5ClassifyLevelPanel:
    def test_step5_class_is_classify_level(self, wizard):
        from app.views.workflow_wizard_view import _Step5ClassifyLevel
        step5 = wizard._panels[4]
        assert isinstance(step5, _Step5ClassifyLevel)

    def test_step5_has_three_radio_buttons(self, wizard):
        step5 = wizard._panels[4]
        assert hasattr(step5, "_radio_series_char")
        assert hasattr(step5, "_radio_series_only")
        assert hasattr(step5, "_radio_tag")

    def test_default_radio_is_series_character(self, wizard):
        step5 = wizard._panels[4]
        assert step5._radio_series_char.isChecked()
        assert not step5._radio_series_only.isChecked()

    def test_tag_radio_is_disabled(self, wizard):
        step5 = wizard._panels[4]
        assert not step5._radio_tag.isEnabled()

    def test_series_only_selection_updates_config(self, qapp, wizard):
        step5 = wizard._panels[4]
        step5._radio_series_only.setChecked(True)
        level = wizard._config.get("classification", {}).get("classification_level")
        assert level == "series_only"
        # 복원
        step5._radio_series_char.setChecked(True)

    def test_series_char_selection_updates_config(self, qapp, wizard):
        step5 = wizard._panels[4]
        step5._radio_series_only.setChecked(True)
        step5._radio_series_char.setChecked(True)
        level = wizard._config.get("classification", {}).get("classification_level")
        assert level == "series_character"

    def test_open_dict_tools_button_exists(self, wizard):
        from PyQt6.QtWidgets import QPushButton
        step5 = wizard._panels[4]
        # ObjectName으로 확인
        btn = step5.findChild(QPushButton, "btn_open_dict_tools")
        assert btn is not None

    def test_step5_label_is_classify_level_not_dict_normalization(self, wizard):
        # _STEPS 상수에 "분류 기준 선택"이 있어야 하고, "사전 정규화"가 없어야 한다
        from app.views.workflow_wizard_view import _STEPS
        step5_entry = _STEPS[4]
        title = step5_entry[2]  # (num, short, title)
        assert title == "분류 기준 선택"
        assert "사전 정규화" not in title

    def test_step5_title_in_wizard_header(self, wizard):
        wizard._go_to_step(4)
        assert "분류 기준 선택" in wizard._step_title.text()
        wizard._go_to_step(0)  # restore


class TestStep5DefaultWithSeriesOnly:
    def test_series_only_config_selects_series_only_radio(self, qapp, tmp_path):
        w = _make_wizard(tmp_path, classification_level="series_only")
        try:
            step5 = w._panels[4]
            assert step5._radio_series_only.isChecked()
            assert not step5._radio_series_char.isChecked()
        finally:
            w.close()


# ---------------------------------------------------------------------------
# Step 6 숨김 / 9 패널 구조 테스트
# ---------------------------------------------------------------------------

class TestStep6HiddenInWizard:
    def test_wizard_has_nine_panels_still(self, wizard):
        assert len(wizard._panels) == 9

    def test_stack_count_is_nine(self, wizard):
        assert wizard._stack.count() == 9

    def test_step6_panel_class_still_present(self, wizard):
        from app.views.workflow_wizard_view import _Step6Retag
        # 클래스 자체가 삭제되지 않았는지 확인 (import 성공 + 클래스 타입 검증)
        assert isinstance(_Step6Retag, type)

    def test_step6_is_sixth_panel(self, wizard):
        from app.views.workflow_wizard_view import _Step6Retag
        assert isinstance(wizard._panels[5], _Step6Retag)

    def test_step6_header_button_is_hidden(self, wizard):
        # 인덱스 5 (Step 6) 헤더 버튼은 숨겨져야 한다
        assert not wizard._step_btns[5].isVisible()

    def test_other_step_buttons_are_not_explicitly_hidden(self, wizard):
        # Step 6 (index 5) 외의 버튼은 명시적으로 숨겨지지 않아야 한다
        # (offscreen에서 show()가 안 된 상태라 isVisible()은 False일 수 있으므로
        #  isHidden()으로 명시적 숨김 여부만 확인)
        for i in range(9):
            if i != 5:
                assert not wizard._step_btns[i].isHidden(), f"Step {i+1} button should not be hidden"

    def test_next_from_step5_skips_step6(self, wizard):
        wizard._go_to_step(4)
        wizard._on_next()
        assert wizard._current == 6  # Step 7 (index 6)
        wizard._go_to_step(0)  # restore

    def test_prev_from_step7_skips_step6(self, wizard):
        wizard._go_to_step(6)
        wizard._on_prev()
        assert wizard._current == 4  # Step 5 (index 4)
        wizard._go_to_step(0)  # restore

    def test_direct_go_to_step6_redirects(self, wizard):
        """직접 Step 6으로 이동 시도 시 forward로 redirect된다."""
        wizard._go_to_step(0)
        wizard._go_to_step(5)  # hidden step
        assert wizard._current != 5  # 5로 머물지 않음


# ---------------------------------------------------------------------------
# Step 7 config override 테스트
# ---------------------------------------------------------------------------

class TestStep7AutoRetag:
    def test_step7_build_config_override_sets_retag_flag(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)
        cfg_override = step7._build_config_override()
        cls = cfg_override.get("classification", {})
        assert cls.get("retag_before_batch_preview") is True

    def test_step7_build_config_override_series_character_default(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        # default classification_level = series_character → 플래그 변경 없음
        cfg_override = step7._build_config_override()
        cls = cfg_override.get("classification", {})
        # series_character: enable_series_character는 기본값(True) 유지
        assert cls.get("enable_series_character", True) is True

    def test_apply_level_to_cfg_series_only_disables_character_flags(self):
        from app.views.workflow_wizard_view import _apply_level_to_cfg
        cfg = {
            "enable_series_character": True,
            "enable_series_uncategorized": True,
            "enable_character_without_series": True,
        }
        _apply_level_to_cfg("series_only", cfg)
        assert cfg["enable_series_character"] is False
        assert cfg["enable_series_uncategorized"] is True
        assert cfg["enable_character_without_series"] is False

    def test_apply_level_to_cfg_series_character_keeps_defaults(self):
        from app.views.workflow_wizard_view import _apply_level_to_cfg
        cfg = {"enable_series_character": True}
        _apply_level_to_cfg("series_character", cfg)
        assert cfg["enable_series_character"] is True

    def test_apply_level_to_cfg_tag_falls_back_to_series_character(self):
        from app.views.workflow_wizard_view import _apply_level_to_cfg
        cfg = {"enable_series_character": True, "enable_character_without_series": True}
        _apply_level_to_cfg("tag", cfg)
        # tag는 미구현 — 기존 값 유지 (변경 없음)
        assert cfg["enable_series_character"] is True
        assert cfg["enable_character_without_series"] is True

    def test_apply_level_to_cfg_series_only_applied_via_config(self, qapp, tmp_path):
        from app.views.workflow_wizard_view import _Step7Preview
        w = _make_wizard(tmp_path, classification_level="series_only")
        try:
            step7 = w._panels[6]
            cfg_override = step7._build_config_override()
            cls = cfg_override.get("classification", {})
            assert cls.get("enable_series_character") is False
            assert cls.get("enable_series_uncategorized") is True
        finally:
            w.close()


# ---------------------------------------------------------------------------
# Step 7 preview dirty state — Step 5 변경이 Step 7 의 stale 표시를 trigger
# ---------------------------------------------------------------------------

class TestStep7PreviewDirtyState:
    """Step 7 의 dirty state helper 와 stale notice label 동작.

    classification / destination / preview row schema 자체는 변경하지 않는다 —
    UI 안내 + dirty flag 만 lock.
    """

    def test_step7_starts_clean(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)
        assert step7.is_preview_dirty() is False
        assert step7._preview_dirty_reason is None
        assert step7._stale_notice_lbl.isVisible() is False

    def test_mark_preview_dirty_sets_reason_and_shows_label(self, wizard):
        step7 = wizard._panels[6]
        step7.mark_preview_dirty("분류 기준이 변경되었습니다.")
        assert step7.is_preview_dirty() is True
        assert step7._preview_dirty_reason == "분류 기준이 변경되었습니다."
        assert step7._stale_notice_lbl.text(), "stale notice text 가 비어 있음"
        assert "분류 기준" in step7._stale_notice_lbl.text()

    def test_mark_preview_dirty_empty_reason_uses_default(self, wizard):
        step7 = wizard._panels[6]
        step7.mark_preview_dirty("")
        assert step7.is_preview_dirty() is True
        # 기본 안내 사용 — 정확한 wording 은 변할 수 있으나 비어 있지 않음.
        assert step7._preview_dirty_reason
        assert step7._stale_notice_lbl.text()

    def test_clear_preview_dirty_resets_state(self, wizard):
        step7 = wizard._panels[6]
        step7.mark_preview_dirty("test reason")
        assert step7.is_preview_dirty() is True
        step7.clear_preview_dirty()
        assert step7.is_preview_dirty() is False
        assert step7._preview_dirty_reason is None
        assert step7._stale_notice_lbl.isVisible() is False
        assert step7._stale_notice_lbl.text() == ""

    def test_step5_level_change_marks_step7_dirty(self, wizard):
        """Step 5 의 분류 기준 라디오 변경 → Step 7 dirty 자동 설정."""
        step5 = wizard._panels[4]
        step7 = wizard._panels[6]

        step7.clear_preview_dirty()
        assert step7.is_preview_dirty() is False

        # series_character → series_only 전환.
        step5._radio_series_only.setChecked(True)

        assert step7.is_preview_dirty() is True
        assert step7._preview_dirty_reason
        assert "분류 기준" in step7._stale_notice_lbl.text()
        # 복원 — 이후 테스트 영향 방지.
        step5._radio_series_char.setChecked(True)

    def test_step5_round_trip_keeps_step7_dirty_until_preview(self, wizard):
        """series_only → series_character round-trip 도 dirty 누적, preview 재생성
        이전까지는 해제되지 않는다."""
        step5 = wizard._panels[4]
        step7 = wizard._panels[6]

        step7.clear_preview_dirty()
        step5._radio_series_only.setChecked(True)
        assert step7.is_preview_dirty() is True
        # round-trip 으로 다시 series_character — 여전히 dirty (분류 기준이 한 번
        # 변경된 것은 사실).
        step5._radio_series_char.setChecked(True)
        assert step7.is_preview_dirty() is True

    def test_on_preview_done_clears_dirty(self, wizard):
        """preview 재생성 성공 경로에서 dirty 가 해제된다."""
        step7 = wizard._panels[6]
        step7.mark_preview_dirty("분류 기준이 변경되었습니다.")
        assert step7.is_preview_dirty() is True

        # _on_preview_done 호출은 retag/loading mock 이 필요하므로 helper 만
        # 직접 simulate — clear_preview_dirty 가 호출 경로에 포함됨을 검증.
        step7._on_preview_done({
            "previews": [], "total_groups": 0, "estimated_copies": 0,
            "estimated_bytes": 0, "author_fallback_count": 0,
            "series_uncategorized_count": 0, "candidate_count": 0,
            "warnings": [], "folder_locale": "ko",
        })
        assert step7.is_preview_dirty() is False

    def test_dirty_state_does_not_disable_preview_button(self, wizard):
        """이번 PR 범위: execute 차단은 하지 않는다. preview 버튼 활성 상태도
        그대로 — dirty 표시는 정보성 안내."""
        step7 = wizard._panels[6]
        step7.mark_preview_dirty("test")
        # preview 버튼은 여전히 enabled. (실행 차단 정책은 별도 PR.)
        assert step7._btn_preview.isEnabled() is True

    def test_step7_existing_widgets_preserved(self, wizard):
        """기존 위젯 (preview table / scope / locale combo / preview button) 유지
        — UI 회귀 가드."""
        step7 = wizard._panels[6]
        from PyQt6.QtWidgets import QComboBox, QPushButton, QTableWidget
        assert isinstance(step7._preview_table, QTableWidget)
        assert isinstance(step7._scope_combo, QComboBox)
        assert isinstance(step7._locale_combo, QComboBox)
        assert isinstance(step7._btn_preview, QPushButton)
