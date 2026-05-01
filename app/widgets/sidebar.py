"""좌측 사이드바 — 카테고리 목록과 카운터."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

# (key, 표시 레이블) — key는 _GALLERY_WHERE / _COUNT_SQL 의존, 변경 금지
CATEGORIES: list[tuple[str, str]] = [
    ("all",         "전체 파일"),
    ("inbox",       "수신함"),
    ("managed",     "관리 중"),
    ("no_metadata", "메타데이터 없음"),
    ("warning",     "경고"),
    ("failed",      "오류"),
]


class SidebarWidget(QWidget):
    """
    카테고리 목록 위젯.

    Signals:
        category_selected(str): 카테고리 key가 변경될 때 발생.
    """

    category_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidebarWidget")
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "#SidebarWidget { background-color: #1A0F14; }"
        )
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(4)

        title = QLabel("카테고리")
        title.setStyleSheet(
            "font-weight: bold; color: #E69AAA; font-size: 12px; padding-left: 4px;"
        )
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget {"
            "  border: none; background: transparent; outline: none;"
            "}"
            "QListWidget::item {"
            "  padding: 7px 10px; border-radius: 5px;"
            "  color: #D8AEBB; font-size: 12px;"
            "}"
            "QListWidget::item:selected {"
            "  background: #452634; color: #F7E8EC;"
            "  border-left: 3px solid #B5526C;"
            "}"
            "QListWidget::item:hover:!selected {"
            "  background: #3A202B; color: #F7E8EC;"
            "}"
        )
        layout.addWidget(self._list)

        self._items: dict[str, QListWidgetItem] = {}
        for key, label in CATEGORIES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(item)
            self._items[key] = item

        self._list.currentItemChanged.connect(self._on_changed)
        self._list.setCurrentRow(0)

    # ------------------------------------------------------------------

    def _on_changed(
        self, current: QListWidgetItem | None, _prev: QListWidgetItem | None
    ) -> None:
        if current:
            self.category_selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def update_counts(self, counts: dict[str, int]) -> None:
        """카운터를 갱신한다. counts = {'all': 10, 'inbox': 5, ...}"""
        label_map = dict(CATEGORIES)
        for key, item in self._items.items():
            base = label_map[key]
            count = counts.get(key, 0)
            item.setText(f"{base}  ({count})")

    def current_category(self) -> str:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else "all"
