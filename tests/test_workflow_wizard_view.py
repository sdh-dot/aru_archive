"""
app/views/workflow_wizard_view.WorkflowWizardView GUI 스모크 테스트.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QPushButton, QStackedWidget

from db.database import initialize_database


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def conn_factory(tmp_path):
    db = tmp_path / "test.db"
    def factory():
        return initialize_database(str(db))
    return factory


@pytest.fixture
def wizard(qapp, conn_factory):
    from app.views.workflow_wizard_view import WorkflowWizardView
    config = {"data_dir": "", "inbox_dir": "", "classified_dir": "", "managed_dir": "", "db": {"path": ""}}
    w = WorkflowWizardView(conn_factory, config, "config.json")
    yield w
    w.close()


# ---------------------------------------------------------------------------
# 기본 구조 테스트
# ---------------------------------------------------------------------------

class TestWorkflowWizardViewCreation:
    def test_wizard_creates_without_error(self, wizard):
        assert wizard is not None

    def test_window_title_contains_mabeobsa(self, wizard):
        assert "마법사" in wizard.windowTitle()

    def test_has_nine_step_buttons(self, wizard):
        assert len(wizard._step_btns) == 9

    def test_has_stacked_widget_with_nine_panels(self, wizard):
        assert wizard._stack.count() == 9

    def test_has_prev_next_refresh_close_buttons(self, wizard):
        assert hasattr(wizard, "_btn_prev")
        assert hasattr(wizard, "_btn_next")
        assert hasattr(wizard, "_btn_refresh")
        assert hasattr(wizard, "_btn_close")

    def test_has_nine_panels(self, wizard):
        assert len(wizard._panels) == 9

    def test_starts_at_step_zero(self, wizard):
        assert wizard._current == 0
        assert wizard._stack.currentIndex() == 0


class TestStepNavigation:
    def test_go_to_step_changes_stack_index(self, wizard):
        wizard._go_to_step(2)
        assert wizard._stack.currentIndex() == 2
        wizard._go_to_step(0)   # restore

    def test_prev_disabled_on_first_step(self, wizard):
        wizard._go_to_step(0)
        assert not wizard._btn_prev.isEnabled()

    def test_next_disabled_on_last_step(self, wizard):
        wizard._go_to_step(8)
        assert not wizard._btn_next.isEnabled()
        wizard._go_to_step(0)   # restore

    def test_prev_enabled_after_going_to_step_1(self, wizard):
        wizard._go_to_step(1)
        assert wizard._btn_prev.isEnabled()
        wizard._go_to_step(0)   # restore

    def test_on_next_advances_step(self, wizard):
        wizard._go_to_step(0)
        wizard._on_next()
        assert wizard._current == 1
        wizard._go_to_step(0)   # restore

    def test_on_prev_goes_back(self, wizard):
        wizard._go_to_step(3)
        wizard._on_prev()
        assert wizard._current == 2
        wizard._go_to_step(0)   # restore

    def test_go_to_step_clamps_below_zero(self, wizard):
        wizard._go_to_step(-1)
        assert wizard._current == 0

    def test_go_to_step_clamps_above_max(self, wizard):
        wizard._go_to_step(100)
        assert wizard._current == 8
        wizard._go_to_step(0)   # restore

    def test_step_title_updates_on_navigation(self, wizard):
        # 사용자에게 보이는 번호 기준 (hidden step 인 internal idx 5 가 빠진 1..8 numbering).
        # internal idx 0 → visible "단계 1 / 8"
        # internal idx 4 → visible "단계 5 / 8"
        wizard._go_to_step(0)
        title_0 = wizard._step_title.text()
        wizard._go_to_step(4)
        title_4 = wizard._step_title.text()
        assert title_0 != title_4
        assert "단계 1 / 8" in title_0
        assert "단계 5 / 8" in title_4
        wizard._go_to_step(0)   # restore


class TestRefreshMainSignal:
    def test_refresh_main_signal_exists(self, wizard):
        received = []
        wizard.refresh_main.connect(lambda: received.append(1))
        wizard.refresh_main.emit()
        assert received == [1]


class TestScanThread:
    def test_scan_thread_uses_current_inbox_scanner_signature(self, qapp, tmp_path):
        from app.views.workflow_wizard_view import _ScanThread

        data_dir = tmp_path / "archive"
        inbox = data_dir / "Inbox"
        inbox.mkdir(parents=True)
        db_path = data_dir / ".runtime" / "aru.db"

        results = []
        logs = []
        managed = tmp_path / "Managed"
        thread = _ScanThread(str(data_dir), str(inbox), str(managed), str(db_path))
        thread.done.connect(results.append)
        thread.log_msg.connect(logs.append)

        thread.run()

        assert results == [{"new": 0, "skipped": 0, "failed": 0}]
        assert not any("unexpected keyword argument" in msg for msg in logs)


class TestStep8ExecuteButton:
    def test_execute_button_disabled_initially(self, wizard):
        from app.views.workflow_wizard_view import _Step8Execute
        step8 = wizard._panels[7]
        assert isinstance(step8, _Step8Execute)
        assert not step8._btn_execute.isEnabled()

    def test_set_preview_enables_execute_button(self, wizard):
        from app.views.workflow_wizard_view import _Step8Execute
        step8 = wizard._panels[7]
        step8.set_preview({"estimated_copies": 5, "estimated_bytes": 1024})
        assert step8._btn_execute.isEnabled()

    def test_set_preview_empty_dict_disables(self, wizard):
        from app.views.workflow_wizard_view import _Step8Execute
        step8 = wizard._panels[7]
        step8.set_preview({})
        assert not step8._btn_execute.isEnabled()

    def test_execute_progress_updates_progress_bar(self, wizard):
        from app.views.workflow_wizard_view import _Step8Execute
        step8 = wizard._panels[7]
        step8._on_execute_progress(1, 3, "완료: abcdef12…")
        assert step8._progress.value() == 1
        assert "1/3" in step8._progress_lbl.text()


class TestStep7PreviewTable:
    def test_show_preview_summary_populates_destination_list(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview

        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)

        preview = {
            "total_groups": 1,
            "classifiable_groups": 1,
            "excluded_groups": 0,
            "estimated_copies": 2,
            "estimated_bytes": 2048,
            "series_uncategorized_count": 0,
            "author_fallback_count": 0,
            "candidate_count": 0,
            "previews": [
                {
                    "source_path": "D:/archive/Inbox/sample.jpg",
                    "destinations": [
                        {
                            "rule_type": "series_character",
                            "dest_path": "D:/archive/Classified/Blue Archive/ワカモ/sample.jpg",
                            "will_copy": True,
                            "conflict": "none",
                        },
                        {
                            "rule_type": "author",
                            "dest_path": "D:/archive/Classified/Author/A/sample.jpg",
                            "will_copy": False,
                            "conflict": "would_skip",
                        },
                    ],
                }
            ],
        }

        step7._show_preview_summary(preview)

        assert step7._preview_table.rowCount() == 2
        assert step7._preview_table.item(0, 0).text() == "sample.jpg"
        # col 2: 분류 대상 여부 ("분류됨" / "제외")
        assert step7._preview_table.item(0, 2).text() == "분류됨"
        assert step7._preview_table.item(1, 2).text() == "제외"
        assert "would_skip" in step7._preview_table.item(1, 4).text()


# ---------------------------------------------------------------------------
# Step 1 — 작업 범위 안내 문구
# ---------------------------------------------------------------------------

class TestStep1ScopeNotice:
    """Step 1 상단의 작업 범위 안내 라벨이 존재하고 사용자에게 정확한 의미를
    전달하는지 lock. UI 텍스트만 변경 — wizard 의 실제 작업 로직과 분리된다."""

    def test_step1_has_scope_notice_label(self, wizard):
        from app.views.workflow_wizard_view import _Step1Root
        step1 = wizard._panels[0]
        assert isinstance(step1, _Step1Root)
        assert hasattr(step1, "_scope_notice"), (
            "Step 1 에 _scope_notice QLabel 이 추가되지 않음"
        )
        from PyQt6.QtWidgets import QLabel
        assert isinstance(step1._scope_notice, QLabel)

    def test_scope_notice_text_contains_keyword(self, wizard):
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        assert "작업 범위" in text, (
            f"안내 문구에 '작업 범위' 표기 누락: {text!r}"
        )

    def test_scope_notice_mentions_pixiv_and_metadata(self, wizard):
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        assert "Pixiv" in text, "Pixiv 언급 누락"
        assert "메타데이터" in text, "메타데이터 언급 누락"

    def test_scope_notice_avoids_absolute_pixiv_only_phrasing(self, wizard):
        """단정적인 'Pixiv 파일만' 표현은 피한다 (XMP 입력 / 분류 등은 비-Pixiv
        파일도 대상이므로 사용자 오해 유발)."""
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        assert "Pixiv 파일만" not in text, (
            f"단정적인 'Pixiv 파일만' 표현 사용됨: {text!r}"
        )

    def test_scope_notice_distinguishes_pixiv_fetch_from_classification(self, wizard):
        """안내 문구가 Pixiv 가져오기와 일반 분류 대상 범위 차이를 명시한다.

        Pixiv 메타데이터 가져오기는 Pixiv 출처 파일에만 적용되지만, 분류
        미리보기/실행은 메타데이터 상태 기반으로 비-Pixiv 파일도 포함한다 —
        이 차이를 사용자에게 명확히 안내해야 한다.
        """
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        # Pixiv 가져오기 한정 안내 문구.
        assert "Pixiv 메타데이터 가져오기" in text, (
            f"안내에 'Pixiv 메타데이터 가져오기' 표기 누락: {text!r}"
        )
        assert "Pixiv 출처 파일에만" in text, (
            f"안내에 'Pixiv 출처 파일에만' 표기 누락: {text!r}"
        )

    def test_scope_notice_word_wraps(self, wizard):
        step1 = wizard._panels[0]
        assert step1._scope_notice.wordWrap() is True

    def test_step1_existing_widgets_preserved(self, wizard):
        """기존 status_table 과 폴더 설정 버튼이 그대로 남아 있다 (UI 회귀 가드)."""
        step1 = wizard._panels[0]
        assert hasattr(step1, "_status_table")
        from PyQt6.QtWidgets import QPushButton, QTableWidget
        assert isinstance(step1._status_table, QTableWidget)
        # 「📁 작업 폴더 설정」 버튼이 child 로 살아 있다.
        buttons = [
            b for b in step1.findChildren(QPushButton)
            if "작업 폴더 설정" in b.text()
        ]
        assert buttons, "'작업 폴더 설정' 버튼이 사라짐"


# ---------------------------------------------------------------------------
# Step 7 — preview button label 통일 (초기 / 재실행 후 동일)
# ---------------------------------------------------------------------------

class TestStep7PreviewButtonLabel:
    """Step 7 의 [📋 분류 미리보기 생성] 버튼 라벨이 초기 / preview 완료 후
    재실행 가능 상태에서 동일하게 표시되는지 lock — 사용자가 무엇을 분류
    미리보는지 명확히 한다."""

    EXPECTED_LABEL = "📋 분류 미리보기 생성"

    def test_initial_label_is_normalized(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)
        assert step7._btn_preview.text() == self.EXPECTED_LABEL, (
            f"초기 버튼 라벨이 통일된 표기와 다름: {step7._btn_preview.text()!r}"
        )

    def test_label_after_preview_done_is_same_as_initial(self, wizard):
        """_on_preview_done 호출 후 버튼 라벨이 초기와 동일해야 한다 (이전에는
        '📋 미리보기 생성' 으로 짧아져 일관성이 깨졌음)."""
        step7 = wizard._panels[6]
        initial = step7._btn_preview.text()
        step7._on_preview_done({
            "previews": [], "total_groups": 0, "estimated_copies": 0,
            "estimated_bytes": 0, "author_fallback_count": 0,
            "series_uncategorized_count": 0, "candidate_count": 0,
            "warnings": [], "folder_locale": "ko",
        })
        assert step7._btn_preview.text() == initial == self.EXPECTED_LABEL, (
            f"preview 완료 후 라벨이 초기와 다름: {step7._btn_preview.text()!r}"
        )
