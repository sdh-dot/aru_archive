"""Aru Archive 시작 안내 다이얼로그.

앱 첫 기동 또는 새 버전 첫 기동 시 사용자에게 핵심 기능과 주의사항을
안내한다. Startup Splash와는 별개로 동작한다.

PyQt6 전용. PySide6 사용 금지.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)


class StartupNoticeDialog(QDialog):
    """버전별 1회 표시되는 시작 안내 다이얼로그.

    제목, 핵심 기능 소개, 사용 시 주의사항, "이 버전에서 다시 보지 않기"
    체크박스, 확인 버튼으로 구성된다. 본 다이얼로그는 실제 파일이나
    설정을 직접 변경하지 않으며, 호출자가 dont_show_again_for_version()을
    조회해 config 저장을 처리한다.
    """

    def __init__(
        self,
        app_version: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aru Archive 시작 안내")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumSize(560, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("<h2>Aru Archive에 오신 것을 환영합니다</h2>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        # 본문 — RichText + QScrollArea로 긴 안내 wrap
        body = QLabel(
            "<p>Aru Archive는 이미지 메타데이터 보강, 중복 정리, 분류 보조를 "
            "위한 데스크톱 도구입니다.</p>"
            "<p><b>현재 개발/테스트 진행 중인 버전</b>이며, 일부 동작과 UI는 "
            "지속적으로 다듬어지고 있습니다.</p>"
            "<h3>처음 사용할 때 알아두면 좋은 점</h3>"
            "<ul>"
            "  <li>처음 작업하실 때는 한 번에 많은 이미지를 옮기지 마시고, "
            "      작은 묶음으로 나누어 처리하시는 것을 권장합니다. 이미지 수가 "
            "      많으면 스캔과 메타데이터 보강에 시간이 걸릴 수 있습니다.</li>"
            "  <li>자동 분류는 현 시점 기준 <b>Pixiv ID / Pixiv 메타데이터가 "
            "      있는 이미지</b>에서 가장 잘 동작합니다.</li>"
            "  <li>사전(시리즈/캐릭터)이 아직 충분하지 않은 경우, 일부 항목은 "
            "      <b>수동 보정</b>이 필요할 수 있습니다.</li>"
            "  <li>원작자가 <b>계정을 삭제</b>했거나 게시글을 <b>삭제/비공개</b> "
            "      처리한 경우 메타데이터를 가져올 수 없습니다.</li>"
            "  <li>수기 입력 기능은 추후 검토 중입니다.</li>"
            "  <li>분류가 필요하지 않으시다면, 메타데이터 입력만 진행하셔도 "
            "      Source Captioner 사용에는 지장이 없습니다.</li>"
            "</ul>"
        )
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll, 1)

        # checkbox
        version_label = app_version or "현재 버전"
        self._dont_show_chk = QCheckBox(
            f"이 버전에서 다시 보지 않기  ({version_label})"
        )
        self._dont_show_chk.setChecked(True)
        layout.addWidget(self._dont_show_chk)

        # 버튼
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("확인")
        ok_btn.setDefault(True)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def dont_show_again_for_version(self) -> bool:
        return self._dont_show_chk.isChecked()
