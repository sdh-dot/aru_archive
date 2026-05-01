"""
수동 분류 지정 다이얼로그.

PyQt6 전용. PySide6 사용 금지.

사용자가 분류 미리보기에서 실패 항목을 선택한 뒤 열린다.
series / character canonical을 수동으로 지정할 수 있다.
기존 tag_aliases에서 canonical 후보를 가져와 QCompleter로 자동완성한다.

label/value 분리:
- 자동완성 표시 레이블: "캐릭터명 (시리즈명)" 형식
- 내부 저장값: canonical 문자열만 (_char_canonical_map dict에서 역조회)
- DB/metadata write 경로에는 canonical만 전달; label 문자열 저장 금지
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)


def _load_canonicals(conn: Optional[sqlite3.Connection], tag_type: str) -> list[str]:
    """DB에서 해당 tag_type의 canonical 목록을 반환한다."""
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT DISTINCT canonical FROM tag_aliases "
            "WHERE tag_type = ? AND enabled = 1 ORDER BY canonical",
            (tag_type,),
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _load_character_labels(
    conn: Optional[sqlite3.Connection],
) -> tuple[list[str], dict[str, str]]:
    """
    캐릭터 자동완성 label 목록과 label→canonical 역매핑을 반환한다.

    label 형식: "캐릭터명 (시리즈명)" — parent_series가 있을 때.
    parent_series가 없으면 "캐릭터명" 단독 사용.

    반환: (labels, label_to_canonical)
    """
    if conn is None:
        return [], {}
    try:
        rows = conn.execute(
            "SELECT DISTINCT canonical, parent_series FROM tag_aliases "
            "WHERE tag_type = 'character' AND enabled = 1 "
            "ORDER BY parent_series, canonical",
        ).fetchall()
    except Exception:
        return [], {}

    labels: list[str] = []
    label_to_canonical: dict[str, str] = {}
    seen_canonicals: set[str] = set()

    for row in rows:
        canonical    = row[0] or ""
        parent_series = (row[1] or "").strip()
        if not canonical:
            continue
        if canonical in seen_canonicals:
            continue
        seen_canonicals.add(canonical)

        label = f"{canonical} ({parent_series})" if parent_series else canonical
        # 동일 label이 이미 있으면 canonical을 suffix로 구별
        if label in label_to_canonical:
            label = f"{canonical} [{canonical}]"
        labels.append(label)
        label_to_canonical[label] = canonical

    return labels, label_to_canonical


class ManualClassifyOverrideDialog(QDialog):
    """
    수동 분류 지정 다이얼로그.

    OK 시 result() dict 반환:
        {series_canonical, character_canonical, folder_locale, reason}
    Cancel 시 result()는 None.
    """

    def __init__(
        self,
        *,
        group_info: dict,
        conn: Optional[sqlite3.Connection] = None,
        current_locale: str = "canonical",
        parent=None,
    ) -> None:
        """
        group_info 키:
            filename      : str
            title         : str
            artist_name   : str
            raw_tags      : list[str]
            rule_type     : str   (현재 분류 실패 유형)
            dest_path     : str   (현재 목적지)
        """
        super().__init__(parent)
        self._group_info = group_info
        self._conn       = conn
        self._result: Optional[dict] = None
        # label → canonical 역매핑 (캐릭터 자동완성 label/value 분리)
        self._char_label_to_canonical: dict[str, str] = {}

        self.setWindowTitle("수동 분류 지정")
        self.setMinimumWidth(560)
        self._setup_ui(current_locale)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _setup_ui(self, current_locale: str) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # ── 현재 항목 정보 ─────────────────────────────────────────────
        info_box = QGroupBox("현재 항목")
        info_form = QFormLayout(info_box)
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def _lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #C0A0B0; font-size: 11px;")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return lbl

        info_form.addRow("파일명:", _lbl(self._group_info.get("filename", "")))
        info_form.addRow("제목:",   _lbl(self._group_info.get("title", "") or "—"))
        info_form.addRow("작가:",   _lbl(self._group_info.get("artist_name", "") or "—"))
        info_form.addRow("분류 상태:", _lbl(self._group_info.get("rule_type", "")))
        info_form.addRow("현재 목적지:", _lbl(self._group_info.get("dest_path", "") or "—"))

        raw_tags = self._group_info.get("raw_tags") or []
        tags_widget = QTextEdit()
        tags_widget.setPlainText(", ".join(raw_tags) if raw_tags else "—")
        tags_widget.setReadOnly(True)
        tags_widget.setFixedHeight(52)
        tags_widget.setStyleSheet(
            "QTextEdit { background: #1A0F14; color: #C0A0B0; "
            "font-size: 10px; border: 1px solid #4A2030; }"
        )
        tags_widget.setToolTip(
            "원본 파일이나 메타데이터에서 읽은 태그입니다. "
            "수동 분류 판단에 참고용으로 표시됩니다."
        )
        info_form.addRow("원본 태그:", tags_widget)
        root.addWidget(info_box)

        # ── 수동 지정 입력 ─────────────────────────────────────────────
        override_box = QGroupBox("수동 분류 지정")
        override_form = QFormLayout(override_box)
        override_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        series_canonicals = _load_canonicals(self._conn, "series")
        char_labels, self._char_label_to_canonical = _load_character_labels(self._conn)

        self._series_edit = QLineEdit()
        self._series_edit.setPlaceholderText("예: Blue Archive")
        if series_canonicals:
            c = QCompleter(series_canonicals, self)
            c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            c.setFilterMode(Qt.MatchFlag.MatchContains)
            self._series_edit.setCompleter(c)
        override_form.addRow("시리즈 이름:", self._series_edit)

        self._char_edit = QLineEdit()
        self._char_edit.setPlaceholderText("예: 伊落マリー (Blue Archive)")
        if char_labels:
            c2 = QCompleter(char_labels, self)
            c2.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            c2.setFilterMode(Qt.MatchFlag.MatchContains)
            # 자동완성 선택 시 label 전체를 LineEdit에 채움 (canonical 역조회는 OK 시 수행)
            self._char_edit.setCompleter(c2)
        override_form.addRow("캐릭터 이름:", self._char_edit)

        self._locale_edit = QLineEdit()
        self._locale_edit.setText(current_locale)
        self._locale_edit.setPlaceholderText("canonical / ko / ja / en")
        self._locale_edit.setToolTip(
            "폴더명 생성에 사용할 언어입니다. 비워두면 기본 설정을 사용합니다."
        )
        override_form.addRow("폴더명 언어:", self._locale_edit)

        self._reason_edit = QLineEdit()
        self._reason_edit.setPlaceholderText("예: 제목에만 캐릭터명 있음")
        override_form.addRow("사유 (선택):", self._reason_edit)

        root.addWidget(override_box)

        # ── 버튼 ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ------------------------------------------------------------------
    # 결과
    # ------------------------------------------------------------------

    def _resolve_character_canonical(self, text: str) -> str:
        """
        입력 텍스트에서 character canonical을 추출한다.

        자동완성 label "캐릭터명 (시리즈명)" 형식이면 역매핑 dict로 canonical 반환.
        매핑에 없으면 텍스트를 그대로 canonical로 사용 (직접 입력 허용).
        """
        text = text.strip()
        if not text:
            return ""
        # label → canonical 역매핑 우선
        if text in self._char_label_to_canonical:
            return self._char_label_to_canonical[text]
        # "canonical (series)" 형식에서 canonical 부분만 추출
        if " (" in text and text.endswith(")"):
            return text[: text.rfind(" (")].strip()
        return text

    def _on_ok(self) -> None:
        series    = self._series_edit.text().strip()
        char_text = self._char_edit.text().strip()
        character = self._resolve_character_canonical(char_text)
        locale    = self._locale_edit.text().strip() or "canonical"
        reason    = self._reason_edit.text().strip() or None

        if not series and not character:
            # 둘 다 비어 있으면 입력 요청
            self._series_edit.setFocus()
            self._series_edit.setStyleSheet("border: 1px solid #ff6b6b;")
            return

        self._result = {
            "series_canonical":    series or None,
            "character_canonical": character or None,
            "folder_locale":       locale,
            "reason":              reason,
        }
        self.accept()

    def result(self) -> Optional[dict]:  # type: ignore[override]
        """OK로 닫혔으면 override dict, 아니면 None."""
        return self._result
