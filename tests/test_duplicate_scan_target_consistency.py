"""
중복 검사 대상 일관성 테스트.

- Explorer에 존재하지만 DB에 없는 Inbox 파일을 unindexed로 보고
- get_duplicate_check_summary가 올바른 수치를 반환하는지 검증
"""
from __future__ import annotations

import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

from core.duplicate_finder import find_unindexed_inbox_files, get_duplicate_check_summary
from db.database import initialize_database


def _make_db() -> sqlite3.Connection:
    conn = initialize_database(":memory:")
    return conn


def _insert_file(conn: sqlite3.Connection, file_path: str, role: str = "original") -> None:
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
           VALUES (?, ?, 0, ?, ?, 'jpg', 'present', ?)""",
        (file_id, group_id, role, file_path, now),
    )
    conn.commit()


class TestFindUnindexedInboxFiles:
    def test_empty_inbox_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_db()
            result = find_unindexed_inbox_files(conn, tmp)
            assert result == []

    def test_all_registered_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            f1 = inbox / "file1.jpg"
            f1.write_bytes(b"data1")
            conn = _make_db()
            _insert_file(conn, str(f1))
            result = find_unindexed_inbox_files(conn, tmp)
            assert result == []

    def test_unregistered_file_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            f1 = inbox / "registered.jpg"
            f2 = inbox / "unregistered.jpg"
            f1.write_bytes(b"data1")
            f2.write_bytes(b"data2")
            conn = _make_db()
            _insert_file(conn, str(f1))
            result = find_unindexed_inbox_files(conn, tmp)
            assert len(result) == 1
            assert result[0] == f2

    def test_windows_duplicate_suffix_detected_as_unindexed(self):
        """
        143243673_p0_master1200 (1).jpg 같이 Windows 복사 suffix 파일이
        원본만 DB에 있을 때 unindexed로 감지되어야 한다.
        """
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            original  = inbox / "143243673_p0_master1200.jpg"
            duplicate = inbox / "143243673_p0_master1200 (1).jpg"
            original.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
            duplicate.write_bytes(b"\xff\xd8\xff" + b"0" * 100)  # 동일 내용
            conn = _make_db()
            _insert_file(conn, str(original))   # 원본만 등록
            result = find_unindexed_inbox_files(conn, tmp)
            assert len(result) == 1
            assert "(1)" in result[0].name

    def test_nonexistent_inbox_returns_empty(self):
        conn = _make_db()
        result = find_unindexed_inbox_files(conn, "/nonexistent/path/inbox")
        assert result == []

    def test_non_image_files_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            (inbox / "notes.txt").write_text("hello")
            (inbox / "script.py").write_text("# code")
            conn = _make_db()
            result = find_unindexed_inbox_files(conn, tmp)
            assert result == []


class TestGetDuplicateCheckSummary:
    def test_summary_counts_db_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            f1 = inbox / "file1.jpg"
            f2 = inbox / "file2.jpg"
            f1.write_bytes(b"data1")
            f2.write_bytes(b"data2")
            conn = _make_db()
            _insert_file(conn, str(f1), "original")
            _insert_file(conn, str(f2), "managed")

            summary = get_duplicate_check_summary(conn, tmp)
            assert summary["db_file_count"] == 2
            assert summary["unindexed_count"] == 0

    def test_summary_reports_unindexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            registered = inbox / "registered.jpg"
            unindexed  = inbox / "extra.jpg"
            registered.write_bytes(b"r")
            unindexed.write_bytes(b"u")
            conn = _make_db()
            _insert_file(conn, str(registered))

            summary = get_duplicate_check_summary(conn, tmp)
            assert summary["unindexed_count"] == 1
            assert summary["unindexed_files"][0].name == "extra.jpg"
