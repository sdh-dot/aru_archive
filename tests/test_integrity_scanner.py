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
    find_restored_files,
    mark_files_as_present,
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
            file_hash TEXT,
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
              file_status="present", file_format="jpg", file_hash=None):
    conn.execute(
        "INSERT INTO artwork_groups (group_id, artwork_id, indexed_at) "
        "VALUES (?, '', '2026-01-01') "
        "ON CONFLICT(group_id) DO NOTHING",
        (group_id,),
    )
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, file_format, "
        " file_hash, file_status, created_at) "
        "VALUES (?, ?, 0, ?, ?, ?, ?, ?, '2026-01-01')",
        (file_id, group_id, file_role, file_path, file_format, file_hash, file_status),
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


class TestFindRestoredFiles:
    def test_finds_missing_path_now_present(self, conn, tmp_path):
        """missing row의 path에 파일이 생기면 결과에 포함."""
        real = tmp_path / "returned.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing")
        result = find_restored_files(conn)
        assert len(result) == 1
        assert result[0]["file_id"] == "f1"
        assert result[0]["file_status"] == "missing"

    def test_present_file_not_in_result(self, conn, tmp_path):
        """이미 present인 row는 결과 제외."""
        real = tmp_path / "present.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="present")
        result = find_restored_files(conn)
        assert result == []

    def test_deleted_file_not_in_result(self, conn, tmp_path):
        """deleted row는 결과 제외 (파일이 있어도 무시)."""
        real = tmp_path / "deleted.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="deleted")
        result = find_restored_files(conn)
        assert result == []

    def test_role_filter_default_excludes_sidecar(self, conn, tmp_path):
        """sidecar / classified_copy는 기본 roles에서 제외."""
        for role in ("sidecar", "classified_copy"):
            fpath = tmp_path / f"{role}.jpg"
            fpath.write_text("x")
            _add_file(conn, file_id=f"f_{role}", group_id="g1",
                      file_path=str(fpath), file_role=role,
                      file_status="missing")
        # original missing (파일 없음) — 복원 후보 아님
        _add_file(conn, file_id="f_orig", group_id="g1",
                  file_path=str(tmp_path / "orig.jpg"),
                  file_role="original", file_status="missing")
        result = find_restored_files(conn)
        ids = {r["file_id"] for r in result}
        assert "f_sidecar" not in ids
        assert "f_classified_copy" not in ids

    def test_empty_or_null_path_excluded(self, conn, tmp_path):
        """file_path가 None 또는 빈 문자열이면 제외."""
        # NULL path — INSERT 시 NOT NULL constraint를 우회하기 위해
        # 일반 INSERT 후 UPDATE로 NULL 설정
        _add_file(conn, file_id="f_empty", group_id="g1",
                  file_path=str(tmp_path / "placeholder.jpg"),
                  file_status="missing")
        conn.execute(
            "UPDATE artwork_files SET file_path = '' WHERE file_id = 'f_empty'"
        )
        conn.commit()
        result = find_restored_files(conn)
        assert all(r["file_id"] != "f_empty" for r in result)

    def test_result_dict_has_required_keys(self, conn, tmp_path):
        """반환 dict에 필수 키가 모두 있는지 확인."""
        real = tmp_path / "back.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing")
        result = find_restored_files(conn)
        assert len(result) == 1
        for key in ("file_id", "group_id", "file_path", "file_role", "file_status"):
            assert key in result[0], f"Missing key: {key}"


class TestMarkFilesAsPresent:
    def test_updates_missing_to_present(self, conn, tmp_path):
        """missing → present."""
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="missing")
        result = mark_files_as_present(conn, ["f1"])
        assert result["updated"] == 1
        assert result["skipped"] == 0
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "present"

    def test_skips_already_present(self, conn, tmp_path):
        """이미 present인 row는 skip (idempotent)."""
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="present")
        result = mark_files_as_present(conn, ["f1"])
        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_skips_deleted(self, conn, tmp_path):
        """deleted row는 건드리지 않음."""
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="deleted")
        result = mark_files_as_present(conn, ["f1"])
        assert result["updated"] == 0
        assert result["skipped"] == 1
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "deleted"

    def test_empty_input_returns_zero(self, conn):
        result = mark_files_as_present(conn, [])
        assert result == {"requested": 0, "updated": 0, "skipped": 0}

    def test_idempotent_double_call(self, conn, tmp_path):
        """두 번 호출해도 두 번째는 skipped."""
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(tmp_path / "x.jpg"),
                  file_status="missing")
        result1 = mark_files_as_present(conn, ["f1"])
        result2 = mark_files_as_present(conn, ["f1"])
        assert result1["updated"] == 1
        assert result2["updated"] == 0
        assert result2["skipped"] == 1


