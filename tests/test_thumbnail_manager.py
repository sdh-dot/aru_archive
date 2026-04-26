"""
thumbnail_manager 단위 테스트.
get_thumb_path 경로 규칙, generate_thumbnail 생성/DB 기록,
invalidate_thumbnail 삭제, purge_orphan_thumbnails, needs_regeneration.
"""
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from db.database import initialize_database
from core.thumbnail_manager import (
    THUMBCACHE_DIR,
    generate_thumbnail,
    get_thumb_path,
    invalidate_thumbnail,
    needs_regeneration,
    purge_orphan_thumbnails,
)


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = initialize_database(db_path)
    yield conn
    conn.close()


def _insert_group(conn) -> str:
    group_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, downloaded_at, indexed_at)
           VALUES (?, 'pixiv', ?, ?, ?)""",
        (group_id, f"art_{group_id[:8]}", now, now),
    )
    conn.commit()
    return group_id


def _insert_file(conn, group_id: str) -> str:
    file_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at)
           VALUES (?, ?, 0, 'original', ?, 'jpg', ?)""",
        (file_id, group_id, f"/dummy/{file_id}.jpg", now),
    )
    conn.commit()
    return file_id


def _make_image(path: str, size=(20, 20), color=(100, 150, 200)):
    Image.new("RGB", size, color=color).save(path, format="JPEG")


# ---------------------------------------------------------------------------
# get_thumb_path
# ---------------------------------------------------------------------------

class TestGetThumbPath:
    def test_prefix_2chars(self, tmp_path):
        file_id = "abcdef1234"
        result = get_thumb_path(str(tmp_path), file_id)
        assert result.parent.name == "ab"

    def test_filename_is_file_id_webp(self, tmp_path):
        file_id = "abcdef1234"
        result = get_thumb_path(str(tmp_path), file_id)
        assert result.name == f"{file_id}.webp"

    def test_inside_thumbcache_dir(self, tmp_path):
        result = get_thumb_path(str(tmp_path), "xy9876")
        parts = result.parts
        assert THUMBCACHE_DIR in parts

    def test_full_path_structure(self, tmp_path):
        file_id = "ff0011aabb"
        result = get_thumb_path(str(tmp_path), file_id)
        expected = Path(tmp_path) / THUMBCACHE_DIR / "ff" / f"{file_id}.webp"
        assert result == expected


# ---------------------------------------------------------------------------
# generate_thumbnail
# ---------------------------------------------------------------------------

class TestGenerateThumbnail:
    def test_creates_file(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        result = generate_thumbnail(db, src, str(tmp_path), file_id, "hash_abc")
        assert Path(result).exists()

    def test_output_is_webp(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        result = generate_thumbnail(db, src, str(tmp_path), file_id, "hash_abc")
        img = Image.open(result)
        assert img.format == "WEBP"

    def test_db_record_created(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        generate_thumbnail(db, src, str(tmp_path), file_id, "hash_xyz")
        row = db.execute(
            "SELECT thumb_path, source_hash FROM thumbnail_cache WHERE file_id=?",
            (file_id,),
        ).fetchone()
        assert row is not None
        assert row["source_hash"] == "hash_xyz"

    def test_path_matches_get_thumb_path(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        result = generate_thumbnail(db, src, str(tmp_path), file_id, "h")
        expected = get_thumb_path(str(tmp_path), file_id)
        assert Path(result) == expected

    def test_respects_size_param(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src, size=(200, 200))
        result = generate_thumbnail(db, src, str(tmp_path), file_id, "h", size=(64, 64))
        img = Image.open(result)
        assert img.width <= 64 and img.height <= 64

    def test_idempotent_replace(self, db, tmp_path):
        """같은 file_id로 두 번 호출하면 덮어쓰기 (INSERT OR REPLACE)."""
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        generate_thumbnail(db, src, str(tmp_path), file_id, "hash_v1")
        generate_thumbnail(db, src, str(tmp_path), file_id, "hash_v2")
        count = db.execute(
            "SELECT COUNT(*) FROM thumbnail_cache WHERE file_id=?", (file_id,)
        ).fetchone()[0]
        assert count == 1
        row = db.execute(
            "SELECT source_hash FROM thumbnail_cache WHERE file_id=?", (file_id,)
        ).fetchone()
        assert row["source_hash"] == "hash_v2"


# ---------------------------------------------------------------------------
# invalidate_thumbnail
# ---------------------------------------------------------------------------

class TestInvalidateThumbnail:
    def test_file_deleted(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        result = generate_thumbnail(db, src, str(tmp_path), file_id, "h")
        assert Path(result).exists()
        invalidate_thumbnail(db, str(tmp_path), file_id)
        assert not Path(result).exists()

    def test_db_record_removed(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        generate_thumbnail(db, src, str(tmp_path), file_id, "h")
        invalidate_thumbnail(db, str(tmp_path), file_id)
        row = db.execute(
            "SELECT 1 FROM thumbnail_cache WHERE file_id=?", (file_id,)
        ).fetchone()
        assert row is None

    def test_no_error_if_not_exists(self, db, tmp_path):
        """존재하지 않는 file_id에 호출해도 예외 없음."""
        invalidate_thumbnail(db, str(tmp_path), "nonexistent_id")


# ---------------------------------------------------------------------------
# purge_orphan_thumbnails
# ---------------------------------------------------------------------------

class TestPurgeOrphanThumbnails:
    def test_orphan_deleted(self, db, tmp_path):
        """DB에 없는 .webp 파일은 삭제된다."""
        orphan_dir = Path(tmp_path) / THUMBCACHE_DIR / "zz"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "zzdeadbeef.webp"
        orphan.write_bytes(b"fake")
        count = purge_orphan_thumbnails(db, str(tmp_path))
        assert count == 1
        assert not orphan.exists()

    def test_valid_thumb_preserved(self, db, tmp_path):
        """DB에 있는 썸네일은 삭제되지 않는다."""
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        result = generate_thumbnail(db, src, str(tmp_path), file_id, "h")
        count = purge_orphan_thumbnails(db, str(tmp_path))
        assert count == 0
        assert Path(result).exists()

    def test_no_thumbcache_dir_returns_zero(self, db, tmp_path):
        """thumbcache 디렉토리가 없으면 0 반환."""
        count = purge_orphan_thumbnails(db, str(tmp_path))
        assert count == 0


# ---------------------------------------------------------------------------
# needs_regeneration
# ---------------------------------------------------------------------------

class TestNeedsRegeneration:
    def test_no_cache_returns_true(self, db):
        assert needs_regeneration(db, "missing_id", "any_hash") is True

    def test_same_hash_returns_false(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        generate_thumbnail(db, src, str(tmp_path), file_id, "stable_hash")
        assert needs_regeneration(db, file_id, "stable_hash") is False

    def test_different_hash_returns_true(self, db, tmp_path):
        group_id = _insert_group(db)
        file_id = _insert_file(db, group_id)
        src = str(tmp_path / "src.jpg")
        _make_image(src)
        generate_thumbnail(db, src, str(tmp_path), file_id, "old_hash")
        assert needs_regeneration(db, file_id, "new_hash") is True
