"""Step 7 preview 우측 패널 layout 안정화 + 파일명/태그 표시 회귀 테스트.

핵심 invariant:
- 우측 thumb 패널에 image / filename / tag area 가 모두 존재
- 태그 영역은 fixed maximum height + scroll 가능 → 태그가 많아도 layout 안정
- 태그가 없는 row 에서는 "태그 없음" fallback 표시
- preview row data / destination path / classification result 변경 없음
- 테이블 minimum width 가 과도하게 크지 않음 (700) → splitter 가 thumb panel 에
  적절한 폭을 줄 수 있음
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHeaderView, QLabel, QScrollArea


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_wizard_stub(tmp_path):
    from db.database import initialize_database

    db_path = str(tmp_path / "preview_layout_tags.db")
    init = initialize_database(db_path)
    init.close()
    config = {
        "classified_dir": str(tmp_path / "Classified"),
        "classification": {"folder_locale": "ko"},
    }

    class _MockWizard:
        _config = config

        def _conn_factory(self):
            return initialize_database(db_path)

        def _db_path(self):
            return db_path

    return _MockWizard()


@pytest.fixture
def step7(qapp, tmp_path):
    from app.views.workflow_wizard_view import _Step7Preview
    step = _Step7Preview(_make_wizard_stub(tmp_path))
    step.show()
    yield step
    step.close()


# ---------------------------------------------------------------------------
# Preview dict 헬퍼
# ---------------------------------------------------------------------------

def _make_preview(
    *,
    group_id: str = "g1",
    source_path: str = "/inbox/12345_p0.jpg",
    title: str = "Test Title",
    will_copy: bool = True,
    rule_type: str = "series_character",
    dest_path: str = "/classified/Blue Archive/Aru/12345_p0.jpg",
    classification_info: dict | None = None,
    fallback_tags: list | None = None,
    inferred_series_evidence: list | None = None,
) -> dict:
    return {
        "group_id": group_id,
        "source_path": source_path,
        "artwork_title": title,
        "fallback_tags": fallback_tags or [],
        "classification_info": classification_info,
        "inferred_series_evidence": inferred_series_evidence or [],
        "destinations": [
            {
                "will_copy": will_copy,
                "rule_type": rule_type,
                "dest_path": dest_path,
                "conflict": None,
                "used_fallback": False,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Layout 구조
# ---------------------------------------------------------------------------

class TestThumbPanelLayout:
    def test_thumb_image_label_exists(self, step7):
        assert hasattr(step7, "_thumb_lbl")
        assert isinstance(step7._thumb_lbl, QLabel)

    def test_filename_label_exists(self, step7):
        assert hasattr(step7, "_thumb_name_lbl")
        assert isinstance(step7._thumb_name_lbl, QLabel)

    def test_tags_label_exists(self, step7):
        assert hasattr(step7, "_thumb_tags_lbl")
        assert isinstance(step7._thumb_tags_lbl, QLabel)
        assert step7._thumb_tags_lbl.wordWrap()

    def test_tags_scroll_area_exists_with_max_height(self, step7):
        assert hasattr(step7, "_thumb_tags_scroll")
        scroll = step7._thumb_tags_scroll
        assert isinstance(scroll, QScrollArea)
        # fixed maximum height 로 layout 보호
        max_h = scroll.maximumHeight()
        assert 0 < max_h <= 200, (
            f"태그 scroll area maximum height 가 너무 크거나 무제한: {max_h}"
        )

    def test_tags_label_initial_fallback_text(self, step7):
        # 초기 selection 없음 → "태그 없음" placeholder
        assert step7._thumb_tags_lbl.text() == "태그 없음"


class TestTableMinimumWidthAdjusted:
    def test_table_minimum_width_relaxed(self, step7):
        # splitter 가 우측 thumb 패널에 충분한 폭을 주도록 minimum 을 줄였음.
        # 컬럼 합 ~690 + stretch col 5 → 700 이면 모든 column 이 표시되면서
        # splitter 유연성 확보.
        assert step7._preview_table.minimumWidth() <= 720, (
            f"테이블 최소폭이 과도함: {step7._preview_table.minimumWidth()}"
        )

    def test_column_count_unchanged(self, step7):
        # 7 column 구조는 변경하지 않는다 (PR 안전 invariant).
        assert step7._preview_table.columnCount() == 7

    def test_stretch_column_unchanged(self, step7):
        hdr = step7._preview_table.horizontalHeader()
        assert hdr.sectionResizeMode(5) == QHeaderView.ResizeMode.Stretch


# ---------------------------------------------------------------------------
# 태그 수집 helper
# ---------------------------------------------------------------------------

class TestCollectPreviewTags:
    def test_none_preview_returns_empty(self, qapp):
        from app.views.workflow_wizard_view import _Step7Preview
        assert _Step7Preview._collect_preview_tags(None) == []

    def test_empty_preview_returns_empty(self, qapp):
        from app.views.workflow_wizard_view import _Step7Preview
        assert _Step7Preview._collect_preview_tags({}) == []

    def test_classification_info_candidate_source_tags(self, qapp):
        from app.views.workflow_wizard_view import _Step7Preview
        preview = {
            "classification_info": {
                "candidate_source_tags": ["tag1", "tag2", "tag3"],
            },
        }
        assert _Step7Preview._collect_preview_tags(preview) == ["tag1", "tag2", "tag3"]

    def test_fallback_tags_included(self, qapp):
        from app.views.workflow_wizard_view import _Step7Preview
        preview = {"fallback_tags": ["Blue Archive", "Aru"]}
        assert _Step7Preview._collect_preview_tags(preview) == ["Blue Archive", "Aru"]

    def test_inferred_series_evidence_canonical(self, qapp):
        from app.views.workflow_wizard_view import _Step7Preview
        preview = {
            "inferred_series_evidence": [
                {"canonical": "Blue Archive", "source": "inferred_from_character"},
                {"canonical": "Other Series"},
            ],
        }
        assert _Step7Preview._collect_preview_tags(preview) == [
            "Blue Archive", "Other Series",
        ]

    def test_dedupe_across_sources_preserves_order(self, qapp):
        from app.views.workflow_wizard_view import _Step7Preview
        preview = {
            "classification_info": {"candidate_source_tags": ["A", "B"]},
            "fallback_tags": ["B", "C"],
            "inferred_series_evidence": [{"canonical": "A"}, {"canonical": "D"}],
        }
        # A, B, C, D — 첫 등장 순서, dedupe 적용
        assert _Step7Preview._collect_preview_tags(preview) == ["A", "B", "C", "D"]

    def test_empty_strings_skipped(self, qapp):
        from app.views.workflow_wizard_view import _Step7Preview
        preview = {
            "classification_info": {"candidate_source_tags": ["", "  ", None, "real"]},
        }
        assert _Step7Preview._collect_preview_tags(preview) == ["real"]


# ---------------------------------------------------------------------------
# Row selection → tag display
# ---------------------------------------------------------------------------

class TestRowSelectionUpdatesTags:
    def test_select_row_with_classification_info_tags_shows_them(self, step7):
        preview = _make_preview(
            group_id="g_with_tags",
            classification_info={
                "candidate_source_tags": ["tagA", "tagB", "tagC"],
            },
        )
        step7._populate_preview_table([preview])
        step7._on_preview_row_changed(0)
        text = step7._thumb_tags_lbl.text()
        assert "tagA" in text
        assert "tagB" in text
        assert "tagC" in text

    def test_select_row_without_tags_shows_fallback(self, step7):
        # classification_info=None / fallback_tags=[] / inferred=[] 모두 비어있음
        step7._populate_preview_table([_make_preview(group_id="empty")])
        step7._on_preview_row_changed(0)
        assert step7._thumb_tags_lbl.text() == "태그 없음"

    def test_filename_label_updates_on_row_change(self, step7):
        step7._populate_preview_table([
            _make_preview(group_id="g1", source_path="/inbox/aaa.jpg"),
            _make_preview(group_id="g2", source_path="/inbox/bbb.jpg"),
        ])
        step7._on_preview_row_changed(0)
        assert step7._thumb_name_lbl.text() == "aaa.jpg"
        step7._on_preview_row_changed(1)
        assert step7._thumb_name_lbl.text() == "bbb.jpg"

    def test_invalid_row_index_resets_tags_to_fallback(self, step7):
        # 빈 상태에서 -1 row → 모든 라벨 fallback
        step7._populate_preview_table([])
        step7._on_preview_row_changed(-1)
        assert step7._thumb_name_lbl.text() == ""
        assert step7._thumb_tags_lbl.text() == "태그 없음"


class TestManyTagsDoNotInflatePanel:
    def test_many_tags_constrained_by_scroll_max_height(self, step7):
        # 50개 태그를 가진 row → maximumHeight 제한이 유지되는지 확인.
        many_tags = [f"tag_{i:02d}" for i in range(50)]
        preview = _make_preview(
            group_id="big",
            classification_info={"candidate_source_tags": many_tags},
        )
        step7._populate_preview_table([preview])
        step7._on_preview_row_changed(0)

        # scroll area 의 maximumHeight 는 절대 변하지 않음
        assert step7._thumb_tags_scroll.maximumHeight() <= 200
        # 모든 50개 태그가 label text 에 들어 있음 (scroll 로 보임)
        text = step7._thumb_tags_lbl.text()
        assert "tag_00" in text
        assert "tag_49" in text


# ---------------------------------------------------------------------------
# 회귀 — preview row data / destination path 변경 없음
# ---------------------------------------------------------------------------

class TestPreviewDataUnchanged:
    def test_preview_rows_only_contain_safe_keys(self, step7):
        preview = _make_preview(
            group_id="g1",
            classification_info={"candidate_source_tags": ["tagA"]},
        )
        step7._populate_preview_table([preview])
        # _preview_rows 의 키 set 은 source_path / group_id / title 만 (이번 PR 에서
        # 새 키 추가하지 않음 — preview dict 는 _preview_items 캐시로 따로 보존).
        row = step7._preview_rows[0]
        assert set(row.keys()) == {"source_path", "group_id", "title"}

    def test_destination_path_unchanged_by_tag_display(self, step7):
        dest = "/classified/Foo/Bar/x.jpg"
        preview = _make_preview(group_id="g1", dest_path=dest)
        step7._populate_preview_table([preview])
        step7._on_preview_row_changed(0)
        # 분류 경로 컬럼 (col 5) 은 입력값 그대로
        assert step7._preview_table.item(0, 5).text() == dest
        # 분류대상 컬럼 (col 2) 도 will_copy 그대로
        assert step7._preview_table.item(0, 2).text() == "분류됨"

    def test_classification_info_dict_not_mutated(self, step7):
        ci = {"candidate_source_tags": ["x", "y"]}
        preview = _make_preview(group_id="g1", classification_info=ci)
        step7._populate_preview_table([preview])
        step7._on_preview_row_changed(0)
        # 원본 dict 는 그대로
        assert ci == {"candidate_source_tags": ["x", "y"]}

    def test_fallback_tags_list_not_mutated(self, step7):
        ft = ["Blue Archive"]
        preview = _make_preview(group_id="g1", fallback_tags=ft)
        step7._populate_preview_table([preview])
        step7._on_preview_row_changed(0)
        assert ft == ["Blue Archive"]