class TestRunIntegrityScanWithRestore:
    def test_dry_run_does_not_restore(self, conn, tmp_path):
        """dry_run=True → restore_updated=0, DB 그대로 missing."""
        real = tmp_path / "returned.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing")
        result = run_integrity_scan(conn, dry_run=True)
        assert result["restore_updated"] == 0
        assert result["dry_run"] is True
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "missing"

    def test_wet_run_restores_returned_file(self, conn, tmp_path):
        """wet_run 후 file_status='present'."""
        real = tmp_path / "returned.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing")
        result = run_integrity_scan(conn, dry_run=False)
        assert result["restore_updated"] == 1
        assert result["restored_count"] == 1
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "present"

    def test_unrelated_missing_row_unchanged(self, conn, tmp_path):
        """복원 파일과 무관한 missing row는 그대로 missing."""
        real = tmp_path / "returned.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f_restored", group_id="g1",
                  file_path=str(real), file_status="missing")
        _add_file(conn, file_id="f_still_missing", group_id="g2",
                  file_path=str(tmp_path / "still_gone.jpg"),
                  file_status="missing")
        run_integrity_scan(conn, dry_run=False)
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f_still_missing'"
        ).fetchone()
        assert row["file_status"] == "missing"

    def test_missing_count_decreases_after_restore(self, conn, tmp_path):
        """wet_run 후 missing 건수가 감소한다."""
        real = tmp_path / "returned.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f_restored", group_id="g1",
                  file_path=str(real), file_status="missing")
        _add_file(conn, file_id="f_still_missing", group_id="g2",
                  file_path=str(tmp_path / "still_gone.jpg"),
                  file_status="missing")

        run_integrity_scan(conn, dry_run=False)

        count = conn.execute(
            "SELECT COUNT(*) FROM artwork_files WHERE file_status='missing'"
        ).fetchone()[0]
        assert count == 1

    def test_restored_files_appear_in_present_query(self, conn, tmp_path):
        """wet_run 후 복원 파일이 present 쿼리에 포함된다."""
        real = tmp_path / "returned.jpg"
        real.write_text("x")
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing")
        run_integrity_scan(conn, dry_run=False)

        rows = conn.execute(
            "SELECT file_id FROM artwork_files WHERE file_status='present'"
        ).fetchall()
        ids = {r["file_id"] for r in rows}
        assert "f1" in ids

    def test_returns_new_keys_in_result(self, conn, tmp_path):
        """반환 dict에 신규 키가 모두 포함되는지 확인."""
        result = run_integrity_scan(conn, dry_run=True)
        for key in ("restored_files", "restored_count", "restore_updated"):
            assert key in result, f"Missing key: {key}"

    def test_existing_missing_keys_unchanged(self, conn, tmp_path):
        """기존 missing 관련 키가 그대로 반환되는지 확인 (회귀)."""
        result = run_integrity_scan(conn, dry_run=True)
        for key in ("missing_files", "missing_count", "affected_group_count",
                    "updated", "dry_run"):
            assert key in result, f"Missing key: {key}"


