"""
갤러리 뷰 — artwork_groups 썸네일 그리드.

각 카드 표시:
  - 썸네일 (thumbnail_cache 경로 또는 형식별 컬러 플레이스홀더)
  - 작품 타이틀 (ellipsis + tooltip)
  - 파일 형식 배지 + metadata_sync_status 배지
  - original / managed 구성 요약
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal as Signal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

THUMB_W = 120
ITEM_W  = 148
ITEM_H  = 172

# 형식별 플레이스홀더 배경색 (와인 팔레트 조화)
_FMT_COLOR: dict[str, str] = {
    "jpg":  "#7B2D40",
    "jpeg": "#7B2D40",
    "png":  "#2D4A7B",
    "webp": "#2D7B4A",
    "gif":  "#6B2D7B",
    "bmp":  "#7B5A2D",
    "zip":  "#4A7B2D",
}

_STATUS_SHORT: dict[str, str] = {
    "full":                  "✅ Full",
    "json_only":             "🟡 JSON",
    "pending":               "⏳ Pending",
    "convert_failed":        "❌ Convert",
    "metadata_write_failed": "❌ MetaFail",
    "xmp_write_failed":      "⚠️ XMP",
    "metadata_missing":      "❓ NoMeta",
    "file_write_failed":     "❌ FileFail",
    "db_update_failed":      "❌ DB",
    "needs_reindex":         "↺ Reindex",
    "out_of_sync":           "! Sync",
}


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _placeholder_icon(fmt: str, w: int = THUMB_W) -> QIcon:
    color = _FMT_COLOR.get(fmt.lower(), "#5C2030")
    pix = QPixmap(w, w)
    pix.fill(QColor(color))
    p = QPainter(pix)
    p.setPen(QColor("#F7E8EC"))
    font = QFont()
    font.setPointSize(14)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, fmt.upper()[:4])
    p.end()
    return QIcon(pix)


def _load_icon(thumb_path: Optional[str], fmt: str) -> QIcon:
    if thumb_path:
        p = Path(thumb_path)
        if p.exists():
            pix = QPixmap(str(p))
            if not pix.isNull():
                pix = pix.scaled(
                    THUMB_W, THUMB_W,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                return QIcon(pix)
    return _placeholder_icon(fmt)


# ---------------------------------------------------------------------------
# GalleryView
# ---------------------------------------------------------------------------

class GalleryView(QWidget):
    """
    artwork_groups 썸네일 그리드.

    Signals:
        item_selected(str): 클릭된 group_id.
    """

    item_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(THUMB_W, THUMB_W))
        self._list.setGridSize(QSize(ITEM_W, ITEM_H))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(6)
        self._list.setStyleSheet(
            "QListWidget {"
            "  border: none; background: #1A0F14; color: #F7E8EC;"
            "}"
            "QListWidget::item {"
            "  border-radius: 8px; padding: 4px;"
            "  background: #3A202B; color: #F7E8EC;"
            "}"
            "QListWidget::item:selected {"
            "  background: #5C2A3A; border: 2px solid #F0A6B8;"
            "  color: #F7E8EC;"
            "}"
            "QListWidget::item:hover:!selected {"
            "  background: #452634; color: #F7E8EC;"
            "}"
        )
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.currentItemChanged.connect(self._on_changed)
        layout.addWidget(self._list)

        self._empty = QLabel(
            "파일이 없습니다.\n[Inbox 스캔] 버튼을 눌러 시작하세요."
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #8F6874; font-size: 13px;")
        layout.addWidget(self._empty)
        self._empty.hide()

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def load_groups(self, rows: list[dict]) -> None:
        """artwork_groups 쿼리 결과를 갤러리에 표시한다."""
        self._list.clear()
        if not rows:
            self._list.hide()
            self._empty.show()
            return
        self._empty.hide()
        self._list.show()
        for row in rows:
            self._list.addItem(self._make_item(row))

    def get_selected_group_id(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def get_selected_group_ids(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._list.selectedItems()
        ]

    def get_visible_group_ids(self) -> list[str]:
        return [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
            if self._list.item(i) is not None
        ]

    def refresh_item(self, group_id: str, row: dict) -> None:
        """특정 카드를 갱신한다."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == group_id:
                new_item = self._make_item(row)
                self._list.takeItem(i)
                self._list.insertItem(i, new_item)
                self._list.setCurrentRow(i)
                break

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _make_item(self, row: dict) -> QListWidgetItem:
        group_id = row.get("group_id", "")
        fmt      = row.get("file_format") or "?"
        thumb    = row.get("thumb_path")
        title    = row.get("artwork_title") or row.get("artwork_id") or "?"
        status   = row.get("metadata_sync_status", "pending")
        role_sum = row.get("role_summary") or ""

        status_txt = _STATUS_SHORT.get(status, status)
        # Line 1: title truncated with ellipsis
        line1 = title if len(title) <= 17 else title[:16] + "…"
        # Line 2: format badge + status in one line
        line2 = f"[{fmt.upper()}]  {status_txt}"
        # Line 3: role summary (small)
        line3 = role_sum[:22] if role_sum else ""

        text = "\n".join(filter(None, [line1, line2, line3]))

        icon = _load_icon(thumb, fmt)
        item = QListWidgetItem(icon, text)
        item.setData(Qt.ItemDataRole.UserRole, group_id)
        item.setSizeHint(QSize(ITEM_W, ITEM_H))
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        item.setForeground(QColor("#F7E8EC"))
        item.setToolTip(f"{title}\n[{fmt.upper()}] {status_txt}\n{role_sum}")
        return item

    def _on_changed(
        self,
        current: QListWidgetItem | None,
        _prev: QListWidgetItem | None,
    ) -> None:
        if current:
            self.item_selected.emit(current.data(Qt.ItemDataRole.UserRole))
