"""
작업 로그 뷰 — Undo 이력 및 분류 로그.

레이아웃:
  상단: QTableWidget (undo_entries 목록)
  하단: QTableWidget (선택된 항목의 copy_records 상세)
  버튼: [🔄 새로고침] [⏪ Undo] [닫기]

Undo 흐름:
  1. 행 선택 → [Undo] 클릭
  2. evaluate_undo_entry() 실행
  3. 확인 다이얼로그 표시
  4. modified 파일 있으면 경고 다이얼로그
  5. execute_undo_entry() 실행
  6. 결과 표시 + 목록 새로고침
"""
from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.undo_manager import (
    STATUS_LABEL, evaluate_undo_entry, execute_undo_entry,
    expire_old_undo_entries, get_undo_entry_detail, list_undo_entries,
)

logger = logging.getLogger(__name__)

_ENTRY_COLS  = ["작업 시각", "유형", "상태", "복사본", "총 크기", "만료일"]
_RECORD_COLS = ["규칙", "원본 파일명", "복사본 경로", "파일 크기", "복사 시각", "현재 상태"]

_RECORD_STATUS_LABEL: dict[str, str] = {
    "deletable":   "삭제 가능",
    "missing":     "이미 없음",
    "modified":    "수정됨 (경고)",
    "unsafe_role": "삭제 불가",
}


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


