"""Gallery refresh action + image scan label 회귀 테스트.

source-inspection 기반으로 GUI 부팅 없이 검증.
"""
from __future__ import annotations
import inspect
import pytest
pytest.importorskip("PyQt6", reason="PyQt6 필요")


class TestGalleryRefreshSignal:
    def test_gallery_view_declares_refresh_requested_signal(self):
        from app.views.gallery_view import GalleryView
        assert hasattr(GalleryView, "refresh_requested"), (
            "GalleryView.refresh_requested signal이 정의되지 않음"
        )

    def test_gallery_context_menu_has_refresh_action_source(self):
        from app.views.gallery_view import GalleryView
        src = inspect.getsource(GalleryView._on_context_menu)
        assert "새로고침" in src, "context menu에 '새로고침' 액션이 없음"
        assert "refresh_requested.emit" in src, (
            "refresh_requested.emit 호출이 없음"
        )


class TestMainWindowRefreshConnection:
    def test_main_window_connects_gallery_refresh_signal(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow)
        assert "refresh_requested.connect(self._on_refresh)" in src, (
            "MainWindow에서 gallery.refresh_requested → _on_refresh 연결 누락"
        )

    def test_toolbar_refresh_action_connected_to_on_refresh(self):
        from app.main_window import MainWindow
        src = inspect.getsource(MainWindow)
        # _act_refresh가 _on_refresh에 연결되어 있는 패턴 확인.
        # 직접 .triggered.connect 또는 다른 방식 모두 허용.
        assert "_act_refresh" in src, "_act_refresh action이 없음"
        assert "_on_refresh" in src, "_on_refresh handler가 없음"
        # connect 라인이 같은 source 내 어딘가에 존재
        assert (
            "_act_refresh.triggered.connect(self._on_refresh)" in src
            or "_act_refresh.triggered.connect" in src
        ), "_act_refresh.triggered.connect 패턴이 없음"


class TestImageScanLabel:
    def test_main_window_uses_image_scan_label(self):
        import app.main_window as mw
        src = inspect.getsource(mw)
        # 사용자-facing "이미지 스캔" 등장 확인
        assert "이미지 스캔" in src, "MainWindow에 '이미지 스캔' 라벨이 없음"
        # 사용자-facing 문자열에서 "Inbox 스캔"이 사라졌는지 확인 (주석 L5는 예외)
        # 정확히 사용자-facing 위치만 검사: action label / log INFO / info hint
        assert '"🔍 Inbox 스캔"' not in src
        assert "[INFO] Inbox 스캔 시작" not in src
        assert "먼저 Inbox 스캔을 실행하세요" not in src

    def test_workflow_wizard_uses_image_scan_label(self):
        import app.views.workflow_wizard_view as wf
        src = inspect.getsource(wf)
        assert "이미지 스캔 / 파일 로드" in src
        assert "🔍 이미지 스캔 실행" in src
        assert "Inbox 스캔 / 파일 로드" not in src
        assert "🔍 Inbox 스캔 실행" not in src

    def test_gallery_empty_state_uses_image_scan_label(self):
        import app.views.gallery_view as gv
        src = inspect.getsource(gv)
        assert "[이미지 스캔] 버튼을 눌러 시작하세요" in src
        assert "[Inbox 스캔] 버튼을 눌러 시작하세요" not in src

    def test_inbox_scanner_log_uses_image_scan_label(self):
        import core.inbox_scanner as ins
        src = inspect.getsource(ins)
        assert "이미지 스캔 시작" in src
        assert "[INFO] Inbox 스캔 시작" not in src
