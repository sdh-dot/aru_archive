"""
분류 미리보기 다이얼로그.

표시 내용:
  - 원본 파일 경로
  - 내부 canonical 태그 / 표시명 (localized)
  - 복사 예정 경로 목록 (rule_type, conflict 상태)
  - fallback 경고
  - 예상 복사본 수 / 예상 용량

버튼:
  [실행]  → QDialog.accept()
  [취소]  → QDialog.reject()
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel,
    QTextEdit, QVBoxLayout,
)

_RULE_LABEL: dict[str, str] = {
    "series_character":          "Series/Character",
    "series_uncategorized":      "Series/Uncategorized",
    "character":                 "Character",
    "author_fallback":           "Author Fallback",
    "author":                    "Author",
    "by_tag":                    "Tag",
    "builtin":                   "기본",
}

_LOCALE_LABEL: dict[str, str] = {
    "ko":        "한국어",
    "ja":        "일본어",
    "en":        "영어",
    "canonical": "canonical",
}


class ClassifyPreviewDialog(QDialog):
    """
    분류 미리보기를 표시하고 [실행] / [취소]를 제공하는 모달 다이얼로그.

    accepted → 호출자가 execute_classify_preview() 실행
    rejected → 취소
    """

    def __init__(self, preview: dict, parent=None) -> None:
        super().__init__(parent)
        self._preview = preview
        self.setWindowTitle("분류 미리보기")
        self.setMinimumSize(680, 460)
        self.resize(760, 520)
        self._setup_ui()

    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # 원본 파일
        src_name = Path(self._preview["source_path"]).name
        hdr = QLabel(f"원본 파일:  {src_name}")
        hdr.setStyleSheet("font-weight: bold; font-size: 12px; color: #E69AAA;")
        layout.addWidget(hdr)

        src_path_lbl = QLabel(self._preview["source_path"])
        src_path_lbl.setWordWrap(True)
        src_path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        src_path_lbl.setStyleSheet("font-size: 10px; color: #D8AEBB; padding-bottom: 4px;")
        layout.addWidget(src_path_lbl)

        # 폴더명 언어 표시
        locale = self._preview.get("folder_locale", "canonical")
        if locale != "canonical":
            locale_lbl = QLabel(
                f"폴더명 언어: {_LOCALE_LABEL.get(locale, locale)}  "
                f"(canonical 태그는 원본 유지)"
            )
            locale_lbl.setStyleSheet("font-size: 10px; color: #8FD694;")
            layout.addWidget(locale_lbl)

        # 복사 예정 목록
        dest_hdr = QLabel("복사 예정:")
        dest_hdr.setStyleSheet("font-weight: bold; font-size: 11px; color: #E69AAA;")
        layout.addWidget(dest_hdr)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        text.setStyleSheet(
            "QTextEdit {"
            "  background: #140A0F; color: #D8AEBB;"
            "  font-family: Consolas, 'Courier New', monospace;"
            "  font-size: 10px;"
            "  border: 1px solid #4A2030;"
            "}"
        )

        lines: list[str] = []
        dests = self._preview.get("destinations", [])
        if dests:
            for i, d in enumerate(dests, 1):
                rule  = _RULE_LABEL.get(d.get("rule_type", ""), d.get("rule_type", ""))
                will  = "✓" if d["will_copy"] else "✗ 건너뜀"
                conf  = d.get("conflict", "none")
                extra = f"  [{conf}]" if conf not in ("none", "") else ""

                # localization info
                loc_info = ""
                if d.get("series_display") and d.get("series_canonical") != d.get("series_display"):
                    loc_info += f" | {d['series_canonical']} → {d['series_display']}"
                if d.get("character_display") and d.get("character_canonical") != d.get("character_display"):
                    loc_info += f" | {d['character_canonical']} → {d['character_display']}"
                if d.get("used_fallback"):
                    loc_info += "  ⚠fallback"

                lines.append(f"{i:2}. [{rule}]{extra}  {will}")
                lines.append(f"    {d['dest_path']}{loc_info}")
        else:
            lines.append(
                "(복사 대상 없음 — 분류 가능한 태그/작가 정보가 없거나 classified_dir 미설정)"
            )

        text.setPlainText("\n".join(lines))
        layout.addWidget(text, 1)

        # fallback 경고
        fallback_tags = self._preview.get("fallback_tags", [])
        if fallback_tags:
            warn_lbl = QLabel(
                f"⚠ {_LOCALE_LABEL.get(locale, locale)} 표시명이 없어 canonical을 사용한 태그: "
                + ", ".join(str(t) for t in fallback_tags)
            )
            warn_lbl.setWordWrap(True)
            warn_lbl.setStyleSheet("font-size: 10px; color: #ffc107;")
            layout.addWidget(warn_lbl)

        # 요약 행
        copies     = self._preview.get("estimated_copies", 0)
        size_bytes = self._preview.get("estimated_bytes", 0)
        size_str   = _fmt_size(size_bytes)

        summary = QLabel(f"예상 복사본: {copies}개    예상 용량: {size_str}")
        summary.setStyleSheet("font-size: 11px; color: #8FD694; padding-top: 4px;")
        layout.addWidget(summary)

        # 버튼
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("실행")
        ok_btn.setEnabled(copies > 0)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------

    def preview(self) -> dict:
        return self._preview


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"
