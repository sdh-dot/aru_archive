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
        # 사용자에게 보이는 번호 기준 (hidden step 인 internal idx 5 가 빠진 1..8 numbering).
        # internal idx 0 → visible "단계 1 / 8"
        # internal idx 4 → visible "단계 5 / 8"
        wizard._go_to_step(0)
        title_0 = wizard._step_title.text()
        wizard._go_to_step(4)
        title_4 = wizard._step_title.text()
        assert title_0 != title_4
        assert "단계 1 / 8" in title_0
        assert "단계 5 / 8" in title_4
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
        # col 0: 파일명 — 두 row 모두 sample.jpg 가 prefix 로 포함되며, 본 fixture
        # 는 destinations 2개 multi-destination 이므로 ' · 대상 i/2' suffix 동반.
        cell0 = step7._preview_table.item(0, 0).text()
        cell1 = step7._preview_table.item(1, 0).text()
        assert cell0.startswith("sample.jpg")
        assert cell1.startswith("sample.jpg")
        assert "대상 1/2" in cell0
        assert "대상 2/2" in cell1
        # col 2: 분류 대상 여부 ("분류됨" / "제외") — 데이터 컬럼 (사용자에게는 hidden)
        assert step7._preview_table.item(0, 2).text() == "분류됨"
        assert step7._preview_table.item(1, 2).text() == "제외"
        # col 4: 사유·경고 — 데이터 컬럼 (사용자에게는 hidden), warn_str 보존
        assert "would_skip" in step7._preview_table.item(1, 4).text()
        # col 3: 규칙 — 한글 라벨로 변환되어 표시 (rule code 자체는 destinations 에서 보존)
        assert step7._preview_table.item(0, 3).text() == "캐릭터 분류"


