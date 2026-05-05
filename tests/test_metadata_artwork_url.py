"""Phase 2 artwork_url 자동 생성 및 artwork_id 복구 테스트.

write_stored_metadata_to_file이 파일에 기록하는 UserComment JSON과
XMP-dc:Source가 올바른 Pixiv 작품 URL을 포함하는지 검증한다.

핵심 시나리오:
  A. 숫자 artwork_id + artwork_url 없음 → artwork_url 자동 생성
  B. hash artwork_id + Pixiv 파일명   → artwork_id 숫자 복구 후 artwork_url 생성
  C. hash artwork_id + 비Pixiv 파일명 → artwork_url 생성 불가 (현상 유지)
  D. 숫자 artwork_id + artwork_url 있음 → 기존 URL 유지 (덮어쓰기 없음)
"""
from __future__ import annotations

import io
import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PILImage


# ---------------------------------------------------------------------------
# fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _make_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    PILImage.new("RGB", (1, 1)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())


def _insert_group(
    conn: sqlite3.Connection,
    group_id: str,
    artwork_id: str,
    artwork_url: str = "",
    sync_status: str = "json_only",
) -> None:
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artwork_url,
            artist_id, artist_name, artist_url,
            downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, 'pixiv', ?, ?, '', '', '', ?, ?, ?)""",
        (group_id, artwork_id, artwork_url, _now(), _now(), sync_status),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection,
    file_id: str,
    group_id: str,
    file_path: str,
    file_format: str = "jpg",
) -> None:
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format,
            created_at, file_status)
           VALUES (?, ?, 0, 'original', ?, ?, ?, 'present')""",
        (file_id, group_id, file_path, file_format, _now()),
    )
    conn.commit()


def _read_user_comment_json(file_path: str) -> dict:
    """piexif로 UserComment UNICODE\\0 payload를 읽어 JSON dict 반환."""
    import piexif
    exif = piexif.load(file_path)
    uc = exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b"")
    assert uc.startswith(b"UNICODE\x00"), f"UserComment에 UNICODE prefix 없음: {uc[:16]}"
    payload_bytes = uc[8:]
    return json.loads(payload_bytes.decode("utf-16-le"))


def _run_phase2(conn, file_id, tmp_path) -> dict:
    from core.metadata_enricher import write_stored_metadata_to_file
    return write_stored_metadata_to_file(conn, file_id, exiftool_path=None)


# ---------------------------------------------------------------------------
# A. 숫자 artwork_id + DB artwork_url 없음 → artwork_url 자동 생성
# ---------------------------------------------------------------------------

class TestNumericArtworkIdUrlGeneration:
    def test_artwork_url_generated_from_numeric_id(self, db, tmp_path):
        """숫자 artwork_id가 있고 artwork_url이 비어 있으면 /artworks/{id} URL 생성."""
        img = tmp_path / "88908024_p0_master1200.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="88908024", artwork_url="")
        _insert_file(db, fid, gid, str(img))

        result = _run_phase2(db, fid, tmp_path)
        assert result["status"] == "ok", result

        meta = _read_user_comment_json(str(img))
        assert meta["artwork_url"] == "https://www.pixiv.net/artworks/88908024"
        assert meta["artwork_id"] == "88908024"

    def test_artwork_url_generation_writes_correct_pixiv_url(self, db, tmp_path):
        """생성된 URL이 Pixiv /artworks/ 형식인지 확인."""
        img = tmp_path / "72043386_p0.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="72043386", artwork_url="")
        _insert_file(db, fid, gid, str(img))

        _run_phase2(db, fid, tmp_path)
        meta = _read_user_comment_json(str(img))
        assert meta["artwork_url"].startswith("https://www.pixiv.net/artworks/")
        assert "72043386" in meta["artwork_url"]


# ---------------------------------------------------------------------------
# B. hash artwork_id + Pixiv 파일명 → 숫자 ID 복구 + artwork_url 생성
# ---------------------------------------------------------------------------