class WorkLogView(QDialog):
    """분류 작업 로그 및 Undo 다이얼로그."""

    log_msg = Signal(str)

    def __init__(
        self,
        conn,
        config: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn   = conn
        self._config = config or {}
        self.setWindowTitle("🕘 작업 로그 / Undo")
        self.resize(1100, 620)
        self._build_ui()
        self._load_entries()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 필터 행
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("상태 필터:"))
        self._filter_box = QComboBox()
        self._filter_box.addItems(["all", "pending", "completed", "partial", "failed", "expired"])
        self._filter_box.currentTextChanged.connect(self._load_entries)
        filter_row.addWidget(self._filter_box)
        filter_row.addStretch()
        btn_refresh = QPushButton("🔄 새로고침")
        btn_refresh.clicked.connect(self._load_entries)
        filter_row.addWidget(btn_refresh)
        root.addLayout(filter_row)

        # 스플리터: 상단=entry 목록, 하단=record 상세
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 상단 — undo_entries 목록
        self._entry_table = QTableWidget(0, len(_ENTRY_COLS))
        self._entry_table.setHorizontalHeaderLabels(_ENTRY_COLS)
        self._entry_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._entry_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._entry_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._entry_table.setAlternatingRowColors(True)
        self._entry_table.itemSelectionChanged.connect(self._on_entry_selected)
        splitter.addWidget(self._entry_table)

        # 하단 — copy_records 상세
        self._record_table = QTableWidget(0, len(_RECORD_COLS))
        self._record_table.setHorizontalHeaderLabels(_RECORD_COLS)
        self._record_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._record_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._record_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._record_table.setAlternatingRowColors(True)
        splitter.addWidget(self._record_table)

        splitter.setSizes([300, 200])
        root.addWidget(splitter, 1)

        # 버튼 행
        btn_row = QHBoxLayout()
        self._btn_undo  = QPushButton("⏪ Undo")
        self._btn_close = QPushButton("닫기")
        self._btn_undo.setEnabled(False)
        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_undo)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # 데이터 로드
    # ------------------------------------------------------------------

    def _load_entries(self) -> None:
        try:
            expire_old_undo_entries(self._conn)
        except Exception:
            pass

        status_filter = self._filter_box.currentText()
        st = None if status_filter == "all" else status_filter
        entries = list_undo_entries(self._conn, limit=200, status=st)

        self._entry_table.setSortingEnabled(False)
        self._entry_table.setRowCount(len(entries))
        for r_idx, e in enumerate(entries):
            values = [
                _fmt_dt(e.get("performed_at")),
                e.get("operation_type", ""),
                STATUS_LABEL.get(e.get("undo_status", ""), e.get("undo_status", "")),
                str(e.get("copy_count", 0)),
                _fmt_size(int(e.get("total_size") or 0)),
                _fmt_dt(e.get("undo_expires_at")),
            ]
            for c_idx, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setData(Qt.ItemDataRole.UserRole, e["entry_id"])
                self._entry_table.setItem(r_idx, c_idx, item)
        self._entry_table.setSortingEnabled(True)
        self._record_table.setRowCount(0)
        self._btn_undo.setEnabled(False)

    def _on_entry_selected(self) -> None:
        entry_id = self._selected_entry_id()
        if not entry_id:
            self._record_table.setRowCount(0)
            self._btn_undo.setEnabled(False)
            return
        try:
            detail = get_undo_entry_detail(self._conn, entry_id)
            self._btn_undo.setEnabled(detail.get("undo_status") == "pending")
            self._load_record_detail(entry_id, detail)
        except Exception as exc:
            logger.error("상세 로드 오류: %s", exc)

    def _load_record_detail(self, entry_id: str, detail: dict) -> None:
        """copy_records를 표시하면서 evaluate로 현재 상태를 함께 보여준다."""
        try:
            evaluation = evaluate_undo_entry(self._conn, entry_id)
            eval_map = {
                r["copy_record_id"]: r["status"]
                for r in evaluation.get("records", [])
            }
        except Exception:
            eval_map = {}

        records = detail.get("records", [])
        self._record_table.setSortingEnabled(False)
        self._record_table.setRowCount(len(records))
        for r_idx, rec in enumerate(records):
            src_name = rec.get("src_path", "")
            if src_name:
                src_name = src_name.replace("\\", "/").split("/")[-1]
            cur_status = eval_map.get(rec.get("id"), "")
            values = [
                rec.get("rule_id", ""),
                src_name,
                rec.get("dest_path", ""),
                _fmt_size(int(rec.get("dest_file_size") or 0)),
                _fmt_dt(rec.get("copied_at")),
                _RECORD_STATUS_LABEL.get(cur_status, cur_status),
            ]
            for c_idx, val in enumerate(values):
                self._record_table.setItem(r_idx, c_idx, QTableWidgetItem(val))
        self._record_table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Undo 실행
    # ------------------------------------------------------------------

    def _selected_entry_id(self) -> str | None:
        selected = self._entry_table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.ItemDataRole.UserRole)

    def _on_undo(self) -> None:
        entry_id = self._selected_entry_id()
        if not entry_id:
            return

        try:
            evaluation = evaluate_undo_entry(self._conn, entry_id)
        except Exception as exc:
            QMessageBox.critical(self, "평가 오류", str(exc))
            return

        if not evaluation["can_undo"]:
            QMessageBox.information(
                self, "Undo 불가",
                f"현재 상태({evaluation['undo_status']})에서는 Undo할 수 없습니다.",
            )
            return

        force_modified = False

        # 수정된 파일 경고
        if evaluation["requires_confirmation"]:
            modified_paths = [
                r["dest_path"] for r in evaluation["records"]
                if r["status"] == "modified"
            ]
            mod_list = "\n".join(f"  • {p}" for p in modified_paths[:10])
            btn = QMessageBox.question(
                self,
                "수정된 복사본 감지",
                f"일부 복사본이 생성 이후 수정된 것으로 보입니다.\n\n"
                f"수정된 파일:\n{mod_list}\n\n"
                f"이 파일도 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if btn == QMessageBox.StandardButton.Cancel:
                return
            force_modified = btn == QMessageBox.StandardButton.Yes

        # 삭제 예정 목록 확인 다이얼로그
        deletable = [
            r["dest_path"] for r in evaluation["records"]
            if r["status"] == "deletable"
               or (r["status"] == "modified" and force_modified)
        ]
        if not deletable and not evaluation["summary"]["missing"]:
            QMessageBox.information(self, "삭제 대상 없음", "삭제할 복사본이 없습니다.")
            return

        dest_list = "\n".join(f"  • {p}" for p in deletable[:15])
        if len(deletable) > 15:
            dest_list += f"\n  … 외 {len(deletable) - 15}개"

        confirm = QMessageBox.question(
            self,
            "Undo 확인",
            f"이 작업으로 생성된 Classified 복사본 {len(deletable)}개를 제거합니다.\n\n"
            f"삭제 대상:\n{dest_list}\n\n"
            f"Inbox 원본과 Managed 파일은 삭제되지 않습니다.\n\n"
            f"계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # 실행
        classified_dir = self._config.get("classified_dir", "") or None
        self.log_msg.emit(f"[INFO] Undo started: entry_id={entry_id[:8]}…")
        try:
            result = execute_undo_entry(
                self._conn,
                entry_id,
                delete_empty_dirs=True,
                force_modified=force_modified,
                classified_dir=classified_dir,
            )
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] Undo 오류: {exc}")
            QMessageBox.critical(self, "Undo 오류", str(exc))
            return

        for path in result.get("deleted", []):
            self.log_msg.emit(f"[INFO] Deleted classified copy: {path}")
        for path in result.get("skipped_modified", []):
            self.log_msg.emit(f"[WARN] Skipped modified copy: {path}")
        for path in result.get("failed", []):
            self.log_msg.emit(f"[ERROR] Delete failed: {path}")

        d = len(result.get("deleted", []))
        s = (len(result.get("skipped_missing", []))
             + len(result.get("skipped_modified", [])))
        self.log_msg.emit(
            f"[INFO] Undo {result['undo_status']}: deleted={d}, skipped={s}"
        )

        QMessageBox.information(
            self, "Undo 결과",
            f"완료: {d}개 삭제, {s}개 건너뜀\n상태: {result['undo_status']}",
        )
        self._load_entries()
