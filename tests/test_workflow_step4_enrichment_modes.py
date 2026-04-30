"""Step 4 enrichment mode 회귀 테스트.

source-inspection 기반 — GUI 부팅 0건.
"""
from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")


class TestEnrichThreadAcceptsMode:
    def test_enrich_thread_accepts_mode_kwarg(self):
        from app.views.workflow_wizard_view import _EnrichThread
        sig = inspect.signature(_EnrichThread.__init__)
        assert "mode" in sig.parameters

    def test_enrich_thread_default_mode_is_missing_only(self):
        from app.views.workflow_wizard_view import _EnrichThread
        sig = inspect.signature(_EnrichThread.__init__)
        assert sig.parameters["mode"].default == "missing_only"


class TestStep4UIHasTwoButtons:
    def test_step4_uses_build_enrichment_queue(self):
        from app.views import workflow_wizard_view as wf
        src = inspect.getsource(wf)
        assert "build_enrichment_queue" in src

    def test_step4_has_missing_only_button_label(self):
        from app.views.workflow_wizard_view import _Step4Enrich
        src = inspect.getsource(_Step4Enrich)
        assert "No Metadata만 보강" in src

    def test_step4_has_all_pixiv_button_label(self):
        from app.views.workflow_wizard_view import _Step4Enrich
        src = inspect.getsource(_Step4Enrich)
        assert "Pixiv ID 있는 모든 항목 재시도" in src

    def test_step4_has_two_distinct_handlers(self):
        from app.views.workflow_wizard_view import _Step4Enrich
        src = inspect.getsource(_Step4Enrich)
        assert "_on_enrich_missing" in src
        assert "_on_enrich_all" in src


class TestAllPixivConfirmDialog:
    def test_all_pixiv_handler_uses_confirm_dialog(self):
        from app.views.workflow_wizard_view import _Step4Enrich
        src = inspect.getsource(_Step4Enrich._on_enrich_all)
        assert "QMessageBox" in src
        assert "question" in src

    def test_all_pixiv_handler_excludes_source_unavailable_in_message(self):
        from app.views.workflow_wizard_view import _Step4Enrich
        src = inspect.getsource(_Step4Enrich._on_enrich_all)
        assert "source_unavailable" in src
        assert "full" in src
        assert "pending" in src

    def test_all_pixiv_handler_starts_with_all_pixiv_mode(self):
        from app.views.workflow_wizard_view import _Step4Enrich
        src = inspect.getsource(_Step4Enrich._on_enrich_all)
        assert 'mode="all_pixiv"' in src or "mode='all_pixiv'" in src
