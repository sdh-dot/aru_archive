"""
app/views/database_reset_confirm_dialog.py

전체 DB 초기화 전 2단계 확인 다이얼로그.

1단계: 위험 안내 + 초기화 범위 + DB 경로 + 자동 생성 백업 경로 표시
2단계: 확인 문구 직접 입력 — 정확히 일치할 때만 OK 버튼 활성화

사용법:
    dialog = DatabaseResetConfirmDialog(
        db_path="/path/to/aru_archive.db",
        backup_path="/path/to/aru_archive_before_reset_20250502_120000.db",
        parent=self,
    )
    if dialog.exec() == QDialog.DialogCode.Accepted:
        ...proceed with backup + reset...
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

# 확인 문구 — 이 문자열을 그대로 입력해야 OK 활성화
CONFIRM_PHRASE = "전체 초기화"


class DatabaseResetConfirmDialog(QDialog):
    """
    전체 DB 초기화 작업 실행 전 2단계 확인 다이얼로그.

    Parameters
    ----------
    db_path:
        초기화 대상 DB 파일의 절대 경로 (표시 전용).
    backup_path:
        실행 시 자동 생성될 백업 파일 경로 (표시 전용).
        실제 백업 생성은 이 다이얼로그가 담당하지 않는다.
    parent:
        부모 위젯.
    """

    def __init__(
        self,
        db_path: str,
        backup_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("전체 DB 초기화")
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── 위험 안내 배너 ────────────────────────────────────────────────
        warning_lbl = QLabel(
            "<b style='color:#c0392b;'>⚠ 위험: 되돌릴 수 없는 작업입니다.</b>"
        )
        warning_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(warning_lbl)

        # ── 범위 안내 ─────────────────────────────────────────────────────
        scope_lbl = QLabel(
            "DB에 저장된 <b>모든</b> 데이터가 삭제됩니다:\n"
            "  • 작품 / 파일 등록 기록\n"
            "  • 분류 / 태그 / 작업 로그\n"
            "  • 사용자 사전 및 로컬라이제이션\n\n"
            "원본 이미지 파일은 삭제되지 않습니다.\n"
            "실행 직전 아래 경로에 자동 백업이 생성됩니다."
        )
        scope_lbl.setWordWrap(True)
        layout.addWidget(scope_lbl)

        # ── 경로 정보 ─────────────────────────────────────────────────────
        path_header = QLabel("<b>초기화 대상 DB:</b>")
        path_header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(path_header)

        db_path_lbl = QLabel(db_path)
        db_path_lbl.setWordWrap(True)
        db_path_lbl.setStyleSheet("color: #555; font-family: monospace;")
        layout.addWidget(db_path_lbl)

        backup_header = QLabel("<b>자동 백업 경로:</b>")
        backup_header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(backup_header)

        backup_path_lbl = QLabel(backup_path)
        backup_path_lbl.setWordWrap(True)
        backup_path_lbl.setStyleSheet("color: #2980b9; font-family: monospace;")
        layout.addWidget(backup_path_lbl)

        # ── 확인 문구 입력 ────────────────────────────────────────────────
        confirm_instruction = QLabel(
            f"계속하려면 아래 입력란에 <b>{CONFIRM_PHRASE}</b> 를 정확히 입력하세요:"
        )
        confirm_instruction.setTextFormat(Qt.TextFormat.RichText)
        confirm_instruction.setWordWrap(True)
        layout.addWidget(confirm_instruction)

        self._confirm_edit = QLineEdit()
        self._confirm_edit.setPlaceholderText(CONFIRM_PHRASE)
        self._confirm_edit.setAccessibleName("확인 문구 입력")
        layout.addWidget(self._confirm_edit)

        # ── 버튼 ─────────────────────────────────────────────────────────
        self._btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_btn is not None
        ok_btn.setText("전체 초기화 실행")
        ok_btn.setEnabled(False)  # 확인 문구 입력 전까지 비활성

        cancel_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        assert cancel_btn is not None
        cancel_btn.setText("취소")

        self._btn_box.accepted.connect(self.accept)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

        # ── 시그널 연결 ───────────────────────────────────────────────────
        self._confirm_edit.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------------
    # 내부 슬롯
    # ------------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        ok_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(text == CONFIRM_PHRASE)
