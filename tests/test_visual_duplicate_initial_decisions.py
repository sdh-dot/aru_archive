"""VisualDuplicateReviewDialog initial_decisions 회귀 테스트.

검증:
- initial_decisions 인자가 _decisions에 그대로 채워진다 (유효 값만)
- initial delete 항목이 selected_for_delete()에 포함된다
- 사용자 클릭이 initial decision을 덮어쓴다
- invalid decision 값/key 타입은 silent 무시된다
- Dialog 생성만으로 file system 변경이 발생하지 않는다
- 초기 라벨이 initial decision을 반영한다

PyQt6 headless 패턴 (기존 test_visual_duplicate_review_dialog.py 동일):
- pytest.importorskip("PyQt6") (모듈 레벨에서 PyQt6 import 시도)
- QApplication.instance() or QApplication([])
- Windows + QT_QPA_PLATFORM 미설정 환경에서는 skipif로 스킵
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402


pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "") == "" and os.name == "nt",
    reason="GUI tests require QT_QPA_PLATFORM=offscreen",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _make_dup_groups(n_groups: int = 1) -> list[dict]:
    """파일 IO 의존성 없는 합성 dup group dict 리스트.

    Dialog는 file_path 존재 시 PIL로 썸네일 생성하지만, 부재 시 fallback
    회색 placeholder 이미지를 사용하므로 실제 파일은 만들지 않는다.
    """
    groups = []
    for i in range(n_groups):
        groups.append({
            "files": [
                {
                    "file_id":              f"fid_{i}_a",
                    "group_id":             f"gid_{i}_a",
                    "file_path":            f"/tmp/img_{i}_a.jpg",
                    "file_role":            "original",
                    "file_size":            1024,
                    "metadata_sync_status": "full",
                    "artist_name":          "Artist",
                    "artwork_id":           f"art_{i}",
                },
                {
                    "file_id":              f"fid_{i}_b",
                    "group_id":             f"gid_{i}_b",
                    "file_path":            f"/tmp/img_{i}_b.jpg",
                    "file_role":            "original",
                    "file_size":            2048,
                    "metadata_sync_status": "json_only",
                    "artist_name":          "Artist",
                    "artwork_id":           f"art_{i}_2",
                },
            ],
            "distance": 3,
        })
    return groups


# ---------------------------------------------------------------------------
# 1. _decisions 초기 채움
# ---------------------------------------------------------------------------

class TestInitialDecisionsPopulate:
    def test_initial_decisions_populates_decisions(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "keep"},
        )
        assert dlg._decisions["fid_0_a"] == "keep"

    def test_initial_decisions_default_none_is_empty(self, app) -> None:
        """initial_decisions 미전달 시 기존 동작 유지 (회귀 가드)."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(_make_dup_groups(1))
        assert dlg._decisions == {}
        assert dlg.selected_for_delete() == []

    def test_initial_decisions_explicit_none_is_empty(self, app) -> None:
        """initial_decisions=None 명시 전달 시에도 안전."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions=None,
        )
        assert dlg._decisions == {}


# ---------------------------------------------------------------------------
# 2. selected_for_delete 동기화
# ---------------------------------------------------------------------------

class TestInitialDeleteSelectedForDelete:
    def test_initial_delete_in_selected_for_delete(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "delete"},
        )
        assert "fid_0_a" in dlg.selected_for_delete()

    def test_initial_keep_not_in_selected_for_delete(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "keep"},
        )
        assert "fid_0_a" not in dlg.selected_for_delete()

    def test_initial_exclude_not_in_selected_for_delete(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "exclude"},
        )
        assert "fid_0_a" not in dlg.selected_for_delete()

    def test_multi_initial_delete_all_in_selected_for_delete(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={
                "fid_0_a": "delete",
                "fid_0_b": "delete",
            },
        )
        sel = dlg.selected_for_delete()
        assert "fid_0_a" in sel
        assert "fid_0_b" in sel


# ---------------------------------------------------------------------------
# 3. 사용자 클릭 우선
# ---------------------------------------------------------------------------

class TestUserClickOverridesInitialDecision:
    def test_user_keep_click_overrides_initial_delete(self, app) -> None:
        """initial=delete였던 항목을 사용자가 keep으로 변경하면 그룹 내
        다른 항목이 자동 delete로 바뀐다 (group sync 회귀)."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={
                "fid_0_a": "delete",
                "fid_0_b": "keep",
            },
        )
        # 초기 상태 확인
        assert dlg._decisions["fid_0_a"] == "delete"
        assert dlg._decisions["fid_0_b"] == "keep"

        # 사용자가 fid_0_a에 대해 keep 결정 — group sync 발동
        dlg._apply_group_decision("fid_0_a", "keep")

        assert dlg._decisions["fid_0_a"] == "keep"
        assert dlg._decisions["fid_0_b"] == "delete"
        assert "fid_0_a" not in dlg.selected_for_delete()
        assert "fid_0_b" in dlg.selected_for_delete()


