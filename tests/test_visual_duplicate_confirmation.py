"""
시각적 중복 검사 실행 전 확인 다이얼로그 테스트.

- config confirm_visual_scan 기본값이 True인지
- get_duplicate_check_summary가 db_file_count와 unindexed_count를 반환하는지
"""
from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

from core.config_manager import _DEFAULTS
from core.duplicate_finder import get_duplicate_check_summary
from db.database import initialize_database


def _make_db() -> sqlite3.Connection:
    return initialize_database(":memory:")


def _insert_original(conn: sqlite3.Connection, file_path: str) -> None:
    group_id = str(uuid.uuid4())
    file_id  = str(uuid.uuid4())
    now = "2024-01-01T00:00:00"
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artwork_title, artwork_kind,
            total_pages, downloaded_at, indexed_at, status, metadata_sync_status,
            tags_json, schema_version)
           VALUES (?, 'local', ?, 'Test', 'single_image', 1, ?, ?, 'inbox', 'pending', '[]', '1.0')""",
        (group_id, group_id[:16], now, now),
    )
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_status, created_at)
           VALUES (?, ?, 0, 'original', ?, 'jpg', 'present', ?)""",
        (file_id, group_id, file_path, now),
    )
    conn.commit()


class TestConfigDefaults:
    def test_confirm_visual_scan_defaults_to_true(self):
        dup_defaults = _DEFAULTS.get("duplicates", {})
        assert dup_defaults.get("confirm_visual_scan") is True

    def test_max_visual_files_per_run_default_is_300(self):
        dup_defaults = _DEFAULTS.get("duplicates", {})
        assert dup_defaults.get("max_visual_files_per_run") == 300


class TestVisualScanSummary:
    def test_returns_db_count_and_unindexed_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            f1 = inbox / "a.jpg"
            f2 = inbox / "b.jpg"  # unindexed
            f1.write_bytes(b"x")
            f2.write_bytes(b"y")

            conn = _make_db()
            _insert_original(conn, str(f1))

            summary = get_duplicate_check_summary(conn, tmp, scope="inbox_managed")
            assert summary["db_file_count"] == 1
            assert summary["unindexed_count"] == 1
            assert summary["scope"] == "inbox_managed"

    def test_no_inbox_dir_skips_unindexed(self):
        conn = _make_db()
        summary = get_duplicate_check_summary(conn, "", scope="inbox_managed")
        assert summary["unindexed_count"] == 0
        assert summary["unindexed_files"] == []
