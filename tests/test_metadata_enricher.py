"""metadata_enricher — enrich_file_from_pixiv() 테스트."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.adapters.pixiv import (
    PixivNetworkError,
    PixivRestrictedError,
)
from core.metadata_enricher import enrich_file_from_pixiv


# ---------------------------------------------------------------------------
# 임시 DB 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    db_path = str(tmp_path / "test.db")
    conn = initialize_database(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_group(conn: sqlite3.Connection, group_id: str, artwork_id: str) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, ?, ?, ?, 'metadata_missing')""",
        (group_id, artwork_id, now, now),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection,
    file_id: str,
    group_id: str,
    file_path: str,
    file_format: str = "jpg",
    page_index: int = 0,
) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at)
           VALUES (?, ?, ?, 'original', ?, ?, ?)""",
        (file_id, group_id, page_index, file_path, file_format, now),
    )
    conn.commit()


def _make_adapter(
    body: dict | None = None,
    error: Exception | None = None,
) -> MagicMock:
    adapter = MagicMock()
    if error:
        adapter.fetch_metadata.side_effect = error
    else:
        adapter.fetch_metadata.return_value = body or {}
        from core.models import AruMetadata
        from datetime import datetime, timezone
        meta = AruMetadata(
            artwork_id=(body or {}).get("illustId", "123"),
            artwork_title=(body or {}).get("title", "Test"),
            artist_id="999",
            artist_name="Artist",
            artist_url="https://www.pixiv.net/users/999",
            tags=["tag1"],
            downloaded_at=datetime.now(timezone.utc).isoformat(),
            _provenance={"source": "pixiv_ajax_api", "confidence": "high",
                         "captured_at": datetime.now(timezone.utc).isoformat()},
        )
        adapter.to_aru_metadata.return_value = meta
    return adapter


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------

class TestEnrichFileFromPixiv:
    def test_success(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        import io
        from PIL import Image as PILImage
        img_path = tmp_path / "12345678_p0.jpg"
        buf = io.BytesIO()
        PILImage.new("RGB", (1, 1), (128, 64, 32)).save(buf, format="JPEG")
        img_path.write_bytes(buf.getvalue())
        img = img_path

        group_id = str(uuid.uuid4())
        file_id  = str(uuid.uuid4())
        _insert_group(db, group_id, "12345678")
        _insert_file(db, file_id, group_id, str(img), "jpg")

        body = {"illustId": "12345678", "title": "My Art", "userId": "999",
                "userName": "Artist", "pageCount": 1, "illustType": 0,
                "tags": {"tags": [{"tag": "original"}]}}
        adapter = _make_adapter(body=body)

        result = enrich_file_from_pixiv(db, file_id, adapter=adapter)

        assert result["status"] == "success"
        assert result["sync_status"] == "json_only"
        assert "My Art" in result["message"] or "12345678" in result["message"]

        # DB 갱신 확인
        row = db.execute(
            "SELECT metadata_sync_status, artist_name, tags_json "
            "FROM artwork_groups WHERE group_id = ?", (group_id,)
        ).fetchone()
        assert row["metadata_sync_status"] == "json_only"
        assert row["artist_name"] == "Artist"
        tags = json.loads(row["tags_json"])
        assert "tag1" in tags

        f_row = db.execute(
            "SELECT metadata_embedded FROM artwork_files WHERE file_id = ?",
            (file_id,)
        ).fetchone()
        assert f_row["metadata_embedded"] == 1

    def test_not_found_file_id(self, db: sqlite3.Connection) -> None:
        result = enrich_file_from_pixiv(db, "nonexistent-file-id")
        assert result["status"] == "not_found"

    def test_no_artwork_id(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        img = tmp_path / "random_photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")

        group_id = str(uuid.uuid4())
        file_id  = str(uuid.uuid4())
        _insert_group(db, group_id, "unknown")
        _insert_file(db, file_id, group_id, str(img), "jpg")

        result = enrich_file_from_pixiv(db, file_id)
        assert result["status"] == "no_artwork_id"

    def test_network_error(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        img = tmp_path / "12345678_p0.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")

        group_id = str(uuid.uuid4())
        file_id  = str(uuid.uuid4())
        _insert_group(db, group_id, "12345678")
        _insert_file(db, file_id, group_id, str(img), "jpg")

        adapter = _make_adapter(error=PixivNetworkError("connection refused"))
        result = enrich_file_from_pixiv(db, file_id, adapter=adapter)
        assert result["status"] == "network_error"
        assert result["sync_status"] is None

    def test_restricted(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        img = tmp_path / "12345678_p0.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")

        group_id = str(uuid.uuid4())
        file_id  = str(uuid.uuid4())
        _insert_group(db, group_id, "12345678")
        _insert_file(db, file_id, group_id, str(img), "jpg")

        adapter = _make_adapter(error=PixivRestrictedError("403 forbidden"))
        result = enrich_file_from_pixiv(db, file_id, adapter=adapter)
        assert result["status"] == "restricted"
        assert result["sync_status"] == "metadata_write_failed"

        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?",
            (group_id,)
        ).fetchone()
        assert row["metadata_sync_status"] == "metadata_write_failed"

    def test_embed_failed(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        img = tmp_path / "12345678_p0.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")  # 유효하지 않은 JPEG (piexif 실패)

        group_id = str(uuid.uuid4())
        file_id  = str(uuid.uuid4())
        _insert_group(db, group_id, "12345678")
        _insert_file(db, file_id, group_id, str(img), "jpg")

        body = {"illustId": "12345678", "title": "Test", "userId": "1",
                "userName": "X", "pageCount": 1, "illustType": 0,
                "tags": {"tags": []}}
        adapter = _make_adapter(body=body)

        # write_aru_metadata가 예외를 던지도록 패치
        with patch("core.metadata_enricher.write_aru_metadata",
                   side_effect=RuntimeError("piexif error")):
            result = enrich_file_from_pixiv(db, file_id, adapter=adapter)

        assert result["status"] == "embed_failed"
        assert result["sync_status"] == "metadata_write_failed"

    def test_series_character_tags_stored(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """classify_pixiv_tags() 통합: series/character 태그가 DB에 올바르게 저장된다."""
        import io
        from PIL import Image as PILImage
        from core.adapters.pixiv import PixivAdapter

        img_path = tmp_path / "12345678_p0.jpg"
        buf = io.BytesIO()
        PILImage.new("RGB", (1, 1), (64, 64, 64)).save(buf, format="JPEG")
        img_path.write_bytes(buf.getvalue())

        group_id = str(uuid.uuid4())
        file_id  = str(uuid.uuid4())
        _insert_group(db, group_id, "12345678")
        _insert_file(db, file_id, group_id, str(img_path), "jpg")

        real_adapter = PixivAdapter()
        body = {
            "illustId": "12345678", "title": "BA Art",
            "userId": "999", "userName": "BAFan",
            "pageCount": 1, "illustType": 0,
            "tags": {"tags": [
                {"tag": "ブルアカ"},
                {"tag": "伊落マリー"},
                {"tag": "ソロ"},
            ]},
        }
        mock_adapter = MagicMock()
        mock_adapter.fetch_metadata.return_value = body
        mock_adapter.to_aru_metadata.side_effect = (
            lambda *a, **kw: real_adapter.to_aru_metadata(*a, **kw)
        )

        result = enrich_file_from_pixiv(db, file_id, adapter=mock_adapter)
        assert result["status"] == "success"

        row = db.execute(
            "SELECT series_tags_json, character_tags_json, tags_json "
            "FROM artwork_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        series = json.loads(row["series_tags_json"])
        chars  = json.loads(row["character_tags_json"])
        general = json.loads(row["tags_json"])

        assert "Blue Archive" in series
        assert "伊落マリー" in chars
        assert "ソロ" in general
        assert "ブルアカ" not in general

        tags_rows = db.execute(
            "SELECT tag, tag_type FROM tags WHERE group_id = ?", (group_id,)
        ).fetchall()
        type_map = {r["tag"]: r["tag_type"] for r in tags_rows}
        assert type_map.get("Blue Archive") == "series"
        assert type_map.get("伊落マリー")   == "character"
        assert type_map.get("ソロ")         == "general"

    def test_png_success(self, db: sqlite3.Connection, tmp_path: Path) -> None:
        # 최소 유효 PNG
        png_data = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        img = tmp_path / "12345678_p0.png"
        img.write_bytes(png_data)

        group_id = str(uuid.uuid4())
        file_id  = str(uuid.uuid4())
        _insert_group(db, group_id, "12345678")
        _insert_file(db, file_id, group_id, str(img), "png")

        body = {"illustId": "12345678", "title": "PNG Art", "userId": "2",
                "userName": "PNG Artist", "pageCount": 1, "illustType": 0,
                "tags": {"tags": [{"tag": "PNG테스트"}]}}
        adapter = _make_adapter(body=body)

        result = enrich_file_from_pixiv(db, file_id, adapter=adapter)
        assert result["status"] == "success"