class TestHashMismatchWarning:
    """same-path restore 시 hash 검증 동작 확인."""

    def _sha256(self, path) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def test_same_path_same_hash_restores_to_present(self, conn, tmp_path):
        """DB hash == 현재 hash → 복원 진행, file_status='present'."""
        real = tmp_path / "returned.jpg"
        real.write_bytes(b"original content")
        real_hash = self._sha256(real)
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing",
                  file_hash=real_hash)

        result = run_integrity_scan(conn, dry_run=False)

        assert result["restore_updated"] == 1
        assert result["restore_skipped_hash_mismatch"] == 0
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "present"

    def test_same_path_hash_mismatch_skips_restore(self, conn, tmp_path):
        """DB hash != 현재 hash → 복원 skip, file_status='missing' 유지."""
        real = tmp_path / "imposter.jpg"
        real.write_bytes(b"different content")
        db_hash = "a" * 64  # DB에 저장된 (다른) hash
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing",
                  file_hash=db_hash)

        result = run_integrity_scan(conn, dry_run=False)

        assert result["restore_updated"] == 0
        assert result["restore_skipped_hash_mismatch"] == 1
        assert result["restored_count"] == 0
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "missing"

    def test_same_path_hash_mismatch_in_reporting(self, conn, tmp_path):
        """hash_mismatch_files에 skip된 후보 상세가 포함된다."""
        real = tmp_path / "imposter.jpg"
        real.write_bytes(b"replaced content")
        db_hash = "b" * 64
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing",
                  file_hash=db_hash)

        result = run_integrity_scan(conn, dry_run=False)

        assert result["restore_skipped_hash_mismatch"] == 1
        assert len(result["hash_mismatch_files"]) == 1
        entry = result["hash_mismatch_files"][0]
        assert entry["file_id"] == "f1"
        assert entry["group_id"] == "g1"
        assert entry["file_path"] == str(real)
        assert entry["db_hash"] is not None
        assert entry["current_hash"] is not None

    def test_db_hash_unavailable_falls_back_to_path_only(self, conn, tmp_path):
        """DB hash 없음 → hash 검증 skip, 기존 same-path 복원 정책 유지."""
        real = tmp_path / "no_hash_file.jpg"
        real.write_bytes(b"some content")
        # file_hash=None (DB에 hash 미기록)
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing",
                  file_hash=None)

        result = run_integrity_scan(conn, dry_run=False)

        assert result["restore_updated"] == 1
        assert result["restore_skipped_hash_mismatch"] == 0
        assert result["restore_skipped_hash_unavailable"] == 1
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "present"

    def test_current_file_hash_unavailable_skips_restore(self, conn, tmp_path,
                                                          monkeypatch):
        """현재 파일 hash 계산 실패(IO 에러) → 보수적으로 복원 skip."""
        import core.integrity_scanner as mod
        real = tmp_path / "unreadable.jpg"
        real.write_bytes(b"content")
        db_hash = "c" * 64
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing",
                  file_hash=db_hash)

        # _compute_file_hash가 None을 반환하도록 monkeypatch
        monkeypatch.setattr(mod, "_compute_file_hash", lambda path: None)

        result = run_integrity_scan(conn, dry_run=False)

        assert result["restore_updated"] == 0
        assert result["restore_skipped_hash_mismatch"] == 1
        row = conn.execute(
            "SELECT file_status FROM artwork_files WHERE file_id='f1'"
        ).fetchone()
        assert row["file_status"] == "missing"

    def test_existing_restore_count_unchanged_when_no_mismatch(self, conn, tmp_path):
        """hash 불일치 없을 때 기존 restore 카운트 동작 회귀 없음."""
        real = tmp_path / "clean.jpg"
        real.write_bytes(b"clean content")
        real_hash = self._sha256(real)
        _add_file(conn, file_id="f1", group_id="g1",
                  file_path=str(real), file_status="missing",
                  file_hash=real_hash)
        # f2: 실제로 존재하지 않는 파일 — present 상태로 등록하면 find_missing_files에서 발견
        _add_file(conn, file_id="f2", group_id="g2",
                  file_path=str(tmp_path / "still_gone.jpg"),
                  file_status="present", file_hash=None)

        result = run_integrity_scan(conn, dry_run=False)

        # f1: hash 일치 → 복원, f2: 파일 없음 → missing으로 마킹
        assert result["restore_updated"] == 1
        assert result["restore_skipped_hash_mismatch"] == 0
        assert result["missing_count"] == 1  # f2 (파일 없음, present→missing)

    def test_run_integrity_scan_returns_new_hash_keys(self, conn, tmp_path):
        """반환 dict에 신규 hash 관련 키가 모두 포함되는지 확인."""
        result = run_integrity_scan(conn, dry_run=True)
        for key in ("restore_skipped_hash_mismatch", "hash_mismatch_files",
                    "restore_skipped_hash_unavailable"):
            assert key in result, f"Missing key: {key}"
        assert isinstance(result["hash_mismatch_files"], list)
        assert result["restore_skipped_hash_mismatch"] == 0
        assert result["restore_skipped_hash_unavailable"] == 0
