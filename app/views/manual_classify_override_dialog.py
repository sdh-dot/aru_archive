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

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel
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

# 다국어 자동완성 candidate 의 metadata 를 model item 에 보존하는 데이터 role.
# Qt UserRole 이상은 사용자 정의 가능.
CANDIDATE_DATA_ROLE = Qt.ItemDataRole.UserRole + 1


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


class _AutocompleteController:
    """``core.autocomplete_provider`` 결과를 ``QLineEdit`` 의 자동완성으로 surface 한다.

    한국어 / 일본어 / 영어 입력 모두에 대해 후보를 띄우고, 선택 시 후보의 전체
    ``TagAutocompleteCandidate`` metadata (canonical, tag_type, parent_series, …)
    를 Qt UserRole 에 보존한다. 호출자는 ``selected_candidate()`` 로 마지막 선택을
    조회해 canonical 을 정확히 추출할 수 있다.

    사용자가 popup 에서 후보를 선택하지 않고 텍스트를 직접 편집하면 마지막 선택은
    무효화돼 ``selected_candidate()`` 가 None 을 반환한다 — 호출자가 fallback
    (텍스트 그대로 사용) 으로 자연스럽게 떨어진다.

    Read-only: 어떤 DB write 도 발생시키지 않는다.
    """

    def __init__(
        self,
        line_edit: QLineEdit,
        conn: Optional[sqlite3.Connection],
        *,
        tag_type: Optional[str] = None,
        limit: int = 20,
    ) -> None:
        self._edit = line_edit
        self._conn = conn
        self._tag_type = tag_type
        self._limit = limit
        self._last_selected = None  # type: object | None

        self._model = QStandardItemModel(line_edit)
        self._completer = QCompleter(self._model, line_edit)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        # MatchContains: 입력이 후보 안 어디든 들어 있으면 표시. SmartContains 는 PyQt 미지원.
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        line_edit.setCompleter(self._completer)

        # 사용자가 텍스트를 직접 편집하면 후보 갱신 + 이전 선택 invalidate.
        line_edit.textEdited.connect(self._on_text_edited)
        # popup 에서 후보 선택 시 metadata 보존.
        self._completer.activated[QModelIndex].connect(self._on_activated)

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_text_edited(self, text: str) -> None:
        """매 keystroke 마다 provider 를 재호출해 model 을 갱신한다."""
        # 직접 편집 = 이전 popup 선택 무효화. 사용자 의도가 다른 candidate 일 수 있다.
        self._last_selected = None

        if self._conn is None:
            return
        query = (text or "").strip()
        self._model.clear()
        if not query:
            return

        try:
            from core.autocomplete_provider import suggest_tag_completions
            candidates = suggest_tag_completions(
                self._conn, query, tag_type=self._tag_type, limit=self._limit,
            )
        except Exception:
            return

        for c in candidates:
            item = QStandardItem(c.display_text)
            item.setData(c, CANDIDATE_DATA_ROLE)
            tooltip_lines = [c.display_text]
            if c.secondary_text:
                tooltip_lines.append(c.secondary_text)
            item.setToolTip("\n".join(tooltip_lines))
            self._model.appendRow(item)

    def _on_activated(self, index: QModelIndex) -> None:
        """popup 에서 후보 클릭 / Enter — metadata 를 보존."""
        if not index.isValid():
            return
        item = self._model.itemFromIndex(index)
        if item is None:
            return
        candidate = item.data(CANDIDATE_DATA_ROLE)
        if candidate is None:
            return
        self._last_selected = candidate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_candidate(self):
        """마지막으로 popup 에서 선택된 후보의 metadata.

        텍스트가 그 후보의 ``display_text`` / ``insert_text`` 와 다르면 None 반환
        (사용자가 선택 후 텍스트를 직접 수정한 케이스 — 의도가 바뀜).
        """
        if self._last_selected is None:
            return None
        text = (self._edit.text() or "").strip()
        candidate = self._last_selected
        # display_text 또는 insert_text 와 일치할 때만 valid
        if text == getattr(candidate, "display_text", None):
            return candidate
        if text == getattr(candidate, "insert_text", None):
            return candidate
        # invalidate
        self._last_selected = None
        return None


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
        # label → canonical 역매핑 (캐릭터 자동완성 label/value 분리, fallback 용)
        self._char_label_to_canonical: dict[str, str] = {}
        # 다국어 자동완성 controller (series / character 각각).
        # 사용자가 ko/ja/en 입력 시 후보 popup + 선택 시 canonical metadata 보존.
        self._series_autocomplete: Optional[_AutocompleteController] = None
        self._character_autocomplete: Optional[_AutocompleteController] = None

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

        # _load_character_labels 의 label → canonical dict 는 fallback 경로 (popup
        # 미선택 + "X (Y)" 형식 직접 입력) 와 기존 회귀 테스트 호환을 위해 유지한다.
        _, self._char_label_to_canonical = _load_character_labels(self._conn)

        self._series_edit = QLineEdit()
        self._series_edit.setPlaceholderText("예: Blue Archive / 블루 아카이브 / ブルーアーカイブ")
        # 다국어 provider 기반 동적 자동완성 (ko / ja / en localized_name + alias + canonical).
        self._series_autocomplete = _AutocompleteController(
            self._series_edit, self._conn, tag_type="series",
        )
        override_form.addRow("시리즈 이름:", self._series_edit)

        self._char_edit = QLineEdit()
        self._char_edit.setPlaceholderText("예: 伊落マリー / 이오치 마리 / Itoraku Mari")
        self._character_autocomplete = _AutocompleteController(
            self._char_edit, self._conn, tag_type="character",
        )
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

        호출 전 ``_resolve_canonical_from_autocomplete`` 가 우선 시도된다.
        이 함수는 controller selection 이 없을 때의 fallback 경로다.
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

    def _resolve_canonical_from_autocomplete(
        self, controller: Optional[_AutocompleteController]
    ) -> Optional[str]:
        """controller 의 마지막 선택이 valid 하면 그 candidate 의 canonical 반환.

        - 사용자가 popup 에서 후보를 선택했고
        - LineEdit 텍스트가 그 후보의 display/insert text 와 일치할 때만 valid
        - 그 외에는 None — 호출자가 텍스트 기반 fallback 경로를 사용해야 한다
        """
        if controller is None:
            return None
        candidate = controller.selected_candidate()
        if candidate is None:
            return None
        canonical = getattr(candidate, "canonical", None)
        if not canonical:
            return None
        return str(canonical).strip() or None

    def _on_ok(self) -> None:
        # 자동완성 선택이 있으면 candidate 의 canonical 우선 (한국어/일본어 입력 시
        # display 가 canonical 과 다를 수 있으므로 텍스트 그대로 쓰면 잘못된 canonical
        # 이 저장됨 — 예: "블루 아카이브" → canonical "Blue Archive").
        series_from_pick = self._resolve_canonical_from_autocomplete(self._series_autocomplete)
        character_from_pick = self._resolve_canonical_from_autocomplete(self._character_autocomplete)

        series_text = self._series_edit.text().strip()
        char_text   = self._char_edit.text().strip()
        series      = series_from_pick if series_from_pick else series_text
        character   = character_from_pick if character_from_pick else self._resolve_character_canonical(char_text)
        locale      = self._locale_edit.text().strip() or "canonical"
        reason      = self._reason_edit.text().strip() or None

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
