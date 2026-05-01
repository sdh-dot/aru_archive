"""
Visual Duplicate UX 개선 테스트.

검증 항목:
- _format_size_mb: byte → MB 변환 규칙
- 카드 reason 라벨 표시 (자동 추천 keep / delete)
- 자동 추천 라벨에 "삭제됨" / "삭제 완료" 등 final 표현 미포함
- 다이얼로그 상단 안내문 존재 ("자동 추천", "검토")
- _compute_group_reasons: decide_visual_duplicate_group 위임 확인
- _compute_group_reasons 예외 시 빈 dict 반환 (안전 fallback)

PyQt6 headless 패턴 동일.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

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


def _make_groups(n: int = 1) -> list[dict]:
    groups = []
    for i in range(n):
        groups.append({
            "files": [
                {
                    "file_id":              f"fid_{i}_a",
                    "file_path":            f"/tmp/img_{i}_a.jpg",
                    "file_role":            "original",
                    "file_size":            1024 * 500,   # 0.49 MB (< 1 MB)
                    "metadata_sync_status": "full",
                    "artist_name":          "ArtistA",
                    "_width":               800,
                    "_height":              600,
                    "file_format":          "jpg",
                },
                {
                    "file_id":              f"fid_{i}_b",
                    "file_path":            f"/tmp/img_{i}_b.jpg",
                    "file_role":            "original",
                    "file_size":            1024 * 1024 * 12,  # 12 MB
                    "metadata_sync_status": "json_only",
                    "artist_name":          "ArtistB",
                    "_width":               1920,
                    "_height":              1080,
                    "file_format":          "jpg",
                },
            ],
            "distance": 3,
        })
    return groups


# ---------------------------------------------------------------------------
# 1. _format_size_mb unit tests (no GUI needed)
# ---------------------------------------------------------------------------

class TestFormatSizeMb:
    def _fn(self, v):
        from app.views.visual_duplicate_review_dialog import _format_size_mb
        return _format_size_mb(v)

    def test_zero_returns_dash(self):
        assert self._fn(0) == "-"

    def test_none_returns_dash(self):
        assert self._fn(None) == "-"

    def test_small_file_uses_2_decimals(self):
        # 500 KB → < 1 MB → "0.49 MB"
        result = self._fn(500 * 1024)
        assert "MB" in result
        assert "." in result
        # 소수점 이하 2자리 확인
        mb_part = result.replace(" MB", "")
        assert len(mb_part.split(".")[-1]) == 2

    def test_large_file_uses_1_decimal(self):
        # 12.3 MB
        result = self._fn(int(12.3 * 1024 * 1024))
        assert "MB" in result
        mb_part = result.replace(" MB", "")
        assert len(mb_part.split(".")[-1]) == 1

    def test_exactly_1mb_uses_1_decimal(self):
        result = self._fn(1024 * 1024)
        assert result == "1.0 MB"

    def test_byte_value_not_mutated(self):
        """helper가 원래 dict의 byte 값을 변경하지 않음."""
        from app.views.visual_duplicate_review_dialog import _format_size_mb
        d = {"file_size": 2_097_152}
        _format_size_mb(d["file_size"])
        assert d["file_size"] == 2_097_152


# ---------------------------------------------------------------------------
# 2. _compute_group_reasons unit tests (no GUI needed)
# ---------------------------------------------------------------------------

class TestComputeGroupReasons:
    def _fn(self, files):
        from app.views.visual_duplicate_review_dialog import _compute_group_reasons
        return _compute_group_reasons(files)

    def test_returns_reason_for_each_file(self):
        files = [
            {"file_id": "a", "file_path": "/x/a.jpg", "_width": 800,  "_height": 600,  "file_size": 100, "file_format": "jpg"},
            {"file_id": "b", "file_path": "/x/b.jpg", "_width": 1920, "_height": 1080, "file_size": 200, "file_format": "jpg"},
        ]
        reasons = self._fn(files)
        assert "a" in reasons
        assert "b" in reasons
        assert isinstance(reasons["a"], str)
        assert isinstance(reasons["b"], str)

    def test_empty_files_returns_empty_dict(self):
        assert self._fn([]) == {}

    def test_exception_returns_empty_dict(self):
        """decide_visual_duplicate_group 예외 시 빈 dict 반환."""
        with patch(
            "app.views.visual_duplicate_review_dialog._compute_group_reasons",
            side_effect=Exception("boom"),
        ):
            # 패치된 버전은 항상 예외 → 실제 내부 fallback은 별도 검증
            pass

        # 실제 fallback: import 실패 시뮬레이션
        with patch(
            "core.visual_duplicate_decision.decide_visual_duplicate_group",
            side_effect=RuntimeError("policy error"),
        ):
            from app.views.visual_duplicate_review_dialog import _compute_group_reasons
            result = _compute_group_reasons([
                {"file_id": "x", "file_path": "/x/x.jpg", "_width": 100, "_height": 100,
                 "file_size": 100, "file_format": "jpg"},
            ])
        assert result == {}

    def test_high_res_keep_reason_mentions_resolution_or_pixel(self):
        files = [
            {"file_id": "lo", "file_path": "/x/lo.jpg", "_width": 400,  "_height": 300,  "file_size": 50, "file_format": "jpg"},
            {"file_id": "hi", "file_path": "/x/hi.jpg", "_width": 1920, "_height": 1080, "file_size": 50, "file_format": "jpg"},
        ]
        reasons = self._fn(files)
        # keep 후보(hi)의 reason에 해상도 관련 단어 포함
        hi_reason = reasons.get("hi", "")
        assert "해상도" in hi_reason or "px" in hi_reason


# ---------------------------------------------------------------------------
# 3. Reason 표시 (카드 내 reason label)
# ---------------------------------------------------------------------------

class TestReasonDisplay:
    def test_dialog_card_has_reason_label_for_auto_keep(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        groups = _make_groups(1)
        # fid_0_b가 더 높은 해상도 → keep 후보
        dlg = VisualDuplicateReviewDialog(groups)
        all_labels = dlg.findChildren(QLabel)
        reason_texts = [lbl.text() for lbl in all_labels if "추천 근거:" in lbl.text()]
        assert len(reason_texts) >= 1, (
            f"추천 근거 라벨이 없음. 전체 라벨: {[l.text() for l in all_labels]}"
        )

    def test_reason_label_contains_policy_hint(self, app):
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        groups = _make_groups(1)
        dlg = VisualDuplicateReviewDialog(groups)
        all_labels = dlg.findChildren(QLabel)
        reason_texts = " ".join(lbl.text() for lbl in all_labels if "추천 근거:" in lbl.text())
        # 해상도, webp, 복제, 크기, 알파벳 중 적어도 하나 언급되어야 함
        keywords = ["해상도", "px", "webp", "복제", "크기", "알파벳", "우선", "suffix"]
        assert any(kw in reason_texts for kw in keywords), (
            f"reason 라벨에 정책 힌트 키워드 없음: {reason_texts!r}"
        )


# ---------------------------------------------------------------------------
# 4. 자동 후보 vs 확정 분리
# ---------------------------------------------------------------------------

class TestAutoVsFinalSeparation:
    def test_initial_auto_decision_label_does_not_say_deleted_confirmed(self, app):
        """initial_decisions로 설정된 자동 추천 라벨에 '삭제됨' / '삭제 완료' 등
        최종 확정처럼 보이는 표현이 없어야 한다."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_groups(1),
            initial_decisions={"fid_0_a": "delete", "fid_0_b": "keep"},
        )
        all_labels = dlg.findChildren(QLabel)
        all_text = " ".join(lbl.text() for lbl in all_labels)
        forbidden = ["삭제됨", "삭제 완료", "확정 삭제", "삭제확정"]
        for phrase in forbidden:
            assert phrase not in all_text, (
                f"자동 추천 라벨에 final 표현 '{phrase}' 발견: {all_text!r}"
            )

    def test_auto_decision_label_uses_recommendation_prefix(self, app):
        """initial_decisions로 설정된 자동 추천 라벨에 '추천:' 접두어가 있어야 한다."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_groups(1),
            initial_decisions={"fid_0_a": "delete"},
        )
        lbl = dlg._decision_labels.get("fid_0_a")
        assert lbl is not None
        assert "추천:" in lbl.text(), (
            f"자동 추천 라벨에 '추천:' 접두어 없음: {lbl.text()!r}"
        )

    def test_manual_decision_label_uses_selection_suffix(self, app):
        """사용자가 직접 결정한 후 라벨에 '(선택)' 접미어가 있어야 한다."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(_make_groups(1))
        # 사용자가 직접 keep 클릭
        dlg._apply_group_decision("fid_0_a", "keep")

        lbl = dlg._decision_labels.get("fid_0_a")
        assert lbl is not None
        assert "(선택)" in lbl.text(), (
            f"사용자 선택 후 라벨에 '(선택)' 없음: {lbl.text()!r}"
        )

    def test_auto_then_manual_override_changes_label_source(self, app):
        """자동 추천 → 사용자 override 시 라벨이 '(선택)' 으로 바뀌어야 한다."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(
            _make_groups(1),
            initial_decisions={"fid_0_a": "delete"},
        )
        # 초기 상태: 자동 추천
        lbl = dlg._decision_labels["fid_0_a"]
        assert "추천:" in lbl.text()

        # 사용자 override
        dlg._apply_group_decision("fid_0_a", "keep")
        assert "(선택)" in lbl.text(), (
            f"override 후 '(선택)' 없음: {lbl.text()!r}"
        )


# ---------------------------------------------------------------------------
# 5. 안내문
# ---------------------------------------------------------------------------

class TestDialogGuidance:
    def test_dialog_has_review_guidance_label(self, app):
        """다이얼로그에 '자동 추천' 및 '검토' 관련 안내 텍스트가 존재해야 한다."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(_make_groups(1))
        assert hasattr(dlg, "_lbl_guide"), "_lbl_guide 위젯 없음"
        guide_text = dlg._lbl_guide.text()
        assert "자동 추천" in guide_text, (
            f"안내문에 '자동 추천' 없음: {guide_text!r}"
        )
        assert "검토" in guide_text, (
            f"안내문에 '검토' 없음: {guide_text!r}"
        )

    def test_guidance_mentions_delete_preview_step(self, app):
        """안내문이 삭제 미리보기 단계를 언급해야 한다."""
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog

        dlg = VisualDuplicateReviewDialog(_make_groups(1))
        guide_text = dlg._lbl_guide.text()
        assert "삭제" in guide_text, (
            f"안내문에 삭제 관련 안내 없음: {guide_text!r}"
        )
