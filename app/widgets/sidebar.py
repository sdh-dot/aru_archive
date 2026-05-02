"""좌측 사이드바 — 카테고리 목록과 카운터."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

# (key, 표시 레이블) — key 는 GALLERY_WHERE_BY_CATEGORY / COUNT_SQL_BY_CATEGORY
# (app.widgets.sidebar_filters) 의존, 변경 금지. 라벨만 사용자 친화적 한국어로
# 정리 (label-only refactor).
CATEGORIES: list[tuple[str, str]] = [
    ("all",         "전체 파일"),
    ("inbox",       "수신함"),
    ("managed",     "관리 중"),
    # no_metadata 는 NoMetadataView panel 로 swap 되며 no_metadata_queue 테이블
    # 기반이므로 "재시도 큐" 가 사용자 행동 의미에 더 가깝다.
    ("no_metadata", "재시도 큐"),
    # warning 은 xmp_write_failed + json_only 를 포함 — JSON 정상 + XMP 부재 등
    # "확인 필요" 의미. "경고" 보다 "주의 필요" 가 더 부드럽고 정확하다.
    ("warning",     "주의 필요"),
    # failed 는 5종 실패 상태 — 사용자가 재처리 / 재등록을 검토해야 함.
    # "오류" 보다 "등록 실패" 가 행동 관점에서 더 명확하다.
    ("failed",      "등록 실패"),
    # missing 라벨은 기존 "⚠ 누락 파일" 그대로 유지 (회귀 테스트 호환).
    ("missing",     "⚠ 누락 파일"),
]

# 카테고리별 툴팁 (없으면 표시 안 함). label-only refactor 의 일부로 모든 카테고리에
# 사용자 친화 설명 추가. tooltip 표시 회로는 sidebar.py 내부 (item.setToolTip) 만
# 사용하므로 외부 파일 변경 없음.
_CATEGORY_TOOLTIPS: dict[str, str] = {
    "all": "현재 라이브러리에서 확인 가능한 모든 파일",
    "inbox": "아직 정리되지 않은 수신함 파일",
    "managed": "Aru Archive 가 관리 중인 변환본 또는 관리 파일",
    "no_metadata": "메타데이터 등록을 다시 시도하거나 확인해야 하는 항목",
    "warning": "일부 메타데이터 처리가 완료되지 않았지만 확인 가능한 항목",
    "failed": "메타데이터 등록 또는 파일 처리 중 실패한 항목",
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
