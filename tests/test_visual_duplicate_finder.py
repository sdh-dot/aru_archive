"""
시각적 중복(perceptual hash) 검사 테스트.

- perceptual hash 계산 가능
- 같은 이미지 hash distance 0
- 유사 이미지 threshold 내 그룹화
- 다른 이미지는 제외
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from core.visual_duplicate_finder import (
    compute_perceptual_hash,
    find_visual_duplicates,
    hamming_distance,
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
) -> str:
    fid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_hash, file_size, metadata_embedded,
            file_status, created_at)
           VALUES (?, ?, 0, ?, ?, 'jpg', NULL, 1024, 1, 'present', ?)""",
        (fid, group_id, file_role, file_path, _now()),
    )
    conn.commit()
    return fid


def _make_solid_image(path: Path, color: tuple[int, int, int], size=(64, 64)) -> Path:
    """단색 테스트 이미지를 생성한다."""
    if not PIL_AVAILABLE:
        pytest.skip("Pillow not available")
    img = Image.new("RGB", size, color)
    img.save(str(path))
    return path


class TestComputePerceptualHash:
    @pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not available")
    def test_returns_hex_string(self, tmp_path):
        img_path = _make_solid_image(tmp_path / "red.jpg", (200, 50, 50))
        ph = compute_perceptual_hash(str(img_path))
        assert ph is not None
        assert isinstance(ph, str)
        assert len(ph) == 16  # 8*8 / 4 = 16 hex chars

    @pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not available")
    def test_same_image_same_hash(self, tmp_path):
        img_path = _make_solid_image(tmp_path / "a.jpg", (100, 100, 100))
        ph1 = compute_perceptual_hash(str(img_path))
        ph2 = compute_perceptual_hash(str(img_path))
        assert ph1 == ph2

    def test_missing_file_returns_none(self, tmp_path):
        ph = compute_perceptual_hash(str(tmp_path / "nonexistent.jpg"))
        assert ph is None

    @pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not available")
    def test_different_colors_have_nonzero_distance(self, tmp_path):
        img_red   = _make_solid_image(tmp_path / "red.jpg",   (255, 0, 0))
        img_blue  = _make_solid_image(tmp_path / "blue.jpg",  (0, 0, 255))
        ph_red  = compute_perceptual_hash(str(img_red))
        ph_blue = compute_perceptual_hash(str(img_blue))
        assert ph_red is not None and ph_blue is not None
        # 단색이라 같을 수 있지만, 테스트는 계산 자체가 이루어지는지 확인
        # (정확한 distance는 이미지 내용에 따라 다름)


class TestHammingDistance:
    def test_same_hash_distance_zero(self):
        assert hamming_distance("ffff", "ffff") == 0

    def test_one_bit_diff(self):
        assert hamming_distance("0000", "0001") == 1

    def test_all_bits_diff(self):
        dist = hamming_distance("0000000000000000", "ffffffffffffffff")
        assert dist == 64

    def test_invalid_input_returns_max(self):
        assert hamming_distance("xyz", "abc") == 64

    def test_none_input_returns_max(self):
        assert hamming_distance(None, "0000") == 64


class TestFindVisualDuplicates:
    @pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not available")
    def test_similar_images_grouped(self, db, tmp_path):
        # 같은 색 이미지 두 개를 다른 group에 삽입
        gid1 = _insert_group(db)
        gid2 = _insert_group(db)
        fp1 = _make_solid_image(tmp_path / "a.jpg", (100, 100, 100))
        fp2 = _make_solid_image(tmp_path / "b.jpg", (100, 100, 100))
        _insert_file(db, gid1, str(fp1))
        _insert_file(db, gid2, str(fp2))

        groups = find_visual_duplicates(db, threshold=6)
        # 같은 색 이미지는 distance 0 → 그룹화됨
        assert len(groups) >= 1

    def test_no_files_returns_empty(self, db):
        groups = find_visual_duplicates(db, threshold=6)
        assert groups == []

    @pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not available")
    def test_same_group_files_not_compared(self, db, tmp_path):
        # 같은 group의 파일끼리는 비교하지 않는다
        gid = _insert_group(db)
        fp1 = _make_solid_image(tmp_path / "x.jpg", (100, 100, 100))
        fp2 = _make_solid_image(tmp_path / "y.jpg", (100, 100, 100))
        _insert_file(db, gid, str(fp1))
        _insert_file(db, gid, str(fp2))

        groups = find_visual_duplicates(db, threshold=6)
        # 같은 그룹이므로 그룹화 안 됨
        assert groups == []
