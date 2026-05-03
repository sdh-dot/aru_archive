from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# 긴 detail/log 한 줄로 인한 layout 흔들림 방지 — 표시용 max characters.
# 전체 원문은 tooltip + 호출자 측 log area 에 보존된다.
_DETAIL_DISPLAY_MAX_CHARS = 140

# detail label 표시 영역의 max height (px). 2~3 줄 분량이며 longer text 는
# truncate 되거나 tooltip 으로만 노출되어 dialog 전체 layout 을 밀어내지
# 않도록 한다.
_DETAIL_LABEL_MAX_HEIGHT = 48


def _truncate_detail_for_display(text: str) -> str:
    """긴 한 줄을 표시용으로 잘라낸다. 끝에 ``…`` 추가, 원문은 tooltip 으로 보존.

    중간을 자르지 않고 head 만 보존 — log line 은 보통 가장 의미있는 정보가
    앞쪽에 모이므로 (e.g. ``[INFO] enrich queue: 1234 files / 567 unique``).
    한국어/영문 모두 글자 단위로 동일 처리.
    """
    if not isinstance(text, str):
        return ""
    if len(text) <= _DETAIL_DISPLAY_MAX_CHARS:
        return text
    return text[: _DETAIL_DISPLAY_MAX_CHARS - 1].rstrip() + "…"

from app.resources import loading_icon_path, loading_image_path

logger = logging.getLogger(__name__)

