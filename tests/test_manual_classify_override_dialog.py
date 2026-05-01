"""
ManualClassifyOverrideDialog GUI smoke 테스트.
PyQt6 전용.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialogButtonBox


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    c = initialize_database(str(tmp_path / "dialog_test.db"))
    now = "2026-01-01T00:00:00+00:00"
    c.execute(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
        "VALUES ('Blue Archive', 'Blue Archive', 'series', '', 1, ?, ?)",
        (now, now),
    )
    c.execute(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
        "VALUES ('伊落マリー', '伊落マリー', 'character', 'Blue Archive', 1, ?, ?)",
        (now, now),
    )
    c.commit()
    yield c
    c.close()


def _make_group_info() -> dict:
    return {
        "filename":    "106586263_p0.jpg",
        "title":       "マリーちゃん",
        "artist_name": "test_artist",
        "raw_tags":    ["ブルーアーカイブ10000users入り", "チャイナドレス"],
        "rule_type":   "author_fallback",
        "dest_path":   "/Classified/ByAuthor/test_artist/106586263_p0.jpg",
    }


# ---------------------------------------------------------------------------
# 1. dialog 생성 가능
# ---------------------------------------------------------------------------

def test_dialog_creates_without_error(qapp, conn):
    from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=conn,
        current_locale="ko",
    )
    assert dlg is not None
    assert dlg.windowTitle() == "수동 분류 지정"
    dlg.close()


# ---------------------------------------------------------------------------
# 2. series/character 입력 가능
# ---------------------------------------------------------------------------

def test_dialog_accepts_series_and_character_input(qapp, conn):
    from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=conn,
        current_locale="canonical",
    )
    dlg._series_edit.setText("Blue Archive")
    dlg._char_edit.setText("伊落マリー")
    assert dlg._series_edit.text() == "Blue Archive"
    assert dlg._char_edit.text() == "伊落マリー"
    dlg.close()


# ---------------------------------------------------------------------------
# 3. OK 시 결과 반환
# ---------------------------------------------------------------------------

def test_dialog_ok_returns_result(qapp, conn):
    from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=conn,
        current_locale="ko",
    )
    dlg._series_edit.setText("Blue Archive")
    dlg._char_edit.setText("伊落マリー")
    dlg._locale_edit.setText("ko")
    dlg._reason_edit.setText("테스트 사유")

    # OK 버튼 클릭 시뮬레이션
    dlg._on_ok()

    result = dlg.result()
    assert result is not None
    assert result["series_canonical"] == "Blue Archive"
    assert result["character_canonical"] == "伊落マリー"
    assert result["folder_locale"] == "ko"
    assert result["reason"] == "테스트 사유"
    dlg.close()


# ---------------------------------------------------------------------------
# 4. cancel 시 변경 없음
# ---------------------------------------------------------------------------

def test_dialog_cancel_returns_none(qapp, conn):
    from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=conn,
        current_locale="canonical",
    )
    dlg._series_edit.setText("Blue Archive")
    dlg._char_edit.setText("伊落マリー")
    dlg.reject()  # Cancel

    assert dlg.result() is None


# ---------------------------------------------------------------------------
# 5. 둘 다 비어 있으면 OK 거부
# ---------------------------------------------------------------------------

def test_dialog_ok_rejected_when_both_empty(qapp, conn):
    from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=conn,
    )
    dlg._series_edit.setText("")
    dlg._char_edit.setText("")
    dlg._on_ok()  # 비어 있으므로 accept() 호출 안 됨

    assert dlg.result() is None
    dlg.close()


# ---------------------------------------------------------------------------
# 6. conn=None 이어도 dialog 생성 가능 (completer 없이)
# ---------------------------------------------------------------------------

def test_dialog_works_without_db_conn(qapp):
    from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=None,
    )
    assert dlg is not None
    dlg._series_edit.setText("Blue Archive")
    dlg._char_edit.setText("伊落マリー")
    dlg._on_ok()

    result = dlg.result()
    assert result is not None
    assert result["series_canonical"] == "Blue Archive"
    dlg.close()


# ---------------------------------------------------------------------------
# 7. label/value 분리: "캐릭터명 (시리즈명)" label → canonical 역조회
# ---------------------------------------------------------------------------

def test_character_label_resolves_to_canonical(qapp, conn):
    """
    _load_character_labels이 생성한 label을 _char_edit에 입력하면
    OK 시 canonical만 character_canonical에 저장된다.
    label 문자열 자체(예: "伊落マリー (Blue Archive)")는 저장되지 않아야 한다.
    """
    from app.views.manual_classify_override_dialog import (
        ManualClassifyOverrideDialog,
        _load_character_labels,
    )

    _, label_to_canonical = _load_character_labels(conn)

    # DB에 "伊落マリー (Blue Archive)" label이 있어야 함
    expected_label = "伊落マリー (Blue Archive)"
    assert expected_label in label_to_canonical, (
        f"Expected label '{expected_label}' in {list(label_to_canonical.keys())}"
    )
    assert label_to_canonical[expected_label] == "伊落マリー"

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=conn,
        current_locale="ko",
    )
    dlg._series_edit.setText("Blue Archive")
    # label 전체를 입력 (자동완성 선택 시 이 값이 LineEdit에 채워짐)
    dlg._char_edit.setText(expected_label)
    dlg._on_ok()

    result = dlg.result()
    assert result is not None
    # canonical만 저장, label 문자열 금지
    assert result["character_canonical"] == "伊落マリー", (
        f"Expected canonical '伊落マリー', got '{result['character_canonical']}'"
    )
    assert result["character_canonical"] != expected_label, (
        "label 문자열이 그대로 저장되면 안 됨"
    )
    dlg.close()


# ---------------------------------------------------------------------------
# 8. label/value 분리: "canonical (series)" 형식 직접 입력도 canonical 추출
# ---------------------------------------------------------------------------

def test_character_label_strip_series_suffix_on_direct_input(qapp):
    """
    label_to_canonical 역매핑에 없는 직접 입력 "キャラ (シリーズ)" 도
    _resolve_character_canonical이 "(시리즈)" suffix를 제거하고 canonical만 반환한다.
    """
    from app.views.manual_classify_override_dialog import ManualClassifyOverrideDialog

    dlg = ManualClassifyOverrideDialog(
        group_info=_make_group_info(),
        conn=None,
    )
    # 매핑에 없는 직접 입력
    resolved = dlg._resolve_character_canonical("キャラA (シリーズB)")
    assert resolved == "キャラA", f"Expected 'キャラA', got '{resolved}'"

    # suffix 없는 단독 입력 그대로 반환
    resolved2 = dlg._resolve_character_canonical("キャラA")
    assert resolved2 == "キャラA"

    dlg.close()


# ---------------------------------------------------------------------------
# 9. _load_character_labels: parent_series 포함 여부 확인
# ---------------------------------------------------------------------------

def test_load_character_labels_includes_parent_series(conn):
    """
    _load_character_labels은 parent_series가 있는 캐릭터에 대해
    "canonical (parent_series)" 형식 label을 반환해야 한다.
    """
    from app.views.manual_classify_override_dialog import _load_character_labels

    labels, label_to_canonical = _load_character_labels(conn)

    assert len(labels) >= 1
    assert "伊落マリー (Blue Archive)" in labels
    # canonical은 "伊落マリー"여야 함
    assert label_to_canonical["伊落マリー (Blue Archive)"] == "伊落マリー"
