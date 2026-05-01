"""StartupNoticeDialog 회귀 테스트.

dialog widget 생성 + 본문/체크박스 검증. dlg.exec() 호출 금지.
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 필요")

from PyQt6.QtWidgets import QApplication, QCheckBox


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def dlg(qapp):
    from app.views.startup_notice_dialog import StartupNoticeDialog
    return StartupNoticeDialog("0.4.1", parent=None)


def _all_text(widget) -> str:
    """widget 트리의 모든 QLabel 텍스트를 합친 문자열을 반환."""
    from PyQt6.QtWidgets import QLabel
    parts = []
    for lbl in widget.findChildren(QLabel):
        try:
            parts.append(lbl.text())
        except Exception:
            pass
    return "\n".join(parts)


class TestDialogTitle:
    def test_window_title_mentions_aru_archive(self, dlg):
        title = dlg.windowTitle()
        assert "Aru Archive" in title or "시작 안내" in title


class TestDialogContent:
    def test_contains_dev_warning(self, dlg):
        text = _all_text(dlg)
        assert "개발" in text or "테스트" in text

    def test_contains_pixiv_metadata_note(self, dlg):
        text = _all_text(dlg)
        assert "Pixiv" in text and "메타데이터" in text

    def test_contains_manual_correction_note(self, dlg):
        text = _all_text(dlg)
        assert "수동 보정" in text or "사전" in text

    def test_contains_account_or_post_deletion_note(self, dlg):
        text = _all_text(dlg)
        assert ("계정" in text and "삭제" in text) or ("비공개" in text)

    def test_contains_split_work_recommendation(self, dlg):
        text = _all_text(dlg)
        assert "나누어" in text or "나눠서" in text or "묶음" in text

    def test_contains_source_captioner_note(self, dlg):
        text = _all_text(dlg)
        assert "Source Captioner" in text

    def test_contains_metadata_only_classification_note(self, dlg):
        """분류 미사용 시 메타데이터 입력만으로 충분 안내."""
        text = _all_text(dlg)
        assert "메타데이터 입력" in text


class TestDialogCheckbox:
    def test_has_checkbox(self, dlg):
        chks = dlg.findChildren(QCheckBox)
        assert len(chks) >= 1

    def test_checkbox_default_checked(self, dlg):
        chks = dlg.findChildren(QCheckBox)
        assert any(c.isChecked() for c in chks)

    def test_checkbox_label_mentions_dont_show_again(self, dlg):
        chks = dlg.findChildren(QCheckBox)
        assert any(
            "다시 보지" in c.text() or "다시 표시" in c.text()
            for c in chks
        )

    def test_dont_show_again_returns_checkbox_state(self, dlg):
        from PyQt6.QtWidgets import QCheckBox
        chks = dlg.findChildren(QCheckBox)
        assert chks
        chk = chks[0]
        chk.setChecked(True)
        assert dlg.dont_show_again_for_version() is True
        chk.setChecked(False)
        assert dlg.dont_show_again_for_version() is False
