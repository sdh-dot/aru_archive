"""
VisualDuplicateReviewDialog smoke 테스트.

- VisualDuplicateReviewDialog 생성 가능
- 그룹 없으면 표시 처리
- 파일 카드 빌드 가능
- selected_for_delete() 초기 빈 목록
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


def _make_dup_groups(n_groups: int = 2) -> list[dict]:
    groups = []
    for i in range(n_groups):
        groups.append({
            "files": [
                {
                    "file_id": f"fid_{i}_a",
                    "group_id": f"gid_{i}_a",
                    "file_path": f"/tmp/img_{i}_a.jpg",
                    "file_role": "original",
                    "file_size": 1024,
                    "metadata_sync_status": "full",
                    "artist_name": "Artist",
                    "artwork_id": f"art_{i}",
                },
                {
                    "file_id": f"fid_{i}_b",
                    "group_id": f"gid_{i}_b",
                    "file_path": f"/tmp/img_{i}_b.jpg",
                    "file_role": "original",
                    "file_size": 2048,
                    "metadata_sync_status": "json_only",
                    "artist_name": "Artist",
                    "artwork_id": f"art_{i}_2",
                },
            ],
            "distance": 3,
        })
    return groups


class TestVisualDuplicateReviewDialogSmoke:
    def test_creates_with_groups(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        dlg = VisualDuplicateReviewDialog(_make_dup_groups(2))
        assert dlg is not None

    def test_creates_with_empty_groups(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        dlg = VisualDuplicateReviewDialog([])
        assert dlg is not None

    def test_selected_for_delete_initially_empty(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        dlg = VisualDuplicateReviewDialog(_make_dup_groups(2))
        assert dlg.selected_for_delete() == []

    def test_progress_label_exists(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        dlg = VisualDuplicateReviewDialog(_make_dup_groups(1))
        assert hasattr(dlg, "_lbl_progress")

    def test_navigation_buttons_exist(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        dlg = VisualDuplicateReviewDialog(_make_dup_groups(3))
        assert hasattr(dlg, "_btn_prev")
        assert hasattr(dlg, "_btn_next")
        assert hasattr(dlg, "_btn_go_delete")

    def test_prev_disabled_on_first_group(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        dlg = VisualDuplicateReviewDialog(_make_dup_groups(3))
        assert not dlg._btn_prev.isEnabled()

    def test_next_enabled_on_first_group_of_multiple(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        dlg = VisualDuplicateReviewDialog(_make_dup_groups(3))
        assert dlg._btn_next.isEnabled()
