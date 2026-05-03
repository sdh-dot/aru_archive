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


# ---------------------------------------------------------------------------
# Step 8 execute — stale preview gate
# ---------------------------------------------------------------------------

class _FakeExecuteThread:
    """``_ExecuteThread`` 대체용 fake — 실제 thread 시작 / DB 쓰기 / 파일 복사
    없이 instantiation 만 추적한다."""

    instances: list["_FakeExecuteThread"] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        # Qt signals 자리에 dummy connectable 객체.
        self.log_msg = _FakeSignal()
        self.progress = _FakeSignal()
        self.done = _FakeSignal()
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True

    def isRunning(self) -> bool:  # noqa: N802 — Qt API name
        return False

    @classmethod
    def reset(cls) -> None:
        cls.instances = []


class _FakeSignal:
    """connect() 만 받는 dummy signal — 실제 emit 없음."""

    def connect(self, _slot) -> None:
        return None


class TestStep8DirtyPreviewGate:
    """Step 8 의 stale preview 확인 dialog 동작.

    실제 _ExecuteThread / 파일 복사는 monkeypatch 로 차단 — gate 통과 여부만
    검증한다. classification / destination / file copy 로직 자체는 변경되지
    않는다.
    """

    def _seed_step8_with_preview(self, wizard):
        """Step 8 에 비어있는 batch_preview 를 set 해 _on_execute 의 첫 가드를 통과
        시킨다 (실제 데이터는 필요 없음 — gate 만 테스트)."""
        step8 = wizard._panels[7]
        step8.set_preview({
            "previews": [], "estimated_copies": 0, "estimated_bytes": 0,
        })
        return step8

    @pytest.fixture(autouse=True)
    def _reset_fake_thread(self):
        _FakeExecuteThread.reset()
        yield
        _FakeExecuteThread.reset()

    @pytest.fixture
    def patched_execute(self, monkeypatch):
        """_ExecuteThread 와 두 번째 confirm 다이얼로그를 fake 로 대체.

        - _ExecuteThread → _FakeExecuteThread (started 추적용, 실제 thread 시작 X)
        - QMessageBox.question → 항상 Yes (downstream 분류 실행 확인 통과)
        """
        from PyQt6.QtWidgets import QMessageBox
        from app.views import workflow_wizard_view as mod

        monkeypatch.setattr(mod, "_ExecuteThread", _FakeExecuteThread)
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **k: QMessageBox.StandardButton.Yes,
        )
        return None

    def test_clean_preview_proceeds_to_thread(self, qapp, tmp_path, patched_execute):
        """Step 7 가 clean 이면 dirty gate 를 통과해 execute thread 가 시작됨."""
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            step8 = self._seed_step8_with_preview(w)
            step7.clear_preview_dirty()
            assert step7.is_preview_dirty() is False

            step8._on_execute()

            assert len(_FakeExecuteThread.instances) == 1, (
                "_ExecuteThread 가 시작되지 않음 — clean 상태에서 gate 가 잘못 차단"
            )
            assert _FakeExecuteThread.instances[0].started is True
        finally:
            w.close()

    def test_dirty_preview_cancel_does_not_start_thread(
        self, qapp, tmp_path, monkeypatch, patched_execute
    ):
        """dirty 상태 + 사용자 Cancel → execute thread 시작 안 됨."""
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            step8 = self._seed_step8_with_preview(w)
            step7.mark_preview_dirty("분류 기준이 변경되었습니다.")

            # Gate 가 False 반환 (사용자가 취소 누른 것과 동일 효과).
            monkeypatch.setattr(
                step8, "_confirm_proceed_with_dirty_preview", lambda: False
            )
            step8._on_execute()

            assert _FakeExecuteThread.instances == [], (
                "Cancel 했는데 _ExecuteThread 가 생성됨"
            )
            # dirty 유지.
            assert step7.is_preview_dirty() is True
        finally:
            w.close()

    def test_dirty_preview_proceed_starts_thread(
        self, qapp, tmp_path, monkeypatch, patched_execute
    ):
        """dirty 상태 + 사용자 '그래도 실행' → execute thread 시작."""
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            step8 = self._seed_step8_with_preview(w)
            step7.mark_preview_dirty("분류 기준이 변경되었습니다.")

            monkeypatch.setattr(
                step8, "_confirm_proceed_with_dirty_preview", lambda: True
            )
            step8._on_execute()

            assert len(_FakeExecuteThread.instances) == 1
            assert _FakeExecuteThread.instances[0].started is True
            # "그래도 실행" 했어도 dirty flag 는 유지 (preview 자체가 최신이 된
            # 것은 아님).
            assert step7.is_preview_dirty() is True
        finally:
            w.close()

    def test_dirty_flag_remains_after_cancel(
        self, qapp, tmp_path, monkeypatch, patched_execute
    ):
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            step8 = self._seed_step8_with_preview(w)
            reason = "round-trip dirty"
            step7.mark_preview_dirty(reason)
            monkeypatch.setattr(
                step8, "_confirm_proceed_with_dirty_preview", lambda: False
            )
            step8._on_execute()
            assert step7.is_preview_dirty() is True
            assert step7._preview_dirty_reason == reason
        finally:
            w.close()

    def test_dirty_flag_remains_after_confirm(
        self, qapp, tmp_path, monkeypatch, patched_execute
    ):
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            step8 = self._seed_step8_with_preview(w)
            reason = "user proceeded anyway"
            step7.mark_preview_dirty(reason)
            monkeypatch.setattr(
                step8, "_confirm_proceed_with_dirty_preview", lambda: True
            )
            step8._on_execute()
            assert step7.is_preview_dirty() is True
            assert step7._preview_dirty_reason == reason
        finally:
            w.close()

    def test_no_step7_panel_is_failsafe(
        self, qapp, tmp_path, monkeypatch, patched_execute
    ):
        """Step 7 instance 를 못 찾으면 기존 execute 동작 유지 (gate 무시)."""
        w = _make_wizard(tmp_path)
        try:
            step8 = self._seed_step8_with_preview(w)
            # _wizard._panels 에서 _Step7Preview 가 안 보이도록 panels 를 dummy 로
            # 교체.
            monkeypatch.setattr(w, "_panels", [])
            step8._on_execute()
            assert len(_FakeExecuteThread.instances) == 1, (
                "Step 7 부재 시 fail-safe 가 작동하지 않음 — 기존 execute 가 차단됨"
            )
        finally:
            w.close()

    def test_find_step7_helper_returns_panel(self, wizard):
        """_find_step7_preview helper 단위 검증 — 정상 케이스."""
        from app.views.workflow_wizard_view import _Step7Preview
        step8 = wizard._panels[7]
        result = step8._find_step7_preview()
        assert isinstance(result, _Step7Preview)

    def test_find_step7_helper_returns_none_when_panels_missing(
        self, wizard, monkeypatch
    ):
        step8 = wizard._panels[7]
        monkeypatch.setattr(wizard, "_panels", [])
        assert step8._find_step7_preview() is None

    def test_confirm_helper_returns_true_when_step7_clean(
        self, wizard, patched_execute
    ):
        """_confirm_proceed_with_dirty_preview 가 dirty=False 일 때 dialog 없이
        True 반환."""
        step7 = wizard._panels[6]
        step8 = wizard._panels[7]
        step7.clear_preview_dirty()
        # clean 이므로 dialog 없이 True (QMessageBox 호출 없음).
        assert step8._confirm_proceed_with_dirty_preview() is True

    def test_confirm_helper_returns_true_when_step7_missing(
        self, wizard, monkeypatch, patched_execute
    ):
        step8 = wizard._panels[7]
        monkeypatch.setattr(wizard, "_panels", [])
        assert step8._confirm_proceed_with_dirty_preview() is True
