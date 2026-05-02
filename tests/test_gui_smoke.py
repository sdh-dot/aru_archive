"""
GUI smoke 테스트.

MainWindow 및 각 뷰 위젯이 예외 없이 초기화·표시되는지 확인한다.
PyQt6 + 실제 디스플레이(또는 QT_QPA_PLATFORM=offscreen) 필요.

실행:
  pytest tests/test_gui_smoke.py -v
  QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py -v  # headless
"""
from __future__ import annotations

import os
import sys

import pytest

# offscreen 플랫폼은 QApplication 생성 전에 설정해야 한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6가 설치되어 있지 않음")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app
    # 모듈 범위에서 한 번만 생성·유지


@pytest.fixture
def tmp_config(tmp_path):
    return {
        "data_dir":  str(tmp_path / "archive"),
        "inbox_dir": str(tmp_path / "inbox"),
        "classified_dir": str(tmp_path / "Classified"),
        "managed_dir": str(tmp_path / "Managed"),
        "db": {"path": str(tmp_path / "archive" / "aru.db")},
        "http_server": {"port": 19999},
    }


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

def test_main_window_init(qt_app, tmp_config, tmp_path):
    """MainWindow가 임시 설정으로 예외 없이 초기화된다."""
    from app.main_window import MainWindow
    cfg_path = str(tmp_path / "cfg.json")
    win = MainWindow(tmp_config, config_path=cfg_path)
    assert win.windowTitle() == "Aru Archive"
    win.close()


def test_main_window_toolbar_buttons(qt_app, tmp_config, tmp_path):
    """툴바 액션이 존재하고 초기에 활성 상태이다."""
    from app.main_window import MainWindow
    win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
    assert win._act_archive_root.isEnabled()
    assert win._act_inbox_scan.isEnabled()
    assert win._act_db_init.isEnabled()
    win.close()


def test_main_window_db_init(qt_app, tmp_config, tmp_path):
    """DB 초기화 버튼 클릭이 예외 없이 처리된다.

    DatabaseResetConfirmDialog를 Rejected로 패치하여 실제 초기화는 실행하지 않는다.
    (dialog가 없으면 offscreen 환경에서 blocking됨)
    """
    from unittest.mock import patch

    from PyQt6.QtWidgets import QDialog

    from app.main_window import MainWindow

    win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
    with patch(
        "app.main_window.DatabaseResetConfirmDialog.exec",
        return_value=QDialog.DialogCode.Rejected,
    ):
        win._on_db_init()
    win.close()


def test_main_window_defers_initial_path_setup_until_show(qt_app, tmp_path, monkeypatch):
    """첫 실행 폴더 설정은 창이 표시된 뒤 이벤트 루프에서 호출된다."""
    from app.main_window import MainWindow

    called = []

    def _fake_open(self, *, first_run: bool) -> None:
        called.append(first_run)

    monkeypatch.setattr(MainWindow, "_open_path_setup_dialog", _fake_open)

    cfg = {
        "data_dir": str(tmp_path / "archive"),
        "inbox_dir": "",
        "classified_dir": "",
        "managed_dir": "",
        "db": {"path": str(tmp_path / "archive" / "aru.db")},
        "http_server": {"port": 19999},
    }
    win = MainWindow(cfg, config_path=str(tmp_path / "cfg.json"))
    assert called == []

    win.show()
    qt_app.processEvents()

    assert called == [True]
    win.close()


def test_main_window_opens_path_setup_when_configured_inbox_is_missing(qt_app, tmp_path, monkeypatch):
    """config에 경로 문자열이 있어도 실제 Inbox가 없으면 경로 설정을 다시 연다."""
    from app.main_window import MainWindow

    called = []

    def _fake_open(self, *, first_run: bool) -> None:
        called.append(first_run)

    monkeypatch.setattr(MainWindow, "_open_path_setup_dialog", _fake_open)

    root = tmp_path / "AruArchive"
    cfg = {
        "data_dir": str(root),
        "inbox_dir": str(root / "Inbox"),
        "classified_dir": str(root / "Classified"),
        "managed_dir": str(root / "Managed"),
        "db": {"path": str(root / ".runtime" / "aru.db")},
        "http_server": {"port": 19999},
    }

    win = MainWindow(cfg, config_path=str(tmp_path / "cfg.json"))
    win.show()
    qt_app.processEvents()

    assert called == [True]
    win.close()


# ---------------------------------------------------------------------------
# GalleryView
# ---------------------------------------------------------------------------

