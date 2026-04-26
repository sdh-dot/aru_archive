"""
저장 작업 상태 뷰 — save_jobs / job_pages 모니터.

레이아웃:
  필터 행:  [상태 필터] [🔄 새로고침]
  중앙:     QSplitter — save_jobs 목록 (상단) / job_pages 상세 (하단)
  하단 행:  [📂 폴더 열기] [🌐 작품 페이지] [📋 실패 로그 복사]  |stretch|  [닫기]
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

_JOB_COLS  = ["job_id", "시작 시각", "제목", "artwork_id", "상태", "저장", "실패", "총 페이지", "완료 시각"]
_PAGE_COLS = ["페이지", "파일명", "경로", "상태", "크기", "오류"]

_JOB_STATUS_LABEL: dict[str, str] = {
    "pending":   "대기",
    "running":   "진행 중",
    "completed": "완료",
    "failed":    "실패",
    "partial":   "일부 완료",
}

_PAGE_STATUS_LABEL: dict[str, str] = {
    "pending":       "대기",
    "downloading":   "다운로드 중",
    "embed_pending": "임베딩 대기",
    "saved":         "저장됨",
    "failed":        "실패",
}


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


class SaveJobsView(QDialog):
    """저장 작업 진행 상황 다이얼로그."""

    def __init__(self, conn, config: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conn   = conn
        self._config = config or {}
        self.setWindowTitle("💾 저장 작업 상태")
        self.resize(1100, 580)
        self._build_ui()
        self._load_jobs()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 필터 행
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("상태 필터:"))
        self._filter_box = QComboBox()
        self._filter_box.addItems(["all", "running", "completed", "partial", "failed", "pending"])
        self._filter_box.currentTextChanged.connect(self._load_jobs)
        filter_row.addWidget(self._filter_box)
        filter_row.addStretch()
        btn_refresh = QPushButton("🔄 새로고침")
        btn_refresh.clicked.connect(self._load_jobs)
        filter_row.addWidget(btn_refresh)
        root.addLayout(filter_row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # 상단 — save_jobs 목록
        self._job_table = QTableWidget(0, len(_JOB_COLS))
        self._job_table.setHorizontalHeaderLabels(_JOB_COLS)
        hh = self._job_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # 제목 열만 Stretch
        self._job_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._job_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._job_table.setAlternatingRowColors(True)
        self._job_table.itemSelectionChanged.connect(self._on_job_selected)
        splitter.addWidget(self._job_table)

        # 하단 — job_pages 상세
        self._page_table = QTableWidget(0, len(_PAGE_COLS))
        self._page_table.setHorizontalHeaderLabels(_PAGE_COLS)
        ph = self._page_table.horizontalHeader()
        ph.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # 경로 열만 Stretch
        self._page_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._page_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._page_table.setAlternatingRowColors(True)
        splitter.addWidget(self._page_table)

        splitter.setSizes([300, 200])
        root.addWidget(splitter, 1)

        # 하단 버튼 행
        btn_row = QHBoxLayout()
        self._btn_folder = QPushButton("📂 폴더 열기")
        self._btn_folder.setEnabled(False)
        self._btn_folder.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self._btn_folder)

        self._btn_pixiv = QPushButton("🌐 작품 페이지")
        self._btn_pixiv.setEnabled(False)
        self._btn_pixiv.clicked.connect(self._on_open_pixiv)
        btn_row.addWidget(self._btn_pixiv)

        self._btn_copy_log = QPushButton("📋 실패 로그 복사")
        self._btn_copy_log.setEnabled(False)
        self._btn_copy_log.clicked.connect(self._on_copy_fail_log)
        btn_row.addWidget(self._btn_copy_log)

        btn_row.addStretch()

        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    # ---------------------------------------------------------------------------
    # 데이터 로드
    # ---------------------------------------------------------------------------

    def _load_jobs(self) -> None:
        status_filter = self._filter_box.currentText()
        base_sql = (
            "SELECT j.job_id, j.started_at, ag.artwork_title, j.artwork_id, j.status,"
            " j.saved_pages, j.failed_pages, j.total_pages, j.completed_at"
            " FROM save_jobs j"
            " LEFT JOIN artwork_groups ag ON j.group_id = ag.group_id"
        )
        if status_filter == "all":
            rows = self._conn.execute(
                base_sql + " ORDER BY j.started_at DESC LIMIT 200"
            ).fetchall()
        else:
            rows = self._conn.execute(
                base_sql + " WHERE j.status=? ORDER BY j.started_at DESC LIMIT 200",
                (status_filter,),
            ).fetchall()

        self._job_table.setSortingEnabled(False)
        self._job_table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            values = [
                (row["job_id"] or "")[:8],
                _fmt_dt(row["started_at"]),
                row["artwork_title"] or "",
                row["artwork_id"]    or "",
                _JOB_STATUS_LABEL.get(row["status"] or "", row["status"] or ""),
                str(row["saved_pages"]  or 0),
                str(row["failed_pages"] or 0),
                str(row["total_pages"]  or 0),
                _fmt_dt(row["completed_at"]),
            ]
            job_data = {"job_id": row["job_id"], "artwork_id": row["artwork_id"]}
            for c_idx, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setData(Qt.ItemDataRole.UserRole, job_data)
                self._job_table.setItem(r_idx, c_idx, item)
        self._job_table.setSortingEnabled(True)
        self._page_table.setRowCount(0)
        self._set_action_buttons_enabled(False)

    def _on_job_selected(self) -> None:
        job_data = self._selected_job_data()
        if not job_data:
            self._page_table.setRowCount(0)
            self._set_action_buttons_enabled(False)
            return

        self._set_action_buttons_enabled(True)

        job_id = job_data["job_id"]
        if not job_id:
            return
        try:
            pages = self._conn.execute(
                "SELECT jp.page_index, jp.filename, af.file_path,"
                " jp.status, jp.download_bytes, jp.error_message"
                " FROM job_pages jp"
                " LEFT JOIN artwork_files af ON jp.file_id = af.file_id"
                " WHERE jp.job_id=? ORDER BY jp.page_index",
                (job_id,),
            ).fetchall()
            self._page_table.setSortingEnabled(False)
            self._page_table.setRowCount(len(pages))
            for r_idx, p in enumerate(pages):
                file_path = p["file_path"] or ""
                values = [
                    str(p["page_index"]),
                    p["filename"]    or "",
                    file_path,
                    _PAGE_STATUS_LABEL.get(p["status"] or "", p["status"] or ""),
                    _fmt_bytes(p["download_bytes"]),
                    p["error_message"] or "",
                ]
                for c_idx, val in enumerate(values):
                    self._page_table.setItem(r_idx, c_idx, QTableWidgetItem(val))
            self._page_table.setSortingEnabled(True)
        except Exception as exc:
            logger.error("job_pages 로드 오류: %s", exc)

    # ---------------------------------------------------------------------------
    # 액션 버튼 핸들러
    # ---------------------------------------------------------------------------

    def _on_open_folder(self) -> None:
        job_data = self._selected_job_data()
        if not job_data:
            return
        try:
            row = self._conn.execute(
                "SELECT af.file_path FROM artwork_files af"
                " JOIN job_pages jp ON jp.file_id = af.file_id"
                " WHERE jp.job_id=? AND jp.status='saved' LIMIT 1",
                (job_data["job_id"],),
            ).fetchone()
            if row and row["file_path"]:
                folder = str(Path(row["file_path"]).parent)
                os.startfile(folder)
                return
        except Exception as exc:
            logger.error("폴더 열기 오류: %s", exc)
        # 파일 경로를 못 찾으면 inbox_dir로 fallback
        inbox_dir = self._config.get("inbox_dir", "")
        if inbox_dir:
            os.startfile(inbox_dir)

    def _on_open_pixiv(self) -> None:
        job_data = self._selected_job_data()
        if not job_data:
            return
        artwork_id = job_data.get("artwork_id", "")
        if artwork_id:
            QDesktopServices.openUrl(
                QUrl(f"https://www.pixiv.net/artworks/{artwork_id}")
            )

    def _on_copy_fail_log(self) -> None:
        job_data = self._selected_job_data()
        if not job_data:
            return
        try:
            rows = self._conn.execute(
                "SELECT page_index, error_message FROM job_pages"
                " WHERE job_id=? AND status='failed' ORDER BY page_index",
                (job_data["job_id"],),
            ).fetchall()
            lines = [
                f"job_id:    {job_data['job_id']}",
                f"artwork_id: {job_data.get('artwork_id', '')}",
            ]
            if rows:
                for r in rows:
                    lines.append(f"  page {r['page_index']}: {r['error_message']}")
            else:
                lines.append("  (실패한 페이지 없음)")
            QApplication.clipboard().setText("\n".join(lines))
        except Exception as exc:
            logger.error("실패 로그 복사 오류: %s", exc)

    # ---------------------------------------------------------------------------
    # 유틸
    # ---------------------------------------------------------------------------

    def _selected_job_data(self) -> dict | None:
        selected = self._job_table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.ItemDataRole.UserRole)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self._btn_folder.setEnabled(enabled)
        self._btn_pixiv.setEnabled(enabled)
        self._btn_copy_log.setEnabled(enabled)
