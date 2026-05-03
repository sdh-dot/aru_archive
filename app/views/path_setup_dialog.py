"""첫 실행 폴더 설정 대화상자 (PR #122 follow-up).

PR #122 의 3-folder 정책:

1. input_dir   — 사용자 직접 선택 (분류 대상)
2. output_dir  — 사용자 직접 선택 (분류 완료) — input 의 sibling 으로 자동
                 파생하지 않는다.
3. app_data_dir — Path.home() / 'AruArchive' 고정. 사용자가 일반 설정에서
                 임의로 변경하지 않는다.
4. managed_dir — app_data_dir / 'managed'. 내부 관리 저장소이며 사용자가
                 선택한 분류 완료 폴더가 아니다. detail / tooltip 으로만
                 노출한다.

OK 활성 조건: input_dir 와 output_dir 가 모두 채워져야 함.
경고 (허용): input_dir == output_dir 인 경우.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.config_manager import default_app_data_dir


class PathSetupDialog(QDialog):
    """3-folder 정책에 맞춘 첫 실행 폴더 설정 대화상자."""

    def __init__(
        self,
        *,
        start_input_dir: str = "",
        start_output_dir: str = "",
        app_data_dir: str = "",
        # legacy positional / keyword 호환 — main_window 가 start_dir / data_dir
        # 형식으로 호출하는 동안에도 기존 코드가 동작하도록 alias 를 받는다.
        start_dir: str = "",
        data_dir: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        # legacy alias 호환 처리.
        if not start_input_dir and start_dir:
            start_input_dir = start_dir
        resolved_app_data = (
            app_data_dir or data_dir or str(default_app_data_dir())
        )
        self._app_data_dir = resolved_app_data
        self._selected_input = (start_input_dir or "").strip()
        self._selected_output = (start_output_dir or "").strip()

        self.setWindowTitle("작업 폴더 설정")
        self.setObjectName("pathSetupDialog")
        self.setMinimumWidth(720)

        root = QVBoxLayout(self)

        # 안내 문구 — PR #122 정책에 맞춰 "Classified / Managed 자동 생성" 표현 제거.
        guide = QLabel(
            "분류 대상 폴더와 분류 완료 폴더를 각각 선택합니다.\n"
            "원본 파일은 분류 대상 폴더에 그대로 유지되며, 분류 결과는 "
            "선택한 분류 완료 폴더에 저장됩니다.\n"
            f"앱 관리 데이터(DB, 로그, 썸네일 캐시, 런타임 파일)는 "
            f"{resolved_app_data} 에 저장됩니다."
        )
        guide.setObjectName("pathSetupGuide")
        guide.setWordWrap(True)
        root.addWidget(guide)

        # 분류 대상 폴더 picker.
        in_row = QHBoxLayout()
        self._btn_pick_input = QPushButton("📁 분류 대상 폴더 선택")
        self._btn_pick_input.setObjectName("btnPickInputDir")
        self._btn_pick_input.clicked.connect(self._on_pick_input)
        self._input_lbl = QLabel(self._selected_input or "선택된 폴더 없음")
        self._input_lbl.setObjectName("lblInputDir")
        self._input_lbl.setWordWrap(True)
        in_row.addWidget(self._btn_pick_input)
        in_row.addWidget(self._input_lbl, 1)
        root.addLayout(in_row)

        # 분류 완료 폴더 picker (PR #122 follow-up — input 으로부터 자동 파생 X).
        out_row = QHBoxLayout()
        self._btn_pick_output = QPushButton("📁 분류 완료 폴더 선택")
        self._btn_pick_output.setObjectName("btnPickOutputDir")
        self._btn_pick_output.clicked.connect(self._on_pick_output)
        self._output_lbl = QLabel(self._selected_output or "선택된 폴더 없음")
        self._output_lbl.setObjectName("lblOutputDir")
        self._output_lbl.setWordWrap(True)
        out_row.addWidget(self._btn_pick_output)
        out_row.addWidget(self._output_lbl, 1)
        root.addLayout(out_row)

        # 같은 경로 경고 (허용은 하되 사용자에게 알린다).
        self._warn_same_lbl = QLabel("")
        self._warn_same_lbl.setObjectName("lblSamePathWarning")
        self._warn_same_lbl.setStyleSheet(
            "color: #FFB070; font-size: 11px; padding: 2px 0px;"
        )
        self._warn_same_lbl.setVisible(False)
        root.addWidget(self._warn_same_lbl)

        # 요약 패널 — 분류 대상 / 분류 완료 / 관리 폴더 / 내부 관리 저장소.
        summary = QFrame()
        summary.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(summary)
        grid.addWidget(QLabel("분류 대상"), 0, 0)
        grid.addWidget(QLabel("분류 완료"), 1, 0)
        grid.addWidget(QLabel("관리 폴더"), 2, 0)
        grid.addWidget(QLabel("내부 관리 저장소"), 3, 0)
        self._summary_input_lbl  = QLabel(self._selected_input or "-")
        self._summary_output_lbl = QLabel(self._selected_output or "-")
        self._summary_managed_lbl = QLabel(resolved_app_data)
        self._summary_internal_managed_lbl = QLabel(
            str(Path(resolved_app_data) / "managed")
        )
        for row, lbl, name in (
            (0, self._summary_input_lbl,             "lblSummaryInput"),
            (1, self._summary_output_lbl,            "lblSummaryOutput"),
            (2, self._summary_managed_lbl,           "lblSummaryManaged"),
            (3, self._summary_internal_managed_lbl,  "lblSummaryInternalManaged"),
        ):
            lbl.setObjectName(name)
            lbl.setWordWrap(True)
            grid.addWidget(lbl, row, 1)
        # 관리 폴더 행에는 설명을 inline 으로 추가.
        managed_help = QLabel(
            "로그, 썸네일 캐시, 런타임 파일 등 앱 관리 데이터가 저장됩니다."
        )
        managed_help.setObjectName("lblManagedHelp")
        managed_help.setWordWrap(True)
        managed_help.setStyleSheet("color: #8F8890; font-size: 11px;")
        grid.addWidget(managed_help, 2, 2)

        internal_help = QLabel(
            "앱이 자동 생성한 managed 사본 / 임시 파일 보관용. "
            "사용자가 직접 다루지 않는 경로입니다."
        )
        internal_help.setObjectName("lblInternalManagedHelp")
        internal_help.setWordWrap(True)
        internal_help.setStyleSheet("color: #8F8890; font-size: 11px;")
        grid.addWidget(internal_help, 3, 2)

        root.addWidget(summary)

        # 표준 OK / Cancel.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._refresh_state()

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def selected_paths(self) -> dict[str, str]:
        """선택 결과를 반환한다.

        ``input_dir`` 와 ``output_dir`` 가 모두 채워졌을 때만 dict 를 반환하며,
        legacy alias (``inbox_dir`` / ``classified_dir``) 도 함께 채운다.
        ``managed_dir`` 는 ``app_data_dir / 'managed'`` 로 강제된다 — 사용자
        선택값이 아니다.
        """
        if not (self._selected_input and self._selected_output):
            return {}
        managed = str(Path(self._app_data_dir) / "managed")
        return {
            "input_dir":      self._selected_input,
            "output_dir":     self._selected_output,
            "inbox_dir":      self._selected_input,
            "classified_dir": self._selected_output,
            "managed_dir":    managed,
            "app_data_dir":   self._app_data_dir,
        }

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _on_pick_input(self) -> None:
        start = self._selected_input or self._selected_output or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "분류 대상 폴더 선택", start)
        if not chosen:
            return
        self._selected_input = chosen
        self._input_lbl.setText(chosen)
        self._summary_input_lbl.setText(chosen)
        self._refresh_state()

    def _on_pick_output(self) -> None:
        start = self._selected_output or self._selected_input or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "분류 완료 폴더 선택", start)
        if not chosen:
            return
        self._selected_output = chosen
        self._output_lbl.setText(chosen)
        self._summary_output_lbl.setText(chosen)
        self._refresh_state()

    def _refresh_state(self) -> None:
        # OK 활성 조건: 두 폴더 모두 채워져야 함.
        self._ok_btn.setEnabled(
            bool(self._selected_input) and bool(self._selected_output)
        )
        # 같은 경로 경고 (정책: 허용하되 표시).
        if (
            self._selected_input
            and self._selected_output
            and Path(self._selected_input) == Path(self._selected_output)
        ):
            self._warn_same_lbl.setText(
                "⚠ 분류 대상 폴더와 분류 완료 폴더가 같습니다. "
                "원본과 분류 사본이 같은 폴더에 섞일 수 있습니다."
            )
            self._warn_same_lbl.setVisible(True)
        else:
            self._warn_same_lbl.setText("")
            self._warn_same_lbl.setVisible(False)
