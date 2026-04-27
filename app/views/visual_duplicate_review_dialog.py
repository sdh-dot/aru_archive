"""
시각적 중복 검토 다이얼로그.

유사 이미지 그룹을 비교하고 삭제 대상을 선택한다.
최종 삭제는 반드시 DeletePreviewDialog를 거쳐야 한다.

PyQt6 전용. PySide6 사용 금지.
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QVBoxLayout, QWidget,
)


class VisualDuplicateReviewDialog(QDialog):
    """
    시각적 중복 후보 그룹을 비교하고 삭제할 파일을 선택하는 다이얼로그.

    사용자가 [삭제 미리보기로 이동]을 클릭하면 selected_for_delete() 로
    선택된 file_id 목록을 반환한다.
    """

    def __init__(
        self,
        visual_dup_groups: list[dict],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._groups = visual_dup_groups
        self._current_idx = 0
        self._decisions: dict[str, str] = {}  # file_id → 'keep'|'delete'|'exclude'
        self._to_delete: list[str] = []

        self.setWindowTitle("시각적 중복 검토")
        self.resize(900, 700)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 상단 진행 표시
        self._lbl_progress = QLabel()
        self._lbl_progress.setStyleSheet("color: #D8AEBB; font-size: 12px; padding: 2px;")
        layout.addWidget(self._lbl_progress)

        # 이미지 비교 영역
        self._image_area = QScrollArea()
        self._image_area.setWidgetResizable(True)
        self._image_area.setStyleSheet("QScrollArea { border: none; }")
        layout.addWidget(self._image_area, 1)

        # 하단 버튼
        btn_layout = QHBoxLayout()
        self._btn_prev = QPushButton("◀ 이전 그룹")
        self._btn_next = QPushButton("다음 그룹 ▶")
        self._btn_go_delete = QPushButton("🗑 삭제 미리보기로 이동")
        self._btn_go_delete.setStyleSheet(
            "QPushButton { background: #8B1A2A; color: #F7E8EC; "
            "font-weight: bold; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #A82035; }"
        )
        self._btn_cancel = QPushButton("취소")
        btn_layout.addWidget(self._btn_prev)
        btn_layout.addWidget(self._btn_next)
        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_go_delete)
        btn_layout.addWidget(self._btn_cancel)
        layout.addLayout(btn_layout)

        self._btn_prev.clicked.connect(self._on_prev)
        self._btn_next.clicked.connect(self._on_next)
        self._btn_go_delete.clicked.connect(self._on_go_delete)
        self._btn_cancel.clicked.connect(self.reject)

        self._load_group(0)

    # ------------------------------------------------------------------
    # 공개
    # ------------------------------------------------------------------

    def selected_for_delete(self) -> list[str]:
        """사용자가 [이 파일 삭제]로 선택한 file_id 목록을 반환한다."""
        return list(self._to_delete)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _load_group(self, idx: int) -> None:
        if not self._groups:
            self._lbl_progress.setText("중복 그룹 없음")
            return

        idx = max(0, min(idx, len(self._groups) - 1))
        self._current_idx = idx
        group = self._groups[idx]
        files = group.get("files", [])
        dist = group.get("distance", 0)

        self._lbl_progress.setText(
            f"그룹 {idx + 1} / {len(self._groups)}  —  "
            f"파일 {len(files)}개  Hamming distance: {dist}"
        )

        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(8)

        for col, f in enumerate(files):
            grid.addWidget(self._build_file_card(f), 0, col)

        self._image_area.setWidget(container)
        self._btn_prev.setEnabled(idx > 0)
        self._btn_next.setEnabled(idx < len(self._groups) - 1)

    def _build_file_card(self, f: dict) -> QWidget:
        file_id = f.get("file_id", "")
        file_path = f.get("file_path", "")
        file_role = f.get("file_role", "")
        file_size = f.get("file_size") or 0
        meta = f.get("metadata_sync_status", "")
        artist = f.get("artist_name", "")

        card = QGroupBox()
        card.setStyleSheet(
            "QGroupBox { background: #2B1720; border: 1px solid #4A2030; "
            "border-radius: 6px; padding: 6px; }"
        )
        vl = QVBoxLayout(card)

        # 썸네일
        pix = QPixmap(180, 180)
        pix.fill(QColor("#3A202B"))
        if file_path and os.path.exists(file_path):
            loaded = QPixmap(file_path)
            if not loaded.isNull():
                pix = loaded.scaled(
                    180, 180,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        thumb = QLabel()
        thumb.setPixmap(pix)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(thumb)

        # 정보 레이블
        info_lines = [
            f"<b>{os.path.basename(file_path)}</b>",
            f"역할: {file_role}",
            f"크기: {file_size:,} bytes" if file_size else "크기: 알 수 없음",
            f"메타: {meta}",
            f"작가: {artist}",
        ]
        info_lbl = QLabel("<br>".join(info_lines))
        info_lbl.setTextFormat(Qt.TextFormat.RichText)
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("font-size: 11px; color: #D8AEBB;")
        vl.addWidget(info_lbl)

        # 버튼 행
        btn_row = QHBoxLayout()
        btn_keep = QPushButton("유지")
        btn_keep.setStyleSheet(
            "QPushButton { background: #1A4A2A; color: #5CDB8F; "
            "padding: 3px 8px; border-radius: 3px; }"
        )
        btn_del = QPushButton("삭제")
        btn_del.setStyleSheet(
            "QPushButton { background: #4A1A20; color: #FF6B7A; "
            "padding: 3px 8px; border-radius: 3px; }"
        )
        btn_excl = QPushButton("제외")
        btn_excl.setStyleSheet(
            "QPushButton { background: #2B2B2B; color: #D8AEBB; "
            "padding: 3px 8px; border-radius: 3px; }"
        )
        btn_row.addWidget(btn_keep)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_excl)
        vl.addLayout(btn_row)

        # 현재 결정 표시 레이블
        decision_lbl = QLabel("")
        decision_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        decision_lbl.setStyleSheet("font-size: 10px; font-weight: bold;")
        vl.addWidget(decision_lbl)
        self._update_decision_label(decision_lbl, self._decisions.get(file_id, ""))

        def _set_keep(_fid=file_id, _lbl=decision_lbl):
            self._decisions[_fid] = "keep"
            if _fid in self._to_delete:
                self._to_delete.remove(_fid)
            self._update_decision_label(_lbl, "keep")

        def _set_delete(_fid=file_id, _lbl=decision_lbl):
            self._decisions[_fid] = "delete"
            if _fid not in self._to_delete:
                self._to_delete.append(_fid)
            self._update_decision_label(_lbl, "delete")

        def _set_exclude(_fid=file_id, _lbl=decision_lbl):
            self._decisions[_fid] = "exclude"
            if _fid in self._to_delete:
                self._to_delete.remove(_fid)
            self._update_decision_label(_lbl, "exclude")

        btn_keep.clicked.connect(_set_keep)
        btn_del.clicked.connect(_set_delete)
        btn_excl.clicked.connect(_set_exclude)

        return card

    def _update_decision_label(self, lbl: QLabel, decision: str) -> None:
        text_map = {
            "keep":    ("✓ 유지", "#5CDB8F"),
            "delete":  ("✗ 삭제", "#FF6B7A"),
            "exclude": ("— 제외", "#D8AEBB"),
            "":        ("미결정", "#8F6874"),
        }
        text, color = text_map.get(decision, ("미결정", "#8F6874"))
        lbl.setText(text)
        lbl.setStyleSheet(f"font-size: 10px; font-weight: bold; color: {color};")

    # ------------------------------------------------------------------
    # 슬롯
    # ------------------------------------------------------------------

    def _on_prev(self) -> None:
        self._load_group(self._current_idx - 1)

    def _on_next(self) -> None:
        self._load_group(self._current_idx + 1)

    def _on_go_delete(self) -> None:
        if not self._to_delete:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "선택 없음", "삭제할 파일을 선택하지 않았습니다.")
            return
        self.accept()
