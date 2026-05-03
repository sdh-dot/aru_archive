"""
LoadingOverlayDialog smoke + asset resolution 회귀 테스트.

목적:
- assets/loading/ 자산이 release build에서 누락된 사고 (v0.6.3 이후) 재발 방지
- frozen-aware 경로 helper (loading_image_path / loading_icon_path) 의 resolver 검증
- pixmap 누락 시 dialog가 crash 없이 fallback text를 보여주는지 검증
- PyInstaller spec datas에 assets/loading/ 가 포함되어 있는지 source-inspection 가드
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6가 설치되어 있지 않음")


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_loading_assets_present_in_repo():
    main_image = REPO_ROOT / "assets" / "loading" / "loading_01.png"
    mini_icon = REPO_ROOT / "assets" / "loading" / "icon_05.png"
    assert main_image.exists(), f"누락된 release asset: {main_image}"
    assert mini_icon.exists(), f"누락된 release asset: {mini_icon}"


def test_loading_image_path_helper_resolves_in_dev():
    from app.resources import loading_image_path

    resolved = loading_image_path()
    assert resolved is not None, "dev 환경에서 loading_image_path()가 None을 반환했다."
    assert Path(resolved).exists(), f"resolver가 가리킨 파일이 실제로 없다: {resolved}"
    assert Path(resolved).name == "loading_01.png"


def test_loading_icon_path_helper_resolves_in_dev():
    from app.resources import loading_icon_path

    resolved = loading_icon_path()
    assert resolved is not None, "dev 환경에서 loading_icon_path()가 None을 반환했다."
    assert Path(resolved).exists(), f"resolver가 가리킨 파일이 실제로 없다: {resolved}"
    assert Path(resolved).name == "icon_05.png"


def test_loading_overlay_dialog_initializes_with_assets(qt_app):
    from app.views.loading_overlay_dialog import LoadingOverlayDialog

    dlg = LoadingOverlayDialog()
    try:
        assert dlg._main_image_path is not None
        assert dlg._mini_icon_path is not None
        assert dlg._main_image.pixmap() is not None
        assert not dlg._main_image.pixmap().isNull(), (
            "메인 이미지 pixmap이 null. release asset이 정상적으로 로드되지 않음."
        )
    finally:
        dlg.deleteLater()


def test_loading_overlay_dialog_falls_back_when_assets_missing(qt_app, monkeypatch):
    """assets/loading 자산이 없을 때 (예: spec 누락) crash 없이 fallback text를 표시."""
    from app.views import loading_overlay_dialog as mod

    monkeypatch.setattr(mod, "loading_image_path", lambda: None)
    monkeypatch.setattr(mod, "loading_icon_path", lambda: None)

    dlg = mod.LoadingOverlayDialog()
    try:
        assert dlg._main_image_path is None
        assert dlg._mini_icon_path is None
        assert dlg._main_image.pixmap().isNull()
        assert "불러오지 못했습니다" in dlg._main_image.text()
    finally:
        dlg.deleteLater()


def test_pyinstaller_spec_includes_loading_assets():
    spec_path = REPO_ROOT / "build" / "aru_archive.spec"
    text = spec_path.read_text(encoding="utf-8")
    assert re.search(r'"assets"\s*/\s*"loading"', text), (
        "build/aru_archive.spec datas에 assets/loading 디렉터리가 포함되어 있지 않다. "
        "release build에서 LoadingOverlayDialog 이미지가 누락된다."
    )


# ---------------------------------------------------------------------------
# Layout stability — 긴 detail/log 한 줄로 인한 dialog 흔들림 방지
# ---------------------------------------------------------------------------

class TestDetailLayoutStability:
    """``set_detail_text`` 가 긴 문자열을 받아도 dialog height 가 폭주하지 않고,
    원문이 tooltip 으로 보존되는지 lock."""

    def test_detail_label_has_max_height_constraint(self, qt_app):
        from app.views.loading_overlay_dialog import (
            LoadingOverlayDialog,
            _DETAIL_LABEL_MAX_HEIGHT,
        )
        dlg = LoadingOverlayDialog()
        try:
            assert dlg._task_message.maximumHeight() == _DETAIL_LABEL_MAX_HEIGHT
        finally:
            dlg.deleteLater()

    def test_detail_label_has_fixed_vertical_size_policy(self, qt_app):
        from PyQt6.QtWidgets import QSizePolicy
        from app.views.loading_overlay_dialog import LoadingOverlayDialog

        dlg = LoadingOverlayDialog()
        try:
            policy = dlg._task_message.sizePolicy()
            assert policy.verticalPolicy() == QSizePolicy.Policy.Fixed
        finally:
            dlg.deleteLater()

    def test_detail_text_with_long_message_does_not_expand_dialog(self, qt_app):
        from app.views.loading_overlay_dialog import LoadingOverlayDialog

        dlg = LoadingOverlayDialog()
        try:
            dlg.set_detail_text("짧은 메시지")
            short_height = dlg.sizeHint().height()

            # 500자 + 무 줄바꿈 라인.
            long_msg = "x" * 500 + " 매우-긴-한-줄-파일명-" + "y" * 200
            dlg.set_detail_text(long_msg)
            long_height = dlg.sizeHint().height()

            # detail 자체가 max height 로 cap 되므로 dialog height 차이가 거의 없어야 한다.
            # 약간의 차이 (한두 픽셀) 는 layout policy 부동소수점 결과로 발생 가능 — 50 px
            # 이상 늘어나지 않는지를 가드.
            assert long_height - short_height < 50, (
                f"긴 detail 로 dialog height 가 과도하게 증가: "
                f"short={short_height} long={long_height}"
            )
        finally:
            dlg.deleteLater()

    def test_detail_text_keeps_full_message_in_tooltip(self, qt_app):
        from app.views.loading_overlay_dialog import LoadingOverlayDialog

        dlg = LoadingOverlayDialog()
        try:
            full = "이것은 매우 긴 detail 메시지입니다. " * 30
            dlg.set_detail_text(full)
            # display 가 truncate 됐다면 원문은 tooltip 에 보존.
            assert dlg._task_message.toolTip() == full
            # display text 는 ellipsis 또는 head fragment.
            displayed = dlg._task_message.text()
            assert displayed != full
            assert displayed.endswith("…")
        finally:
            dlg.deleteLater()

    def test_detail_text_short_message_no_tooltip_pollution(self, qt_app):
        """짧은 메시지는 tooltip 을 비워둔다 (불필요한 tooltip 표시 방지)."""
        from app.views.loading_overlay_dialog import LoadingOverlayDialog

        dlg = LoadingOverlayDialog()
        try:
            dlg.set_detail_text("정상 길이")
            assert dlg._task_message.text() == "정상 길이"
            assert dlg._task_message.toolTip() == ""
        finally:
            dlg.deleteLater()

    def test_truncate_helper_returns_short_strings_unchanged(self):
        from app.views.loading_overlay_dialog import (
            _DETAIL_DISPLAY_MAX_CHARS,
            _truncate_detail_for_display,
        )
        text = "a" * _DETAIL_DISPLAY_MAX_CHARS
        assert _truncate_detail_for_display(text) == text

    def test_truncate_helper_truncates_long_strings_with_ellipsis(self):
        from app.views.loading_overlay_dialog import (
            _DETAIL_DISPLAY_MAX_CHARS,
            _truncate_detail_for_display,
        )
        text = "a" * (_DETAIL_DISPLAY_MAX_CHARS + 200)
        result = _truncate_detail_for_display(text)
        assert result.endswith("…")
        assert len(result) == _DETAIL_DISPLAY_MAX_CHARS


# ---------------------------------------------------------------------------
# Wizard _mirror_loading_log truncation — caller-side defense
# ---------------------------------------------------------------------------

class TestWizardMirrorLoadingLogTruncation:
    """Wizard 의 ``_mirror_loading_log`` 가 긴 log 한 줄을 dialog detail 로 그대로
    넘기지 않고 짧게 잘라 dialog layout 을 보호하는지 lock."""

    @pytest.fixture
    def wizard(self, qt_app, tmp_path):
        from app.views.workflow_wizard_view import WorkflowWizardView

        config = {
            "data_dir": "", "inbox_dir": "", "classified_dir": "/Classified",
            "managed_dir": "", "db": {"path": str(tmp_path / "x.db")},
        }

        def factory():
            from db.database import initialize_database
            return initialize_database(config["db"]["path"])

        w = WorkflowWizardView(factory, config, "config.json")
        # loading dialog 강제 ensure (mirror 가 None 일 때 조기 반환되는 분기 회피).
        w._ensure_loading_dialog()
        yield w
        w.close()

    def test_short_log_passes_through_to_detail(self, wizard):
        wizard._mirror_loading_log("[INFO] 짧은 로그")
        # prefix 제거 후 detail 에 표시.
        assert wizard._loading_dialog._task_message.text() == "짧은 로그"

    def test_long_log_is_truncated_for_detail(self, wizard):
        from app.views.workflow_wizard_view import WorkflowWizardView

        long_msg = "[INFO] " + ("x" * 400)
        wizard._mirror_loading_log(long_msg)

        displayed = wizard._loading_dialog._task_message.text()
        assert displayed.endswith("…")
        # caller-side truncate cap 이내 — dialog 측 truncate 와 함께 두번 거쳐도
        # 안전.
        assert len(displayed) <= WorkflowWizardView._DETAIL_MIRROR_MAX_CHARS

    def test_empty_log_does_not_overwrite_detail(self, wizard):
        wizard._mirror_loading_log("정상 메시지")
        wizard._mirror_loading_log("")
        # 빈 메시지는 무시 (detail 그대로 유지).
        assert wizard._loading_dialog._task_message.text() == "정상 메시지"

    def test_mirror_without_dialog_is_noop(self, qt_app, tmp_path):
        """loading dialog 미생성 상태에서도 예외 없이 조기 반환."""
        from app.views.workflow_wizard_view import WorkflowWizardView

        config = {
            "data_dir": "", "inbox_dir": "", "classified_dir": "/Classified",
            "managed_dir": "", "db": {"path": str(tmp_path / "y.db")},
        }

        def factory():
            from db.database import initialize_database
            return initialize_database(config["db"]["path"])

        w = WorkflowWizardView(factory, config, "config.json")
        try:
            assert w._loading_dialog is None
            w._mirror_loading_log("[INFO] 어떤 메시지")  # 예외 없이 반환
        finally:
            w.close()
