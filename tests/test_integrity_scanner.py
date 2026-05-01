"""file integrity scanner 단위 테스트.

DB schema는 변경하지 않는다. tmp_path에 실제 파일을 만들고
in-memory SQLite로 artwork_files row를 등록해 검사한다.
"""
from __future__ import annotations

import sqlite3

import pytest
from pathlib import Path

from core.integrity_scanner import (
    find_missing_files,
    mark_files_as_missing,
    run_integrity_scan,
)


def _bootstrap_schema(conn):
    conn.executescript("""
        CREATE TABLE artwork_groups (
            group_id TEXT PRIMARY KEY,
            artwork_id TEXT,
            indexed_at TEXT
        );
        CREATE TABLE artwork_files (
            file_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            page_index INTEGER NOT NULL DEFAULT 0,
            file_role TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            file_format TEXT NOT NULL,
            file_status TEXT NOT NULL DEFAULT 'present',
            last_seen_at TEXT,
            created_at TEXT
        );
    """)
    conn.commit()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _bootstrap_schema(c)
    yield c
    c.close()


def _add_file(conn, *, file_id, group_id, file_path, file_role="original",
              file_status="present", file_format="jpg"):
    conn.execute(
        "INSERT INTO artwork_groups (group_id, artwork_id, indexed_at) "
        "VALUES (?, '', '2026-01-01') "
        "ON CONFLICT(group_id) DO NOTHING",
        (group_id,),
    )
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, file_format, "
        " file_status, created_at) "
        "VALUES (?, ?, 0, ?, ?, ?, ?, '2026-01-01')",
        (file_id, group_id, file_role, file_path, file_format, file_status),
    )
    conn.commit()


class TestFindMissingFiles:
    def test_finds_missing_path(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "nonexistent.jpg"))
        result = find_missing_files(conn)
        assert len(result) == 1
        assert result[0]["file_id"] == "f1"

    def test_existing_file_not_in_result(self, conn, tmp_path):
        real = tmp_path / "real.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1", file_path=str(real))
        result = find_missing_files(conn)
        assert result == []

    def test_already_missing_status_excluded(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="missing")
        result = find_missing_files(conn)
        assert result == []

    def test_already_deleted_status_excluded(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="deleted")
        result = find_missing_files(conn)
        assert result == []

    def test_role_filter_default_includes_original_managed(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "a.jpg"), file_role="original")
        _add_file(conn, file_id="f2", group_id="g1",
                  file_path=str(tmp_path / "b.png"), file_role="managed")
        _add_file(conn, file_id="f3", group_id="g1",
                  file_path=str(tmp_path / "c.json"), file_role="sidecar")
        _add_file(conn, file_id="f4", group_id="g1",
                  file_path=str(tmp_path / "d.jpg"),
                  file_role="classified_copy")
        result = find_missing_files(conn)
        ids = {r["file_id"] for r in result}
        assert ids == {"f1", "f2"}

    def test_role_filter_custom(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "a.jpg"), file_role="original")
        _add_file(conn, file_id="f2", group_id="g1",
                  file_path=str(tmp_path / "b.png"), file_role="managed")
        result = find_missing_files(conn, roles=("original",))
        ids = {r["file_id"] for r in result}
        assert ids == {"f1"}

    def test_group_ids_filter(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "a.jpg"))
        _add_file(conn, file_id="f2", group_id="g2",
                  file_path=str(tmp_path / "b.jpg"))
        result = find_missing_files(conn, group_ids=["g1"])
        assert {r["file_id"] for r in result} == {"f1"}

    def test_empty_roles_returns_empty(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "a.jpg"))
        result = find_missing_files(conn, roles=())
        assert result == []

    def test_empty_group_ids_returns_empty(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "a.jpg"))
        result = find_missing_files(conn, group_ids=[])
        assert result == []

    def test_result_dict_has_required_keys(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "nonexistent.jpg"))
        result = find_missing_files(conn)
        assert len(result) == 1
        entry = result[0]
        for key in ("file_id", "group_id", "file_path", "file_role", "file_status"):
            assert key in entry, f"Missing key: {key}"


class TestMarkFilesAsMissing:
    def test_updates_present_to_missing(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"))
        result = mark_files_as_missing(conn, ["f1"])
        assert result["updated"] == 1
        assert result["skipped"] == 0
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "missing"

    def test_skips_already_missing(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="missing")
        result = mark_files_as_missing(conn, ["f1"])
        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_skips_already_deleted(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="deleted")
        result = mark_files_as_missing(conn, ["f1"])
        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_empty_input_returns_zero(self, conn):
        result = mark_files_as_missing(conn, [])
        assert result == {"requested": 0, "updated": 0, "skipped": 0}

    def test_missing_file_id_returns_skipped(self, conn):
        result = mark_files_as_missing(conn, ["nonexistent_id"])
        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_idempotent_double_call(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"))
        result1 = mark_files_as_missing(conn, ["f1"])
        result2 = mark_files_as_missing(conn, ["f1"])
        assert result1["updated"] == 1
        assert result2["updated"] == 0
        assert result2["skipped"] == 1


class TestRunIntegrityScan:
    def test_dry_run_does_not_mutate_db(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "missing.jpg"))
        result = run_integrity_scan(conn, dry_run=True)
        assert result["missing_count"] == 1
        assert result["updated"] == 0
        assert result["dry_run"] is True
        # DB 상태 그대로
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "present"

    def test_wet_run_updates_status(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "missing.jpg"))
        _add_file(conn, file_id="f2", group_id="g1",
                  file_path=str(tmp_path / "also_missing.jpg"))
        result = run_integrity_scan(conn, dry_run=False)
        assert result["missing_count"] == 2
        assert result["updated"] == 2
        assert result["dry_run"] is False
        rows = conn.execute(
            "SELECT file_status FROM artwork_files"
        ).fetchall()
        assert all(r["file_status"] == "missing" for r in rows)

    def test_returns_affected_group_count(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "a.jpg"))
        _add_file(conn, file_id="f2", group_id="g1",
                  file_path=str(tmp_path / "b.jpg"))
        _add_file(conn, file_id="f3", group_id="g2",
                  file_path=str(tmp_path / "c.jpg"))
        result = run_integrity_scan(conn, dry_run=True)
        assert result["affected_group_count"] == 2

    def test_zero_missing_returns_zero_counts(self, conn, tmp_path):
        real = tmp_path / "real.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1", file_path=str(real))
        result = run_integrity_scan(conn, dry_run=False)
        assert result["missing_count"] == 0
        assert result["updated"] == 0

    def test_returns_missing_files_list(self, conn, tmp_path):
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "gone.jpg"))
        result = run_integrity_scan(conn, dry_run=True)
        assert isinstance(result["missing_files"], list)
        assert len(result["missing_files"]) == 1
        assert result["missing_files"][0]["file_id"] == "f1"
