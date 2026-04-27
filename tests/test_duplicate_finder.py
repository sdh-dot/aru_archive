"""
완전 중복(SHA-256) 검사 테스트.

- SHA-256 같은 파일이 duplicate group으로 묶임
- recommend_keep_file이 full/original 우선
- classified_copy는 삭제 후보 우선
- cleanup preview가 보존 1개 / 삭제 후보 N개 생성
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.duplicate_finder import (
    build_exact_duplicate_cleanup_preview,
    find_exact_duplicates,
    recommend_keep_file,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _insert_group(conn: sqlite3.Connection) -> str:
    gid = str(uuid.uuid4())
    aid = str(uuid.uuid4())[:8]
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artist_name,
            series_tags_json, character_tags_json, tags_json,
            metadata_sync_status, status, indexed_at, updated_at, downloaded_at)
           VALUES (?, 'pixiv', ?, 'Artist', '[]', '[]', '[]',
                   'full', 'inbox', ?, ?, ?)""",
        (gid, aid, _now(), _now(), _now()),
    )
    conn.commit()
    return gid


def _insert_file(
    conn: sqlite3.Connection,
    group_id: str,
    file_path: str,
    file_role: str = "original",
    file_hash: str = "abc123",
    metadata_sync_status: str | None = None,
) -> str:
    fid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_hash, file_size, metadata_embedded,
            file_status, created_at)
           VALUES (?, ?, 0, ?, ?, 'jpg', ?, 1024, 1, 'present', ?)""",
        (fid, group_id, file_role, file_path, file_hash, _now()),
    )
    conn.commit()
    # metadata_sync_status is on artwork_groups; override if needed
    if metadata_sync_status:
        conn.execute(
            "UPDATE artwork_groups SET metadata_sync_status=? WHERE group_id=?",
            (metadata_sync_status, group_id),
        )
        conn.commit()
    return fid


class TestFindExactDuplicates:
    def test_no_duplicates_returns_empty(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_hash="hash_unique_a")
        result = find_exact_duplicates(db)
        assert result == []

    def test_same_hash_grouped(self, db, tmp_path):
        gid1 = _insert_group(db)
        gid2 = _insert_group(db)
        _insert_file(db, gid1, str(tmp_path / "a.jpg"), file_hash="same_hash")
        _insert_file(db, gid2, str(tmp_path / "b.jpg"), file_hash="same_hash")

        result = find_exact_duplicates(db)
        assert len(result) == 1
        assert result[0]["hash"] == "same_hash"
        assert len(result[0]["files"]) == 2

    def test_different_hashes_not_grouped(self, db, tmp_path):
        gid1 = _insert_group(db)
        gid2 = _insert_group(db)
        _insert_file(db, gid1, str(tmp_path / "a.jpg"), file_hash="hash_A")
        _insert_file(db, gid2, str(tmp_path / "b.jpg"), file_hash="hash_B")

        result = find_exact_duplicates(db)
        assert result == []

    def test_three_files_same_hash(self, db, tmp_path):
        g1 = _insert_group(db)
        g2 = _insert_group(db)
        g3 = _insert_group(db)
        for i, gid in enumerate([g1, g2, g3]):
            _insert_file(db, gid, str(tmp_path / f"f{i}.jpg"), file_hash="triple_hash")

        result = find_exact_duplicates(db)
        assert len(result) == 1
        assert len(result[0]["files"]) == 3

    def test_ignores_non_present_files(self, db, tmp_path):
        gid1 = _insert_group(db)
        gid2 = _insert_group(db)
        fid1 = _insert_file(db, gid1, str(tmp_path / "a.jpg"), file_hash="hash_x")
        fid2 = _insert_file(db, gid2, str(tmp_path / "b.jpg"), file_hash="hash_x")
        # 두 번째를 missing으로 변경
        db.execute(
            "UPDATE artwork_files SET file_status='missing' WHERE file_id=?", (fid2,)
        )
        db.commit()

        result = find_exact_duplicates(db)
        assert result == []


class TestRecommendKeepFile:
    def test_prefers_original_over_classified_copy(self):
        group = {
            "hash": "h",
            "files": [
                {"file_id": "a", "file_role": "classified_copy", "metadata_sync_status": "full",
                 "file_size": 2000, "file_path": "12345_p0.jpg"},
                {"file_id": "b", "file_role": "original", "metadata_sync_status": "json_only",
                 "file_size": 1000, "file_path": "12345_p0.jpg"},
            ],
        }
        keep = recommend_keep_file(group)
        assert keep["file_id"] == "b"

    def test_prefers_full_over_json_only(self):
        group = {
            "hash": "h",
            "files": [
                {"file_id": "a", "file_role": "original", "metadata_sync_status": "json_only",
                 "file_size": 1000, "file_path": "a.jpg"},
                {"file_id": "b", "file_role": "original", "metadata_sync_status": "full",
                 "file_size": 1000, "file_path": "b.jpg"},
            ],
        }
        keep = recommend_keep_file(group)
        assert keep["file_id"] == "b"

    def test_prefers_pixiv_id_filename(self):
        group = {
            "hash": "h",
            "files": [
                {"file_id": "a", "file_role": "original", "metadata_sync_status": "json_only",
                 "file_size": 1000, "file_path": "random_name.jpg"},
                {"file_id": "b", "file_role": "original", "metadata_sync_status": "json_only",
                 "file_size": 1000, "file_path": "12345678_p0.jpg"},
            ],
        }
        keep = recommend_keep_file(group)
        assert keep["file_id"] == "b"

    def test_prefers_larger_file_size(self):
        group = {
            "hash": "h",
            "files": [
                {"file_id": "a", "file_role": "original", "metadata_sync_status": "json_only",
                 "file_size": 500, "file_path": "12345_p0.jpg"},
                {"file_id": "b", "file_role": "original", "metadata_sync_status": "json_only",
                 "file_size": 5000, "file_path": "12345_p0.jpg"},
            ],
        }
        keep = recommend_keep_file(group)
        assert keep["file_id"] == "b"

    def test_single_file_returns_itself(self):
        group = {"hash": "h", "files": [{"file_id": "x"}]}
        assert recommend_keep_file(group)["file_id"] == "x"

    def test_empty_group_returns_empty(self):
        assert recommend_keep_file({"hash": "h", "files": []}) == {}


class TestBuildExactDuplicateCleanupPreview:
    def test_keeps_one_deletes_rest(self, db, tmp_path):
        gid1 = _insert_group(db)
        gid2 = _insert_group(db)
        gid3 = _insert_group(db)
        for i, gid in enumerate([gid1, gid2, gid3]):
            _insert_file(
                db, gid, str(tmp_path / f"f{i}.jpg"),
                file_role="original", file_hash="same_hash",
            )

        dup_groups = find_exact_duplicates(db)
        assert len(dup_groups) == 1

        preview = build_exact_duplicate_cleanup_preview(db, dup_groups)
        assert preview["total_groups"] == 1
        assert preview["total_keep"] == 1
        assert preview["total_delete_candidates"] == 2

    def test_keep_file_not_in_delete_candidates(self, db, tmp_path):
        gid1 = _insert_group(db)
        gid2 = _insert_group(db)
        for i, gid in enumerate([gid1, gid2]):
            _insert_file(
                db, gid, str(tmp_path / f"g{i}.jpg"),
                file_hash="hash_pair",
            )

        dup_groups = find_exact_duplicates(db)
        preview = build_exact_duplicate_cleanup_preview(db, dup_groups)
        keep_id = preview["groups"][0]["keep_file"]["file_id"]
        delete_ids = {f["file_id"] for f in preview["groups"][0]["delete_candidates"]}
        assert keep_id not in delete_ids

    def test_classified_copy_is_delete_candidate(self, db, tmp_path):
        # all_archive scope에서 original + classified_copy 동시 검사 시
        # original이 보존, classified_copy가 삭제 후보여야 함
        gid1 = _insert_group(db)
        gid2 = _insert_group(db)
        fid_orig = _insert_file(
            db, gid1, str(tmp_path / "orig.jpg"),
            file_role="original", file_hash="same_h",
        )
        fid_copy = _insert_file(
            db, gid2, str(tmp_path / "copy.jpg"),
            file_role="classified_copy", file_hash="same_h",
        )

        # 기본 scope(inbox_managed)에서는 classified_copy 제외 → 중복 그룹 없음
        dup_groups_default = find_exact_duplicates(db)
        assert dup_groups_default == []

        # all_archive scope에서는 두 파일 모두 포함 → 중복 그룹 생성
        dup_groups = find_exact_duplicates(db, scope="all_archive")
        preview = build_exact_duplicate_cleanup_preview(db, dup_groups)
        keep_id = preview["groups"][0]["keep_file"]["file_id"]
        assert keep_id == fid_orig
        delete_ids = {f["file_id"] for f in preview["groups"][0]["delete_candidates"]}
        assert fid_copy in delete_ids
