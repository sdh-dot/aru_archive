"""core.visual_duplicate_decision pure function 단위 테스트.

검증:
- has_copy_suffix 정규식 분기
- build_visual_duplicate_keep_score 우선순위 5단계
- decide_visual_duplicate_group 결과 invariant (빈 그룹 → [], 그 외 keep ≥ 1)
- decide_visual_duplicate_groups 다중 그룹 처리
- 자동 선택 로직이 file system을 변경하지 않음
- 손상/누락 데이터 (file_size None, file_path 부재, dimensions 0) 안전 fallback

외부 의존:
- 실제 파일/이미지 호출 0건 — _width/_height를 item dict에 미리 주입해
  PIL.Image.open 우회 (테스트 hook).
- _safe_dimensions를 직접 검증할 때만 PIL이 필요한데, 이 모듈은
  존재하지 않는 file_path를 전달해 fallback (0, 0)을 반환하므로
  PIL 호출도 silent.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.visual_duplicate_decision import (
    VisualDuplicateDecision,
    build_visual_duplicate_keep_score,
    decide_visual_duplicate_group,
    decide_visual_duplicate_groups,
    has_copy_suffix,
)


# ---------------------------------------------------------------------------
# 헬퍼: 합성 item dict (파일 IO 회피)
# ---------------------------------------------------------------------------

def _item(
    file_id: str,
    *,
    width: int = 0,
    height: int = 0,
    ext: str = "jpg",
    size: int | None = 0,
    name: str | None = None,
) -> dict:
    """테스트용 item dict. _width/_height를 주입해 PIL 호출을 우회한다."""
    fname = name if name is not None else f"{file_id}.{ext}"
    return {
        "file_id":     file_id,
        "file_path":   f"/test/{fname}",
        "file_format": ext,
        "file_size":   size,
        "_width":      width,
        "_height":     height,
    }


# ---------------------------------------------------------------------------
# 1. has_copy_suffix
# ---------------------------------------------------------------------------

class TestHasCopySuffix:
    def test_simple_filename_returns_false(self):
        assert has_copy_suffix("image.jpg") is False

    def test_space_paren_digit_returns_true(self):
        assert has_copy_suffix("image (1).jpg") is True

    def test_no_space_paren_digits_returns_true(self):
        assert has_copy_suffix("image(10).png") is True

    def test_paren_with_word_returns_false(self):
        assert has_copy_suffix("image (Final).jpg") is False

    def test_full_path_uses_basename_stem(self):
        assert has_copy_suffix("/some/dir/image (2).jpg") is True
        assert has_copy_suffix("/some/dir/image.jpg") is False

    def test_paren_in_middle_returns_false(self):
        # "(123)image.jpg" — stem 끝이 아니라 시작에 있음
        assert has_copy_suffix("(123)image.jpg") is False


# ---------------------------------------------------------------------------
# 2. 해상도 우선
# ---------------------------------------------------------------------------

class TestResolutionPriority:
    def test_higher_resolution_keeps(self):
        small = _item("a", width=800,  height=600)
        big   = _item("b", width=1920, height=1080)
        decisions = decide_visual_duplicate_group([small, big])
        kept = [d for d in decisions if d.decision == "keep"]
        deleted = [d for d in decisions if d.decision == "delete"]
        assert len(kept) == 1
        assert kept[0].file_id == "b"
        assert len(deleted) == 1
        assert deleted[0].file_id == "a"


# ---------------------------------------------------------------------------
# 3. webp 우선 (해상도 동일)
# ---------------------------------------------------------------------------

class TestWebpPriority:
    def test_webp_kept_over_jpg_at_same_resolution(self):
        jpg  = _item("j", width=1024, height=1024, ext="jpg",  size=200_000)
        webp = _item("w", width=1024, height=1024, ext="webp", size=200_000)
        decisions = decide_visual_duplicate_group([jpg, webp])
        kept = [d for d in decisions if d.decision == "keep"]
        assert len(kept) == 1
        assert kept[0].file_id == "w"


# ---------------------------------------------------------------------------
# 4. (숫자) suffix 없는 쪽 우선
# ---------------------------------------------------------------------------

class TestCopySuffixPriority:
    def test_no_copy_suffix_kept(self):
        normal = _item("n", width=1024, height=768, ext="jpg",
                       size=200_000, name="image.jpg")
        copy   = _item("c", width=1024, height=768, ext="jpg",
                       size=200_000, name="image (1).jpg")
        decisions = decide_visual_duplicate_group([normal, copy])
        kept = [d for d in decisions if d.decision == "keep"]
        assert len(kept) == 1
        assert kept[0].file_id == "n"


# ---------------------------------------------------------------------------
# 5. file_size tie-breaker
# ---------------------------------------------------------------------------

class TestFileSizePriority:
    def test_larger_file_size_kept_when_otherwise_tied(self):
        small = _item("s", width=1024, height=768, ext="jpg",
                      size=100_000, name="image.jpg")
        large = _item("l", width=1024, height=768, ext="jpg",
                      size=500_000, name="image.jpg")
        # Note: same filename — full tie except file_size
        decisions = decide_visual_duplicate_group([small, large])
        kept = [d for d in decisions if d.decision == "keep"]
        assert len(kept) == 1
        assert kept[0].file_id == "l"


# ---------------------------------------------------------------------------
# 6. filename alphabetical tie-breaker
# ---------------------------------------------------------------------------

class TestFilenameTieBreaker:
    def test_alphabetical_first_kept_in_full_tie(self):
        a = _item("a", width=1024, height=768, ext="jpg",
                  size=200_000, name="a.jpg")
        b = _item("b", width=1024, height=768, ext="jpg",
                  size=200_000, name="b.jpg")
        decisions = decide_visual_duplicate_group([b, a])  # 입력 순서 뒤섞기
        kept = [d for d in decisions if d.decision == "keep"]
        assert len(kept) == 1
        assert kept[0].file_id == "a"


# ---------------------------------------------------------------------------
# 7. 빈 그룹 / 단일 항목
# ---------------------------------------------------------------------------

class TestEmptyAndSingle:
    def test_empty_group_returns_empty(self):
        assert decide_visual_duplicate_group([]) == []

    def test_single_item_group_returns_one_keep(self):
        only = _item("solo", width=800, height=600)
        decisions = decide_visual_duplicate_group([only])
        assert len(decisions) == 1
        assert decisions[0].file_id == "solo"
        assert decisions[0].decision == "keep"


# ---------------------------------------------------------------------------
# 8. 다중 그룹 처리
# ---------------------------------------------------------------------------

class TestMultipleGroups:
    def test_decide_groups_returns_list_per_group(self):
        groups = [
            {
                "files": [
                    _item("g1a", width=800,  height=600),
                    _item("g1b", width=1920, height=1080),
                ],
                "distance": 3,
            },
            {
                "files": [
                    _item("g2a", width=1024, height=1024, ext="jpg"),
                    _item("g2b", width=1024, height=1024, ext="webp"),
                ],
                "distance": 2,
            },
            {
                "files": [_item("g3a", width=600, height=400)],
                "distance": 0,
            },
        ]
        result = decide_visual_duplicate_groups(groups)
        assert len(result) == 3
        for group_decisions in result:
            keeps = [d for d in group_decisions if d.decision == "keep"]
            assert len(keeps) >= 1, "그룹마다 keep ≥ 1 보장이 깨짐"
        # 각 그룹 keep 후보 검증
        assert next(d for d in result[0] if d.decision == "keep").file_id == "g1b"
        assert next(d for d in result[1] if d.decision == "keep").file_id == "g2b"
        assert next(d for d in result[2] if d.decision == "keep").file_id == "g3a"


# ---------------------------------------------------------------------------
# 9. file system 변경 없음
# ---------------------------------------------------------------------------

class TestNoFileSystemMutation:
    def test_decide_does_not_call_os_remove_or_unlink(self):
        items = [
            _item("a", width=800,  height=600),
            _item("b", width=1024, height=768),
            _item("c", width=1024, height=768, ext="webp"),
        ]
        with patch("os.remove") as os_remove, \
             patch("pathlib.Path.unlink") as path_unlink, \
             patch("os.unlink") as os_unlink:
            decisions = decide_visual_duplicate_group(items)
            decisions_multi = decide_visual_duplicate_groups([
                {"files": items, "distance": 1},
            ])
        assert os_remove.call_count == 0, "os.remove 호출됨 — 파일 변경 위험"
        assert path_unlink.call_count == 0, "Path.unlink 호출됨 — 파일 변경 위험"
        assert os_unlink.call_count == 0, "os.unlink 호출됨 — 파일 변경 위험"
        # 결정 자체는 정상 반환
        assert len(decisions) == 3
        assert sum(1 for d in decisions if d.decision == "keep") == 1
        assert len(decisions_multi) == 1


# ---------------------------------------------------------------------------
# 10. None / missing 필드 안전 처리
# ---------------------------------------------------------------------------

class TestMissingFieldsFallback:
    def test_missing_file_size_treated_as_zero(self):
        # None size + 동일 해상도 → file_size sub-key가 0으로 정규화됨
        a = _item("a", width=1024, height=768, ext="jpg",
                  size=None, name="image.jpg")
        b = _item("b", width=1024, height=768, ext="jpg",
                  size=100_000, name="image.jpg")
        decisions = decide_visual_duplicate_group([a, b])
        kept = [d for d in decisions if d.decision == "keep"]
        # b가 file_size=100_000으로 더 크므로 keep
        assert kept[0].file_id == "b"

    def test_missing_dimensions_does_not_raise(self):
        # _width/_height 부재 + 존재하지 않는 file_path → (0, 0) fallback
        item = {
            "file_id":     "missing",
            "file_path":   "/nonexistent/path/img.jpg",
            "file_format": "jpg",
            "file_size":   100,
        }
        # 예외 없이 score 생성되어야 함
        score = build_visual_duplicate_keep_score(item)
        assert isinstance(score, tuple)
        assert score[0] == 0  # -pixels = 0 (둘 다 0)

    def test_missing_path_returns_zero_dimensions(self):
        item = {
            "file_id":     "x",
            "file_path":   "",
            "file_format": "jpg",
            "file_size":   0,
        }
        score = build_visual_duplicate_keep_score(item)
        assert score[0] == 0

    def test_decision_dataclass_is_frozen(self):
        item = _item("a", width=100, height=100)
        decisions = decide_visual_duplicate_group([item])
        d = decisions[0]
        assert isinstance(d, VisualDuplicateDecision)
        with pytest.raises(Exception):
            d.decision = "delete"  # frozen → FrozenInstanceError


# ---------------------------------------------------------------------------
# 11. reason 문자열 sanity (UI 표시 가능)
# ---------------------------------------------------------------------------

class TestReasonStringsArePresent:
    def test_keep_reason_non_empty(self):
        item = _item("a", width=800, height=600)
        decisions = decide_visual_duplicate_group([item])
        assert decisions[0].reason
        assert isinstance(decisions[0].reason, str)

    def test_delete_reason_mentions_resolution_when_lower(self):
        small = _item("s", width=400, height=300)
        big   = _item("b", width=1920, height=1080)
        decisions = decide_visual_duplicate_group([small, big])
        deleted = next(d for d in decisions if d.decision == "delete")
        # 정확한 문구 의존성을 피하되 "해상도" 또는 px 표기는 포함되어야
        assert "해상도" in deleted.reason or "px" in deleted.reason
