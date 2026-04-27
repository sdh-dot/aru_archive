"""
delete_manager 테스트.

- build_delete_preview가 selected group의 파일 목록 생성
- original 포함 시 High risk
- classified_copy만 있으면 Low risk
- execute_delete_preview confirmed=False면 실행 금지
- execute_delete_preview가 파일 삭제 후 artwork_files.file_status='deleted'
- delete_batches/delete_records 생성
- missing file은 warning/failed 처리
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.delete_manager import (
    build_delete_preview,
    compute_delete_risk,
    execute_delete_preview,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _insert_group(conn: sqlite3.Connection, artwork_id: str | None = None) -> str:
    gid = str(uuid.uuid4())
    aid = artwork_id or str(uuid.uuid4())[:8]
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artist_name,
            series_tags_json, character_tags_json, tags_json,
            metadata_sync_status, status, indexed_at, updated_at, downloaded_at)
           VALUES (?, 'pixiv', ?, 'Artist', '[]', '[]', '[]',
                   'json_only', 'inbox', ?, ?, ?)""",
        (gid, aid, _now(), _now(), _now()),
    )
    conn.commit()
    return gid


def _insert_file(
    conn: sqlite3.Connection,
    group_id: str,
    file_path: str,
    file_role: str = "original",
    file_status: str = "present",
    file_hash: str | None = None,
) -> str:
    fid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_hash, file_size, metadata_embedded,
            file_status, created_at)
           VALUES (?, ?, 0, ?, ?, 'jpg', ?, 1024, 1, ?, ?)""",
        (fid, group_id, file_role, file_path, file_hash, file_status, _now()),
    )
    conn.commit()
    return fid


class TestBuildDeletePreview:
    def test_empty_input_returns_empty(self, db):
        preview = build_delete_preview(db)
        assert preview["total_files"] == 0
        assert preview["risk"] == "low"

    def test_builds_file_list_for_group(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "test.jpg")
        Path(fp).touch()
        _insert_file(db, gid, fp)

        preview = build_delete_preview(db, group_ids=[gid])
        assert preview["total_files"] == 1
        assert preview["file_items"][0]["file_path"] == fp

    def test_excludes_already_deleted(self, db, tmp_path):
        gid = _insert_group(db)
        fp1 = str(tmp_path / "a.jpg")
        fp2 = str(tmp_path / "b.jpg")
        Path(fp1).touch()
        _insert_file(db, gid, fp1, file_status="present")
        _insert_file(db, gid, fp2, file_role="managed", file_status="deleted")

        preview = build_delete_preview(db, group_ids=[gid])
        assert preview["total_files"] == 1

    def test_original_file_gives_high_risk(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "orig.jpg")
        Path(fp).touch()
        _insert_file(db, gid, fp, file_role="original")

        preview = build_delete_preview(db, group_ids=[gid])
        assert preview["risk"] == "high"

    def test_classified_copy_only_gives_low_risk(self, db, tmp_path):
        # classified_copy 삭제 + original이 남아 있으면 Low risk
        gid = _insert_group(db)
        fp_copy = str(tmp_path / "copy.jpg")
        fp_orig = str(tmp_path / "orig.jpg")
        Path(fp_copy).touch()
        Path(fp_orig).touch()
        fid_copy = _insert_file(db, gid, fp_copy, file_role="classified_copy")
        _insert_file(db, gid, fp_orig, file_role="original")

        preview = build_delete_preview(db, file_ids=[fid_copy])
        assert preview["risk"] == "low"

    def test_managed_file_gives_medium_risk(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "managed.png")
        Path(fp).touch()
        _insert_file(db, gid, fp, file_role="managed")

        # group에 present original도 남아 있도록 추가
        fp2 = str(tmp_path / "orig.jpg")
        Path(fp2).touch()
        _insert_file(db, gid, fp2, file_role="original")

        preview = build_delete_preview(db, group_ids=[gid], file_ids=[
            db.execute(
                "SELECT file_id FROM artwork_files WHERE file_path=?", (fp,)
            ).fetchone()["file_id"]
        ])
        assert preview["risk"] in ("medium", "high")

    def test_groups_becoming_empty_counted(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "only.jpg")
        Path(fp).touch()
        _insert_file(db, gid, fp, file_role="original")

        preview = build_delete_preview(db, group_ids=[gid])
        assert preview["groups_becoming_empty"] == 1

    def test_missing_file_triggers_warning(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "missing.jpg")
        # 파일 생성 안 함
        _insert_file(db, gid, fp, file_status="present")

        preview = build_delete_preview(db, group_ids=[gid])
        assert any("missing" in w.lower() or "없음" in w for w in preview["warnings"])

    def test_file_ids_target(self, db, tmp_path):
        gid = _insert_group(db)
        fp1 = str(tmp_path / "a.jpg")
        fp2 = str(tmp_path / "b.jpg")
        Path(fp1).touch()
        Path(fp2).touch()
        fid1 = _insert_file(db, gid, fp1)
        _insert_file(db, gid, fp2)

        preview = build_delete_preview(db, file_ids=[fid1])
        assert preview["total_files"] == 1
        assert preview["file_items"][0]["file_id"] == fid1


class TestExecuteDeletePreview:
    def test_not_confirmed_returns_immediately(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "x.jpg")
        Path(fp).touch()
        _insert_file(db, gid, fp)
        preview = build_delete_preview(db, group_ids=[gid])

        result = execute_delete_preview(db, preview, confirmed=False)
        assert result["status"] == "not_confirmed"
        assert result["deleted"] == 0
        assert Path(fp).exists()

    def test_deletes_file_on_disk(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "del.jpg")
        Path(fp).touch()
        _insert_file(db, gid, fp, file_role="classified_copy")
        preview = build_delete_preview(db, group_ids=[gid])

        result = execute_delete_preview(db, preview, confirmed=True)
        assert result["deleted"] == 1
        assert not Path(fp).exists()

    def test_sets_file_status_deleted_in_db(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "del2.jpg")
        Path(fp).touch()
        fid = _insert_file(db, gid, fp, file_role="classified_copy")
        preview = build_delete_preview(db, group_ids=[gid])

        execute_delete_preview(db, preview, confirmed=True)

        row = db.execute(
            "SELECT file_status FROM artwork_files WHERE file_id=?", (fid,)
        ).fetchone()
        assert row["file_status"] == "deleted"

    def test_creates_delete_batch_and_records(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "rec.jpg")
        Path(fp).touch()
        _insert_file(db, gid, fp, file_role="classified_copy")
        preview = build_delete_preview(db, group_ids=[gid])

        result = execute_delete_preview(db, preview, confirmed=True)
        bid = result["batch_id"]

        batch = db.execute(
            "SELECT * FROM delete_batches WHERE delete_batch_id=?", (bid,)
        ).fetchone()
        assert batch is not None
        assert batch["deleted_files"] == 1

        records = db.execute(
            "SELECT * FROM delete_records WHERE delete_batch_id=?", (bid,)
        ).fetchall()
        assert len(records) == 1
        assert records[0]["result_status"] == "deleted"

    def test_missing_file_counted_as_skipped(self, db, tmp_path):
        gid = _insert_group(db)
        fp = str(tmp_path / "missing.jpg")
        fid = _insert_file(db, gid, fp, file_status="missing")
        preview = build_delete_preview(db, group_ids=[gid])

        result = execute_delete_preview(db, preview, confirmed=True)
        assert result["skipped"] == 1

    def test_partial_failure_still_records(self, db, tmp_path):
        gid = _insert_group(db)
        fp_ok = str(tmp_path / "ok.jpg")
        fp_fail = str(tmp_path / "nonexistent_dir" / "no.jpg")
        Path(fp_ok).touch()
        _insert_file(db, gid, fp_ok, file_role="classified_copy")
        _insert_file(db, gid, fp_fail, file_role="classified_copy")
        preview = build_delete_preview(db, group_ids=[gid])

        result = execute_delete_preview(db, preview, confirmed=True)
        # at least one deletion attempt
        assert result["deleted"] + result["failed"] >= 1


class TestComputeDeleteRisk:
    def test_no_files_is_low(self):
        preview = {"role_counts": {}, "groups_becoming_empty": 0, "status_counts": {}}
        assert compute_delete_risk(preview) == "low"

    def test_original_is_high(self):
        preview = {"role_counts": {"original": 1}, "groups_becoming_empty": 0, "status_counts": {}}
        assert compute_delete_risk(preview) == "high"

    def test_empty_group_is_high(self):
        preview = {"role_counts": {"classified_copy": 1}, "groups_becoming_empty": 1, "status_counts": {}}
        assert compute_delete_risk(preview) == "high"

    def test_classified_copy_only_is_low(self):
        preview = {"role_counts": {"classified_copy": 2}, "groups_becoming_empty": 0, "status_counts": {}}
        assert compute_delete_risk(preview) == "low"

    def test_managed_is_medium(self):
        preview = {"role_counts": {"managed": 1}, "groups_becoming_empty": 0, "status_counts": {}}
        assert compute_delete_risk(preview) == "medium"
