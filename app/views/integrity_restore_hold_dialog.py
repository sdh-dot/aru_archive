"""복원 보류 항목 확인 다이얼로그.

hash mismatch로 자동 복원이 보류된 항목 목록을 표시한다.
실제 파일 복원 / DB 변경 / hash 갱신 등 어떤 액션도 수행하지 않는다.

PyQt6 전용. PySide6 사용 금지.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_COLUMNS = ["파일 경로", "그룹 ID", "역할", "DB 해시", "현재 해시"]
_COL_PATH = 0
_COL_GROUP = 1
_COL_ROLE = 2
_COL_DB_HASH = 3
_COL_CURRENT_HASH = 4


class IntegrityRestoreHoldDialog(QDialog):
    """hash mismatch로 복원이 보류된 파일 목록을 보여주는 다이얼로그.

    어떤 DB 변경도 수행하지 않습니다.
    강제 복원 / hash 갱신 / 새 파일 등록 액션은 포함하지 않습니다.
    """

    def __init__(
        self,
        mismatch_files: list[dict],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("복원 보류 항목")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(700, 420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 안내 문구
        notice = QLabel(
            "같은 경로에 파일이 다시 나타났지만 저장된 해시와 달라 자동 복원을 보류했습니다.\n"
            "파일이 의도적으로 변경되었다면 무결성 검사를 다시 실행하거나 수동으로 확인해 주세요."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        # 건수 요약
        count_label = QLabel(f"복원 보류: <b>{len(mismatch_files)}</b>건")
        count_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(count_label)

        # 항목 표
        table = QTableWidget(len(mismatch_files), len(_COLUMNS), parent=self)
        table.setHorizontalHeaderLabels(_COLUMNS)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)

        for row, item in enumerate(mismatch_files):
            # 파일 경로 — file_id는 UserRole에 저장 (표시 안 함)
            path_item = QTableWidgetItem(str(item.get("file_path", "")))
            path_item.setData(Qt.ItemDataRole.UserRole, item.get("file_id"))
            table.setItem(row, _COL_PATH, path_item)

            table.setItem(row, _COL_GROUP, QTableWidgetItem(str(item.get("group_id", ""))))
            table.setItem(row, _COL_ROLE, QTableWidgetItem(str(item.get("file_role", ""))))
            table.setItem(row, _COL_DB_HASH, QTableWidgetItem(str(item.get("db_hash", ""))))
            table.setItem(row, _COL_CURRENT_HASH, QTableWidgetItem(str(item.get("current_hash", ""))))

        table.resizeColumnsToContents()
        layout.addWidget(table, 1)

        # 버튼 — 닫기만 제공
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            parent=self,
        )
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setText("닫기")
        close_btn.setDefault(True)
        buttons.rejected.connect(self.reject)
        # Close 버튼은 rejected 시그널을 발생시키므로 accept()로도 처리
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
