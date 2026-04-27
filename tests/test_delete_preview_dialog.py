"""
DeletePreviewDialog smoke 테스트.

- DeletePreviewDialog 생성 가능
- High risk 시 confirm_input이 있음
- Low risk 시 confirm_input이 없음
- 삭제 버튼 핸들러 존재
"""
from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "") == "" and os.name == "nt",
    reason="GUI tests require QT_QPA_PLATFORM=offscreen",
)


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    import sys
    a = QApplication.instance() or QApplication(sys.argv)
    return a


def _make_preview(risk: str = "low", has_original: bool = False) -> dict:
    role_counts = {}
    if has_original:
        role_counts["original"] = 1
    else:
        role_counts["classified_copy"] = 1
    return {
        "risk": risk,
        "total_files": 1,
        "file_items": [
            {
                "file_id": "test-file-id",
                "group_id": "test-group-id",
                "file_path": "/tmp/test.jpg",
                "file_role": "original" if has_original else "classified_copy",
                "file_format": "jpg",
                "file_hash": None,
                "file_size": 1024,
                "file_status": "present",
                "metadata_sync_status": "full",
                "artist_name": "Artist",
                "exists_on_disk": True,
                "has_json_sidecar": False,
                "remaining_present_files": 0,
            }
        ],
        "role_counts": role_counts,
        "status_counts": {"full": 1},
        "groups_affected": 1,
        "groups_becoming_empty": 1 if has_original else 0,
        "warnings": [],
    }


class TestDeletePreviewDialogSmoke:
    def test_creates_low_risk_dialog(self, app):
        from app.views.delete_preview_dialog import DeletePreviewDialog
        preview = _make_preview(risk="low")
        dlg = DeletePreviewDialog(preview)
        assert dlg is not None
        assert dlg._confirm_input is None

    def test_creates_high_risk_dialog_with_confirm_input(self, app):
        from app.views.delete_preview_dialog import DeletePreviewDialog
        preview = _make_preview(risk="high", has_original=True)
        dlg = DeletePreviewDialog(preview)
        assert dlg._confirm_input is not None

    def test_delete_button_exists(self, app):
        from app.views.delete_preview_dialog import DeletePreviewDialog
        preview = _make_preview(risk="low")
        dlg = DeletePreviewDialog(preview)
        assert hasattr(dlg, "_btn_delete")
        assert dlg._btn_delete is not None

    def test_cancel_button_exists(self, app):
        from app.views.delete_preview_dialog import DeletePreviewDialog
        preview = _make_preview(risk="low")
        dlg = DeletePreviewDialog(preview)
        assert hasattr(dlg, "_btn_cancel")

    def test_high_risk_delete_button_disabled_initially(self, app):
        from app.views.delete_preview_dialog import DeletePreviewDialog
        preview = _make_preview(risk="high", has_original=True)
        dlg = DeletePreviewDialog(preview)
        assert not dlg._btn_delete.isEnabled()

    def test_high_risk_delete_button_enabled_after_correct_input(self, app):
        from app.views.delete_preview_dialog import DeletePreviewDialog
        preview = _make_preview(risk="high", has_original=True)
        dlg = DeletePreviewDialog(preview)
        dlg._confirm_input.setText("DELETE")
        assert dlg._btn_delete.isEnabled()

    def test_is_confirmed_initially_false(self, app):
        from app.views.delete_preview_dialog import DeletePreviewDialog
        preview = _make_preview(risk="low")
        dlg = DeletePreviewDialog(preview)
        assert not dlg.is_confirmed()
