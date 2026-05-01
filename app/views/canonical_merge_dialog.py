"""
기존 canonical 선택 다이얼로그.

TagCandidateView와 DictionaryImportView에서 "기존 canonical에 병합" 선택 시 열린다.
사용자가 검색 필드로 canonical을 필터링하고 선택할 수 있다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QLineEdit, QVBoxLayout, QWidget,
)


class CanonicalMergeDialog(QDialog):
    """기존 canonical을 검색·선택하는 다이얼로그."""

    def __init__(
        self,
        canonicals: list[dict],
        raw_tag: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """
        canonicals: list[{"canonical": str, "tag_type": str, "parent_series": str}]
        raw_tag:    병합 대상 원본 태그 (표시용)
        """
        super().__init__(parent)
        self._canonicals = canonicals
        self._raw_tag = raw_tag
        self.setWindowTitle("기존 항목과 병합")
        self.resize(440, 220)
        self._build_ui()
        self._filter("")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        if self._raw_tag:
            layout.addWidget(
                QLabel(f"'{self._raw_tag}' → 병합할 대상 canonical을 선택하세요.")
            )

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("검색:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("canonical 이름...")
        self._search.textChanged.connect(self._filter)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(360)
        layout.addWidget(self._combo)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _filter(self, text: str) -> None:
        self._combo.clear()
        lower = text.lower()
        for c in self._canonicals:
            if lower not in c["canonical"].lower():
                continue
            label = f"{c['canonical']}  ({c['tag_type']})"
            if c.get("parent_series"):
                label += f"  [{c['parent_series']}]"
            self._combo.addItem(label, c)

    # ------------------------------------------------------------------
    # 결과 접근
    # ------------------------------------------------------------------

    def selected_canonical(self) -> dict | None:
        """선택된 canonical dict 반환. 선택 없으면 None."""
        idx = self._combo.currentIndex()
        if idx < 0:
            return None
        return self._combo.itemData(idx)
