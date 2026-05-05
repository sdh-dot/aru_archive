"""
DB 마이그레이션 회귀 테스트.

- artwork_files: metadata_embedded / source_file_id / classify_rule_id 컬럼
- copy_records:  dest_mtime_at_copy / dest_hash_at_copy 컬럼
- 기존 DB에 컬럼이 없어도 initialize_database() 후 컬럼이 추가된다
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db.database import initialize_database


@pytest.fixture
def fresh_db(tmp_path) -> sqlite3.Connection:
    """현재 schema.sql로 초기화된 DB."""
    conn = initialize_database(str(tmp_path / "aru.db"))
    yield conn
    conn.close()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------------------
# artwork_files 컬럼 마이그레이션
# ---------------------------------------------------------------------------

class TestArtworkFilesMigration:
    def test_metadata_embedded_exists(self, fresh_db):
        assert "metadata_embedded" in _column_names(fresh_db, "artwork_files")

    def test_source_file_id_exists(self, fresh_db):
        assert "source_file_id" in _column_names(fresh_db, "artwork_files")

    def test_classify_rule_id_exists(self, fresh_db):
        assert "classify_rule_id" in _column_names(fresh_db, "artwork_files")

    def test_migration_on_old_db(self, tmp_path):
        """컬럼이 없는 구DB에 _migrate_artwork_files()를 실행하면 bookkeeping 컬럼이 추가된다."""
        from db.database import _migrate_artwork_files

        conn = sqlite3.connect(tmp_path / "old.db")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE artwork_files (
                file_id    TEXT PRIMARY KEY,
                group_id   TEXT NOT NULL,
                file_path  TEXT NOT NULL,
                file_role  TEXT NOT NULL DEFAULT 'original',
                file_status TEXT NOT NULL DEFAULT 'present',
                file_size  INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.commit()
        _migrate_artwork_files(conn)
        cols = _column_names(conn, "artwork_files")
        conn.close()

        assert "metadata_embedded" in cols
        assert "source_file_id" in cols
        assert "classify_rule_id" in cols

    def test_metadata_embedded_default_zero(self, tmp_path):
        """기존 행에 _migrate_artwork_files() 후 metadata_embedded 기본값 0이 적용된다."""
        from db.database import _migrate_artwork_files

        conn = sqlite3.connect(tmp_path / "old2.db")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE artwork_files (
                file_id    TEXT PRIMARY KEY,
                group_id   TEXT NOT NULL,
                file_path  TEXT NOT NULL,
                file_role  TEXT NOT NULL DEFAULT 'original',
                file_status TEXT NOT NULL DEFAULT 'present',
                file_size  INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.execute(
            "INSERT INTO artwork_files VALUES ('f1','g1','/p','original','present',0,'')"
        )
        conn.commit()
        _migrate_artwork_files(conn)
        row = conn.execute(
            "SELECT metadata_embedded FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 0


# ---------------------------------------------------------------------------
# copy_records 컬럼 마이그레이션
# ---------------------------------------------------------------------------

class TestCopyRecordsMigration:
    def test_dest_mtime_at_copy_exists(self, fresh_db):
        assert "dest_mtime_at_copy" in _column_names(fresh_db, "copy_records")

    def test_dest_hash_at_copy_exists(self, fresh_db):
        assert "dest_hash_at_copy" in _column_names(fresh_db, "copy_records")

    def test_migration_on_old_copy_records(self, tmp_path):
        """copy_records에 bookkeeping 컬럼이 없는 구DB에 _migrate_copy_records()를 실행하면 추가된다."""
        from db.database import _migrate_copy_records

        conn = sqlite3.connect(tmp_path / "old_cr.db")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE copy_records (
                entry_id   TEXT PRIMARY KEY,
                src_path   TEXT NOT NULL,
                dest_path  TEXT NOT NULL,
                copied_at  TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.commit()
        _migrate_copy_records(conn)
        cols = _column_names(conn, "copy_records")
        conn.close()

        assert "dest_mtime_at_copy" in cols
        assert "dest_hash_at_copy" in cols


# ---------------------------------------------------------------------------
# execute_classify_batch 오류 전파
# ---------------------------------------------------------------------------

class TestExecuteBatchErrorPropagation:
    def test_success_result_has_error_none(self, tmp_path):
        """성공 시 error/first_error가 None이다."""
        from core.batch_classifier import execute_classify_batch
        conn = initialize_database(str(tmp_path / "aru.db"))
        result = execute_classify_batch(conn, {"previews": []}, {})
        conn.close()
        assert result["error"] is None
        assert result["first_error"] is None
        assert result["errors"] == []

    def test_failed_group_populates_first_error(self, tmp_path):
        """execute_classify_preview가 예외를 던지면 first_error가 채워진다."""
        from unittest.mock import patch
        from core.batch_classifier import execute_classify_batch

        conn = initialize_database(str(tmp_path / "aru.db"))
        fake_preview = {"group_id": "g1", "estimated_copies": 0, "estimated_bytes": 0}
        batch = {"previews": [fake_preview]}

        with patch(
            "core.batch_classifier.execute_classify_preview",
            side_effect=Exception("no such column: metadata_embedded"),
        ):
            result = execute_classify_batch(conn, batch, {})
        conn.close()

        assert result["success"] is False
        assert result["first_error"] == "no such column: metadata_embedded"
        assert result["error"] is not None
        assert "metadata_embedded" in result["error"]
        assert len(result["errors"]) == 1
        assert result["errors"][0]["group_id"] == "g1"

    def test_partial_failure_success_is_true(self, tmp_path):
        """일부 성공 일부 실패면 success=True, status='partial'."""
        from unittest.mock import patch
        from core.batch_classifier import execute_classify_batch

        conn = initialize_database(str(tmp_path / "aru.db"))
        ok_preview = {"group_id": "g_ok", "estimated_copies": 0, "estimated_bytes": 0}
        err_preview = {"group_id": "g_err", "estimated_copies": 0, "estimated_bytes": 0}
        batch = {"previews": [ok_preview, err_preview]}

        call_count = {"n": 0}

        def _side_effect(conn, preview, config, **kwargs):
            call_count["n"] += 1
            if preview["group_id"] == "g_err":
                raise Exception("fail")
            return {"copied": 1, "skipped": 0}

        with patch("core.batch_classifier.execute_classify_preview", side_effect=_side_effect):
            result = execute_classify_batch(conn, batch, {})
        conn.close()

        assert result["success"] is True
        assert result["status"] == "partial"
        assert result["first_error"] == "fail"

    def test_progress_fn_receives_error_string(self, tmp_path):
        """오류 발생 시 progress_fn에 error 문자열이 전달된다."""
        from unittest.mock import patch
        from core.batch_classifier import execute_classify_batch

        conn = initialize_database(str(tmp_path / "aru.db"))
        fake_preview = {"group_id": "g1", "estimated_copies": 0, "estimated_bytes": 0}
        batch = {"previews": [fake_preview]}

        received: list[tuple] = []

        def _progress(*args):
            received.append(args)

        with patch(
            "core.batch_classifier.execute_classify_preview",
            side_effect=Exception("column missing"),
        ):
            execute_classify_batch(conn, batch, {}, progress_fn=_progress)
        conn.close()

        error_call = next((a for a in received if len(a) >= 5 and a[3] == "error"), None)
        assert error_call is not None
        assert "column missing" in error_call[4]
