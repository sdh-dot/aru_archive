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
        wizard._go_to_step(0)
        title_0 = wizard._step_title.text()
        wizard._go_to_step(4)
        title_4 = wizard._step_title.text()
        assert title_0 != title_4
        assert "Step 1" in title_0
        assert "Step 5" in title_4
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
