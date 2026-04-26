"""
No Metadata 큐 뷰 — no_metadata_queue 항목 목록 및 수동 처리.

표시 컬럼: 파일명 / 경로 / fail_reason / 등록 시각 / 해결됨 / 메모
버튼: 재시도 (skeleton) / 무시 / 파일 열기 / 폴더 열기
목록 표시와 카운터는 완전 동작. 재시도는 MVP-B에서 구현.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

_FAIL_REASON_LABEL: dict[str, str] = {
    "no_dom_data":               "DOM 데이터 없음",
    "parse_error":               "파싱 오류",
    "network_error":             "네트워크 오류",
    "unsupported_format":        "미지원 형식",
    "manual_add":                "수동 추가",
    "embed_failed":              "임베딩 오류",
    "partial_data":              "불완전 데이터",
    "artwork_restricted":        "접근 제한",
    "api_error":                 "API 오류",
    "bmp_convert_failed":        "BMP 변환 실패",
    "managed_file_create_failed": "관리본 생성 실패",
    "metadata_write_failed":     "메타데이터 쓰기 실패",
}

_COLS = ["파일명", "경로", "fail_reason", "등록 시각", "해결됨", "메모"]
_COL = {name: i for i, name in enumerate(_COLS)}


class NoMetadataView(QWidget):
    """
    no_metadata_queue 항목 목록.

    Signals:
        retry_requested(queue_id)   : [재시도] 버튼 (MVP-B skeleton)
        ignore_requested(queue_id)  : [무시] 버튼 → resolved=1
    """

    retry_requested  = Signal(str)
    ignore_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 헤더 행
        hdr = QHBoxLayout()
        self._count_lbl = QLabel("No Metadata Queue — 0건")
        self._count_lbl.setStyleSheet(
            "font-weight: bold; color: #E69AAA; font-size: 12px;"
        )
        hdr.addWidget(self._count_lbl)
        hdr.addStretch()
        layout.addLayout(hdr)

        # 테이블
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            _COL["경로"], QHeaderView.ResizeMode.Stretch
        )
        self._table.setStyleSheet(
            "QTableWidget {"
            "  background: #1A0F14; color: #F7E8EC; font-size: 11px;"
            "  border: 1px solid #4A2030;"
            "  alternate-background-color: #211018;"
            "  gridline-color: #4A2030;"
            "}"
            "QHeaderView::section {"
            "  background: #2B1720; color: #D8AEBB;"
            "  border: none; padding: 4px; font-size: 11px;"
            "}"
            "QTableWidget::item:selected { background: #5C2A3A; color: #F7E8EC; }"
            "QTableWidget::item:hover { background: #3A202B; }"
        )
        self._table.selectionModel().selectionChanged.connect(self._update_buttons)
        layout.addWidget(self._table)

        # 버튼 행
        btn_row = QHBoxLayout()
        self._btn_retry       = _btn("재시도",     "#3949ab", "fail_reason 재처리 (MVP-B)")
        self._btn_ignore      = _btn("무시",       "#555555", "resolved=1 처리")
        self._btn_open_file   = _btn("파일 열기",  "#2a5a2a", "파일을 기본 앱으로 열기")
        self._btn_open_folder = _btn("폴더 열기",  "#2a3a5a", "파일이 있는 폴더 열기")

        for b in [self._btn_retry, self._btn_ignore,
                  self._btn_open_file, self._btn_open_folder]:
            b.setEnabled(False)
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._btn_retry      .clicked.connect(self._on_retry)
        self._btn_ignore     .clicked.connect(self._on_ignore)
        self._btn_open_file  .clicked.connect(self._on_open_file)
        self._btn_open_folder.clicked.connect(self._on_open_folder)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def load_queue(self, rows: list[dict]) -> None:
        """no_metadata_queue 쿼리 결과를 테이블에 표시한다."""
        self._table.setRowCount(0)

        unresolved = sum(1 for r in rows if not r.get("resolved"))
        self._count_lbl.setText(
            f"No Metadata Queue — {unresolved}건 미해결 / 전체 {len(rows)}건"
        )

        for r in rows:
            ri = self._table.rowCount()
            self._table.insertRow(ri)

            fp = r.get("file_path", "")
            self._cell(ri, _COL["파일명"],   Path(fp).name if fp else "—")
            self._cell(ri, _COL["경로"],     fp)
            reason = r.get("fail_reason", "")
            self._cell(ri, _COL["fail_reason"], _FAIL_REASON_LABEL.get(reason, reason))
            self._cell(ri, _COL["등록 시각"],
                       (r.get("detected_at") or "")[:19].replace("T", " "))
            self._cell(ri, _COL["해결됨"],   "✓" if r.get("resolved") else "")
            self._cell(ri, _COL["메모"],     r.get("notes") or "")

            # queue_id를 첫 번째 셀의 UserRole에 저장
            item = self._table.item(ri, 0)
            if item:
                item.setData(Qt.ItemDataRole.UserRole, r.get("queue_id"))

        self._update_buttons()

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _cell(self, row: int, col: int, text: str) -> None:
        self._table.setItem(row, col, QTableWidgetItem(str(text)))

    def _selected_queue_id(self) -> Optional[str]:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_file_path(self) -> Optional[str]:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, _COL["경로"])
        return item.text() if item else None

    def _update_buttons(self) -> None:
        has_sel = self._table.currentRow() >= 0
        for b in [self._btn_retry, self._btn_ignore,
                  self._btn_open_file, self._btn_open_folder]:
            b.setEnabled(has_sel)

    def _on_retry(self) -> None:
        qid = self._selected_queue_id()
        if qid:
            self.retry_requested.emit(qid)

    def _on_ignore(self) -> None:
        qid = self._selected_queue_id()
        if qid:
            self.ignore_requested.emit(qid)

    def _on_open_file(self) -> None:
        fp = self._selected_file_path()
        if fp and Path(fp).exists():
            _open_path(fp)

    def _on_open_folder(self) -> None:
        fp = self._selected_file_path()
        if fp:
            _open_path(str(Path(fp).parent))


# ------------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------------

def _btn(text: str, bg: str, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tooltip)
    b.setFixedHeight(28)
    b.setStyleSheet(
        f"QPushButton {{ background: {bg}; color: #F7E8EC;"
        "  border-radius: 4px; padding: 0 12px; font-size: 11px;"
        "  border: 1px solid transparent; }"
        "QPushButton:hover { border-color: #F0A6B8; }"
        "QPushButton:disabled { background: #211018; color: #8F6874; }"
    )
    return b


def _open_path(path: str) -> None:
    """OS-native 파일/폴더 열기."""
    if sys.platform == "win32":
        import os
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
