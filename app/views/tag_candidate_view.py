"""
태그 후보 검토 다이얼로그.

tag_candidates 테이블의 pending 후보를 표시하고,
사용자가 개별 행을 승인/거부/무시할 수 있다.
승인된 항목은 tag_aliases에 등록되어 다음 [🏷 태그 재분류]부터 적용된다.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

_COLS = [
    "raw_tag", "translated", "type", "canonical", "series",
    "confidence", "evidence", "source", "status",
]
_COL_LABELS = [
    "원본 태그", "번역", "타입", "canonical", "시리즈",
    "신뢰도", "근거수", "소스", "상태",
]


class TagCandidateView(QDialog):
    """태그 후보 검토 다이얼로그."""

    def __init__(self, conn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conn = conn
        self.setWindowTitle("🏷 태그 후보 검토")
        self.resize(900, 500)
        self._build_ui()
        self._load_candidates()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 필터 행
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("상태 필터:"))
        self._filter_box = QComboBox()
        self._filter_box.addItems(["pending", "accepted", "rejected", "ignored", "all"])
        self._filter_box.currentTextChanged.connect(self._load_candidates)
        filter_row.addWidget(self._filter_box)

        filter_row.addSpacing(16)
        filter_row.addWidget(QLabel("소스 필터:"))
        self._source_filter_box = QComboBox()
        self._source_filter_box.addItems([
            "all", "group_analysis", "full_analysis", "classification_failure"
        ])
        self._source_filter_box.currentTextChanged.connect(self._load_candidates)
        filter_row.addWidget(self._source_filter_box)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # 테이블
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COL_LABELS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table, 1)

        # 버튼 행
        btn_row = QHBoxLayout()
        self._btn_accept     = QPushButton("✅ 승인")
        self._btn_reject     = QPushButton("❌ 거부")
        self._btn_ignore     = QPushButton("⏭ 무시")
        self._btn_regenerate = QPushButton("🔄 후보 재생성")
        self._btn_close      = QPushButton("닫기")

        self._btn_accept    .clicked.connect(self._on_accept)
        self._btn_reject    .clicked.connect(self._on_reject)
        self._btn_ignore    .clicked.connect(self._on_ignore)
        self._btn_regenerate.clicked.connect(self._on_regenerate)
        self._btn_close     .clicked.connect(self.accept)

        for btn in (self._btn_accept, self._btn_reject, self._btn_ignore,
                    self._btn_regenerate):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # 데이터 로드
    # ------------------------------------------------------------------

    def _load_candidates(self) -> None:
        status_filter = self._filter_box.currentText()
        source_filter = self._source_filter_box.currentText()

        conditions: list[str] = []
        params: list = []
        if status_filter != "all":
            conditions.append("status = ?")
            params.append(status_filter)
        if source_filter != "all":
            conditions.append("source = ?")
            params.append(source_filter)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._conn.execute(
            f"SELECT * FROM tag_candidates {where} ORDER BY confidence_score DESC",
            params,
        ).fetchall()

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            values = [
                row["raw_tag"] or "",
                row["translated_tag"] or "",
                row["suggested_type"] or "",
                row["suggested_canonical"] or "",
                row["suggested_parent_series"] or "",
                f"{row['confidence_score']:.2f}" if row["confidence_score"] is not None else "",
                str(row["evidence_count"]),
                row["source"] or "",
                row["status"] or "",
            ]
            for c_idx, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setData(Qt.ItemDataRole.UserRole, row["candidate_id"])
                self._table.setItem(r_idx, c_idx, item)
        self._table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # 버튼 핸들러
    # ------------------------------------------------------------------

    def _selected_candidate_id(self) -> str | None:
        selected = self._table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.ItemDataRole.UserRole)

    def _on_accept(self) -> None:
        candidate_id = self._selected_candidate_id()
        if not candidate_id:
            QMessageBox.warning(self, "선택 없음", "승인할 항목을 선택하세요.")
            return
        try:
            from core.tag_candidate_actions import accept_tag_candidate
            accept_tag_candidate(self._conn, candidate_id)
            self._load_candidates()
        except ValueError as exc:
            QMessageBox.warning(self, "승인 실패", str(exc))
        except Exception as exc:
            logger.error("태그 후보 승인 오류: %s", exc)
            QMessageBox.critical(self, "오류", str(exc))

    def _on_reject(self) -> None:
        candidate_id = self._selected_candidate_id()
        if not candidate_id:
            QMessageBox.warning(self, "선택 없음", "거부할 항목을 선택하세요.")
            return
        try:
            from core.tag_candidate_actions import reject_tag_candidate
            reject_tag_candidate(self._conn, candidate_id)
            self._load_candidates()
        except ValueError as exc:
            QMessageBox.warning(self, "거부 실패", str(exc))
        except Exception as exc:
            logger.error("태그 후보 거부 오류: %s", exc)
            QMessageBox.critical(self, "오류", str(exc))

    def _on_ignore(self) -> None:
        candidate_id = self._selected_candidate_id()
        if not candidate_id:
            QMessageBox.warning(self, "선택 없음", "무시할 항목을 선택하세요.")
            return
        try:
            from core.tag_candidate_actions import ignore_tag_candidate
            ignore_tag_candidate(self._conn, candidate_id)
            self._load_candidates()
        except ValueError as exc:
            QMessageBox.warning(self, "무시 실패", str(exc))
        except Exception as exc:
            logger.error("태그 후보 무시 오류: %s", exc)
            QMessageBox.critical(self, "오류", str(exc))

    def _on_regenerate(self) -> None:
        try:
            from core.tag_candidate_generator import generate_tag_candidates_from_observations
            generated = generate_tag_candidates_from_observations(self._conn)
            self._load_candidates()
            QMessageBox.information(
                self, "재생성 완료",
                f"후보 {len(generated)}건 생성/갱신 완료."
            )
        except Exception as exc:
            logger.error("후보 재생성 오류: %s", exc)
            QMessageBox.critical(self, "오류", str(exc))
