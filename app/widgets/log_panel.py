"""하단 로그 패널 위젯. Python logging과 연동."""
from __future__ import annotations

import logging
from html import escape

from PyQt6.QtCore import Qt, QMetaObject, Q_ARG, pyqtSlot as Slot
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)


class _GuiLogHandler(logging.Handler):
    """Python logging → GUI 패널로 메시지를 포워딩하는 핸들러."""

    def __init__(self, panel: "LogPanel") -> None:
        super().__init__()
        self._panel = panel

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        try:
            QMetaObject.invokeMethod(
                self._panel,
                "_append_text",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, msg),
            )
        except RuntimeError:
            # Panel C++ object has been deleted (e.g. during tests)
            pass


class LogPanel(QWidget):
    """
    하단 로그 패널.
    - append(msg): 직접 메시지 추가
    - Python logging(INFO/WARN/ERROR)을 자동 수신하여 색상 구분 표시
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogPanel")
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "#LogPanel { background-color: #1A0F14; border-top: 1px solid #4A2030; }"
        )
        self._setup_ui()
        self._connect_logging()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 4)
        layout.setSpacing(2)

        header = QHBoxLayout()
        lbl = QLabel("로그")
        lbl.setStyleSheet(
            "font-weight: bold; color: #D8AEBB; font-size: 11px;"
        )
        header.addWidget(lbl)
        header.addStretch()
        btn_clear = QPushButton("지우기")
        btn_clear.setFixedSize(52, 20)
        btn_clear.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 0;"
            "  background: #3A202B; color: #D8AEBB; border: 1px solid #4A2030;"
            "  border-radius: 3px; }"
            "QPushButton:hover { background: #452634; }"
        )
        btn_clear.clicked.connect(self.clear)
        header.addWidget(btn_clear)
        layout.addLayout(header)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.setStyleSheet(
            "QTextEdit {"
            "  background: #140A0F;"
            "  color: #D8AEBB;"
            "  font-family: Consolas, 'Courier New', monospace;"
            "  font-size: 11px;"
            "  border: 1px solid #4A2030;"
            "}"
        )
        layout.addWidget(self._text)

    def _connect_logging(self) -> None:
        handler = _GuiLogHandler(self)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
        )
        handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(handler)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def append(self, message: str) -> None:
        """직접 메시지 추가 (메인 스레드에서 호출)."""
        self._append_text(message)

    @Slot(str)
    def _append_text(self, message: str) -> None:
        """색상 구분 HTML로 로그를 삽입한다."""
        upper = message.upper()[:20]
        if "[ERROR]" in message or "ERROR" in upper:
            color = "#FF6B7A"
        elif "[WARN]" in message or "WARNING" in upper:
            color = "#FFC857"
        elif "[INFO]" in message or "INFO" in upper:
            color = "#8FD694"
        else:
            color = "#D8AEBB"

        html = f'<span style="color:{color}">{escape(message)}</span>'
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._text.setTextCursor(cursor)
        self._text.insertHtml(html + "<br>")
        self._text.ensureCursorVisible()

    def clear(self) -> None:
        self._text.clear()