# ---------------------------------------------------------------------------
# 4. invalid 입력 silent 무시
# ---------------------------------------------------------------------------

class TestInvalidInitialDecisionsDropped:
    def test_invalid_decision_value_silently_dropped(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "invalid"},
        )
        assert "fid_0_a" not in dlg._decisions

    def test_invalid_key_type_silently_dropped(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={123: "delete"},  # type: ignore[dict-item]
        )
        assert dlg._decisions == {}

    def test_invalid_value_type_silently_dropped(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": 99},  # type: ignore[dict-item]
        )
        assert "fid_0_a" not in dlg._decisions

    def test_mixed_valid_and_invalid(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={
                "fid_0_a": "keep",       # valid
                "fid_0_b": "garbage",    # invalid value → drop
                42:        "delete",     # invalid key → drop
            },
        )
        assert dlg._decisions == {"fid_0_a": "keep"}
        assert dlg.selected_for_delete() == []


# ---------------------------------------------------------------------------
# 5. file system 영향 없음
# ---------------------------------------------------------------------------

class TestNoFileSystemSideEffect:
    def test_initial_decisions_does_not_touch_file_system(self, app) -> None:
        """Dialog 생성만으로 os.remove / os.unlink / Path.unlink 호출 0건."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        with patch("os.remove") as os_remove, \
             patch("os.unlink") as os_unlink, \
             patch("pathlib.Path.unlink") as path_unlink:
            dlg = VisualDuplicateReviewDialog(
                _make_dup_groups(1),
                initial_decisions={
                    "fid_0_a": "delete",
                    "fid_0_b": "keep",
                },
            )
            # Dialog 즉시 close — file system 영향 0 검증
            assert dlg is not None

        assert os_remove.call_count == 0
        assert os_unlink.call_count == 0
        assert path_unlink.call_count == 0


# ---------------------------------------------------------------------------
# 6. 라벨 반영
# ---------------------------------------------------------------------------

class TestLabelReflectsInitialDecision:
    def test_label_reflects_initial_delete(self, app) -> None:
        """initial_decisions={"fid_0_a": "delete"}일 때 카드 라벨에
        '삭제' 또는 '✗' 마커가 표시되어야 한다."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "delete"},
        )
        lbl = dlg._decision_labels.get("fid_0_a")
        assert lbl is not None, "_decision_labels에 fid_0_a 라벨 부재"
        text = lbl.text()
        assert "삭제" in text or "✗" in text, (
            f"라벨이 delete 결정을 반영하지 않음: {text!r}"
        )

    def test_label_reflects_initial_keep(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "keep"},
        )
        lbl = dlg._decision_labels.get("fid_0_a")
        assert lbl is not None
        text = lbl.text()
        # 자동 추천 initial_decisions → "추천: keep" 표현.
        # "유지", "✓", "keep" 중 하나 이상 포함.
        assert "유지" in text or "✓" in text or "keep" in text, (
            f"라벨이 keep 결정을 반영하지 않음: {text!r}"
        )

    def test_label_reflects_initial_exclude(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_dup_groups(1),
            initial_decisions={"fid_0_a": "exclude"},
        )
        lbl = dlg._decision_labels.get("fid_0_a")
        assert lbl is not None
        text = lbl.text()
        assert "제외" in text or "—" in text, (
            f"라벨이 exclude 결정을 반영하지 않음: {text!r}"
        )

    def test_label_default_is_undecided_without_initial(self, app) -> None:
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(_make_dup_groups(1))
        lbl = dlg._decision_labels.get("fid_0_a")
        assert lbl is not None
        text = lbl.text()
        assert "미결정" in text, (
            f"initial_decisions 없을 때 라벨이 미결정이 아님: {text!r}"
        )
