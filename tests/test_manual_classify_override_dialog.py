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