class TestHashArtworkIdFilenameRecovery:
    def test_hash_id_recovered_from_pixiv_filename(self, db, tmp_path):
        """DB artwork_id가 hash이면 파일명에서 숫자 Pixiv ID를 복구한다."""
        img = tmp_path / "88908024_p0_master1200.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="89b60d43b5d23e86", artwork_url="")
        _insert_file(db, fid, gid, str(img))

        result = _run_phase2(db, fid, tmp_path)
        assert result["status"] == "ok", result

        meta = _read_user_comment_json(str(img))
        # 파일명에서 복구한 숫자 ID가 쓰여야 함
        assert meta["artwork_id"] == "88908024"
        assert meta["artwork_url"] == "https://www.pixiv.net/artworks/88908024"

    @pytest.mark.parametrize("hash_val,filename,expected_id", [
        ("d43965258a880b20", "72043386_p0_master1200.webp", "72043386"),
        ("ea6f21659f3a6d5f", "78563767_p5_master1200.jpg",  "78563767"),
        ("c7ebd6a56a72929a", "72043386_p0.png",             "72043386"),
    ])
    def test_reported_hash_placeholders(self, db, tmp_path, hash_val, filename, expected_id):
        """실제 보고된 hash placeholder 값들로 복구 경로 검증."""
        img = tmp_path / filename
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id=hash_val, artwork_url="")
        _insert_file(db, fid, gid, str(img))

        result = _run_phase2(db, fid, tmp_path)
        assert result["status"] == "ok", result

        meta = _read_user_comment_json(str(img))
        assert meta["artwork_id"] == expected_id
        assert meta["artwork_url"] == f"https://www.pixiv.net/artworks/{expected_id}"


# ---------------------------------------------------------------------------
# C. hash artwork_id + 비Pixiv 파일명 → artwork_url 생성 불가
# ---------------------------------------------------------------------------

class TestHashArtworkIdNoFilenameMatch:
    def test_non_pixiv_filename_no_url_generated(self, db, tmp_path):
        """파일명이 Pixiv 패턴이 아니면 artwork_url은 빈 문자열 유지."""
        img = tmp_path / "sample_photo.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="c7ebd6a56a72929a", artwork_url="")
        _insert_file(db, fid, gid, str(img))

        result = _run_phase2(db, fid, tmp_path)
        assert result["status"] == "ok", result

        meta = _read_user_comment_json(str(img))
        # 복구 불가 → 원래 hash 유지, artwork_url 비어 있음
        assert meta["artwork_id"] == "c7ebd6a56a72929a"
        assert meta["artwork_url"] == ""

    def test_short_numeric_filename_not_matched(self, db, tmp_path):
        """5자리 이하 숫자 파일명은 Pixiv ID로 오인하지 않는다."""
        img = tmp_path / "12345.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="c7ebd6a56a72929a", artwork_url="")
        _insert_file(db, fid, gid, str(img))

        result = _run_phase2(db, fid, tmp_path)
        assert result["status"] == "ok", result

        meta = _read_user_comment_json(str(img))
        assert meta["artwork_url"] == ""


# ---------------------------------------------------------------------------
# D. 숫자 artwork_id + DB artwork_url 이미 있음 → 기존 URL 유지
# ---------------------------------------------------------------------------

class TestExistingArtworkUrlPreserved:
    def test_existing_artwork_url_not_overwritten(self, db, tmp_path):
        """DB에 artwork_url이 이미 있으면 덮어쓰지 않는다."""
        existing_url = "https://www.pixiv.net/artworks/88908024"
        img = tmp_path / "88908024_p0_master1200.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="88908024", artwork_url=existing_url)
        _insert_file(db, fid, gid, str(img))

        _run_phase2(db, fid, tmp_path)
        meta = _read_user_comment_json(str(img))
        assert meta["artwork_url"] == existing_url

    def test_custom_artwork_url_preserved(self, db, tmp_path):
        """DB의 커스텀 artwork_url이 그대로 파일에 기록된다."""
        custom_url = "https://www.pixiv.net/artworks/99999999"
        img = tmp_path / "88908024_p0.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="88908024", artwork_url=custom_url)
        _insert_file(db, fid, gid, str(img))

        _run_phase2(db, fid, tmp_path)
        meta = _read_user_comment_json(str(img))
        assert meta["artwork_url"] == custom_url


# ---------------------------------------------------------------------------
# E. DB 변경 없음 확인 (write_stored_metadata_to_file은 파일만 바꿈)
# ---------------------------------------------------------------------------

class TestDatabaseNotModifiedByPhase2Fix:
    def test_db_artwork_id_unchanged_after_phase2(self, db, tmp_path):
        """파일명 복구는 파일 write에만 영향. DB artwork_id는 변경하지 않는다."""
        hash_val = "89b60d43b5d23e86"
        img = tmp_path / "88908024_p0_master1200.jpg"
        _make_jpg(img)

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id=hash_val, artwork_url="")
        _insert_file(db, fid, gid, str(img))

        _run_phase2(db, fid, tmp_path)

        row = db.execute(
            "SELECT artwork_id, artwork_url FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        # DB는 변경하지 않는다
        assert row["artwork_id"] == hash_val
