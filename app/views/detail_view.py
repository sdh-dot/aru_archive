"""
우측 상세 패널.

선택된 artwork_group 정보 및 파일 구성 표시.
수동 작업 버튼 두 종류:
  - 파일 내 메타데이터 읽기 (embedded AruArchive JSON)
  - Pixiv 메타데이터 가져오기 (파일명 기반 artwork_id 추출 → Pixiv URL)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from app.ui_action_text import (
    EXPLORER_META_REPAIR_LABEL,  # noqa: F401 — backwards-compat re-export
    EXPLORER_META_REPAIR_TOOLTIP,  # noqa: F401
    PIXIV_META_LABEL,
    PIXIV_META_TOOLTIP,
    PIXIV_META_TOOLTIP_MISSING,
    READ_EMBEDDED_META_LABEL,  # noqa: F401 — backwards-compat re-export
    READ_EMBEDDED_META_TOOLTIP,  # noqa: F401
    RE_REGISTER_META_LABEL,
    RE_REGISTER_META_TOOLTIP,
    REINDEX_LABEL,  # noqa: F401 — backwards-compat re-export
    REINDEX_TOOLTIP,  # noqa: F401
    RESCAN_LABEL,
    RESCAN_TOOLTIP,
    XMP_RETRY_LABEL,  # noqa: F401 — backwards-compat re-export
    XMP_RETRY_TOOLTIP,  # noqa: F401
)
from core.filename_parser import parse_pixiv_filename

_STATUS_DISPLAY: dict[str, str] = {
    "full":                  "✅ Full",
    "json_only":             "🟡 JSON Only",
    "pending":               "⏳ Pending",
    "convert_failed":        "❌ Convert Failed",
    "metadata_write_failed": "❌ Metadata Failed",
    "xmp_write_failed":      "⚠️ XMP Warning",
    "metadata_missing":      "❓ Metadata Missing",
    "file_write_failed":     "❌ File Write Failed",
    "db_update_failed":      "❌ DB Update Failed",
    "needs_reindex":         "↺ Needs Reindex",
    "out_of_sync":           "! Out of Sync",
}

# 상태별 텍스트 색상 (와인 팔레트)
_STYLE_VAL_LBL = "font-size: 11px; color: #F7E8EC;"

_STATUS_COLOR: dict[str, str] = {
    "full":                  "#8FD694",
    "json_only":             "#FFC857",
    "pending":               "#D8AEBB",
    "convert_failed":        "#FF6B7A",
    "metadata_write_failed": "#FF6B7A",
    "xmp_write_failed":      "#FFC857",
    "metadata_missing":      "#E69AAA",
    "file_write_failed":     "#FF6B7A",
    "db_update_failed":      "#FF6B7A",
    "needs_reindex":         "#D8AEBB",
    "out_of_sync":           "#FFC857",
}


def _info_lbl() -> QLabel:
    lbl = QLabel("—")
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lbl.setStyleSheet(_STYLE_VAL_LBL)
    return lbl


def _btn(text: str, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tooltip)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.setStyleSheet(
        "QPushButton {"
        "  padding: 5px 8px; border-radius: 4px; font-size: 11px;"
        "  background: #3A202B; color: #F7E8EC; border: 1px solid #B5526C;"
        "}"
        "QPushButton:hover { background: #5C2A3A; border-color: #E69AAA; }"
        "QPushButton:disabled { color: #8F6874; background: #211018;"
        "  border-color: #4A2030; }"
    )
    return b


class DetailView(QWidget):
    """
    Signals (MainWindow가 연결):
        read_meta_requested(group_id)      : 파일 내 메타데이터 읽기
        pixiv_meta_requested(group_id)     : Pixiv에서 메타데이터 가져오기
        regen_thumb_requested(group_id)
        bmp_convert_requested(group_id)
        gif_convert_requested(group_id)
        sidecar_requested(group_id)
        reindex_requested()
    """

    read_meta_requested   = Signal(str)
    pixiv_meta_requested  = Signal(str)
    regen_thumb_requested = Signal(str)
    bmp_convert_requested = Signal(str)
    gif_convert_requested = Signal(str)
    sidecar_requested     = Signal(str)
    reindex_requested     = Signal()
    xmp_retry_requested   = Signal(str)
    explorer_meta_repair_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_group_id: Optional[str] = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #1A0F14; border: none; }")

        inner = QWidget()
        inner.setStyleSheet("background: #1A0F14;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 헤더
        self._header = QLabel("파일을 선택하세요")
        self._header.setWordWrap(True)
        self._header.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #E69AAA; padding-bottom: 4px;"
        )
        layout.addWidget(self._header)

        # 기본 정보
        info_box = QGroupBox("기본 정보")
        info_form = QFormLayout(info_box)
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        info_form.setSpacing(4)
        self._info: dict[str, QLabel] = {}
        self._status_lbl: Optional[QLabel] = None
        for key, label in [
            ("group_id",             "Group ID"),
            ("source_site",          "Source"),
            ("artwork_id",           "Artwork ID"),
            # 생성 URL 은 source/artwork_id 로부터 표시 시점에 계산 (DB 컬럼 없음).
            ("source_url",           "생성 URL"),
            ("artwork_title",        "Title"),
            ("artist_name",          "Artist"),
            ("metadata_sync_status", "Status"),
            ("indexed_at",           "Indexed"),
        ]:
            val_lbl = QLabel("—")
            val_lbl.setWordWrap(True)
            val_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            val_lbl.setStyleSheet(_STYLE_VAL_LBL)
            self._info[key] = val_lbl
            if key == "metadata_sync_status":
                self._status_lbl = val_lbl
            row_lbl = QLabel(label + ":")
            row_lbl.setStyleSheet("font-size: 11px; color: #D8AEBB;")
            info_form.addRow(row_lbl, val_lbl)
        layout.addWidget(info_box)

        # 파일 구성
        file_box = QGroupBox("파일 구성")
        file_layout = QVBoxLayout(file_box)
        file_layout.setSpacing(3)
        self._file_lbls: dict[str, QLabel] = {}
        for role in ("original", "managed", "sidecar"):
            row = QHBoxLayout()
            rl = QLabel(f"{role}:")
            rl.setFixedWidth(58)
            rl.setStyleSheet("font-size: 10px; color: #D8AEBB;")
            pl = QLabel("—")
            pl.setWordWrap(True)
            pl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            pl.setStyleSheet("font-size: 10px; color: #F7E8EC;")
            self._file_lbls[role] = pl
            row.addWidget(rl)
            row.addWidget(pl, 1)
            file_layout.addLayout(row)
        layout.addWidget(file_box)

        # 태그
        tag_box = QGroupBox("태그")
        tag_vl = QVBoxLayout(tag_box)
        self._tags_edit = QTextEdit()
        self._tags_edit.setReadOnly(True)
        self._tags_edit.setFixedHeight(64)
        self._tags_edit.setStyleSheet(
            "font-size: 10px; border: none; background: transparent; color: #D8AEBB;"
        )
        tag_vl.addWidget(self._tags_edit)
        layout.addWidget(tag_box)

        # 수동 작업 버튼
        action_box = QGroupBox("수동 작업")
        action_vl = QVBoxLayout(action_box)
        action_vl.setSpacing(4)

        # PR #119 정리:
        #   - "파일 내 메타데이터 읽기" / "BMP → PNG managed" /
        #     "GIF → WebP managed" / "Sidecar 생성" / "Pixiv 보강 Delete" 버튼
        #     은 release 사용자 흐름에서 노출하지 않으므로 detail panel 에서
        #     제거. 연결된 Signal 객체와 외부 caller 의 connect 는 그대로 둔다
        #     (gallery context menu 등 다른 진입점에서 emit 가능).
        #   - "🔄 XMP 재처리" 와 "🛠 Explorer 메타 복구" 는 사실상 동일 (PR #116
        #     이 두 경로 모두 같은 clear-first writer 를 통일). 단일
        #     "🔄 메타데이터 재등록" 버튼으로 통합하고 기존 xmp_retry_requested
        #     signal 을 그대로 emit 한다 (handler 무변경).
        self._btn_pixiv_meta  = _btn(
            PIXIV_META_LABEL,
            PIXIV_META_TOOLTIP,
        )
        self._btn_regen_thumb = _btn(
            "🖼 썸네일 재생성",
            "선택한 파일의 썸네일을 다시 생성합니다.",
        )
        self._btn_re_register_meta = _btn(
            RE_REGISTER_META_LABEL,
            RE_REGISTER_META_TOOLTIP,
        )
        self._btn_reindex     = _btn(
            RESCAN_LABEL,
            RESCAN_TOOLTIP,
        )

        for b in [
            self._btn_pixiv_meta,
            self._btn_regen_thumb,
            self._btn_re_register_meta,
            self._btn_reindex,
        ]:
            action_vl.addWidget(b)

        self._btn_pixiv_meta .clicked.connect(
            lambda: self._emit_if_selected(self.pixiv_meta_requested)
        )
        self._btn_regen_thumb.clicked.connect(
            lambda: self._emit_if_selected(self.regen_thumb_requested)
        )
        # 통합 버튼 — 기존 XMP retry handler 를 그대로 사용. PR #116/#117 의
        # write_xmp_metadata_with_exiftool(clear_windows_xp_fields_before_write=True)
        # 경로가 발화된다.
        self._btn_re_register_meta.clicked.connect(
            lambda: self._emit_if_selected(self.xmp_retry_requested)
        )
        self._btn_reindex    .clicked.connect(self.reindex_requested.emit)

        layout.addWidget(action_box)
        layout.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def show_group(self, group: dict, files: list[dict]) -> None:
        """group + files 데이터를 패널에 표시한다."""
        self._current_group_id = group.get("group_id")
        title = group.get("artwork_title") or group.get("artwork_id") or "?"
        self._header.setText(title[:60])

        self._update_info_section(group)
        self._update_file_section(files)
        self._update_tags_section(group)
        self._update_button_states(files)

    def clear(self) -> None:
        self._current_group_id = None
        self._header.setText("파일을 선택하세요")
        for lbl in self._info.values():
            lbl.setText("—")
            lbl.setStyleSheet(_STYLE_VAL_LBL)
        for lbl in self._file_lbls.values():
            lbl.setText("—")
            lbl.setToolTip("")
        self._tags_edit.clear()
        for b in [
            self._btn_pixiv_meta, self._btn_regen_thumb,
            self._btn_re_register_meta, self._btn_reindex,
        ]:
            b.setEnabled(False)

    def show_pixiv_result(self, artwork_id: str, url: str) -> None:  # noqa: ARG002
        """레거시 호환 stub — PR #119 에서 별도 'Pixiv 보강' 섹션을 제거.

        artwork_id / url 정보는 기본 정보 영역의 'Source' / 'Artwork ID' /
        '생성 URL' row 가 자동으로 표시한다 (set_group / show_group 흐름).
        본 메서드는 외부 caller (MainWindow._on_pixiv_meta) 호환을 위해
        남겨두지만 추가 UI 출력은 하지 않는다.
        """

    # ------------------------------------------------------------------
    # 내부: show_group 분리 메서드
    # ------------------------------------------------------------------

    def _update_info_section(self, group: dict) -> None:
        sync = group.get("metadata_sync_status", "pending")
        source = (group.get("source_site") or "").strip()
        artwork_id = (group.get("artwork_id") or "").strip()
        for key, lbl in self._info.items():
            if key == "metadata_sync_status":
                display = _STATUS_DISPLAY.get(sync, sync)
                lbl.setText(display)
                color = _STATUS_COLOR.get(sync, "#F7E8EC")
                lbl.setStyleSheet(
                    f"font-size: 11px; color: {color}; font-weight: bold;"
                )
            elif key == "source_url":
                # 표시 시점에 계산 (DB 컬럼 없음 — schema 무수정).
                if source == "pixiv" and artwork_id:
                    url = f"https://www.pixiv.net/artworks/{artwork_id}"
                else:
                    url = "—"
                lbl.setText(url)
                lbl.setStyleSheet(_STYLE_VAL_LBL)
            else:
                lbl.setText(str(group.get(key) or "—")[:80])
                lbl.setStyleSheet(_STYLE_VAL_LBL)

    def _update_file_section(self, files: list[dict]) -> None:
        role_data: dict[str, tuple[str, str]] = {
            "original": ("—", ""),
            "managed":  ("—", ""),
            "sidecar":  ("—", ""),
        }
        for f in files:
            role = f.get("file_role", "")
            if role not in role_data:
                continue
            fp  = f.get("file_path") or ""
            fmt = f.get("file_format", "")
            if fp:
                exists = "✓" if Path(fp).exists() else "✗ 없음"
                name   = Path(fp).name
                display = f"[{fmt}] {name}  ({exists})"
            else:
                display = "—"
            role_data[role] = (display, fp)
        for role, (text, tooltip) in role_data.items():
            lbl = self._file_lbls[role]
            lbl.setText(text)
            lbl.setToolTip(tooltip if tooltip else "")

    def _update_tags_section(self, group: dict) -> None:
        tags: list[str] = []
        for key in ("tags_json", "character_tags_json", "series_tags_json"):
            raw = group.get(key)
            if raw:
                try:
                    tags.extend(json.loads(raw))
                except Exception:
                    pass
        self._tags_edit.setPlainText(", ".join(tags) if tags else "(없음)")

    def _update_button_states(self, files: list[dict]) -> None:
        # PR #119: BMP / GIF / Sidecar / Read meta / XMP retry / Explorer 메타
        # 복구 버튼은 detail panel 에서 제거됐으므로 여기서 enable 처리하지
        # 않는다. 남은 4개 버튼만 정책에 맞게 활성화한다.

        # 항상 활성 (그룹 선택 시) — 썸네일 재생성 / 메타데이터 재등록 / 재스캔
        self._btn_regen_thumb.setEnabled(True)
        self._btn_re_register_meta.setEnabled(True)
        self._btn_reindex.setEnabled(True)

        # Pixiv 메타데이터 가져오기 — Pixiv 파일명 패턴이 있을 때만 활성.
        has_pixiv = any(
            f.get("file_role") == "original" and
            parse_pixiv_filename(f.get("file_path", "")) is not None
            for f in files
        )
        self._btn_pixiv_meta.setEnabled(has_pixiv)
        if not has_pixiv:
            self._btn_pixiv_meta.setToolTip(PIXIV_META_TOOLTIP_MISSING)
        else:
            self._btn_pixiv_meta.setToolTip(PIXIV_META_TOOLTIP)

    # ------------------------------------------------------------------

    def _emit_if_selected(self, signal: Signal) -> None:
        if self._current_group_id:
            signal.emit(self._current_group_id)