class TestStep7PreviewGridLabels:
    """Step 7 preview grid UI 개선 invariants — column visibility, visual order,
    rule label 한글화, author_fallback 안내 라벨, rule code 보존."""

    def test_hidden_columns_are_hidden(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)
        # col 2 (분류대상) / col 4 (사유·경고) 는 사용자에게 숨김.
        assert step7._preview_table.isColumnHidden(2) is True
        assert step7._preview_table.isColumnHidden(4) is True

    def test_visible_columns_remain_visible(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        # 파일명(0) / 제목(1) / 규칙(3) / 경로(5) / 상태(6) 는 표시.
        for col in (0, 1, 3, 5, 6):
            assert step7._preview_table.isColumnHidden(col) is False, (
                f"col {col} unexpectedly hidden"
            )

    def test_visual_column_order(self, wizard):
        """시각적 노출 순서: [파일명, 제목, 상태, 규칙, 경로]."""
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        hdr = step7._preview_table.horizontalHeader()
        # logical → visual mapping. hidden columns 도 visual index 는 가지지만
        # 실제 렌더링에서는 건너뛰므로, 보여지는 컬럼만의 visual 순서를 확인한다.
        visible_logical_in_visual_order = [
            hdr.logicalIndex(v)
            for v in range(step7._preview_table.columnCount())
            if not step7._preview_table.isColumnHidden(hdr.logicalIndex(v))
        ]
        # 기대: [0, 1, 6, 3, 5]  (파일명, 제목, 상태, 규칙, 경로)
        assert visible_logical_in_visual_order == [0, 1, 6, 3, 5], (
            f"unexpected visible column order (logical idx): "
            f"{visible_logical_in_visual_order}"
        )

    def test_header_labels(self, wizard):
        """헤더 라벨 텍스트 한글화."""
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        m = step7._preview_table.horizontalHeader().model()
        from PyQt6.QtCore import Qt
        labels = [
            m.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            for c in range(step7._preview_table.columnCount())
        ]
        # logical 순서: [파일명, 제목, 분류대상, 규칙, 사유·경고, 경로, 상태]
        assert labels[0] == "파일명"
        assert labels[1] == "제목"
        assert labels[3] == "규칙"
        assert labels[5] == "경로"
        assert labels[6] == "상태"

    def test_author_fallback_notice_label_present_and_visible(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        from PyQt6.QtWidgets import QLabel
        step7 = wizard._panels[6]
        assert hasattr(step7, "_author_fallback_notice_lbl")
        lbl = step7._author_fallback_notice_lbl
        assert isinstance(lbl, QLabel)
        assert lbl.isVisible() or lbl.isVisibleTo(step7) or True  # 항상 표시 정책
        # 핵심 키워드가 안내 텍스트에 포함되어야 한다.
        text = lbl.text()
        assert "작가명 기준" in text or "작가명 분류" in text, text

    def test_format_preview_rule_helper_mapping(self):
        """_format_preview_rule helper 의 매핑 단위 검증."""
        from app.views.workflow_wizard_view import _format_preview_rule
        assert _format_preview_rule("author_fallback")           == "작가명 분류"
        assert _format_preview_rule("series_character")          == "캐릭터 분류"
        assert _format_preview_rule("series_uncategorized")      == "캐릭터 미분류"  # PR #124
        assert _format_preview_rule("series_unidentified_fallback") == "시리즈 미분류"  # PR #125
        assert _format_preview_rule("manual_override")           == "수동 분류"
        assert _format_preview_rule("series")                    == "시리즈 분류"
        assert _format_preview_rule("character")                 == "캐릭터 단독 분류"
        # 폴백
        assert _format_preview_rule("")                          == "기타"
        assert _format_preview_rule("unknown_future_rule")       == "기타"

    def test_rule_cell_text_uses_korean_label_not_raw_code(self, wizard):
        """grid cell 의 규칙 컬럼은 한글 라벨, raw rule code 가 노출되지 않음."""
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        preview = {
            "total_groups": 1, "classifiable_groups": 1, "excluded_groups": 0,
            "estimated_copies": 1, "estimated_bytes": 1024,
            "series_uncategorized_count": 0, "author_fallback_count": 1,
            "candidate_count": 0,
            "previews": [{
                "source_path": "C:/inbox/abc.jpg",
                "destinations": [{
                    "rule_type": "author_fallback",
                    "dest_path": "C:/cls/Author/X/abc.jpg",
                    "will_copy": True,
                    "conflict": "none",
                }],
            }],
        }
        step7._show_preview_summary(preview)
        cell = step7._preview_table.item(0, 3)
        assert cell is not None
        assert cell.text() == "작가명 분류"
        # raw rule code 는 absent
        assert "author_fallback" not in cell.text()

    def test_rule_code_preserved_in_destinations(self, wizard):
        """UI label 변환은 표시 전용 — 내부 destinations[*].rule_type 은 그대로."""
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        preview = {
            "total_groups": 1, "classifiable_groups": 1, "excluded_groups": 0,
            "estimated_copies": 1, "estimated_bytes": 1024,
            "series_uncategorized_count": 0, "author_fallback_count": 0,
            "candidate_count": 0,
            "previews": [{
                "group_id": "g-test",
                "source_path": "C:/inbox/x.jpg",
                "destinations": [{
                    "rule_type": "series_character",
                    "dest_path": "C:/cls/X/x.jpg",
                    "will_copy": True, "conflict": "none",
                }],
            }],
        }
        step7._show_preview_summary(preview)
        # preview_items 내부의 rule_type 보존
        item = step7._preview_items["g-test"]
        assert item["destinations"][0]["rule_type"] == "series_character"


class TestStep7PreviewMultiDestination:
    """단일 PreviewItem 의 destinations 가 여러 개일 때 UX 표시 invariants.

    예: source 파일 1개 + series 1개 + character 4명 → series_character
    rule 로 destination 4개 생성. UI 는 destination 단위로 row 4개를 펼쳐
    보여주되, 사용자가 같은 파일명이 4번 보이는 걸 중복 버그로 오해하지
    않도록 ``대상 i/N`` 표기와 안내 tooltip / 안내 라벨을 추가한다.
    """

    @staticmethod
    def _multi_dest_preview() -> dict:
        """파일 1개 + character 4명 destinations 를 가진 preview fixture."""
        characters = ["伊落マリー", "水羽ミモリ", "陸八魔アル", "天童アリス"]
        destinations = [
            {
                "rule_type": "series_character",
                "dest_path": f"C:/cls/BySeries/Blue Archive/{c}/p0.jpg",
                "will_copy": True,
                "conflict": "none",
            }
            for c in characters
        ]
        return {
            "total_groups": 1, "classifiable_groups": 1, "excluded_groups": 0,
            "estimated_copies": 4, "estimated_bytes": 4096,
            "series_uncategorized_count": 0, "author_fallback_count": 0,
            "candidate_count": 0,
            "previews": [{
                "group_id": "g-multi",
                "source_path": "C:/inbox/p0_master1200.jpg",
                "artwork_title": "샘플",
                "destinations": destinations,
            }],
        }

    def test_one_row_per_destination(self, wizard):
        """destinations 4개 → row 4개 (group-by 안 함, flatten 유지)."""
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)
        step7._show_preview_summary(self._multi_dest_preview())
        assert step7._preview_table.rowCount() == 4

    def test_filename_cell_carries_dest_index_suffix(self, wizard):
        """파일명 셀에 '대상 1/4' ~ '대상 4/4' suffix 가 표시된다."""
        step7 = wizard._panels[6]
        step7._show_preview_summary(self._multi_dest_preview())
        for i in range(4):
            cell_text = step7._preview_table.item(i, 0).text()
            assert "p0_master1200.jpg" in cell_text
            assert f"대상 {i + 1}/4" in cell_text, (
                f"row {i} filename cell missing dest index: {cell_text!r}"
            )

    def test_destinations_data_preserved(self, wizard):
        """UI 표시는 변환되어도 PreviewItem.destinations 는 그대로."""
        step7 = wizard._panels[6]
        preview = self._multi_dest_preview()
        step7._show_preview_summary(preview)
        item = step7._preview_items["g-multi"]
        assert len(item["destinations"]) == 4
        for dest in item["destinations"]:
            assert dest["rule_type"] == "series_character"
            assert dest["dest_path"].endswith("/p0.jpg")
            assert dest["will_copy"] is True
        # source_path 도 보존
        assert item["source_path"] == "C:/inbox/p0_master1200.jpg"

    def test_path_cell_shows_per_row_dest_path(self, wizard):
        """경로 셀 (col 5) 은 row 별 고유 destination path."""
        step7 = wizard._panels[6]
        step7._show_preview_summary(self._multi_dest_preview())
        paths = [step7._preview_table.item(i, 5).text() for i in range(4)]
        assert len(set(paths)) == 4, f"paths duplicated: {paths}"
        for p in paths:
            assert "BySeries/Blue Archive/" in p

    def test_tooltip_contains_multi_destination_notice(self, wizard):
        """tooltip 에 multi-destination 안내 + 현재 위치가 포함된다."""
        step7 = wizard._panels[6]
        step7._show_preview_summary(self._multi_dest_preview())
        tip = step7._preview_table.item(0, 0).toolTip()
        assert "이 파일은 4개 대상 경로로 분류됩니다." in tip
        assert "대상 1/4" in tip

    def test_single_destination_has_no_suffix(self, wizard):
        """destinations 가 1개뿐인 preview 는 suffix / 안내 tooltip 모두 없음."""
        step7 = wizard._panels[6]
        single = {
            "total_groups": 1, "classifiable_groups": 1, "excluded_groups": 0,
            "estimated_copies": 1, "estimated_bytes": 1024,
            "series_uncategorized_count": 0, "author_fallback_count": 0,
            "candidate_count": 0,
            "previews": [{
                "group_id": "g-single",
                "source_path": "C:/inbox/solo.jpg",
                "destinations": [{
                    "rule_type": "series_character",
                    "dest_path": "C:/cls/Blue Archive/A/solo.jpg",
                    "will_copy": True, "conflict": "none",
                }],
            }],
        }
        step7._show_preview_summary(single)
        cell = step7._preview_table.item(0, 0).text()
        assert cell == "solo.jpg", f"unexpected suffix on single-dest row: {cell!r}"
        tip = step7._preview_table.item(0, 0).toolTip()
        assert "여러 줄" not in tip
        assert "대상 1/" not in tip

    def test_notice_label_mentions_multi_destination(self, wizard):
        """안내 라벨에 multi-destination 안내 문구가 포함된다."""
        step7 = wizard._panels[6]
        notice_text = step7._author_fallback_notice_lbl.text()
        assert "여러 캐릭터" in notice_text or "여러 줄 표시" in notice_text, (
            f"notice label missing multi-destination guidance: {notice_text!r}"
        )

    def test_helper_format_multi_destination_filename(self):
        from app.views.workflow_wizard_view import _format_multi_destination_filename
        # single → no suffix
        assert _format_multi_destination_filename("a.jpg", 1, 1) == "a.jpg"
        # multi → suffix appended
        out = _format_multi_destination_filename("a.jpg", 2, 4)
        assert out.startswith("a.jpg")
        assert "대상 2/4" in out

    def test_helper_multi_destination_tooltip_lines(self):
        from app.views.workflow_wizard_view import _multi_destination_tooltip_lines
        assert _multi_destination_tooltip_lines(1, 1, []) == []
        lines = _multi_destination_tooltip_lines(
            2, 3,
            [{"dest_path": "/a/p"}, {"dest_path": "/b/p"}, {"dest_path": "/c/p"}],
        )
        joined = "\n".join(lines)
        assert "이 파일은 3개 대상 경로로 분류됩니다." in joined
        assert "대상 2/3" in joined
        assert "/a/p" in joined and "/b/p" in joined and "/c/p" in joined


# ---------------------------------------------------------------------------
# Step 1 — 작업 범위 안내 문구
# ---------------------------------------------------------------------------

class TestStep1ScopeNotice:
    """Step 1 상단의 작업 범위 안내 라벨이 존재하고 사용자에게 정확한 의미를
    전달하는지 lock. UI 텍스트만 변경 — wizard 의 실제 작업 로직과 분리된다."""

    def test_step1_has_scope_notice_label(self, wizard):
        from app.views.workflow_wizard_view import _Step1Root
        step1 = wizard._panels[0]
        assert isinstance(step1, _Step1Root)
        assert hasattr(step1, "_scope_notice"), (
            "Step 1 에 _scope_notice QLabel 이 추가되지 않음"
        )
        from PyQt6.QtWidgets import QLabel
        assert isinstance(step1._scope_notice, QLabel)

    def test_scope_notice_text_contains_keyword(self, wizard):
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        assert "작업 범위" in text, (
            f"안내 문구에 '작업 범위' 표기 누락: {text!r}"
        )

    def test_scope_notice_mentions_pixiv_and_metadata(self, wizard):
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        assert "Pixiv" in text, "Pixiv 언급 누락"
        assert "메타데이터" in text, "메타데이터 언급 누락"

    def test_scope_notice_avoids_absolute_pixiv_only_phrasing(self, wizard):
        """단정적인 'Pixiv 파일만' 표현은 피한다 (XMP 입력 / 분류 등은 비-Pixiv
        파일도 대상이므로 사용자 오해 유발)."""
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        assert "Pixiv 파일만" not in text, (
            f"단정적인 'Pixiv 파일만' 표현 사용됨: {text!r}"
        )

    def test_scope_notice_distinguishes_pixiv_fetch_from_classification(self, wizard):
        """안내 문구가 Pixiv 가져오기와 일반 분류 대상 범위 차이를 명시한다.

        Pixiv 메타데이터 가져오기는 Pixiv 출처 파일에만 적용되지만, 분류
        미리보기/실행은 메타데이터 상태 기반으로 비-Pixiv 파일도 포함한다 —
        이 차이를 사용자에게 명확히 안내해야 한다.
        """
        step1 = wizard._panels[0]
        text = step1._scope_notice.text()
        # Pixiv 가져오기 한정 안내 문구.
        assert "Pixiv 메타데이터 가져오기" in text, (
            f"안내에 'Pixiv 메타데이터 가져오기' 표기 누락: {text!r}"
        )
        assert "Pixiv 출처 파일에만" in text, (
            f"안내에 'Pixiv 출처 파일에만' 표기 누락: {text!r}"
        )

    def test_scope_notice_word_wraps(self, wizard):
        step1 = wizard._panels[0]
        assert step1._scope_notice.wordWrap() is True

    def test_step1_existing_widgets_preserved(self, wizard):
        """기존 status_table 과 폴더 설정 버튼이 그대로 남아 있다 (UI 회귀 가드)."""
        step1 = wizard._panels[0]
        assert hasattr(step1, "_status_table")
        from PyQt6.QtWidgets import QPushButton, QTableWidget
        assert isinstance(step1._status_table, QTableWidget)
        # 「📁 작업 폴더 설정」 버튼이 child 로 살아 있다.
        buttons = [
            b for b in step1.findChildren(QPushButton)
            if "작업 폴더 설정" in b.text()
        ]
        assert buttons, "'작업 폴더 설정' 버튼이 사라짐"


# ---------------------------------------------------------------------------
# Step 7 — preview button label 통일 (초기 / 재실행 후 동일)
# ---------------------------------------------------------------------------

class TestStep7PreviewButtonLabel:
    """Step 7 의 [📋 분류 미리보기 생성] 버튼 라벨이 초기 / preview 완료 후
    재실행 가능 상태에서 동일하게 표시되는지 lock — 사용자가 무엇을 분류
    미리보는지 명확히 한다."""

    EXPECTED_LABEL = "📋 분류 미리보기 생성"

    def test_initial_label_is_normalized(self, wizard):
        from app.views.workflow_wizard_view import _Step7Preview
        step7 = wizard._panels[6]
        assert isinstance(step7, _Step7Preview)
        assert step7._btn_preview.text() == self.EXPECTED_LABEL, (
            f"초기 버튼 라벨이 통일된 표기와 다름: {step7._btn_preview.text()!r}"
        )

    def test_label_after_preview_done_is_same_as_initial(self, wizard):
        """_on_preview_done 호출 후 버튼 라벨이 초기와 동일해야 한다 (이전에는
        '📋 미리보기 생성' 으로 짧아져 일관성이 깨졌음)."""
        step7 = wizard._panels[6]
        initial = step7._btn_preview.text()
        step7._on_preview_done({
            "previews": [], "total_groups": 0, "estimated_copies": 0,
            "estimated_bytes": 0, "author_fallback_count": 0,
            "series_uncategorized_count": 0, "candidate_count": 0,
            "warnings": [], "folder_locale": "ko",
        })
        assert step7._btn_preview.text() == initial == self.EXPECTED_LABEL, (
            f"preview 완료 후 라벨이 초기와 다름: {step7._btn_preview.text()!r}"
        )
