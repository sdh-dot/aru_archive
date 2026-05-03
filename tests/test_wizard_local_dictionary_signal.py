"""tests/test_wizard_local_dictionary_signal.py

Local Dictionary 변경 → Wizard Step 7 preview dirty 표시 신호 흐름 회귀 테스트.

검증 대상:
1. WorkflowWizardView.handle_local_dictionary_changed → Step 7 dirty mark
2. MainWindow.local_dictionary_changed signal 정의
3. dict-changing UI handler 들이 dialog 종료 후 emit
4. wizard 미연결 상태에서 emit 가 무해
5. 통합: emit → dirty → preview 재생성 → clear 사이클

Wizard 가 현재 ApplicationModal 이라 사용자 visible runtime 효과는 dormant
하지만, signal/slot 인프라 자체는 향후 wizard non-modal 화 또는 in-wizard
dict 편집 도입 시 자동 작동해야 한다 — 본 테스트는 그 인프라를 lock 한다.

테스트 정책:
- 실제 dict write 호출 / 실제 thread 시작 / 실제 파일 ops 모두 차단
- monkeypatch 로 dialog exec / TagCandidateView / DictionaryImportView 스텁
- 모두 offscreen Qt 환경에서 실행 가능
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog

from db.database import initialize_database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_wizard(tmp_path):
    """offscreen WorkflowWizardView 인스턴스 생성. 실제 DB 는 빈 상태."""
    from app.views.workflow_wizard_view import WorkflowWizardView

    db_path = str(tmp_path / "wizard.db")
    initialize_database(db_path).close()

    config = {
        "data_dir": "",
        "inbox_dir": "",
        "classified_dir": "",
        "managed_dir": "",
        "db": {"path": db_path},
        "classification": {"classification_level": "series_character"},
    }
    config_path = str(tmp_path / "config.json")
    return WorkflowWizardView(
        lambda: initialize_database(db_path),
        config,
        config_path,
    )


@pytest.fixture
def wizard(qapp, tmp_path):
    w = _make_wizard(tmp_path)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# 1. WorkflowWizardView.handle_local_dictionary_changed — 단위
# ---------------------------------------------------------------------------

class TestWizardHandleLocalDictionaryChanged:
    """Wizard 의 public slot 이 Step 7 preview dirty 를 정확히 trigger 하는지."""

    def test_wizard_has_handler_method(self, wizard):
        assert hasattr(wizard, "handle_local_dictionary_changed")
        assert callable(wizard.handle_local_dictionary_changed)

    def test_handle_local_dictionary_changed_marks_step7_dirty(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)
        # 초기 clean.
        step7.clear_preview_dirty()
        assert step7.is_preview_dirty() is False

        wizard.handle_local_dictionary_changed()

        assert step7.is_preview_dirty() is True
        # reason 에 "사용자 사전" 포함 — 사용자 안내 invariant.
        reason = step7._preview_dirty_reason
        assert reason is not None
        assert "사용자 사전" in reason, (
            f"dirty reason 에 '사용자 사전' 표기 누락: {reason!r}"
        )

    def test_handle_makes_stale_notice_label_visible(self, wizard):
        step7 = wizard._panels[6]
        step7.clear_preview_dirty()
        wizard.handle_local_dictionary_changed()
        assert step7._stale_notice_lbl.text(), "stale notice text 가 비어 있음"
        assert "사용자 사전" in step7._stale_notice_lbl.text()

    def test_handle_silently_no_op_when_step7_missing(self, qapp, tmp_path, monkeypatch):
        """Step 7 패널이 없는 비정상 상태에서도 예외를 던지지 않는다."""
        w = _make_wizard(tmp_path)
        try:
            # _panels 를 빈 list 로 강제 (defensive).
            monkeypatch.setattr(w, "_panels", [])
            # 호출 자체가 예외 없이 끝나야 한다.
            w.handle_local_dictionary_changed()
        finally:
            w.close()


# ---------------------------------------------------------------------------
# 2. MainWindow.local_dictionary_changed signal 정의 + emit 사이트
# ---------------------------------------------------------------------------

class TestMainWindowLocalDictionarySignal:
    """MainWindow 의 signal 정의와 dict-changing handler 의 emit 동작."""

    @pytest.fixture
    def main_window(self, qapp, tmp_path, monkeypatch):
        """MainWindow 인스턴스 — 무거운 startup 로직은 건너뛴다."""
        # MainWindow.__init__ 가 무거우므로 path 설정만 하고 직접 인스턴스 생성.
        from app.main_window import MainWindow

        config = {
            "data_dir": str(tmp_path / "data"),
            "inbox_dir": str(tmp_path / "inbox"),
            "classified_dir": str(tmp_path / "classified"),
            "managed_dir": str(tmp_path / "managed"),
            "db": {"path": str(tmp_path / "main.db")},
        }
        for key in ("data_dir", "inbox_dir", "classified_dir", "managed_dir"):
            Path(config[key]).mkdir(parents=True, exist_ok=True)
        Path(config["data_dir"]).joinpath(".runtime").mkdir(exist_ok=True)
        initialize_database(config["db"]["path"]).close()

        mw = MainWindow(config, config_path=str(tmp_path / "config.json"))
        yield mw
        mw.close()

    def test_main_window_has_local_dictionary_changed_signal(self, main_window):
        # Signal 클래스 속성으로 정의되어 있어야 한다.
        from PyQt6.QtCore import pyqtBoundSignal
        sig = getattr(main_window, "local_dictionary_changed", None)
        assert sig is not None
        # 인스턴스 attribute 는 bound signal.
        assert isinstance(sig, pyqtBoundSignal), (
            "local_dictionary_changed 가 pyqtBoundSignal 이 아님"
        )

    def test_signal_can_be_connected_and_emitted_safely(self, main_window):
        """구독자가 없어도 emit 무해, 구독자가 있으면 호출됨."""
        received: list[bool] = []

        def slot():
            received.append(True)

        main_window.local_dictionary_changed.connect(slot)
        main_window.local_dictionary_changed.emit()
        assert received == [True]

        main_window.local_dictionary_changed.disconnect(slot)
        # 구독자 없을 때 emit 도 무해.
        main_window.local_dictionary_changed.emit()
        assert received == [True]  # 변화 없음

    def test_emit_helper_exists_and_callable(self, main_window):
        """_emit_local_dictionary_changed helper 가 정의되어 있고 호출 가능하다."""
        helper = getattr(main_window, "_emit_local_dictionary_changed", None)
        assert helper is not None
        assert callable(helper)
        # 구독자 없이 호출도 무해.
        main_window._emit_local_dictionary_changed()

    def test_on_show_candidates_emits_after_dialog(self, main_window, monkeypatch):
        """_on_show_candidates 가 dialog 종료 후 local_dictionary_changed 를 emit."""
        emit_count: list[int] = [0]
        main_window.local_dictionary_changed.connect(
            lambda: emit_count.__setitem__(0, emit_count[0] + 1)
        )

        # TagCandidateView 를 fake 로 대체해 실제 dialog 표시 회피.
        from app.views import tag_candidate_view as tcv_mod

        class _FakeTagCandidateView(QDialog):
            def __init__(self, conn, parent=None):
                super().__init__(parent)

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(tcv_mod, "TagCandidateView", _FakeTagCandidateView)

        main_window._on_show_candidates()
        assert emit_count[0] == 1, (
            f"_on_show_candidates 가 emit 하지 않음 (count={emit_count[0]})"
        )

    def test_on_show_dict_import_emits_after_dialog(self, main_window, monkeypatch):
        """_on_show_dict_import 가 dialog 종료 후 emit."""
        emit_count: list[int] = [0]
        main_window.local_dictionary_changed.connect(
            lambda: emit_count.__setitem__(0, emit_count[0] + 1)
        )

        from app.views import dictionary_import_view as div_mod

        class _FakeDictionaryImportView(QDialog):
            log_msg = None  # signal placeholder
            def __init__(self, conn_factory, *, current_group_ids=None, parent=None):
                super().__init__(parent)
                from PyQt6.QtCore import pyqtSignal
                # 실제 signal 객체를 동적으로 부여하지 않고 Mock 으로 처리.

            def exec(self):
                return QDialog.DialogCode.Accepted

        # main_window._on_show_dict_import 가 dlg.log_msg.connect 를 호출한다.
        # log_msg 자리에 connect 가 가능한 stub 필요.
        class _StubSignal:
            def connect(self, _slot):
                # signal 인터페이스 stub — 본 테스트는 emit 동작이 아니라
                # main_window 의 emit 사이트만 검증하므로 실제 slot 등록 불필요.
                return None

        _FakeDictionaryImportView.log_msg = _StubSignal()
        monkeypatch.setattr(div_mod, "DictionaryImportView", _FakeDictionaryImportView)

        main_window._on_show_dict_import()
        assert emit_count[0] == 1


# ---------------------------------------------------------------------------
# 3. 통합: signal emit → wizard dirty → preview 재생성 → clear
# ---------------------------------------------------------------------------

class TestSignalWizardIntegration:
    """signal → wizard slot → dirty → preview 재생성 시 clear 사이클."""

    def test_step7_dirty_after_dict_change_then_clear_after_preview_regen(
        self, qapp, tmp_path
    ):
        """signal emit → Step 7 dirty → preview 재생성 시 dirty clear."""
        from app.views.workflow_wizard_view import _Step7Preview
        from PyQt6.QtCore import QObject, pyqtSignal as Signal

        # 가벼운 signal 발화기 — MainWindow 의 emit 패턴을 emulate.
        class _Emitter(QObject):
            local_dictionary_changed = Signal()

        emitter = _Emitter()
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            assert isinstance(step7, _Step7Preview)
            assert step7.is_preview_dirty() is False

            # MainWindow._on_show_wizard 패턴: signal connect.
            emitter.local_dictionary_changed.connect(w.handle_local_dictionary_changed)

            # 1) dict 변경 emit → dirty 표시.
            emitter.local_dictionary_changed.emit()
            assert step7.is_preview_dirty() is True
            assert "사용자 사전" in (step7._preview_dirty_reason or "")

            # 2) preview 재생성 simulate (_on_preview_done 호출 — clear 경로).
            step7._on_preview_done({
                "previews": [], "total_groups": 0, "estimated_copies": 0,
                "estimated_bytes": 0, "author_fallback_count": 0,
                "series_uncategorized_count": 0, "candidate_count": 0,
                "warnings": [], "folder_locale": "ko",
            })
            assert step7.is_preview_dirty() is False, (
                "preview 재생성 후 dirty 가 clear 되지 않음"
            )

            # 3) 두 번째 emit → 다시 dirty.
            emitter.local_dictionary_changed.emit()
            assert step7.is_preview_dirty() is True
        finally:
            try:
                emitter.local_dictionary_changed.disconnect(
                    w.handle_local_dictionary_changed
                )
            except (TypeError, RuntimeError):
                pass
            w.close()
