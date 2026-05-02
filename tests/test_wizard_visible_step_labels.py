"""Wizard 상단 step 표시 번호/라벨 helper 회귀 테스트.

내부 stack 은 9개 패널을 그대로 유지하되, 사용자에게는 hidden step (현재 internal
index 5 = 태그 재분류 자동 단계) 을 제외한 1..8 visible numbering 으로 보여야
한다. 이 테스트는 helper 함수들의 결정성과 wizard 의 실제 헤더/타이틀 출력이
일치하는지 lock 한다.

핵심 invariant:
- 내부 stack 길이 == 9 유지
- 내부 hidden index 집합 == {5}
- visible 총 단계 수 == 8
- hidden step 은 visible_number / button_label 모두 None
- visible 6 = internal 6 (hidden index 5 가 빠지므로 internal 6 부터 visible 6)
- 헤더 버튼 레이블이 한국어 + visible 번호로 표시
- 단계 제목 바가 "단계 N / 8: ..." 형식
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from app.views.workflow_wizard_view import (
    _HIDDEN_STEP_INDICES,
    _STEPS,
    _total_visible_steps,
    _visible_step_button_label,
    _visible_step_number,
    _visible_step_title_text,
)


# ---------------------------------------------------------------------------
# 구조 invariant
# ---------------------------------------------------------------------------

class TestStackStructureUnchanged:
    def test_internal_stack_has_nine_steps(self):
        """내부 stack 길이는 9 그대로 유지."""
        assert len(_STEPS) == 9

    def test_hidden_step_indices_exactly_index_five(self):
        """hidden 은 internal index 5 (태그 재분류) 한 곳만."""
        assert _HIDDEN_STEP_INDICES == {5}

    def test_total_visible_steps_is_eight(self):
        assert _total_visible_steps() == 8


# ---------------------------------------------------------------------------
# _visible_step_number
# ---------------------------------------------------------------------------

class TestVisibleStepNumber:
    def test_visible_steps_numbered_one_through_eight(self):
        """visible step 만 1..8 번호."""
        expected = {
            0: 1,   # 작업 폴더
            1: 2,   # 이미지 스캔
            2: 3,   # 메타데이터 확인
            3: 4,   # 메타데이터 보강
            4: 5,   # 분류 기준 선택
            6: 6,   # 분류 미리보기 (internal 6, hidden 5 가 빠지므로 visible 6)
            7: 7,   # 분류 실행
            8: 8,   # 결과 / 되돌리기
        }
        for internal_idx, visible_num in expected.items():
            assert _visible_step_number(internal_idx) == visible_num, (
                f"internal {internal_idx} → expected visible {visible_num}, "
                f"got {_visible_step_number(internal_idx)}"
            )

    def test_hidden_step_returns_none(self):
        assert _visible_step_number(5) is None

    def test_out_of_range_returns_none(self):
        assert _visible_step_number(-1) is None
        assert _visible_step_number(9) is None
        assert _visible_step_number(100) is None


# ---------------------------------------------------------------------------
# _visible_step_button_label
# ---------------------------------------------------------------------------

class TestVisibleStepButtonLabel:
    def test_button_label_uses_visible_number_and_korean(self):
        # internal 0 → "1. 작업 폴더"
        assert _visible_step_button_label(0) == "1. 작업 폴더"
        # internal 4 → "5. 분류 기준 선택"
        assert _visible_step_button_label(4) == "5. 분류 기준 선택"
        # internal 6 (hidden 5 가 빠진 후 visible 6) → "6. 분류 미리보기"
        assert _visible_step_button_label(6) == "6. 분류 미리보기"
        assert _visible_step_button_label(8) == "8. 결과 / 되돌리기"

    def test_hidden_step_returns_none(self):
        assert _visible_step_button_label(5) is None

    def test_no_english_label_in_visible_buttons(self):
        """visible 버튼에 영어 라벨이 섞이지 않아야 한다."""
        for internal_idx in range(len(_STEPS)):
            label = _visible_step_button_label(internal_idx)
            if label is None:
                continue
            # 한국어 가나다 또는 숫자/공백/구두점만 (영문 알파벳 0개)
            for ch in label:
                # ASCII 알파벳이 있으면 fail (단, 숫자/구두점/공백은 OK)
                assert not ch.isalpha() or not ch.isascii(), (
                    f"internal {internal_idx} 라벨에 영어 알파벳: {label!r}"
                )

    def test_no_visible_number_gap(self):
        """visible 버튼 라벨의 번호가 1..8 연속이어야 한다."""
        nums = []
        for internal_idx in range(len(_STEPS)):
            label = _visible_step_button_label(internal_idx)
            if label is None:
                continue
            # "N. 한국어" 형식에서 N 추출
            num_str = label.split(".")[0].strip()
            nums.append(int(num_str))
        assert nums == list(range(1, _total_visible_steps() + 1))


# ---------------------------------------------------------------------------
# _visible_step_title_text
# ---------------------------------------------------------------------------

class TestVisibleStepTitleText:
    def test_visible_step_title_format(self):
        title = _visible_step_title_text(0)
        assert "단계 1 / 8" in title
        assert "작업 폴더" in title

    def test_visible_step_title_for_internal_six(self):
        # hidden 5 가 빠진 후 internal 6 → visible 6
        title = _visible_step_title_text(6)
        assert "단계 6 / 8" in title
        assert "분류 미리보기" in title

    def test_hidden_step_title_marked_as_auto(self):
        title = _visible_step_title_text(5)
        assert "자동 진행" in title or "자동" in title
        assert "Step" not in title  # 영어 prefix 제거

    def test_no_step_word_in_titles(self):
        """기존 영어 'Step N:' prefix 가 더 이상 사용자 출력에 노출되지 않는다."""
        for idx in range(len(_STEPS)):
            assert "Step " not in _visible_step_title_text(idx), (
                f"internal {idx} 제목에 영어 'Step ' 잔존: "
                f"{_visible_step_title_text(idx)!r}"
            )


# ---------------------------------------------------------------------------
# wizard 실제 출력 검증
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wizard(qapp, tmp_path):
    from app.views.workflow_wizard_view import WorkflowWizardView
    from db.database import initialize_database

    db = tmp_path / "wizard_visible_steps.db"

    def factory():
        return initialize_database(str(db))

    config = {
        "data_dir": "", "inbox_dir": "", "classified_dir": "",
        "managed_dir": "", "db": {"path": ""},
    }
    w = WorkflowWizardView(factory, config, "config.json")
    yield w
    w.close()


class TestWizardActualHeaderOutput:
    def test_header_buttons_use_visible_numbering(self, wizard):
        # _step_btns 9개 모두 존재 (내부 구조 유지)
        assert len(wizard._step_btns) == 9
        # hidden step 버튼은 보이지 않아야 함
        assert not wizard._step_btns[5].isVisible()
        # visible step 버튼들은 visible numbering + 한국어
        assert wizard._step_btns[0].text() == "1. 작업 폴더"
        assert wizard._step_btns[4].text() == "5. 분류 기준 선택"
        assert wizard._step_btns[6].text() == "6. 분류 미리보기"
        assert wizard._step_btns[8].text() == "8. 결과 / 되돌리기"

    def test_step_title_uses_visible_numbering(self, wizard):
        wizard._go_to_step(0)
        assert "단계 1 / 8" in wizard._step_title.text()
        assert "작업 폴더" in wizard._step_title.text()

        wizard._go_to_step(6)
        # internal 6 → visible 6
        assert "단계 6 / 8" in wizard._step_title.text()
        assert "분류 미리보기" in wizard._step_title.text()

        wizard._go_to_step(0)  # restore

    def test_navigation_skips_hidden_step(self, wizard):
        """internal go_to_step(5) 호출 시 hidden 패널 자동 skip — 기존 동작 유지."""
        wizard._go_to_step(4)  # 분류 기준 선택
        assert wizard._current == 4
        wizard._go_to_step(5)  # hidden — forward direction → 6
        assert wizard._current == 6
        # 역방향
        wizard._go_to_step(5)  # hidden — backward → 4
        assert wizard._current == 4
        wizard._go_to_step(0)  # restore

    def test_internal_stack_count_unchanged(self, wizard):
        assert wizard._stack.count() == 9
        assert len(wizard._panels) == 9
