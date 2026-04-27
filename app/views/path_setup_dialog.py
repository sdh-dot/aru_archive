from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import derive_workspace_dirs


class PathSetupDialog(QDialog):
    def __init__(self, *, start_dir: str = "", data_dir: str = "", parent=None) -> None:
        super().__init__(parent)
        self._selected_inbox = ""
        self._data_dir = data_dir

        self.setWindowTitle("작업 폴더 설정")
        self.setMinimumWidth(720)

        root = QVBoxLayout(self)
        guide = QLabel(
            "처음 한 번만 분류 대상 폴더를 선택하면 됩니다.\n"
            "선택한 폴더는 이름 변경 없이 그대로 사용되며, 같은 위치에 `Classified`, `Managed` 폴더가 자동 생성됩니다.\n"
            "원본 파일은 선택한 폴더에 그대로 유지되고, 분류 결과는 `Classified`, 관리본은 `Managed`에 저장됩니다.\n"
            f"앱 내부 데이터(DB, 로그, 썸네일)는 `{data_dir}` 에 저장됩니다."
        )
        guide.setWordWrap(True)
        root.addWidget(guide)

        picker_row = QHBoxLayout()
        self._selected_lbl = QLabel(start_dir or "선택된 폴더 없음")
        self._selected_lbl.setWordWrap(True)
        btn_pick = QPushButton("분류 대상 폴더 선택")
        btn_pick.clicked.connect(self._on_pick)
        picker_row.addWidget(btn_pick)
        picker_row.addWidget(self._selected_lbl, 1)
        root.addLayout(picker_row)

        preview = QWidget()
        grid = QGridLayout(preview)
        grid.addWidget(QLabel("분류 대상"), 0, 0)
        grid.addWidget(QLabel("분류 완료"), 1, 0)
        grid.addWidget(QLabel("관리 폴더"), 2, 0)
        grid.addWidget(QLabel("앱 데이터"), 3, 0)
        self._inbox_lbl = QLabel("-")
        self._classified_lbl = QLabel("-")
        self._managed_lbl = QLabel("-")
        self._data_lbl = QLabel(data_dir or "-")
        for row, lbl in enumerate(
            [self._inbox_lbl, self._classified_lbl, self._managed_lbl, self._data_lbl]
        ):
            lbl.setWordWrap(True)
            grid.addWidget(lbl, row, 1)
        root.addWidget(preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if start_dir:
            self._apply_selection(start_dir)

    def selected_paths(self) -> dict[str, str]:
        return derive_workspace_dirs(self._selected_inbox) if self._selected_inbox else {}

    def _on_pick(self) -> None:
        start = self._selected_inbox or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "분류 대상 폴더 선택", start)
        if chosen:
            self._apply_selection(chosen)

    def _apply_selection(self, chosen: str) -> None:
        self._selected_inbox = chosen
        self._selected_lbl.setText(chosen)
        paths = derive_workspace_dirs(chosen)
        self._inbox_lbl.setText(paths["inbox_dir"])
        self._classified_lbl.setText(paths["classified_dir"])
        self._managed_lbl.setText(paths["managed_dir"])
        self._ok_btn.setEnabled(True)