def test_gallery_empty(qt_app):
    """GalleryView — 빈 rows 로드."""
    from app.views.gallery_view import GalleryView
    v = GalleryView()
    v.load_groups([])


def test_gallery_with_rows(qt_app):
    """GalleryView — 일반 rows 로드."""
    from app.views.gallery_view import GalleryView
    v = GalleryView()
    rows = [
        {
            "group_id": f"g{i}",
            "artwork_title": f"Title {i}",
            "artwork_id": f"a{i}",
            "metadata_sync_status": "full",
            "status": "inbox",
            "source_site": "local",
            "file_format": "jpg",
            "thumb_path": None,
            "role_summary": "original",
        }
        for i in range(5)
    ]
    v.load_groups(rows)
    assert v.get_selected_group_id() is None
    assert v.get_visible_group_ids() == [f"g{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# DetailView
# ---------------------------------------------------------------------------

def test_detail_clear(qt_app):
    from app.views.detail_view import DetailView
    v = DetailView()
    v.clear()


def test_detail_show_group(qt_app):
    """DetailView — 그룹 데이터 표시."""
    from app.views.detail_view import DetailView
    v = DetailView()
    v.show_group(
        {
            "group_id": "test-uuid",
            "artwork_title": "테스트 작품",
            "artist_name": "테스트 작가",
            "artwork_id": "abc123",
            "source_site": "local",
            "metadata_sync_status": "full",
            "indexed_at": "2025-01-01T00:00:00",
            "tags_json": '["tag1", "tag2"]',
        },
        [
            {
                "file_role": "original",
                "file_path": "/fake/file.jpg",
                "file_format": "jpg",
            }
        ],
    )


def test_detail_bmp_buttons(qt_app):
    """DetailView — BMP 파일 시 BMP 변환 버튼 활성, GIF 버튼 비활성."""
    from app.views.detail_view import DetailView
    v = DetailView()
    v.show_group(
        {"group_id": "g1", "metadata_sync_status": "pending"},
        [{"file_role": "original", "file_path": "/f.bmp", "file_format": "bmp"}],
    )
    assert v._btn_bmp.isEnabled()
    assert not v._btn_gif.isEnabled()


def test_detail_gif_buttons(qt_app):
    """DetailView — GIF 파일 시 GIF 버튼 활성, BMP 버튼 비활성."""
    from app.views.detail_view import DetailView
    v = DetailView()
    v.show_group(
        {"group_id": "g1", "metadata_sync_status": "pending"},
        [{"file_role": "original", "file_path": "/f.gif", "file_format": "gif"}],
    )
    assert not v._btn_bmp.isEnabled()
    assert v._btn_gif.isEnabled()


def test_detail_read_meta_button_label(qt_app):
    """DetailView — '파일 내 메타데이터 읽기' 버튼 이름 확인."""
    from app.views.detail_view import DetailView
    v = DetailView()
    assert v._btn_read_meta.text() == "파일 내 메타데이터 읽기"


def test_detail_pixiv_meta_signal_exists(qt_app):
    """DetailView — pixiv_meta_requested 시그널 존재 확인."""
    from app.views.detail_view import DetailView
    v = DetailView()
    received = []
    v.pixiv_meta_requested.connect(received.append)
    # Pixiv 파일명 패턴 파일이 없으면 버튼 비활성 — 시그널은 emit되지 않아야 함
    v.show_group(
        {"group_id": "g1", "metadata_sync_status": "pending"},
        [{"file_role": "original", "file_path": "/f.jpg", "file_format": "jpg"}],
    )
    assert not v._btn_pixiv_meta.isEnabled()
    assert received == []


def test_detail_pixiv_meta_button_enabled_for_pixiv_filename(qt_app):
    """DetailView — Pixiv 파일명 패턴일 때 Pixiv 버튼 활성."""
    from app.views.detail_view import DetailView
    v = DetailView()
    v.show_group(
        {"group_id": "g1", "metadata_sync_status": "pending"},
        [
            {
                "file_role": "original",
                "file_path": "/downloads/141100516_p0.jpg",
                "file_format": "jpg",
            }
        ],
    )
    assert v._btn_pixiv_meta.isEnabled()


def test_detail_show_pixiv_result(qt_app):
    """DetailView.show_pixiv_result() 호출 시 Pixiv 보강 섹션이 표시된다."""
    from app.views.detail_view import DetailView
    v = DetailView()
    v.show_pixiv_result("141100516", "https://www.pixiv.net/artworks/141100516")
    assert not v._pixiv_box.isHidden()
    assert v._lbl_pixiv_id.text() == "141100516"
    assert "141100516" in v._lbl_pixiv_url.text()


def test_detail_clear_hides_pixiv_section(qt_app):
    """DetailView.clear() 시 Pixiv 보강 섹션이 숨겨진다."""
    from app.views.detail_view import DetailView
    v = DetailView()
    v.show_pixiv_result("999", "https://www.pixiv.net/artworks/999")
    v.clear()
    assert v._pixiv_box.isHidden()


# ---------------------------------------------------------------------------
# NoMetadataView
# ---------------------------------------------------------------------------

def test_no_metadata_empty(qt_app):
    from app.views.no_metadata_view import NoMetadataView
    v = NoMetadataView()
    v.load_queue([])
    assert "0건" in v._count_lbl.text()


def test_no_metadata_with_rows(qt_app):
    """NoMetadataView — 항목 표시 및 카운터 갱신."""
    from app.views.no_metadata_view import NoMetadataView
    v = NoMetadataView()
    rows = [
        {
            "queue_id": "q1",
            "file_path": "/fake/img.jpg",
            "fail_reason": "manual_add",
            "detected_at": "2025-01-01T00:00:00",
            "resolved": 0,
            "notes": "",
        },
        {
            "queue_id": "q2",
            "file_path": "/fake/img2.bmp",
            "fail_reason": "bmp_convert_failed",
            "detected_at": "2025-01-02T00:00:00",
            "resolved": 1,
            "notes": "무시됨",
        },
    ]
    v.load_queue(rows)
    assert v._table.rowCount() == 2
    assert "1건 미해결" in v._count_lbl.text()


# ---------------------------------------------------------------------------
# SidebarWidget
# ---------------------------------------------------------------------------

def test_sidebar_update_counts(qt_app):
    from app.widgets.sidebar import SidebarWidget
    s = SidebarWidget()
    s.update_counts({"all": 10, "inbox": 5, "managed": 3,
                     "no_metadata": 2, "failed": 1})
    assert s.current_category() == "all"


# ---------------------------------------------------------------------------
# LogPanel
# ---------------------------------------------------------------------------

def test_log_panel_append(qt_app):
    from app.widgets.log_panel import LogPanel
    lp = LogPanel()
    lp.append("[INFO] 테스트 메시지")
    lp.append("[ERROR] 오류 메시지")
    lp.clear()


# ---------------------------------------------------------------------------
# TagCandidateView
# ---------------------------------------------------------------------------

def test_tag_candidate_view_init(qt_app, tmp_path):
    """TagCandidateView가 빈 DB로 예외 없이 초기화된다."""
    from db.database import initialize_database
    from app.views.tag_candidate_view import TagCandidateView

    conn = initialize_database(str(tmp_path / "tc.db"))
    dlg = TagCandidateView(conn)
    assert dlg.windowTitle() == "🏷 태그 후보 검토"
    assert dlg._table.rowCount() == 0
    conn.close()


def test_tag_candidate_view_loads_rows(qt_app, tmp_path):
    """TagCandidateView가 tag_candidates 행을 로드한다."""
    import uuid
    from datetime import datetime, timezone
    from db.database import initialize_database
    from app.views.tag_candidate_view import TagCandidateView

    conn = initialize_database(str(tmp_path / "tc2.db"))
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO tag_candidates
           (candidate_id, raw_tag, suggested_type, suggested_parent_series,
            confidence_score, evidence_count, source, status, created_at)
           VALUES (?, 'テスト', 'character', 'Blue Archive', 0.70, 1, 'test', 'pending', ?)""",
        (str(uuid.uuid4()), now),
    )
    conn.commit()

    dlg = TagCandidateView(conn)
    assert dlg._table.rowCount() == 1
    conn.close()


def test_main_window_has_candidates_button(qt_app, tmp_config, tmp_path):
    """MainWindow에 후보 태그 액션이 존재한다."""
    from app.main_window import MainWindow
    win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
    assert win._act_candidates.isEnabled()
    win.close()


def test_main_window_no_stale_btn_scan_reference():
    """PR #47 toolbar rename 이후 _btn_scan 잔재가 MainWindow 소스에 없어야 한다."""
    import inspect
    from app.main_window import MainWindow
    src = inspect.getsource(MainWindow)
    assert "_btn_scan" not in src, (
        "Stale _btn_scan reference still present in MainWindow source"
    )
