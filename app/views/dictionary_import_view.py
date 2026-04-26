"""
외부 사전 후보 가져오기 다이얼로그.

Danbooru 등 외부 소스에서 series/character 후보를 수집하고
사용자 승인 후 tag_aliases / tag_localizations로 승격한다.

자동 확정 금지 — 모든 승격은 사용자 승인 기반.
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

_SOURCE_OPTIONS = [("danbooru", "Danbooru"), ("safebooru", "Safebooru")]

_COLS = [
    "source", "danbooru_tag", "tag_type", "parent_series",
    "alias", "canonical", "locale", "display_name",
    "confidence", "status",
]
_COL_LABELS = [
    "소스", "외부 태그", "타입", "시리즈",
    "alias", "canonical", "locale", "표시명",
    "신뢰도", "상태",
]


# ---------------------------------------------------------------------------
# 백그라운드 스레드
# ---------------------------------------------------------------------------

class _FetchThread(QThread):
    done    = Signal(list)   # list[dict]
    err_msg = Signal(str)

    def __init__(
        self,
        conn_factory,
        source: str,
        series_query: str,
        char_query: str,
        fallback_to_safebooru: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._factory      = conn_factory
        self._source       = source
        self._series_query = series_query
        self._char_query   = char_query
        self._fallback     = fallback_to_safebooru

    def _create_adapter(self, source: str):
        if source == "safebooru":
            from core.dictionary_sources.safebooru_source import SafebooruSourceAdapter
            return SafebooruSourceAdapter()
        from core.dictionary_sources.danbooru_source import DanbooruSourceAdapter
        return DanbooruSourceAdapter()

    def _fetch_from(self, adapter, series_slug: str) -> list[dict]:
        if self._char_query:
            return adapter.fetch_character_candidates(series_slug, self._char_query)
        return (
            adapter.fetch_character_candidates(series_slug)
            + adapter.fetch_series_candidates(self._series_query)
        )

    def run(self) -> None:
        try:
            series_slug = self._series_query.lower().replace(" ", "_")
            candidates: list[dict] = []

            adapter = self._create_adapter(self._source)
            try:
                candidates = self._fetch_from(adapter, series_slug)
            except Exception as primary_exc:
                if self._source == "danbooru" and self._fallback:
                    self.err_msg.emit(
                        f"Danbooru 오류, Safebooru로 재시도합니다: {primary_exc}"
                    )
                    try:
                        fallback = self._create_adapter("safebooru")
                        candidates = self._fetch_from(fallback, series_slug)
                    except Exception as fallback_exc:
                        raise fallback_exc from primary_exc
                else:
                    raise

            from core.external_dictionary import import_external_entries
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            entries = [{**c, "imported_at": now} for c in candidates]
            conn = self._factory()
            try:
                import_external_entries(conn, entries)
            finally:
                conn.close()

            self.done.emit(candidates)
        except Exception as exc:
            logger.error("사전 후보 수집 오류: %s", exc)
            self.err_msg.emit(
                f"후보 수집에 실패했습니다.\n\n"
                f"가능한 원인:\n"
                f"  - 네트워크 오류\n"
                f"  - 사이트 접속 제한\n"
                f"  - timeout\n"
                f"  - API 응답 형식 변경\n\n"
                f"Aru Archive는 기존 로컬 사전과 Pixiv 관측 데이터를 계속 사용합니다.\n"
                f"오류: {exc}"
            )
            self.done.emit([])


class _AcceptThread(QThread):
    done    = Signal(int)   # 승인된 수
    err_msg = Signal(str)

    def __init__(
        self,
        conn_factory,
        entry_ids: list[str],
        retag_group_ids: list[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._factory       = conn_factory
        self._entry_ids     = entry_ids
        self._retag_ids     = retag_group_ids

    def run(self) -> None:
        from core.external_dictionary import accept_external_entry
        conn = self._factory()
        accepted = 0
        try:
            for eid in self._entry_ids:
                try:
                    accept_external_entry(conn, eid)
                    accepted += 1
                except Exception as exc:
                    logger.warning("승인 실패 (%s): %s", eid, exc)
            if self._retag_ids:
                from core.tag_reclassifier import retag_groups_from_existing_tags
                retag_groups_from_existing_tags(conn, self._retag_ids)
        finally:
            conn.close()
        self.done.emit(accepted)


# ---------------------------------------------------------------------------
# 메인 다이얼로그
# ---------------------------------------------------------------------------

class DictionaryImportView(QDialog):
    """외부 사전 후보 수집 · 검토 · 승인 다이얼로그."""

    log_msg = Signal(str)

    def __init__(
        self,
        conn_factory,
        *,
        current_group_ids: Optional[list[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._factory    = conn_factory
        self._group_ids  = current_group_ids or []
        self._fetch_thread:  Optional[_FetchThread]  = None
        self._accept_thread: Optional[_AcceptThread] = None
        self._staged_entries: list[dict] = []

        self.setWindowTitle("🌐 외부 사전 후보 가져오기")
        self.setMinimumSize(960, 580)
        self.resize(1080, 640)
        self._build_ui()
        self._load_staged()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── 검색 행 ──
        search_row = QHBoxLayout()

        search_row.addWidget(QLabel("소스:"))
        self._source_combo = QComboBox()
        for val, label in _SOURCE_OPTIONS:
            self._source_combo.addItem(label, val)
        search_row.addWidget(self._source_combo)

        search_row.addSpacing(12)
        search_row.addWidget(QLabel("시리즈:"))
        self._series_input = QLineEdit()
        self._series_input.setPlaceholderText("예: Blue Archive")
        self._series_input.setFixedWidth(180)
        search_row.addWidget(self._series_input)

        search_row.addSpacing(12)
        search_row.addWidget(QLabel("캐릭터 검색:"))
        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("비워두면 시리즈 전체")
        self._query_input.setFixedWidth(160)
        search_row.addWidget(self._query_input)

        search_row.addSpacing(12)
        self._btn_fetch = QPushButton("🔍 후보 수집")
        self._btn_fetch.clicked.connect(self._on_fetch)
        search_row.addWidget(self._btn_fetch)

        search_row.addSpacing(16)
        self._fallback_checkbox = QCheckBox("Danbooru 실패 시 Safebooru로 재시도")
        search_row.addWidget(self._fallback_checkbox)
        search_row.addStretch()
        root.addLayout(search_row)

        # ── 필터 행 ──
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("상태 필터:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(["staged", "accepted", "rejected", "ignored", "all"])
        self._status_filter.currentTextChanged.connect(self._load_staged)
        filter_row.addWidget(self._status_filter)

        filter_row.addSpacing(12)
        filter_row.addWidget(QLabel("타입 필터:"))
        self._type_filter = QComboBox()
        self._type_filter.addItems(["all", "series", "character", "general"])
        self._type_filter.currentTextChanged.connect(self._load_staged)
        filter_row.addWidget(self._type_filter)

        filter_row.addSpacing(12)
        filter_row.addWidget(QLabel("최소 신뢰도:"))
        self._min_conf = QDoubleSpinBox()
        self._min_conf.setRange(0.0, 1.0)
        self._min_conf.setSingleStep(0.05)
        self._min_conf.setValue(0.0)
        self._min_conf.setDecimals(2)
        self._min_conf.setFixedWidth(70)
        self._min_conf.valueChanged.connect(self._load_staged)
        filter_row.addWidget(self._min_conf)

        filter_row.addStretch()
        root.addLayout(filter_row)

        # ── 일괄 선택 행 ──
        bulk_row = QHBoxLayout()
        self._bulk_threshold = QDoubleSpinBox()
        self._bulk_threshold.setRange(0.0, 1.0)
        self._bulk_threshold.setSingleStep(0.05)
        self._bulk_threshold.setValue(0.85)
        self._bulk_threshold.setDecimals(2)
        self._bulk_threshold.setFixedWidth(70)
        self._btn_bulk_select = QPushButton("신뢰도 이상 선택")
        self._btn_bulk_select.clicked.connect(self._on_bulk_select)
        bulk_row.addWidget(QLabel("신뢰도"))
        bulk_row.addWidget(self._bulk_threshold)
        bulk_row.addWidget(self._btn_bulk_select)

        self._retag_checkbox = QCheckBox("승인 후 현재 목록 태그 재분류 실행")
        self._retag_checkbox.setChecked(True)
        bulk_row.addSpacing(20)
        bulk_row.addWidget(self._retag_checkbox)
        bulk_row.addStretch()
        root.addLayout(bulk_row)

        # ── 테이블 ──
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COL_LABELS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#1A0F14; color:#D8AEBB; "
            "alternate-background-color:#211018; border:1px solid #4A2030; }"
        )
        root.addWidget(self._table, 1)

        # ── 버튼 행 ──
        btn_row = QHBoxLayout()
        self._btn_accept = QPushButton("✅ 선택 승인")
        self._btn_merge  = QPushButton("🔀 기존 canonical에 병합 승인")
        self._btn_reject = QPushButton("❌ 선택 거부")
        self._btn_ignore = QPushButton("⏭ 선택 무시")
        self._btn_accept.clicked.connect(self._on_accept)
        self._btn_merge .clicked.connect(self._on_merge)
        self._btn_reject.clicked.connect(self._on_reject)
        self._btn_ignore.clicked.connect(self._on_ignore)
        for btn in (self._btn_accept, self._btn_merge, self._btn_reject, self._btn_ignore):
            btn_row.addWidget(btn)
        btn_row.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btn_row.addWidget(btns)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # 데이터 로드
    # ------------------------------------------------------------------

    def _load_staged(self) -> None:
        from core.external_dictionary import list_external_entries
        status_val = self._status_filter.currentText()
        type_val   = self._type_filter.currentText()
        min_conf   = self._min_conf.value()

        conn = self._factory()
        try:
            rows = list_external_entries(
                conn,
                status=None if status_val == "all" else status_val,
                tag_type=None if type_val == "all" else type_val,
                min_confidence=min_conf if min_conf > 0 else None,
            )
        finally:
            conn.close()

        self._staged_entries = rows
        self._populate_table(rows)

    def _populate_table(self, rows: list[dict]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            vals = [
                row.get("source", ""),
                row.get("danbooru_tag", ""),
                row.get("tag_type", ""),
                row.get("parent_series", ""),
                row.get("alias", ""),
                row.get("canonical", ""),
                row.get("locale", ""),
                row.get("display_name", ""),
                f"{row.get('confidence_score', 0):.2f}",
                row.get("status", ""),
            ]
            for c_idx, val in enumerate(vals):
                item = QTableWidgetItem(val or "")
                item.setData(Qt.ItemDataRole.UserRole, row.get("entry_id", ""))
                self._table.setItem(r_idx, c_idx, item)
        self._table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # 후보 수집
    # ------------------------------------------------------------------

    def _on_fetch(self) -> None:
        if self._fetch_thread and self._fetch_thread.isRunning():
            return
        series = self._series_input.text().strip()
        if not series:
            QMessageBox.warning(self, "입력 필요", "시리즈 이름을 입력하세요.")
            return
        self._btn_fetch.setEnabled(False)
        self._btn_fetch.setText("수집 중…")
        query = self._query_input.text().strip()
        source = self._source_combo.currentData()
        self._fetch_thread = _FetchThread(
            self._factory, source, series, query,
            fallback_to_safebooru=self._fallback_checkbox.isChecked(),
            parent=self,
        )
        self._fetch_thread.done   .connect(self._on_fetch_done)
        self._fetch_thread.err_msg.connect(lambda m: self.log_msg.emit(f"[ERROR] {m}"))
        self._fetch_thread.start()

    def _on_fetch_done(self, candidates: list[dict]) -> None:
        self._btn_fetch.setEnabled(True)
        self._btn_fetch.setText("🔍 후보 수집")
        self.log_msg.emit(f"[INFO] 사전 후보 {len(candidates)}건 수집 완료")
        self._load_staged()

    # ------------------------------------------------------------------
    # 선택 헬퍼
    # ------------------------------------------------------------------

    def _selected_entry_ids(self) -> list[str]:
        seen: set[str] = set()
        ids: list[str] = []
        for item in self._table.selectedItems():
            eid = item.data(Qt.ItemDataRole.UserRole)
            if eid and eid not in seen:
                seen.add(eid)
                ids.append(eid)
        return ids

    def _on_bulk_select(self) -> None:
        threshold = self._bulk_threshold.value()
        self._table.clearSelection()
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 8)  # confidence column
            if item:
                try:
                    if float(item.text()) >= threshold:
                        self._table.selectRow(r)
                except ValueError:
                    pass

    # ------------------------------------------------------------------
    # 승인 / 거부 / 무시
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        entry_ids = self._selected_entry_ids()
        if not entry_ids:
            QMessageBox.warning(self, "선택 없음", "승인할 항목을 선택하세요.")
            return
        retag_ids = self._group_ids if self._retag_checkbox.isChecked() else []
        self._btn_accept.setEnabled(False)
        self._accept_thread = _AcceptThread(
            self._factory, entry_ids, retag_ids, self
        )
        self._accept_thread.done   .connect(self._on_accept_done)
        self._accept_thread.err_msg.connect(lambda m: self.log_msg.emit(f"[ERROR] {m}"))
        self._accept_thread.start()

    def _on_accept_done(self, count: int) -> None:
        self._btn_accept.setEnabled(True)
        self.log_msg.emit(f"[INFO] 사전 후보 {count}건 승인 완료")
        self._load_staged()

    def _on_merge(self) -> None:
        entry_ids = self._selected_entry_ids()
        if not entry_ids:
            QMessageBox.warning(self, "선택 없음", "병합할 항목을 선택하세요.")
            return
        if len(entry_ids) > 1:
            QMessageBox.warning(
                self, "단일 선택 필요",
                "기존 canonical 병합은 한 번에 항목 1개만 처리 가능합니다.",
            )
            return
        entry_id = entry_ids[0]
        conn = self._factory()
        try:
            row = conn.execute(
                "SELECT * FROM external_dictionary_entries WHERE entry_id=?",
                (entry_id,),
            ).fetchone()
            if not row:
                return
            from core.tag_merge import list_existing_canonicals
            from app.views.canonical_merge_dialog import CanonicalMergeDialog
            canonicals = list_existing_canonicals(conn, tag_type=row["tag_type"])
            if not canonicals:
                QMessageBox.information(
                    self, "canonical 없음",
                    f"'{row['tag_type']}' 타입의 기존 canonical이 없습니다.\n"
                    "먼저 다른 항목을 승인하거나 태그 팩을 로드하세요.",
                )
                return
            dlg = CanonicalMergeDialog(
                canonicals,
                raw_tag=row.get("alias") or row.get("danbooru_tag") or "",
                parent=self,
            )
            if dlg.exec() != CanonicalMergeDialog.DialogCode.Accepted:
                return
            chosen = dlg.selected_canonical()
            if not chosen:
                return
            from core.external_dictionary import accept_external_entry_with_override_canonical
            accept_external_entry_with_override_canonical(
                conn,
                entry_id,
                chosen["canonical"],
                chosen["tag_type"],
                chosen.get("parent_series", ""),
            )
            self.log_msg.emit(
                f"[INFO] 사전 후보 병합 승인: {row.get('alias')} → {chosen['canonical']}"
            )
        except Exception as exc:
            logger.error("사전 후보 병합 오류: %s", exc)
            QMessageBox.critical(self, "오류", str(exc))
        finally:
            conn.close()
        self._load_staged()

    def _on_reject(self) -> None:
        from core.external_dictionary import reject_external_entry
        entry_ids = self._selected_entry_ids()
        if not entry_ids:
            QMessageBox.warning(self, "선택 없음", "거부할 항목을 선택하세요.")
            return
        conn = self._factory()
        try:
            for eid in entry_ids:
                try:
                    reject_external_entry(conn, eid)
                except Exception as exc:
                    logger.warning("거부 실패 (%s): %s", eid, exc)
        finally:
            conn.close()
        self.log_msg.emit(f"[INFO] 사전 후보 {len(entry_ids)}건 거부")
        self._load_staged()

    def _on_ignore(self) -> None:
        from core.external_dictionary import ignore_external_entry
        entry_ids = self._selected_entry_ids()
        if not entry_ids:
            QMessageBox.warning(self, "선택 없음", "무시할 항목을 선택하세요.")
            return
        conn = self._factory()
        try:
            for eid in entry_ids:
                try:
                    ignore_external_entry(conn, eid)
                except Exception as exc:
                    logger.warning("무시 실패 (%s): %s", eid, exc)
        finally:
            conn.close()
        self.log_msg.emit(f"[INFO] 사전 후보 {len(entry_ids)}건 무시")
        self._load_staged()
