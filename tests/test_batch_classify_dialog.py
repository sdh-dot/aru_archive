"""tests/test_batch_classify_dialog.py — BatchClassifyDialog GUI 스모크 테스트."""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton

from app.views.batch_classify_dialog import BatchClassifyDialog


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE artwork_groups (
            group_id TEXT PRIMARY KEY,
            metadata_sync_status TEXT DEFAULT 'full',
            indexed_at TEXT DEFAULT '2024-01-01T00:00:00+00:00'
        );
        CREATE TABLE tag_localizations (
            localization_id TEXT PRIMARY KEY,
            canonical       TEXT NOT NULL,
            tag_type        TEXT NOT NULL,
            parent_series   TEXT NOT NULL DEFAULT '',
            locale          TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            sort_name       TEXT,
            source          TEXT,
            enabled         INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT,
            UNIQUE(canonical, tag_type, parent_series, locale)
        );
    """)
    yield conn
    conn.close()


@pytest.fixture
def dialog(qapp, mem_db, tmp_path):
    classified = tmp_path / "Classified"
    classified.mkdir()
    config = {
        "classified_dir": str(classified),
        "classification": {"folder_locale": "ko"},
    }

    def _factory():
        return sqlite3.connect(":memory:")

    dlg = BatchClassifyDialog(
        _factory,
        config,
        selected_group_ids=[],
        current_filter_group_ids=[],
    )
    yield dlg
    dlg.close()


# ---------------------------------------------------------------------------
# 스모크 테스트
# ---------------------------------------------------------------------------

def test_dialog_creates_without_error(dialog):
    assert dialog is not None


def test_dialog_has_scope_combo(dialog):
    combos = dialog.findChildren(QComboBox)
    assert len(combos) >= 1


def test_dialog_scope_combo_has_options(dialog):
    # 첫 번째 콤보박스 = scope combo
    scope_combo = dialog._scope_combo
    assert scope_combo.count() == 3  # selected, current_filter, all_classifiable


def test_dialog_has_locale_combo(dialog):
    locale_combo = dialog._locale_combo
    assert locale_combo.count() == 4  # canonical, ko, ja, en


def test_dialog_has_policy_combo(dialog):
    policy_combo = dialog._policy_combo
    assert policy_combo.count() == 2  # keep_existing, skip_existing


def test_preview_button_exists(dialog):
    assert hasattr(dialog, "_btn_preview")
    assert dialog._btn_preview is not None


def test_execute_button_exists_and_disabled(dialog):
    assert hasattr(dialog, "_btn_execute")
    assert not dialog._btn_execute.isEnabled()


def test_dialog_signals_exist(dialog):
    # batch_done, log_msg 시그널이 접근 가능한지 확인
    assert hasattr(dialog, "batch_done")
    assert hasattr(dialog, "log_msg")


def test_build_config_snapshot(dialog):
    snapshot = dialog._build_config_snapshot()
    assert "classification" in snapshot
    cls = snapshot["classification"]
    assert "folder_locale" in cls
    assert "on_conflict" in cls


def test_scope_default_is_current_filter(dialog):
    # 기본 scope = current_filter (index 1)
    assert dialog._scope_combo.currentData() == "current_filter"
