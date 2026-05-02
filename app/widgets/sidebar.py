"""좌측 사이드바 — 카테고리 목록과 카운터."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

# (key, 표시 레이블) — 사용자 행동 의미 기반 분할.
#
# key 는 GALLERY_WHERE_BY_CATEGORY / COUNT_SQL_BY_CATEGORY (sidebar_filters)
# 와 _refresh_gallery / _refresh_counts (main_window) 의존. 변경 시 양쪽을 함께
# 수정해야 한다.
#
# 카테고리 의미:
# - all          : 라이브러리 내 모든 present 파일
# - work_target  : 분류 가능한 상태 (full / json_only / xmp_write_failed)
# - unregistered : metadata_missing — 메타데이터가 등록되지 않은 그룹
# - failed       : 5종 실패 상태 — 사용자 재처리 필요
# - other        : pending / out_of_sync / source_unavailable
# - no_metadata  : NoMetadataView panel 로 swap (no_metadata_queue 기반)
# - inbox        : 미분류 수신함
# - managed      : managed file_role 보유
# - missing      : DB 등록 + 현재 누락
CATEGORIES: list[tuple[str, str]] = [
    ("all",          "전체 파일"),
    ("work_target",  "작업 대상"),
    ("unregistered", "메타데이터 미등록"),
    ("failed",       "등록 실패"),
    ("other",        "기타 파일"),
    ("no_metadata",  "재시도 큐"),
    ("inbox",        "수신함"),
    ("managed",      "관리 중"),
    ("missing",      "⚠ 누락 파일"),
]

# 카테고리별 툴팁 (없으면 표시 안 함). 사용자 행동 의미를 한 줄로 요약.
_CATEGORY_TOOLTIPS: dict[str, str] = {
    "all": "현재 라이브러리에서 확인 가능한 모든 파일",
    "work_target": (
        "지금 분류하거나 관리할 수 있는 파일 "
        "(메타데이터가 정상 또는 부분적으로 정상)"
    ),
    "unregistered": (
        "메타데이터가 아직 등록되지 않은 그룹 — 외부 소스에서 가져오기 또는 수동 입력 필요"
    ),
    "failed": "메타데이터 등록 또는 파일 처리 중 실패한 항목 — 재처리 필요",
    "other": (
        "처리 대기 또는 외부 의존 상태의 항목 (대기/동기화/소스 미가용)"
    ),
    "no_metadata": "메타데이터 등록을 다시 시도하거나 확인해야 하는 항목",
    "inbox": "아직 정리되지 않은 수신함 파일",
    "managed": "Aru Archive 가 관리 중인 변환본 또는 관리 파일",
    "missing": (
        "DB에는 기록되어 있지만 현재 경로에서 찾을 수 없는 파일입니다. "
        "파일 무결성 검사로 표시됩니다."
    ),
}


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
            tooltip = _CATEGORY_TOOLTIPS.get(key)
            if tooltip:
                item.setToolTip(tooltip)
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

    def select_category(self, key: str) -> None:
        """주어진 key의 카테고리를 선택 상태로 만든다.

        ``category_selected`` 시그널을 발생시켜 연결된 갤러리 갱신을 트리거한다.
        key가 존재하지 않으면 아무 동작도 하지 않는다.
        """
        item = self._items.get(key)
        if item is not None:
            self._list.setCurrentItem(item)
