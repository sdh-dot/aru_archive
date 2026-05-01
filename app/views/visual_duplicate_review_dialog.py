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


_VALID_DECISIONS = frozenset({"keep", "delete", "exclude"})

# 자동 후보 결정 소스 태그 — 사용자가 직접 결정했으면 None
_SOURCE_AUTO   = "auto"
_SOURCE_MANUAL = "manual"


def _compute_group_reasons(files: list[dict]) -> dict[str, str]:
    """그룹 파일 목록에서 각 file_id에 대한 자동 추천 reason을 계산한다.

    decision policy 본문을 변경하지 않고 `decide_visual_duplicate_group`을
    호출해 reason 필드를 추출한다. 예외 발생 시 빈 dict 반환.
    """
    if not files:
        return {}
    try:
        from core.visual_duplicate_decision import decide_visual_duplicate_group
        decisions = decide_visual_duplicate_group(files)
        return {d.file_id: d.reason for d in decisions if d.file_id}
    except Exception:
        return {}


def _format_size_mb(size_bytes) -> str:
    """파일 크기 byte 값을 사용자 친화 MB 문자열로 변환.

    None / 0 → "-"
    1 MB 미만 → 소수점 2자리 (e.g. "0.12 MB")
    일반 → 소수점 1자리 (e.g. "12.3 MB")
    """
    if not size_bytes:
        return "-"
    mb = size_bytes / (1024 * 1024)
    if mb < 1:
        return f"{mb:.2f} MB"
    return f"{mb:.1f} MB"


