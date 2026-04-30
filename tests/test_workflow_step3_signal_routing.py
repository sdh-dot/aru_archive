"""Workflow Wizard Step 3 → MainWindow handler signal routing 회귀 테스트.

검증 대상:
- WorkflowWizardView.exact_duplicate_scan_requested / visual_duplicate_scan_requested signal 정의
- _Step3Meta._on_exact_dup / _on_visual_dup이 본문에서 직접 duplicate scan 로직을
  호출하지 않고 wizard signal만 emit하는지 검증
- core.visual_duplicate_finder.find_visual_duplicates / core.duplicate_finder.find_exact_duplicates
  가 Step 3 핸들러에서 직접 호출되지 않는 것을 mock으로 잠금
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def wizard(qapp, tmp_path: Path):
    """`WorkflowWizardView`를 in-memory DB + 더미 config로 생성한다."""
    from db.database import initialize_database
    from app.views.workflow_wizard_view import WorkflowWizardView

    db_path = tmp_path / "wizard.db"
    initialize_database(str(db_path)).close()

    def conn_factory():
        return initialize_database(str(db_path))

    config = {
        "data_dir": str(tmp_path),
        "inbox_dir": str(tmp_path / "Inbox"),
        "classified_dir": str(tmp_path / "Classified"),
        "managed_dir": str(tmp_path / "Managed"),
        "db": {"path": str(db_path)},
        "duplicates": {
            "default_scope": "inbox_managed",
            "confirm_visual_scan": True,
            "max_visual_files_per_run": 300,
        },
    }
    config_path = str(tmp_path / "config.json")
    w = WorkflowWizardView(conn_factory, config, config_path, parent=None)
    yield w
    w.close()
    w.deleteLater()


def _step3_panel(wizard) -> object:
    """워크플로 wizard의 _Step3Meta 패널 인스턴스를 추출한다."""
    # WorkflowWizardView._panels는 step 인덱스 순으로 _StepPanel 인스턴스 보관
    # _Step3Meta는 0-based index 2 (Step 3)
    panels = getattr(wizard, "_panels", None)
    assert panels is not None, "WorkflowWizardView._panels 부재 — 내부 구조 변경"
    assert len(panels) >= 3, f"패널 개수 부족: {len(panels)}"
    return panels[2]


# ---------------------------------------------------------------------------
# Test 1 — visual duplicate 버튼이 signal emit
# ---------------------------------------------------------------------------

class TestStep3VisualDuplicateSignal:
    def test_signals_defined_on_wizard(self, wizard) -> None:
        """WorkflowWizardView 클래스에 신규 signal 2개가 등록되어 있어야 한다."""
        assert hasattr(wizard, "visual_duplicate_scan_requested")
        assert hasattr(wizard, "exact_duplicate_scan_requested")

    def test_step3_visual_duplicate_button_emits_signal(self, wizard) -> None:
        """_btn_visual_dup 클릭 → wizard.visual_duplicate_scan_requested 1회 emit."""
        step3 = _step3_panel(wizard)
        assert hasattr(step3, "_btn_visual_dup"), "Step 3에 _btn_visual_dup 부재"

        emitted: list[None] = []
        wizard.visual_duplicate_scan_requested.connect(lambda: emitted.append(None))

        step3._btn_visual_dup.click()

        assert len(emitted) == 1, (
            f"visual_duplicate_scan_requested 1회 emit 기대, 실제 {len(emitted)}회"
        )

    def test_step3_visual_dup_does_not_call_find_visual_duplicates(
        self, wizard,
    ) -> None:
        """Step 3 button 클릭 시 core.visual_duplicate_finder.find_visual_duplicates를
        직접 호출하면 안 된다 (MainWindow handler 경로로만 도달해야 함)."""
        step3 = _step3_panel(wizard)
        with patch(
            "core.visual_duplicate_finder.find_visual_duplicates"
        ) as mock_find:
            step3._btn_visual_dup.click()
        assert not mock_find.called, (
            "Step 3가 find_visual_duplicates를 직접 호출함 — "
            "signal emit으로 위임되어야 함"
        )


# ---------------------------------------------------------------------------
# Test 2 — exact duplicate 버튼이 signal emit
# ---------------------------------------------------------------------------

class TestStep3ExactDuplicateSignal:
    def test_step3_exact_duplicate_button_emits_signal(self, wizard) -> None:
        """_btn_exact_dup 클릭 → wizard.exact_duplicate_scan_requested 1회 emit."""
        step3 = _step3_panel(wizard)
        assert hasattr(step3, "_btn_exact_dup"), "Step 3에 _btn_exact_dup 부재"

        emitted: list[None] = []
        wizard.exact_duplicate_scan_requested.connect(lambda: emitted.append(None))

        step3._btn_exact_dup.click()

        assert len(emitted) == 1, (
            f"exact_duplicate_scan_requested 1회 emit 기대, 실제 {len(emitted)}회"
        )

    def test_step3_exact_dup_does_not_call_find_exact_duplicates(
        self, wizard,
    ) -> None:
        """Step 3 button 클릭 시 core.duplicate_finder.find_exact_duplicates를
        직접 호출하면 안 된다."""
        step3 = _step3_panel(wizard)
        with patch(
            "core.duplicate_finder.find_exact_duplicates"
        ) as mock_find:
            step3._btn_exact_dup.click()
        assert not mock_find.called, (
            "Step 3가 find_exact_duplicates를 직접 호출함 — "
            "signal emit으로 위임되어야 함"
        )


# ---------------------------------------------------------------------------
# Test 3 — Step 3 안내 라벨이 정적 문구로 갱신
# ---------------------------------------------------------------------------

class TestStep3DupStatusLabel:
    def test_dup_status_label_shows_static_guidance(self, wizard) -> None:
        """이전 '마지막 검사: 미실행' 동적 라벨 대신 정적 안내 문구가 표시되어야 한다."""
        step3 = _step3_panel(wizard)
        assert hasattr(step3, "_dup_status_lbl")
        text = step3._dup_status_lbl.text()
        assert "메인 화면" in text or "기존 중복 검사 흐름" in text, (
            f"안내 문구가 정적 형태가 아님: {text!r}"
        )
        # 동적 결과 표시 흔적이 남아 있지 않아야 함
        assert "미실행" not in text
