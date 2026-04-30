"""MainWindow._on_visual_duplicate_check가 자동 keep/delete 후보를
VisualDuplicateReviewDialog에 initial_decisions로 전달하는지 검증.

테스트 방식:
- source inspection (`inspect.getsource`) 위주 — GUI 의존 0건.
- 핵심 토큰(`decide_visual_duplicate_groups`, `initial_decisions=`,
  fallback 패턴, 안내 INFO 문구)이 handler 본문에 존재하는지 잠금.

이 테스트는 PR #21(decision policy) + PR #22(dialog initial_decisions)
+ 본 PR의 통합이 깨지지 않도록 미래 리팩터링을 보호한다.
"""
from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")


@pytest.fixture(scope="module")
def handler_source() -> str:
    from app.main_window import MainWindow
    return inspect.getsource(MainWindow._on_visual_duplicate_check)


# ---------------------------------------------------------------------------
# Source inspection 테스트
# ---------------------------------------------------------------------------

class TestHandlerSourceIntegratesDecisionPolicy:
    def test_handler_source_imports_decide_visual_duplicate_groups(
        self, handler_source: str,
    ) -> None:
        """handler 본문이 core.visual_duplicate_decision 모듈을 참조해야 한다."""
        assert "decide_visual_duplicate_groups" in handler_source, (
            "MainWindow._on_visual_duplicate_check가 "
            "decide_visual_duplicate_groups를 호출하지 않음 — "
            "PR 3 통합 누락"
        )

    def test_handler_source_passes_initial_decisions_to_dialog(
        self, handler_source: str,
    ) -> None:
        """VisualDuplicateReviewDialog 호출 시 initial_decisions kwarg를
        전달해야 한다."""
        assert "initial_decisions=initial_decisions" in handler_source, (
            "VisualDuplicateReviewDialog에 initial_decisions=initial_decisions "
            "kwarg가 전달되지 않음"
        )

    def test_handler_source_has_safe_fallback(
        self, handler_source: str,
    ) -> None:
        """decision 계산 예외 시 빈 dict로 fallback하는 try/except 패턴을
        보유해야 한다."""
        assert "try:" in handler_source
        assert "except Exception" in handler_source
        # initial_decisions를 빈 dict로 초기화하는 패턴
        assert (
            "initial_decisions: dict[str, str] = {}" in handler_source
            or "initial_decisions = {}" in handler_source
        ), (
            "initial_decisions 빈 dict 초기화 fallback 패턴 부재"
        )

    def test_handler_source_logs_auto_decision_notice(
        self, handler_source: str,
    ) -> None:
        """자동 후보 적용 시 사용자에게 INFO 로그로 안내해야 한다."""
        assert "자동 유지/삭제 후보" in handler_source, (
            "자동 후보 적용 INFO 안내 문구가 누락됨"
        )

    def test_handler_source_logs_warn_on_decision_failure(
        self, handler_source: str,
    ) -> None:
        """decision 계산 실패 시 WARN 로그를 남겨야 한다."""
        assert "[WARN]" in handler_source, (
            "decision 계산 실패 시 WARN 로그 패턴 부재"
        )
        assert "자동 keep/delete 계산 실패" in handler_source

    def test_handler_source_does_not_call_unlink_or_remove_directly(
        self, handler_source: str,
    ) -> None:
        """handler가 자동 선택 결과로 직접 파일을 삭제하면 안 된다.

        실제 삭제는 execute_delete_preview만 담당해야 하며 os.remove /
        os.unlink / pathlib.Path.unlink 호출은 handler에 추가되지 않아야
        한다.
        """
        assert "os.remove" not in handler_source
        assert "os.unlink" not in handler_source
        assert ".unlink(" not in handler_source

    def test_handler_source_preserves_delete_preview_gate(
        self, handler_source: str,
    ) -> None:
        """기존 multi-stage gate(DeletePreviewDialog + execute_delete_preview)
        가 유지되어야 한다."""
        assert "DeletePreviewDialog" in handler_source
        assert "execute_delete_preview" in handler_source

    def test_handler_source_preserves_confirm_visual_scan(
        self, handler_source: str,
    ) -> None:
        """confirm_visual_scan 다이얼로그 단계가 유지되어야 한다."""
        assert "confirm_visual_scan" in handler_source

    def test_decide_call_precedes_dialog_creation(
        self, handler_source: str,
    ) -> None:
        """decide_visual_duplicate_groups 호출은 VisualDuplicateReviewDialog
        생성보다 앞서야 한다 (initial_decisions를 dialog에 주입 가능)."""
        decide_idx = handler_source.find("decide_visual_duplicate_groups(")
        dialog_idx = handler_source.find("VisualDuplicateReviewDialog(")
        assert decide_idx >= 0, "decide call not found"
        assert dialog_idx >= 0, "dialog instantiation not found"
        assert decide_idx < dialog_idx, (
            f"decide_visual_duplicate_groups 호출이 dialog 생성 이후에 있음 "
            f"(decide_idx={decide_idx}, dialog_idx={dialog_idx})"
        )
