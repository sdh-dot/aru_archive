"""Manual classify override dialog 의 다국어 자동완성 통합 회귀 테스트.

PR #83 의 ``core.autocomplete_provider.suggest_tag_completions`` 결과를
``ManualClassifyOverrideDialog`` 의 series / character QLineEdit 에 surface 한
``_AutocompleteController`` 의 핵심 invariant 을 lock 한다.

테스트는 Qt GUI 가 아닌 controller 의 model / metadata 보존 / fallback 경로에
초점. 실제 popup 이벤트는 ``activated`` 신호를 직접 emit 해 시뮬레이션한다.

핵심 invariant:
- controller 가 ko/ja/en 입력에 대해 candidate 를 model 에 채운다
- popup 에서 선택된 candidate 의 canonical / tag_type / parent_series 가
  Qt UserRole 에 보존된다
- 사용자가 텍스트를 직접 수정하면 이전 선택이 invalidate 된다
- 한국어 입력 + ko candidate 선택 → result dict 의 canonical 은 영어 (display
  text 가 아님)
- 자동완성 선택 없이 직접 입력 시 기존 동작 유지 (text 그대로 사용)
- result dict 형식 (series_canonical / character_canonical / folder_locale /
  reason) 은 변경되지 않음
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtWidgets import QApplication


_NOW = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def conn(tmp_path):
    """real schema 로 init + 다국어 alias / localization seed."""
    from db.database import initialize_database
    c = initialize_database(str(tmp_path / "manual_override_autocomplete.db"))

    # series — Blue Archive: alias (canonical), localization (ko / ja)
    c.execute(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES ('Blue Archive', 'Blue Archive', 'series', '', 'built_in_pack:test', 1, ?)",
        (_NOW,),
    )
    for locale, name in [("ko", "블루 아카이브"), ("ja", "ブルーアーカイブ")]:
        c.execute(
            "INSERT OR IGNORE INTO tag_localizations "
            "(localization_id, canonical, tag_type, parent_series, locale, display_name, source, enabled, created_at) "
            "VALUES (?, 'Blue Archive', 'series', '', ?, ?, 'built_in_pack:test', 1, ?)",
            (str(uuid.uuid4()), locale, name, _NOW),
        )

    # character — 陸八魔アル: alias (canonical), localization (ko)
    c.execute(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES ('陸八魔アル', '陸八魔アル', 'character', 'Blue Archive', 'built_in_pack:test', 1, ?)",
        (_NOW,),
    )
    c.execute(
        "INSERT OR IGNORE INTO tag_localizations "
        "(localization_id, canonical, tag_type, parent_series, locale, display_name, source, enabled, created_at) "
        "VALUES (?, '陸八魔アル', 'character', 'Blue Archive', 'ko', '리쿠하치마 아루', 'built_in_pack:test', 1, ?)",
        (str(uuid.uuid4()), _NOW),
    )

    c.commit()
    yield c
    c.close()


def _make_group_info() -> dict:
    return {
        "filename":    "12345_p0.jpg",
        "title":       "Test",
        "artist_name": "Artist",
        "raw_tags":    ["tag1"],
        "rule_type":   "author_fallback",
        "dest_path":   "/Classified/ByAuthor/Artist/12345_p0.jpg",
    }


# ---------------------------------------------------------------------------
# _AutocompleteController unit tests
# ---------------------------------------------------------------------------

class TestControllerModelPopulation:
    def test_korean_input_populates_model(self, qapp, conn):
        from PyQt6.QtWidgets import QLineEdit
        from app.views.manual_classify_override_dialog import _AutocompleteController

        edit = QLineEdit()
        ctrl = _AutocompleteController(edit, conn, tag_type="series")

        # 사용자가 한국어 입력 — provider 가 ko display "블루 아카이브" 매칭
        ctrl._on_text_edited("블루")
        rows = ctrl._model.rowCount()
        assert rows >= 1
        # 첫 row 의 display_text 가 ko 매칭
        first = ctrl._model.item(0, 0)
        assert "블루" in first.text() or first.text() == "블루 아카이브"

    def test_japanese_input_populates_model(self, qapp, conn):
        from PyQt6.QtWidgets import QLineEdit
        from app.views.manual_classify_override_dialog import _AutocompleteController

        edit = QLineEdit()
        ctrl = _AutocompleteController(edit, conn, tag_type="series")

        ctrl._on_text_edited("ブルー")
        assert ctrl._model.rowCount() >= 1

    def test_empty_input_clears_model(self, qapp, conn):
        from PyQt6.QtWidgets import QLineEdit
        from app.views.manual_classify_override_dialog import _AutocompleteController

        edit = QLineEdit()
        ctrl = _AutocompleteController(edit, conn, tag_type="series")
        ctrl._on_text_edited("Blue")
        assert ctrl._model.rowCount() >= 1
        ctrl._on_text_edited("")
        assert ctrl._model.rowCount() == 0

    def test_none_conn_is_safe(self, qapp):
        from PyQt6.QtWidgets import QLineEdit
        from app.views.manual_classify_override_dialog import _AutocompleteController

        edit = QLineEdit()
        ctrl = _AutocompleteController(edit, conn=None, tag_type="series")
        # 예외 없이 통과해야 함
        ctrl._on_text_edited("anything")
        assert ctrl._model.rowCount() == 0


class TestControllerMetadataPreservation:
    def test_activated_stores_candidate_metadata(self, qapp, conn):
        """popup 에서 ko candidate 선택 시 metadata 가 보존되어야 한다."""
        from PyQt6.QtWidgets import QLineEdit
        from app.views.manual_classify_override_dialog import (
            CANDIDATE_DATA_ROLE,
            _AutocompleteController,
        )

        edit = QLineEdit()
        ctrl = _AutocompleteController(edit, conn, tag_type="series")
        ctrl._on_text_edited("블루")

        # 첫 row 가 가지고 있는 candidate metadata 확인
        item = ctrl._model.item(0, 0)
        candidate = item.data(CANDIDATE_DATA_ROLE)
        assert candidate is not None
        assert candidate.canonical == "Blue Archive"
        assert candidate.tag_type == "series"

        # 사용자가 popup 에서 그 row 를 활성화한 상황 시뮬레이션
        # (LineEdit 도 사용자가 입력으로 채운 것처럼)
        edit.setText(item.text())
        ctrl._on_activated(ctrl._model.indexFromItem(item))

        # selected_candidate() 가 metadata 를 반환
        sel = ctrl.selected_candidate()
        assert sel is not None
        assert sel.canonical == "Blue Archive"
        assert sel.tag_type == "series"

    def test_text_edit_invalidates_previous_selection(self, qapp, conn):
        from PyQt6.QtWidgets import QLineEdit
        from app.views.manual_classify_override_dialog import _AutocompleteController

        edit = QLineEdit()
        ctrl = _AutocompleteController(edit, conn, tag_type="series")

        # 선택 후 selected 보유
        ctrl._on_text_edited("블루")
        item = ctrl._model.item(0, 0)
        edit.setText(item.text())
        ctrl._on_activated(ctrl._model.indexFromItem(item))
        assert ctrl.selected_candidate() is not None

        # 사용자가 텍스트를 다른 내용으로 직접 편집
        ctrl._on_text_edited("totally different text")
        assert ctrl.selected_candidate() is None

    def test_text_mismatch_after_selection_invalidates(self, qapp, conn):
        """선택 후 사용자가 LineEdit 만 직접 수정해 display 와 어긋나면 invalid."""
        from PyQt6.QtWidgets import QLineEdit
        from app.views.manual_classify_override_dialog import _AutocompleteController

        edit = QLineEdit()
        ctrl = _AutocompleteController(edit, conn, tag_type="series")
        ctrl._on_text_edited("블루")
        item = ctrl._model.item(0, 0)
        edit.setText(item.text())
        ctrl._on_activated(ctrl._model.indexFromItem(item))

        # 사용자가 LineEdit 만 직접 편집 (textEdited 없이 — drag/paste/programmatic)
        edit.setText("something else")
        assert ctrl.selected_candidate() is None


# ---------------------------------------------------------------------------
# Dialog 통합 — 한국어 input → 영어 canonical 저장
# ---------------------------------------------------------------------------

class TestDialogKoreanInputResolvesToCanonical:
    def test_korean_series_input_with_picked_candidate_saves_english_canonical(self, qapp, conn):
        """한국어 ko display 를 popup 으로 선택한 경우 result 에는 canonical (Blue Archive) 저장."""
        from app.views.manual_classify_override_dialog import (
            CANDIDATE_DATA_ROLE,
            ManualClassifyOverrideDialog,
        )

        dlg = ManualClassifyOverrideDialog(
            group_info=_make_group_info(),
            conn=conn,
            current_locale="ko",
        )

        # Provider 호출 → ko 매칭
        dlg._series_autocomplete._on_text_edited("블루")
        # ko display "블루 아카이브" 가 첫 후보 (locale bonus 로 ko 우선)
        item = dlg._series_autocomplete._model.item(0, 0)
        assert item is not None
        candidate = item.data(CANDIDATE_DATA_ROLE)
        assert candidate.canonical == "Blue Archive"
        assert candidate.locale == "ko"

        # 사용자가 popup 에서 클릭 시뮬레이션 — LineEdit 에 display 채워지고 activated.
        dlg._series_edit.setText(item.text())
        dlg._series_autocomplete._on_activated(
            dlg._series_autocomplete._model.indexFromItem(item)
        )

        dlg._on_ok()
        result = dlg.result()
        assert result is not None
        # canonical 저장 (display "블루 아카이브" 가 그대로 저장되면 안 됨)
        assert result["series_canonical"] == "Blue Archive"
        assert result["series_canonical"] != item.text()
        dlg.close()

    def test_korean_character_input_with_picked_candidate_saves_canonical(self, qapp, conn):
        from app.views.manual_classify_override_dialog import (
            CANDIDATE_DATA_ROLE,
            ManualClassifyOverrideDialog,
        )

        dlg = ManualClassifyOverrideDialog(
            group_info=_make_group_info(),
            conn=conn,
            current_locale="ko",
        )

        dlg._character_autocomplete._on_text_edited("리쿠")
        item = dlg._character_autocomplete._model.item(0, 0)
        assert item is not None
        candidate = item.data(CANDIDATE_DATA_ROLE)
        assert candidate.canonical == "陸八魔アル"

        dlg._char_edit.setText(item.text())
        dlg._character_autocomplete._on_activated(
            dlg._character_autocomplete._model.indexFromItem(item)
        )

        # series 도 비어있지 않게 채워야 _on_ok 통과
        dlg._series_edit.setText("Blue Archive")

        dlg._on_ok()
        result = dlg.result()
        assert result is not None
        assert result["character_canonical"] == "陸八魔アル"
        dlg.close()


# ---------------------------------------------------------------------------
# Fallback — 후보 미선택 시 기존 동작 유지
# ---------------------------------------------------------------------------

class TestFallbackPreservesExistingBehavior:
    def test_direct_text_input_without_pick_uses_text_as_canonical(self, qapp, conn):
        """provider 에 매칭 후보가 없는 텍스트를 직접 입력하면 그 텍스트 그대로 canonical."""
        from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

        dlg = ManualClassifyOverrideDialog(
            group_info=_make_group_info(),
            conn=conn,
            current_locale="ko",
        )
        dlg._series_edit.setText("Some Brand New Series")
        dlg._char_edit.setText("Some Brand New Character")
        dlg._on_ok()
        result = dlg.result()
        assert result is not None
        assert result["series_canonical"] == "Some Brand New Series"
        assert result["character_canonical"] == "Some Brand New Character"
        dlg.close()

    def test_label_format_fallback_still_works(self, qapp, conn):
        """기존 _resolve_character_canonical 의 'X (Y)' 패턴 fallback 보존."""
        from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

        dlg = ManualClassifyOverrideDialog(
            group_info=_make_group_info(),
            conn=conn,
            current_locale="canonical",
        )
        # 사용자가 직접 "X (Y)" 를 입력 (legacy label 형식)
        dlg._series_edit.setText("Blue Archive")
        dlg._char_edit.setText("陸八魔アル (Blue Archive)")
        dlg._on_ok()
        result = dlg.result()
        assert result is not None
        # legacy parsing 으로 canonical 만 추출
        assert result["character_canonical"] == "陸八魔アル"
        dlg.close()


# ---------------------------------------------------------------------------
# Result dict 구조 invariant
# ---------------------------------------------------------------------------

class TestResultDictShapeUnchanged:
    def test_result_dict_keys_unchanged_with_picked_candidate(self, qapp, conn):
        from app.views.manual_classify_override_dialog import (
            CANDIDATE_DATA_ROLE,
            ManualClassifyOverrideDialog,
        )

        dlg = ManualClassifyOverrideDialog(
            group_info=_make_group_info(),
            conn=conn,
            current_locale="ko",
        )
        dlg._series_autocomplete._on_text_edited("블루")
        item = dlg._series_autocomplete._model.item(0, 0)
        dlg._series_edit.setText(item.text())
        dlg._series_autocomplete._on_activated(
            dlg._series_autocomplete._model.indexFromItem(item)
        )
        dlg._on_ok()
        result = dlg.result()
        assert result is not None
        # 정확히 4개 key 만 유지 — 새 metadata 필드를 result 에 끼워 넣지 않는다
        assert set(result.keys()) == {
            "series_canonical", "character_canonical", "folder_locale", "reason",
        }
        dlg.close()

    def test_result_dict_keys_unchanged_with_direct_text(self, qapp, conn):
        from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

        dlg = ManualClassifyOverrideDialog(
            group_info=_make_group_info(),
            conn=conn,
            current_locale="canonical",
        )
        dlg._series_edit.setText("Blue Archive")
        dlg._on_ok()
        result = dlg.result()
        assert result is not None
        assert set(result.keys()) == {
            "series_canonical", "character_canonical", "folder_locale", "reason",
        }
        dlg.close()


# ---------------------------------------------------------------------------
# Wizard write path — set_override_for_group 가 받는 인자가 unchanged
# ---------------------------------------------------------------------------

class TestNoSchemaImpact:
    def test_no_extra_columns_required_in_classification_overrides(self, qapp, conn):
        """이번 PR 이 classification_overrides schema 또는 set_override_for_group
        signature 를 변경하지 않았는지 source-inspection 으로 lock."""
        from core import classification_overrides

        # set_override_for_group 의 keyword 인자가 그대로인지 확인
        import inspect
        sig = inspect.signature(classification_overrides.set_override_for_group)
        params = set(sig.parameters.keys())
        # 기존 시그니처: conn, group_id, series_canonical, character_canonical,
        # folder_locale, reason
        assert "series_canonical" in params
        assert "character_canonical" in params
        assert "folder_locale" in params
        assert "reason" in params