class VisualDuplicateReviewDialog(QDialog):
    """
    시각적 중복 후보 그룹을 비교하고 삭제할 파일을 선택하는 다이얼로그.

    사용자가 [삭제 미리보기로 이동]을 클릭하면 selected_for_delete() 로
    선택된 file_id 목록을 반환한다.

    initial_decisions로 자동 keep/delete/exclude 후보를 초기 UI 상태로
    주입할 수 있다. 사용자가 이후 수동으로 결정을 변경할 수 있으며,
    실제 파일 삭제는 [삭제 미리보기로 이동] → DeletePreviewDialog →
    execute_delete_preview 단계를 거쳐야만 발생한다.
    """

    def __init__(
        self,
        visual_dup_groups: list[dict],
        parent: Optional[QWidget] = None,
        *,
        initial_decisions: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(parent)
        self._groups = visual_dup_groups
        self._current_idx = 0

        # initial_decisions를 안전하게 필터링 — invalid key/value는 silent 무시.
        # decision은 "keep" / "delete" / "exclude" 중 하나만 허용.
        filtered: dict[str, str] = {
            fid: decision
            for fid, decision in (initial_decisions or {}).items()
            if isinstance(fid, str)
            and isinstance(decision, str)
            and decision in _VALID_DECISIONS
        }
        self._decisions: dict[str, str] = filtered  # file_id → 'keep'|'delete'|'exclude'
        # _to_delete는 selected_for_delete()의 백엔드 — initial delete와 동기화.
        self._to_delete: list[str] = [
            fid for fid, decision in filtered.items() if decision == "delete"
        ]
        self._decision_labels: dict[str, QLabel] = {}
        # 결정 소스 추적 — "auto": initial_decisions로 채워진 것, "manual": 사용자 직접 선택
        self._decision_sources: dict[str, str] = {
            fid: _SOURCE_AUTO for fid in filtered
        }

        self.setWindowTitle("시각적 중복 검토")
        self.resize(900, 700)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 상단 안내문 — 자동 추천과 실제 삭제의 차이를 명확히 안내
        self._lbl_guide = QLabel(
            "자동 추천 결과가 미리 채워져 있습니다. "
            "검토 후 [삭제 미리보기로 이동]을 눌러야 실제 삭제가 시작됩니다."
        )
        self._lbl_guide.setWordWrap(True)
        self._lbl_guide.setStyleSheet(
            "background: #1E2B1A; color: #8FDB6F; "
            "font-size: 11px; padding: 5px 8px; border-radius: 4px; "
            "border: 1px solid #2E5A1A;"
        )
        layout.addWidget(self._lbl_guide)

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

        # _load_group 내부에서 _current_group_reasons를 갱신하므로 미리 초기화
        self._current_group_reasons: dict[str, str] = {}
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
        self._decision_labels = {}
        # 현재 그룹의 자동 추천 reason을 미리 계산해 카드 빌드에 활용
        self._current_group_reasons: dict[str, str] = _compute_group_reasons(files)

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
            f"크기: {_format_size_mb(file_size)}",
            f"메타: {meta}",
            f"작가: {artist}",
        ]
        info_lbl = QLabel("<br>".join(info_lines))
        info_lbl.setTextFormat(Qt.TextFormat.RichText)
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("font-size: 11px; color: #D8AEBB;")
        vl.addWidget(info_lbl)

        # 자동 추천 reason 표시
        reason_text = self._compute_reason_for_file(file_id, f)
        if reason_text:
            reason_lbl = QLabel(f"추천 근거: {reason_text}")
            reason_lbl.setWordWrap(True)
            reason_lbl.setStyleSheet(
                "font-size: 10px; color: #A8C4FF; font-style: italic; padding: 1px 0;"
            )
            vl.addWidget(reason_lbl)

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
        self._decision_labels[file_id] = decision_lbl
        init_source = self._decision_sources.get(file_id, _SOURCE_MANUAL)
        self._update_decision_label(
            decision_lbl, self._decisions.get(file_id, ""), source=init_source
        )

        def _set_keep(_checked: bool = False, _fid=file_id):
            self._apply_group_decision(_fid, "keep")

        def _set_delete(_checked: bool = False, _fid=file_id):
            self._apply_group_decision(_fid, "delete")

        def _set_exclude(_checked: bool = False, _fid=file_id):
            self._apply_group_decision(_fid, "exclude")

        btn_keep.clicked.connect(_set_keep)
        btn_del.clicked.connect(_set_delete)
        btn_excl.clicked.connect(_set_exclude)

        return card

    def _current_group_files(self) -> list[dict]:
        if not self._groups:
            return []
        return list(self._groups[self._current_idx].get("files", []))

    def _compute_reason_for_file(self, file_id: str, _f: dict) -> str:
        """현재 그룹에서 해당 file_id의 자동 추천 reason을 반환한다.

        _load_group에서 미리 계산된 _current_group_reasons를 우선 사용하며,
        없으면 빈 문자열을 반환한다.
        """
        reasons = getattr(self, "_current_group_reasons", {})
        return reasons.get(file_id, "")

    def _set_file_decision(self, file_id: str, decision: str, *, source: str = _SOURCE_MANUAL) -> None:
        self._decisions[file_id] = decision
        self._decision_sources[file_id] = source
        if decision == "delete":
            if file_id not in self._to_delete:
                self._to_delete.append(file_id)
        elif file_id in self._to_delete:
            self._to_delete.remove(file_id)

        lbl = self._decision_labels.get(file_id)
        if lbl is not None:
            self._update_decision_label(lbl, decision, source=source)

    def _apply_group_decision(self, file_id: str, decision: str) -> None:
        current_file_ids = [
            f.get("file_id", "")
            for f in self._current_group_files()
            if f.get("file_id")
        ]
        if file_id not in current_file_ids:
            return

        if decision == "keep":
            for other_id in current_file_ids:
                self._set_file_decision(
                    other_id,
                    "keep" if other_id == file_id else "delete",
                )
            return

        self._set_file_decision(file_id, decision)

    def _update_decision_label(
        self, lbl: QLabel, decision: str, *, source: str = _SOURCE_MANUAL
    ) -> None:
        """결정 상태와 소스(자동 추천 / 사용자 선택)에 따라 라벨을 갱신한다.

        자동 추천(source=_SOURCE_AUTO): "추천: keep" / "추천: 삭제" 등
          — 아직 확정된 액션이 아님을 명확히 표현.
        사용자 선택(source=_SOURCE_MANUAL): "keep (선택)" / "삭제 (선택)" 등
          — 사용자가 직접 결정한 상태임을 표현.
        미결정: "미결정"
        """
        if source == _SOURCE_AUTO:
            text_map = {
                "keep":    ("추천: keep",   "#5CDB8F"),
                "delete":  ("추천: 삭제",   "#FF6B7A"),
                "exclude": ("추천: 제외",   "#D8AEBB"),
                "":        ("미결정",        "#8F6874"),
            }
        else:
            text_map = {
                "keep":    ("keep (선택)",  "#5CDB8F"),
                "delete":  ("삭제 (선택)",  "#FF6B7A"),
                "exclude": ("제외 (선택)",  "#D8AEBB"),
                "":        ("미결정",        "#8F6874"),
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
