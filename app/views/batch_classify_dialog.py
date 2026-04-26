"""
일괄 분류 다이얼로그.

선택 범위:
  selected        – 갤러리에서 선택된 항목
  current_filter  – 현재 필터 표시 중인 항목
  all_classifiable – DB 전체 분류 가능 항목

폴더명 언어:
  canonical / 한국어(ko) / 일본어(ja) / 영어(en)

기존 복사본 처리:
  keep_existing  – 기존 복사본 유지, 새 경로에 추가 복사 가능
  skip_existing  – 같은 목적지 파일이 있으면 skip

흐름:
  1. 파라미터 설정
  2. [미리보기 생성] → 요약 + 목록 표시
  3. [실행] → batch execute → WorkLog에 반영
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from core.batch_classifier import (
    build_classify_batch_preview,
    collect_classifiable_group_ids,
    execute_classify_batch,
)

_LOCALE_OPTIONS = [
    ("canonical", "canonical (변경 없음)"),
    ("ko", "한국어"),
    ("ja", "일본어"),
    ("en", "영어"),
]

_SCOPE_OPTIONS = [
    ("selected",        "선택 항목"),
    ("current_filter",  "현재 목록 전체"),
    ("all_classifiable","전체 분류 가능 항목"),
]

_POLICY_OPTIONS = [
    ("keep_existing", "기존 복사본 유지 (새 경로에 추가 복사)"),
    ("skip_existing", "같은 목적지 파일 skip"),
]


def _fmt_size(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / (1024 ** 3):.1f} GB"
    if b >= 1024 ** 2:
        return f"{b / (1024 ** 2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


# ---------------------------------------------------------------------------
# 백그라운드 스레드
# ---------------------------------------------------------------------------

class _PreviewThread(QThread):
    done    = Signal(dict)
    log_msg = Signal(str)

    def __init__(self, conn_factory, group_ids, config, parent=None):
        super().__init__(parent)
        self._factory   = conn_factory
        self._group_ids = group_ids
        self._config    = config

    def run(self):
        conn = self._factory()
        try:
            result = build_classify_batch_preview(conn, self._group_ids, self._config)
            self.done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 미리보기 실패: {exc}")
            self.done.emit({})
        finally:
            conn.close()


class _ExecuteThread(QThread):
    done    = Signal(dict)
    log_msg = Signal(str)

    def __init__(self, conn_factory, batch_preview, config, parent=None):
        super().__init__(parent)
        self._factory       = conn_factory
        self._batch_preview = batch_preview
        self._config        = config

    def run(self):
        conn = self._factory()
        try:
            result = execute_classify_batch(conn, self._batch_preview, self._config)
            self.done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 실행 실패: {exc}")
            self.done.emit({"success": False, "error": str(exc)})
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 다이얼로그
# ---------------------------------------------------------------------------

class BatchClassifyDialog(QDialog):
    """
    일괄 분류 미리보기 및 실행 다이얼로그.

    Signals:
        batch_done(dict): 실행 완료 결과. MainWindow에서 갤러리 갱신에 사용.
        log_msg(str):     MainWindow LogPanel에 전달할 메시지.
    """

    batch_done = Signal(dict)
    log_msg    = Signal(str)

    def __init__(
        self,
        conn_factory,                         # () -> sqlite3.Connection
        config: dict,
        *,
        selected_group_ids: Optional[list[str]] = None,
        current_filter_group_ids: Optional[list[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conn_factory             = conn_factory
        self._config                   = config
        self._selected_group_ids       = selected_group_ids or []
        self._current_filter_group_ids = current_filter_group_ids or []
        self._batch_preview: Optional[dict] = None
        self._preview_thread: Optional[_PreviewThread] = None
        self._execute_thread: Optional[_ExecuteThread] = None

        self.setWindowTitle("일괄 분류")
        self.setMinimumSize(800, 580)
        self.resize(900, 640)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── 설정 행 ──────────────────────────────────────────────────
        settings_row = QHBoxLayout()

        settings_row.addWidget(QLabel("대상 범위:"))
        self._scope_combo = QComboBox()
        for val, label in _SCOPE_OPTIONS:
            self._scope_combo.addItem(label, val)
        self._scope_combo.setCurrentIndex(1)  # current_filter default
        settings_row.addWidget(self._scope_combo)

        settings_row.addSpacing(16)
        settings_row.addWidget(QLabel("폴더명 언어:"))
        self._locale_combo = QComboBox()
        for val, label in _LOCALE_OPTIONS:
            self._locale_combo.addItem(label, val)
        cfg_locale = self._config.get("classification", {}).get("folder_locale", "ko")
        for i, (val, _) in enumerate(_LOCALE_OPTIONS):
            if val == cfg_locale:
                self._locale_combo.setCurrentIndex(i)
                break
        settings_row.addWidget(self._locale_combo)

        settings_row.addSpacing(16)
        settings_row.addWidget(QLabel("기존 복사본:"))
        self._policy_combo = QComboBox()
        for val, label in _POLICY_OPTIONS:
            self._policy_combo.addItem(label, val)
        settings_row.addWidget(self._policy_combo)

        settings_row.addStretch()
        layout.addLayout(settings_row)

        # ── 재분류 옵션 행 ─────────────────────────────────────────────
        retag_row = QHBoxLayout()
        retag_default = self._config.get("classification", {}).get(
            "retag_before_batch_preview", False
        )
        self._retag_checkbox = QCheckBox("미리보기 생성 전 태그 재분류 실행")
        self._retag_checkbox.setChecked(bool(retag_default))
        retag_row.addWidget(self._retag_checkbox)
        retag_row.addStretch()
        self._btn_preview = QPushButton("미리보기 생성")
        self._btn_preview.clicked.connect(self._on_preview)
        retag_row.addWidget(self._btn_preview)
        layout.addLayout(retag_row)

        # ── 요약 ─────────────────────────────────────────────────────
        self._summary_lbl = QLabel("미리보기를 생성하세요.")
        self._summary_lbl.setStyleSheet("font-size: 11px; color: #D8AEBB;")
        layout.addWidget(self._summary_lbl)

        # ── 경고 ─────────────────────────────────────────────────────
        self._warn_text = QTextEdit()
        self._warn_text.setReadOnly(True)
        self._warn_text.setFixedHeight(48)
        self._warn_text.setStyleSheet(
            "QTextEdit { background: #1A0F14; color: #ffc107; "
            "font-size: 10px; border: 1px solid #4A2030; }"
        )
        self._warn_text.hide()
        layout.addWidget(self._warn_text)

        # ── 목록 ─────────────────────────────────────────────────────
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["제목", "상태", "rule type", "목적지 경로", "경고"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background: #1A0F14; color: #D8AEBB; "
            "alternate-background-color: #211018; border: 1px solid #4A2030; }"
        )
        layout.addWidget(self._table, 1)

        # ── 진행 바 ──────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        layout.addWidget(self._progress)

        # ── 버튼 ─────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._btn_execute = QPushButton("▶ 실행")
        self._btn_execute.setEnabled(False)
        self._btn_execute.clicked.connect(self._on_execute)
        btns.addButton(self._btn_execute, QDialogButtonBox.ButtonRole.ActionRole)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    # 미리보기
    # ------------------------------------------------------------------

    def _build_config_snapshot(self) -> dict:
        """현재 UI 설정을 config에 반영한 사본 반환."""
        cfg = dict(self._config)
        cls = dict(cfg.get("classification", {}))
        cls["folder_locale"]              = self._locale_combo.currentData()
        cls["on_conflict"]                = (
            "skip" if self._policy_combo.currentData() == "skip_existing" else "rename"
        )
        cls["retag_before_batch_preview"] = self._retag_checkbox.isChecked()
        cfg["classification"] = cls
        return cfg

    def _collect_ids(self) -> list[str]:
        scope = self._scope_combo.currentData()
        conn = self._conn_factory()
        try:
            result = collect_classifiable_group_ids(
                conn, scope,
                selected_group_ids=self._selected_group_ids,
                current_filter_group_ids=self._current_filter_group_ids,
                classified_dir=self._config.get("classified_dir", ""),
            )
        finally:
            conn.close()
        return result["included_group_ids"]

    def _on_preview(self) -> None:
        if self._preview_thread and self._preview_thread.isRunning():
            return
        self._btn_preview.setEnabled(False)
        self._btn_execute.setEnabled(False)
        self._progress.show()

        group_ids = self._collect_ids()
        if not group_ids:
            self._summary_lbl.setText("분류 가능한 항목이 없습니다.")
            self._progress.hide()
            self._btn_preview.setEnabled(True)
            return

        config = self._build_config_snapshot()
        self._preview_thread = _PreviewThread(self._conn_factory, group_ids, config, self)
        self._preview_thread.done   .connect(self._on_preview_done)
        self._preview_thread.log_msg.connect(self.log_msg)
        self._preview_thread.start()

    def _on_preview_done(self, result: dict) -> None:
        self._progress.hide()
        self._btn_preview.setEnabled(True)
        if not result:
            return

        self._batch_preview = result

        total        = result.get("total_groups", 0)
        cls_ok       = result.get("classifiable_groups", 0)
        excl         = result.get("excluded_groups", 0)
        copies       = result.get("estimated_copies", 0)
        size         = _fmt_size(result.get("estimated_bytes", 0))
        locale       = result.get("folder_locale", "canonical")
        s_uncat      = result.get("series_uncategorized_count", 0)
        a_fallback   = result.get("author_fallback_count", 0)
        cand_count   = result.get("candidate_count", 0)

        summary = (
            f"대상: {total}개 작품   분류 가능: {cls_ok}개   제외: {excl}개   "
            f"예상 복사본: {copies}개   예상 용량: {size}   언어: {locale}"
        )
        if s_uncat or a_fallback:
            summary += (
                f"   ⚠ 미분류: series_uncategorized={s_uncat} / "
                f"author_fallback={a_fallback}"
            )
        if cand_count:
            summary += f"   후보 생성: {cand_count}건"
        self._summary_lbl.setText(summary)

        warnings = result.get("warnings", [])
        if warnings:
            self._warn_text.setPlainText("\n".join(f"⚠ {w}" for w in warnings))
            self._warn_text.show()
        else:
            self._warn_text.hide()

        self._populate_table(result.get("previews", []))

        self._btn_execute.setEnabled(copies > 0)

    def _populate_table(self, previews: list[dict]) -> None:
        self._table.setRowCount(0)
        for p in previews:
            title = p.get("source_path", "").split("/")[-1].split("\\")[-1]
            ci = p.get("classification_info")
            ci_warn = ""
            if ci:
                reason = ci.get("classification_reason", "")
                if reason == "series_detected_but_character_missing":
                    ci_warn = f"series_uncategorized ({ci.get('series_context', '')})"
                elif reason == "series_and_character_missing":
                    ci_warn = "author_fallback"
            for dest in p.get("destinations", []):
                row = self._table.rowCount()
                self._table.insertRow(row)
                self._table.setItem(row, 0, QTableWidgetItem(title))
                self._table.setItem(row, 1, QTableWidgetItem(
                    "✓" if dest.get("will_copy") else "✗"
                ))
                self._table.setItem(row, 2, QTableWidgetItem(dest.get("rule_type", "")))
                self._table.setItem(row, 3, QTableWidgetItem(dest.get("dest_path", "")))
                warn_parts = []
                if dest.get("used_fallback"):
                    warn_parts.append("fallback")
                if dest.get("conflict") not in (None, "none", ""):
                    warn_parts.append(dest["conflict"])
                if ci_warn:
                    warn_parts.append(ci_warn)
                self._table.setItem(row, 4, QTableWidgetItem(", ".join(warn_parts)))

    # ------------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------------

    def _on_execute(self) -> None:
        if not self._batch_preview:
            return
        if self._execute_thread and self._execute_thread.isRunning():
            return

        self._btn_execute.setEnabled(False)
        self._btn_preview.setEnabled(False)
        self._progress.show()

        config = self._build_config_snapshot()
        self._execute_thread = _ExecuteThread(
            self._conn_factory, self._batch_preview, config, self
        )
        self._execute_thread.done   .connect(self._on_execute_done)
        self._execute_thread.log_msg.connect(self.log_msg)
        self._execute_thread.start()

    def _on_execute_done(self, result: dict) -> None:
        self._progress.hide()
        self._btn_preview.setEnabled(True)
        self.batch_done.emit(result)

        copied  = result.get("copied", 0)
        skipped = result.get("skipped", 0)
        failed  = result.get("failed_groups", 0)

        if result.get("success"):
            self.log_msg.emit(
                f"[INFO] 일괄 분류 완료: {copied}개 복사, "
                f"{skipped}개 건너뜀, {failed}개 그룹 오류"
            )
        else:
            self.log_msg.emit(f"[ERROR] 일괄 분류 실패: {result.get('error', '')}")
