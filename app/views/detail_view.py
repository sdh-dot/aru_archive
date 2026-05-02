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
    EXPLORER_META_REPAIR_LABEL,
    EXPLORER_META_REPAIR_TOOLTIP,
    PIXIV_META_LABEL,
    PIXIV_META_TOOLTIP,
    PIXIV_META_TOOLTIP_MISSING,
    READ_EMBEDDED_META_LABEL,
    READ_EMBEDDED_META_TOOLTIP,
    REINDEX_LABEL,
    REINDEX_TOOLTIP,
    XMP_RETRY_LABEL,
    XMP_RETRY_TOOLTIP,
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

        self._btn_read_meta   = _btn(
            READ_EMBEDDED_META_LABEL,
            READ_EMBEDDED_META_TOOLTIP
        )
        self._btn_pixiv_meta  = _btn(
            PIXIV_META_LABEL,
            PIXIV_META_TOOLTIP
        )
        self._btn_regen_thumb = _btn(
            "썸네일 재생성",
            "thumbnail_cache 재생성"
        )
        self._btn_bmp         = _btn(
            "BMP → PNG managed",
            "BMP original에서 PNG managed 생성"
        )
        self._btn_gif         = _btn(
            "GIF → WebP managed",
            "animated GIF에서 WebP managed 생성"
        )
        self._btn_sidecar     = _btn(
            "Sidecar 생성",
            "static GIF / ZIP용 .aru.json 생성"
        )
        self._btn_reindex     = _btn(
            REINDEX_LABEL,
            REINDEX_TOOLTIP
        )
        self._btn_xmp_retry   = _btn(
            XMP_RETRY_LABEL,
            XMP_RETRY_TOOLTIP
        )

        self._btn_explorer_meta = _btn(
            EXPLORER_META_REPAIR_LABEL,
            EXPLORER_META_REPAIR_TOOLTIP
        )

        for b in [
            self._btn_read_meta, self._btn_pixiv_meta,
            self._btn_regen_thumb, self._btn_bmp,
            self._btn_gif, self._btn_sidecar,
            self._btn_xmp_retry, self._btn_explorer_meta, self._btn_reindex,
        ]:
            action_vl.addWidget(b)

        self._btn_read_meta  .clicked.connect(
            lambda: self._emit_if_selected(self.read_meta_requested)
        )
        self._btn_pixiv_meta .clicked.connect(
            lambda: self._emit_if_selected(self.pixiv_meta_requested)
        )
        self._btn_regen_thumb.clicked.connect(
            lambda: self._emit_if_selected(self.regen_thumb_requested)
        )
        self._btn_bmp        .clicked.connect(
            lambda: self._emit_if_selected(self.bmp_convert_requested)
        )
        self._btn_gif        .clicked.connect(
            lambda: self._emit_if_selected(self.gif_convert_requested)
        )
        self._btn_sidecar    .clicked.connect(
            lambda: self._emit_if_selected(self.sidecar_requested)
        )
        self._btn_xmp_retry  .clicked.connect(
            lambda: self._emit_if_selected(self.xmp_retry_requested)
        )
        self._btn_explorer_meta.clicked.connect(
            self.explorer_meta_repair_requested.emit
        )
        self._btn_reindex    .clicked.connect(self.reindex_requested.emit)

        layout.addWidget(action_box)

        # Pixiv 보강 결과 (초기에는 숨김 — show_pixiv_result() 호출 시 표시)
        self._pixiv_box = QGroupBox("Pixiv 보강")
        pixiv_form = QFormLayout(self._pixiv_box)
        pixiv_form.setSpacing(4)
        pixiv_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._lbl_pixiv_id     = _info_lbl()
        self._lbl_pixiv_url    = _info_lbl()
        self._lbl_pixiv_url.setOpenExternalLinks(True)
        self._lbl_pixiv_status = _info_lbl()

        for key, lbl in [
            ("추출된 ID",  self._lbl_pixiv_id),
            ("생성 URL",   self._lbl_pixiv_url),
            ("상태",       self._lbl_pixiv_status),
        ]:
            row_lbl = QLabel(f"{key}:")
            row_lbl.setStyleSheet("font-size: 11px; color: #D8AEBB;")
            pixiv_form.addRow(row_lbl, lbl)

        self._pixiv_box.hide()
        layout.addWidget(self._pixiv_box)
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
            self._btn_read_meta, self._btn_pixiv_meta, self._btn_regen_thumb,
            self._btn_bmp, self._btn_gif, self._btn_sidecar,
            self._btn_xmp_retry, self._btn_explorer_meta, self._btn_reindex,
        ]:
            b.setEnabled(False)
        self._pixiv_box.hide()
        for lbl in [self._lbl_pixiv_id, self._lbl_pixiv_url, self._lbl_pixiv_status]:
            lbl.setText("—")

    def show_pixiv_result(self, artwork_id: str, url: str) -> None:
        """Pixiv 파일명 추출 결과를 Pixiv 보강 섹션에 표시한다."""
        self._lbl_pixiv_id.setText(artwork_id)
        self._lbl_pixiv_url.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_pixiv_url.setText(
            f'<a href="{url}" style="color:#D8AEBB;">{url}</a>'
        )
        self._lbl_pixiv_status.setText("Fetcher 미구현 — URL 생성만 완료")
        self._lbl_pixiv_status.setStyleSheet(
            "font-size: 11px; color: #FFC857;"
        )
        self._pixiv_box.show()

    # ------------------------------------------------------------------
    # 내부: show_group 분리 메서드
    # ------------------------------------------------------------------

    def _update_info_section(self, group: dict) -> None:
        sync = group.get("metadata_sync_status", "pending")
        for key, lbl in self._info.items():
            if key == "metadata_sync_status":
                display = _STATUS_DISPLAY.get(sync, sync)
                lbl.setText(display)
                color = _STATUS_COLOR.get(sync, "#F7E8EC")
                lbl.setStyleSheet(
                    f"font-size: 11px; color: {color}; font-weight: bold;"
                )
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
        fmts  = {f.get("file_format", "") for f in files}
        roles = {f.get("file_role", "") for f in files}
        has_bmp     = "bmp" in fmts
        has_gif     = "gif" in fmts
        has_zip     = "zip" in fmts
        has_managed = "managed" in roles

        # 항상 활성 (그룹 선택 시)
        self._btn_read_meta  .setEnabled(True)
        self._btn_regen_thumb.setEnabled(True)
        self._btn_reindex    .setEnabled(True)
        self._btn_explorer_meta.setEnabled(True)

        # BMP → PNG
        bmp_ok = has_bmp and not has_managed
        self._btn_bmp.setEnabled(bmp_ok)
        if bmp_ok:
            bmp_tip = "BMP original에서 PNG managed 생성"
        elif not has_bmp:
            bmp_tip = "BMP original이 없습니다"
        else:
            bmp_tip = "이미 managed 파일이 존재합니다"
        self._btn_bmp.setToolTip(bmp_tip)

        # GIF → WebP
        gif_ok = has_gif and not has_managed
        self._btn_gif.setEnabled(gif_ok)
        if gif_ok:
            gif_tip = "animated GIF에서 WebP managed 생성"
        elif not has_gif:
            gif_tip = "animated GIF original이 없습니다"
        else:
            gif_tip = "이미 managed 파일이 존재합니다"
        self._btn_gif.setToolTip(gif_tip)

        # Sidecar
        sidecar_ok = has_gif or has_zip
        self._btn_sidecar.setEnabled(sidecar_ok)
        self._btn_sidecar.setToolTip(
            "static GIF / ZIP용 .aru.json 생성"
            if sidecar_ok
            else "static GIF 또는 ZIP 파일이 선택되어야 합니다"
        )

        # Pixiv 메타데이터 가져오기
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

        # XMP 재시도 — json_only / xmp_write_failed 상태에서 활성
        # (실제 ExifTool 가용 여부는 MainWindow에서 체크)
        self._btn_xmp_retry.setEnabled(True)

    # ------------------------------------------------------------------

    def _emit_if_selected(self, signal: Signal) -> None:
        if self._current_group_id:
            signal.emit(self._current_group_id)