class LoadingOverlayDialog(QDialog):
    """Shared loading/progress dialog for long-running app tasks.

    The dialog is intentionally non-canceling: closing it only hides the UI and
    lets the worker continue in the background.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setWindowTitle("작업 진행 중")
        self.setMinimumSize(900, 580)
        self._apply_initial_size()

        self._main_image_path = self._resolve_asset(loading_image_path(), "loading_01.png")
        self._mini_icon_path = self._resolve_asset(loading_icon_path(), "icon_05.png")

        self._build_ui()
        self.set_title_text("작업 진행 중")
        self.set_message_text("작업이 완료될 때까지 잠시만 기다려주세요.")
        self.set_task_message("", "")
        self.update_progress(0, 0)

    def _resolve_asset(self, raw: Optional[str], label: str) -> Optional[Path]:
        if not raw:
            logger.warning("LoadingOverlayDialog asset missing: %s (resolver returned None)", label)
            return None
        candidate = Path(raw)
        if not candidate.exists():
            logger.warning("LoadingOverlayDialog asset not found on disk: %s", candidate)
            return None
        return candidate

    def _apply_initial_size(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent_size = parent.size()
            target_width = min(1100, int(parent_size.width() * 0.88))
            target_height = min(720, int(parent_size.height() * 0.88))
            self.resize(max(target_width, 900), max(target_height, 580))
            return
        self.resize(1050, 680)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #f6ede3;
            }
            QFrame#shell {
                background: #fff8f0;
                border: 2px solid #e4b48f;
                border-radius: 24px;
            }
            QFrame#content_card {
                background: #fff7ee;
                border: 1px solid #e8bc95;
                border-radius: 20px;
            }
            QFrame#left_panel, QFrame#right_panel, QFrame#card_box, QFrame#bottom_box {
                background: #fff5ea;
                border: 1px solid #ebc39c;
                border-radius: 18px;
            }
            QFrame#stat_cell {
                background: #fff4e8;
                border: 1px solid #e8b98f;
                border-radius: 14px;
            }
            QLabel {
                background: transparent;
                color: #6c4337;
            }
            QLabel#section_title {
                color: #7c4a3d;
                font-size: 23px;
                font-weight: 800;
            }
            QLabel#section_subtitle {
                color: #765144;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#percent_label {
                color: #f292aa;
                font-size: 36px;
                font-weight: 800;
            }
            QLabel#count_label {
                color: #6d473b;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#panel_caption {
                color: #7d5546;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#panel_body {
                color: #7b5a4e;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#stat_value {
                color: #9a4d5f;
                font-size: 26px;
                font-weight: 800;
            }
            QLabel#stat_name {
                color: #5a2e24;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#tip_title {
                color: #9c6a2f;
                font-size: 17px;
                font-weight: 800;
            }
            QLabel#tip_body {
                color: #725548;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#illustration_caption {
                color: #7b5548;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#bottomAruIcon {
                background: transparent;
                border: none;
            }
            QPushButton#background_button {
                background: #8c4f60;
                border: 1px solid #9d6172;
                border-radius: 14px;
                color: #fff8fb;
                font-size: 17px;
                font-weight: 800;
                padding: 12px 22px;
            }
            QPushButton#background_button:hover {
                background: #a35d71;
            }
            QPushButton#background_button:pressed {
                background: #7b4555;
            }
            QProgressBar {
                min-height: 26px;
                border: 2px solid #e7b894;
                border-radius: 13px;
                background: #5b2f38;
                color: transparent;
                text-align: center;
                padding: 2px;
            }
            QProgressBar::chunk {
                border-radius: 10px;
                background: #ef97ad;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("shell")
        root.addWidget(shell)

        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        body = QWidget()
        shell_layout.addWidget(body, 1)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 14, 14, 14)
        body_layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_left_image_panel(), 7)
        top_row.addWidget(self._build_progress_panel(), 5)
        body_layout.addLayout(top_row, 1)

        body_layout.addWidget(self._build_bottom_panel())

    def _build_left_image_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("left_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        image_frame = QFrame()
        image_frame.setObjectName("content_card")
        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(14, 14, 14, 14)
        image_layout.setSpacing(10)

        self._main_image = QLabel("작업 이미지를 불러오지 못했습니다.")
        self._main_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._main_image.setMinimumSize(520, 360)
        self._main_image.setWordWrap(True)
        self._main_image.setStyleSheet(
            "color:#8d6a5e; font-size:18px; font-weight:700; background:#fffaf5; border-radius:16px;"
        )
        self._set_label_pixmap(
            self._main_image,
            self._main_image_path,
            720,
            600,
            fallback_text="작업 이미지를 불러오지 못했습니다.",
        )
        image_layout.addWidget(self._main_image, 1)

        caption = QLabel("선생님을 위해 열심히 정리하고 있어요...!")
        caption.setObjectName("illustration_caption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_layout.addWidget(caption)

        layout.addWidget(image_frame, 1)
        return panel

    def _build_progress_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("right_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel("작업 진행 상황")
        title.setObjectName("section_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._section_subtitle = QLabel("작업이 완료될 때까지 잠시만 기다려주세요.")
        self._section_subtitle.setObjectName("section_subtitle")
        self._section_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._section_subtitle)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(14)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        progress_row.addWidget(self._progress, 1)

        self._percent_label = QLabel("0%")
        self._percent_label.setObjectName("percent_label")
        progress_row.addWidget(self._percent_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(progress_row)

        self._count_label = QLabel("0 / 0 항목 처리 중")
        self._count_label.setObjectName("count_label")
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._count_label)

        layout.addWidget(self._build_current_task_card())
        layout.addWidget(self._build_stats_card())
        layout.addStretch(1)
        return panel

    def _build_current_task_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card_box")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("현재 작업")
        title.setObjectName("panel_caption")
        layout.addWidget(title)

        self._task_title = QLabel("대기 중")
        self._task_title.setObjectName("section_subtitle")
        layout.addWidget(self._task_title)

        self._task_message = QLabel("작업 정보를 준비하고 있습니다.")
        self._task_message.setObjectName("panel_body")
        self._task_message.setWordWrap(True)
        # Layout stability — 긴 한 줄이 wrap 되어도 dialog 전체 height 가 늘어나
        # 다른 위젯을 밀어내지 않도록 max height 와 vertical Fixed sizePolicy 적용.
        # 원문 손실 방지: set_detail_text 에서 tooltip 에 full text 보존.
        self._task_message.setMaximumHeight(_DETAIL_LABEL_MAX_HEIGHT)
        self._task_message.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self._task_message)

        eta_row = QHBoxLayout()
        eta_row.setSpacing(12)
        eta_label = QLabel("예상 남은 시간")
        eta_label.setObjectName("panel_caption")
        eta_row.addWidget(eta_label)
        eta_row.addStretch(1)
        self._eta_label = QLabel("계산 중")
        self._eta_label.setObjectName("panel_body")
        eta_row.addWidget(self._eta_label)
        layout.addLayout(eta_row)
        return card

    def _build_stats_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card_box")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("처리 정보")
        title.setObjectName("panel_caption")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self._stat_values: dict[str, QLabel] = {}
        stats = [
            ("completed", "완료", "✓"),
            ("processing", "처리 중", "◔"),
            ("pending", "대기 중", "◷"),
            ("errors", "오류", "⚠"),
        ]
        for column, (key, name, icon_text) in enumerate(stats):
            cell = QVBoxLayout()
            cell.setSpacing(4)

            icon = QLabel(icon_text)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setStyleSheet("color:#9f6c5b; font-size:26px; font-weight:700;")
            cell.addWidget(icon)

            value = QLabel("0")
            value.setObjectName("stat_value")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(value)
            self._stat_values[key] = value

            name_label = QLabel(name)
            name_label.setObjectName("stat_name")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(name_label)

            holder = QFrame()
            holder.setObjectName("stat_cell")
            holder.setLayout(cell)
            grid.addWidget(holder, 0, column)

        layout.addLayout(grid)
        return card

    def _build_bottom_panel(self) -> QWidget:
        outer = QFrame()
        outer.setObjectName("bottom_box")
        layout = QHBoxLayout(outer)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        tip_box = QFrame()
        tip_box.setObjectName("bottom_box")
        tip_layout = QVBoxLayout(tip_box)
        tip_layout.setContentsMargins(14, 14, 14, 14)
        tip_layout.setSpacing(8)

        tip_title = QLabel("팁")
        tip_title.setObjectName("tip_title")
        tip_layout.addWidget(tip_title)

        tip_body = QLabel(
            "대량 작업은 시간이 걸릴 수 있지만,\n모든 데이터는 안전하게 처리되고 있어요!"
        )
        tip_body.setObjectName("tip_body")
        tip_body.setWordWrap(True)
        tip_layout.addWidget(tip_body)
        layout.addWidget(tip_box, 5)

        center_box = QWidget()
        center_layout = QVBoxLayout(center_box)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addStretch(1)
        self._mini_icon = QLabel("Aru")
        self._mini_icon.setObjectName("bottomAruIcon")
        self._mini_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mini_icon.setMinimumSize(120, 88)
        self._set_label_pixmap(
            self._mini_icon,
            self._mini_icon_path,
            140,
            96,
            fallback_text="Aru",
        )
        center_layout.addWidget(self._mini_icon, 0, Qt.AlignmentFlag.AlignCenter)
        center_layout.addStretch(1)
        layout.addWidget(center_box, 2)

        action_box = QFrame()
        action_box.setObjectName("bottom_box")
        action_layout = QVBoxLayout(action_box)
        action_layout.setContentsMargins(14, 14, 14, 14)
        action_layout.setSpacing(8)
        action_layout.addStretch(1)

        background_btn = QPushButton("백그라운드로 실행")
        background_btn.setObjectName("background_button")
        background_btn.clicked.connect(self.run_in_background)
        action_layout.addWidget(background_btn)

        hint = QLabel("창을 닫아도 작업은 계속됩니다.")
        hint.setObjectName("panel_body")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_layout.addWidget(hint)
        action_layout.addStretch(1)
        layout.addWidget(action_box, 4)

        return outer

    def _load_pixmap(self, path: Optional[Path], width: int, height: int) -> Optional[QPixmap]:
        if path is None or not path.exists():
            return None
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            logger.warning("LoadingOverlayDialog pixmap failed to decode: %s", path)
            return None
        return pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _set_label_pixmap(
        self,
        label: QLabel,
        path: Optional[Path],
        width: int,
        height: int,
        *,
        fallback_text: str,
    ) -> None:
        pixmap = self._load_pixmap(path, width, height)
        if pixmap is None:
            # QLabel.setPixmap()는 기존 text 를 덮어쓰므로, 빈 pixmap 으로 먼저 비운 뒤 fallback text 를 마지막에 설정해야
            # 실제 화면에 안내 문구가 표시된다.
            label.setPixmap(QPixmap())
            label.setText(fallback_text)
            return
        label.setPixmap(pixmap)

    def set_title_text(self, text: str) -> None:
        self.setWindowTitle(text)

    def set_message_text(self, text: str) -> None:
        self._section_subtitle.setText(text or "작업이 완료될 때까지 잠시만 기다려주세요.")

    def set_task_message(self, task_title: str = "", task_message: str = "") -> None:
        self._task_title.setText(task_title or "진행 중인 작업")
        # set_detail_text 와 동일한 truncate/tooltip 정책을 거치도록 위임.
        self.set_detail_text(task_message)

    def set_detail_text(self, text: str) -> None:
        """detail label 갱신. 긴 text 는 layout 안정을 위해 표시용으로 truncate
        하되, 원문은 tooltip 에 보존한다 (QLabel 도 hover 시 tooltip 으로 full
        text 확인 가능).
        """
        full = text or "세부 작업 정보를 준비하고 있습니다."
        display = _truncate_detail_for_display(full)
        self._task_message.setText(display)
        # 원문 보존 — display 가 truncate 되었거나 원문이 default placeholder 가
        # 아니라면 tooltip 으로 full text 노출.
        if display != full or (text and text != full):
            self._task_message.setToolTip(full)
        else:
            self._task_message.setToolTip("")

    def set_indeterminate(self, text: Optional[str] = None) -> None:
        self._progress.setRange(0, 0)
        if text:
            self._count_label.setText(text)
        self._percent_label.setText("...")

    def set_progress(self, current: int, total: int, text: Optional[str] = None) -> None:
        self.update_progress(current=current, total=total)
        if text:
            self._count_label.setText(text)

    def update_progress(
        self,
        current: int,
        total: int,
        task_title: str = "",
        task_message: str = "",
        completed: int | None = None,
        processing: int | None = None,
        pending: int | None = None,
        errors: int | None = None,
        eta_text: str | None = None,
    ) -> None:
        safe_total = max(total, 0)
        if safe_total <= 0:
            self._progress.setRange(0, 0)
            self._percent_label.setText("...")
            self._count_label.setText("항목 수 계산 중")
        else:
            safe_current = min(max(current, 0), safe_total)
            percent = int(round((safe_current / safe_total) * 100))
            self._progress.setRange(0, safe_total)
            self._progress.setValue(safe_current)
            self._percent_label.setText(f"{percent}%")
            self._count_label.setText(f"{safe_current} / {safe_total} 항목 처리 중")

        self.set_task_message(task_title, task_message or self._task_message.text())

        done_value = max(current, 0) if completed is None else max(completed, 0)
        processing_value = max(safe_total - done_value, 0) if processing is None else max(processing, 0)
        pending_value = 0 if pending is None else max(pending, 0)
        error_value = 0 if errors is None else max(errors, 0)

        self._stat_values["completed"].setText(f"{done_value:,}")
        self._stat_values["processing"].setText(f"{processing_value:,}")
        self._stat_values["pending"].setText(f"{pending_value:,}")
        self._stat_values["errors"].setText(f"{error_value:,}")
        self._eta_label.setText(eta_text or "계산 중")

    def run_in_background(self) -> None:
        # TODO: 별도의 트레이/작업 센터가 생기면 그쪽 상태 진입과 연계할 수 있다.
        self.hide()

    def reject(self) -> None:
        self.run_in_background()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.run_in_background()
        event.ignore()
