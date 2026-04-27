"""
삭제 미리보기 다이얼로그.

삭제 전 반드시 이 다이얼로그를 통해 사용자에게 내용을 보여주고 확인을 받아야 한다.
High risk (original 포함 등)일 때는 'DELETE' 직접 입력 확인을 요구한다.

PyQt6 전용. PySide6 사용 금지.
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

_RISK_COLOR = {
    "high":   "#FF6B7A",
    "medium": "#FFD166",
    "low":    "#5CDB8F",
}


class DeletePreviewDialog(QDialog):
    """
    삭제 미리보기를 표시하고 사용자 확인을 받는 다이얼로그.

    accepted() 시그널이 발생하면 execute_delete_preview(confirmed=True)를 호출해야 한다.
    """

    def __init__(
        self,
        preview: dict,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._preview = preview
        self._confirmed = False

        risk = preview.get("risk", "low")
        self.setWindowTitle("영구 삭제 미리보기")
        self.resize(700, 560)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- 경고 헤더 ---
        has_original = preview.get("role_counts", {}).get("original", 0) > 0
        if has_original:
            warn = QLabel(
                "⚠️  선택한 항목에는 original 파일이 포함되어 있습니다.\n"
                "이 작업은 파일을 영구 삭제하며 복구할 수 없습니다."
            )
            warn.setStyleSheet(
                "color: #FF6B7A; font-weight: bold; "
                "background: #3A1A20; border: 1px solid #FF6B7A; "
                "border-radius: 4px; padding: 8px;"
            )
            warn.setWordWrap(True)
            layout.addWidget(warn)
        else:
            warn = QLabel("이 작업은 파일을 영구 삭제하며 복구할 수 없습니다.")
            warn.setStyleSheet("color: #FFD166; font-weight: bold; padding: 4px;")
            layout.addWidget(warn)

        # --- 요약 ---
        layout.addWidget(self._build_summary(preview))

        # --- 경고 목록 ---
        warnings = preview.get("warnings", [])
        if warnings:
            layout.addWidget(self._build_warning_list(warnings))

        # --- 파일 목록 ---
        layout.addWidget(self._build_file_list(preview.get("file_items", [])))

        # --- High risk: DELETE 입력 확인 ---
        self._confirm_input: Optional[QLineEdit] = None
        if risk == "high":
            layout.addWidget(self._build_confirm_input())

        # --- 버튼 ---
        btn_box = QDialogButtonBox()
        self._btn_delete = QPushButton("🗑 영구 삭제")
        self._btn_delete.setStyleSheet(
            "QPushButton { background: #8B1A2A; color: #F7E8EC; "
            "font-weight: bold; padding: 6px 18px; border-radius: 4px; }"
            "QPushButton:hover { background: #A82035; }"
            "QPushButton:disabled { background: #4A2030; color: #8F6874; }"
        )
        self._btn_cancel = QPushButton("취소")
        self._btn_cancel.setStyleSheet(
            "QPushButton { background: #2B1720; color: #F7E8EC; "
            "padding: 6px 18px; border-radius: 4px; }"
        )
        btn_box.addButton(self._btn_delete, QDialogButtonBox.ButtonRole.AcceptRole)
        btn_box.addButton(self._btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(btn_box)

        self._btn_delete.clicked.connect(self._on_delete_clicked)
        self._btn_cancel.clicked.connect(self.reject)

        # High risk면 DELETE 입력 전까지 버튼 비활성
        if risk == "high" and self._confirm_input:
            self._btn_delete.setEnabled(False)
            self._confirm_input.textChanged.connect(self._on_confirm_text_changed)

    # ------------------------------------------------------------------
    # 공개
    # ------------------------------------------------------------------

    def is_confirmed(self) -> bool:
        return self._confirmed

    # ------------------------------------------------------------------
    # 내부 빌더
    # ------------------------------------------------------------------

    def _build_summary(self, preview: dict) -> QGroupBox:
        gb = QGroupBox("삭제 요약")
        layout = QVBoxLayout(gb)
        layout.setSpacing(2)

        risk = preview.get("risk", "low")
        risk_color = _RISK_COLOR.get(risk, "#F7E8EC")
        role_counts = preview.get("role_counts", {})

        rows = [
            ("삭제 대상 파일 수", str(preview.get("total_files", 0))),
            ("영향받는 작품 그룹", str(preview.get("groups_affected", 0))),
            ("삭제 후 빈 그룹", str(preview.get("groups_becoming_empty", 0))),
            ("위험도",
             f'<span style="color:{risk_color}; font-weight:bold;">{risk.upper()}</span>'),
        ]
        for role in ("original", "managed", "sidecar", "classified_copy"):
            cnt = role_counts.get(role, 0)
            if cnt:
                rows.append((f"  · {role}", str(cnt)))
        for meta_status, cnt in preview.get("status_counts", {}).items():
            if cnt:
                rows.append((f"  · {meta_status}", str(cnt)))

        for label, value in rows:
            lbl = QLabel(f"<b>{label}:</b> {value}")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(lbl)

        return gb

    def _build_warning_list(self, warnings: list[str]) -> QGroupBox:
        gb = QGroupBox(f"경고 ({len(warnings)}건)")
        gb.setStyleSheet("QGroupBox { color: #FFD166; }")
        layout = QVBoxLayout(gb)
        lw = QListWidget()
        lw.setMaximumHeight(100)
        lw.setStyleSheet(
            "QListWidget { background: #2B1018; color: #FFD166; border: none; }"
        )
        for w in warnings:
            lw.addItem(QListWidgetItem(w))
        layout.addWidget(lw)
        return gb

    def _build_file_list(self, file_items: list[dict]) -> QGroupBox:
        gb = QGroupBox(f"삭제 대상 파일 ({len(file_items)}개)")
        layout = QVBoxLayout(gb)
        lw = QListWidget()
        lw.setStyleSheet(
            "QListWidget { background: #211018; color: #F7E8EC; border: none; }"
        )
        for item in file_items:
            path = item.get("file_path", "")
            role = item.get("file_role", "")
            status = item.get("metadata_sync_status", "")
            exists = "✓" if item.get("exists_on_disk") else "✗ missing"
            text = f"[{role}] {os.path.basename(path)}  ({status})  {exists}"
            wi = QListWidgetItem(text)
            if role == "original":
                wi.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#FF6B7A"))
            lw.addItem(wi)
        layout.addWidget(lw)
        return gb

    def _build_confirm_input(self) -> QGroupBox:
        gb = QGroupBox("위험 작업 확인")
        gb.setStyleSheet("QGroupBox { color: #FF6B7A; }")
        layout = QVBoxLayout(gb)
        lbl = QLabel("계속하려면 <b>DELETE</b>를 정확히 입력하세요:")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(lbl)
        self._confirm_input = QLineEdit()
        self._confirm_input.setPlaceholderText("DELETE")
        self._confirm_input.setStyleSheet(
            "QLineEdit { background: #211018; color: #FF6B7A; "
            "border: 1px solid #FF6B7A; padding: 4px; font-weight: bold; }"
        )
        layout.addWidget(self._confirm_input)
        return gb

    # ------------------------------------------------------------------
    # 슬롯
    # ------------------------------------------------------------------

    def _on_confirm_text_changed(self, text: str) -> None:
        self._btn_delete.setEnabled(text.strip() == "DELETE")

    def _on_delete_clicked(self) -> None:
        risk = self._preview.get("risk", "low")
        if risk == "high" and self._confirm_input:
            if self._confirm_input.text().strip() != "DELETE":
                QMessageBox.warning(self, "확인 필요", "DELETE를 정확히 입력해야 합니다.")
                return
        self._confirmed = True
        self.accept()
