"""파일 무결성 검사 결과 confirm 다이얼로그.

dry-run 결과를 사용자에게 보여주고 missing으로 표시할지 confirm 받는다.
실제 파일 삭제는 절대 수행하지 않는다.

PyQt6 전용. PySide6 사용 금지.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

_PREVIEW_LIMIT = 20


class IntegrityConfirmDialog(QDialog):
    """파일 무결성 검사 결과 — 누락 파일을 missing으로 표시할지 확인.

    실제 파일을 삭제하지 않습니다.
    DB에서 해당 파일을 누락(missing) 상태로만 표시합니다.
    """

    def __init__(
        self,
        scan_result: dict,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("파일 무결성 검사 — 누락 파일 처리")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(560, 480)

        missing_files = scan_result.get("missing_files", [])
        missing_count = scan_result.get("missing_count", 0)
        affected_group_count = scan_result.get("affected_group_count", 0)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 안내 문구
        notice = QLabel(
            "<b>실제 파일을 삭제하지 않습니다.</b><br>"
            "DB에서 해당 파일을 '누락(missing)' 상태로 표시합니다.<br>"
            "파일 복원 자동 처리는 별도 기능입니다."
        )
        notice.setTextFormat(Qt.TextFormat.RichText)
        notice.setWordWrap(True)
        layout.addWidget(notice)

        # 요약
        summary = QLabel(
            f"누락 파일: <b>{missing_count}</b>건  /  "
            f"영향받는 그룹: <b>{affected_group_count}</b>개"
        )
        summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(summary)

        # 샘플 경로 리스트 (상위 _PREVIEW_LIMIT개)
        sample_label = QLabel(f"샘플 경로 (상위 {_PREVIEW_LIMIT}개):")
        layout.addWidget(sample_label)

        list_widget = QListWidget()
        for item in missing_files[:_PREVIEW_LIMIT]:
            text = f"[{item.get('file_role', '?')}] {item.get('file_path', '')}"
            list_widget.addItem(QListWidgetItem(text))
        if missing_count > _PREVIEW_LIMIT:
            list_widget.addItem(QListWidgetItem(
                f"... 외 {missing_count - _PREVIEW_LIMIT}건"
            ))
        layout.addWidget(list_widget, 1)

        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("누락으로 표시")
        ok_btn.setToolTip(
            "선택한 파일들을 DB에서 '누락' 상태로 기록합니다. 실제 파일은 삭제되지 않습니다."
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
