"""metadata enrichment Phase 1 / Phase 2 분리 구조 테스트.

확인 사항:
- fetch_and_store_pixiv_metadata: DB only (파일 write 없음)
- write_stored_metadata_to_file: 파일 write only (Pixiv API 없음)
- enrich_file_from_pixiv: Phase 1 + Phase 2 wrapper 호환
- json_only 상태도 분류 미리보기에 사용 가능
"""
from __future__ import annotations

import io
import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from PIL import Image as PILImage

from core.adapters.pixiv import PixivNetworkError, PixivRestrictedError, PixivNotFoundError
from core.metadata_enricher import (
    fetch_and_store_pixiv_metadata,
    write_stored_metadata_to_file,
    enrich_file_from_pixiv,
)


# ---------------------------------------------------------------------------
# fixtures & helpers (기존 test_metadata_enricher.py 패턴 동일)
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


def _insert_group(conn: sqlite3.Connection, group_id: str, artwork_id: str,
                  sync_status: str = "metadata_missing") -> None:
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, ?, ?, ?, ?)""",
        (group_id, artwork_id, _now(), _now(), sync_status),
    )
    conn.commit()


def _insert_file(conn: sqlite3.Connection, file_id: str, group_id: str,
                 file_path: str, file_format: str = "jpg",
                 page_index: int = 0) -> None:
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at)
           VALUES (?, ?, ?, 'original', ?, ?, ?)""",
        (file_id, group_id, page_index, file_path, file_format, _now()),
    )
    conn.commit()


def _make_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    PILImage.new("RGB", (1, 1), (128, 64, 32)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())


def _make_adapter(artwork_id: str = "12345678") -> MagicMock:
    from core.models import AruMetadata
    adapter = MagicMock()
    adapter.fetch_metadata.return_value = {
        "illustId": artwork_id, "title": "Test Art", "userId": "999",
        "userName": "TestArtist", "pageCount": 1, "illustType": 0,
        "tags": {"tags": [{"tag": "ブルーアーカイブ"}, {"tag": "アル"}]},
    }
    meta = AruMetadata(
        artwork_id=artwork_id, artwork_title="Test Art",
        artist_id="999", artist_name="TestArtist",
        artist_url="https://www.pixiv.net/users/999",
        tags=["tag1"], series_tags=["Blue Archive"], character_tags=["アル"],
        raw_tags=["ブルーアーカイブ", "アル"],
    )
    adapter.to_aru_metadata.return_value = meta
    return adapter


# ---------------------------------------------------------------------------
# TestFetchAndStore — Phase 1
# ---------------------------------------------------------------------------

class TestFetchAndStore:
    def test_success_returns_ok_and_json_only(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 성공 → status='ok', sync_status='json_only'."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        r = fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())

        assert r["status"] == "ok"
        assert r["phase"] == "fetch_store"
        assert r["sync_status"] == "json_only"
        assert r["error"] is None

        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row["metadata_sync_status"] == "json_only"

    def test_no_file_write_occurs(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1은 파일 write 함수를 절대 호출하지 않는다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        with patch("core.metadata_enricher.write_aru_metadata") as mock_write, \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool") as mock_xmp:
            fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())
            mock_write.assert_not_called()
            mock_xmp.assert_not_called()

    def test_raw_tags_stored_in_db(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 성공 시 raw_tags_json이 DB에 저장된다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())

        row = db.execute(
            "SELECT raw_tags_json FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        raw_tags = json.loads(row["raw_tags_json"])
        assert "ブルーアーカイブ" in raw_tags or "アル" in raw_tags

    def test_full_status_preserved_on_restricted(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """full 상태는 PixivRestrictedError가 와도 downgrade되지 않는다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678", sync_status="full")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivRestrictedError("403 restricted")

        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["status"] == "error"
        assert r["error"] == "restricted"
        # full 상태 보호: sync_status=None (downgrade 없음)
        assert r["sync_status"] is None

        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row["metadata_sync_status"] == "full"

    def test_restricted_non_full_sets_metadata_write_failed(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """non-full 상태에서 PixivRestrictedError → metadata_write_failed."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678", sync_status="metadata_missing")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivRestrictedError("403")

        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["error"] == "restricted"
        assert r["sync_status"] == "metadata_write_failed"

    def test_not_found_non_full_sets_source_unavailable(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """non-full 상태에서 PixivNotFoundError → source_unavailable."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678", sync_status="metadata_missing")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivNotFoundError("404")

        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["error"] == "not_found_at_source"
        assert r["sync_status"] == "source_unavailable"

    def test_network_error_no_status_change(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """PixivNetworkError → status 변경 없음, 기존 sync_status 유지."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678", sync_status="metadata_missing")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivNetworkError("timeout")

        r = fetch_and_store_pixiv_metadata(db, fid, adapter=adapter)

        assert r["error"] == "network_error"
        # DB sync_status는 변경되지 않아야 함
        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row["metadata_sync_status"] == "metadata_missing"

    def test_unknown_file_id_returns_error(self, db: sqlite3.Connection) -> None:
        """존재하지 않는 file_id → error not_found."""
        r = fetch_and_store_pixiv_metadata(db, "nonexistent-id")
        assert r["status"] == "error"
        assert r["error"] == "not_found"
        assert r["group_id"] is None


# ---------------------------------------------------------------------------
# TestWriteStoredMetadata — Phase 2
# ---------------------------------------------------------------------------

class TestWriteStoredMetadata:
    def _setup(self, db: sqlite3.Connection, tmp_path: Path,
               sync_status: str = "json_only") -> tuple[str, str, Path]:
        """공통 셋업: group + file + DB metadata + 물리 파일 생성."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678", sync_status=sync_status)
        # artwork_groups에 metadata 직접 저장 (Phase 1 완료 시뮬레이션)
        db.execute(
            """UPDATE artwork_groups SET
               artwork_title='Test Art', artist_name='TestArtist',
               artist_id='999', artist_url='https://www.pixiv.net/users/999',
               tags_json='["tag1"]', series_tags_json='["Blue Archive"]',
               character_tags_json='["アル"]', raw_tags_json='["ブルーアーカイブ"]'
               WHERE group_id = ?""",
            (gid,),
        )
        db.commit()
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))
        return gid, fid, img

    def test_success_json_only_no_exiftool(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """exiftool 없으면 Phase 2 성공 → sync_status='json_only'."""
        gid, fid, _ = self._setup(db, tmp_path)

        with patch("core.metadata_enricher.write_aru_metadata") as mock_write:
            r = write_stored_metadata_to_file(db, fid, exiftool_path=None)

        assert r["status"] == "ok"
        assert r["phase"] == "metadata_write"
        assert r["sync_status"] == "json_only"
        assert r["error"] is None
        mock_write.assert_called_once()

    def test_success_full_with_exiftool(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """exiftool 제공 + 성공 → sync_status='full'."""
        gid, fid, _ = self._setup(db, tmp_path)

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool",
                   return_value=True) as mock_xmp:
            r = write_stored_metadata_to_file(db, fid, exiftool_path="/fake/exiftool")

        assert r["sync_status"] == "full"
        mock_xmp.assert_called_once()

        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row["metadata_sync_status"] == "full"

    def test_no_pixiv_api_called(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 2는 PixivAdapter를 절대 호출하지 않는다."""
        gid, fid, _ = self._setup(db, tmp_path)

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.adapters.pixiv.PixivAdapter") as mock_adapter_cls:
            write_stored_metadata_to_file(db, fid)
            mock_adapter_cls.assert_not_called()

    def test_missing_artwork_id_returns_skipped(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """DB에 artwork_id 없으면 status='skipped', error='metadata_missing'."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        # artwork_id가 빈 group
        db.execute(
            "INSERT INTO artwork_groups (group_id, artwork_id, downloaded_at, indexed_at) "
            "VALUES (?, '', ?, ?)",
            (gid, _now(), _now()),
        )
        db.commit()
        img = tmp_path / "no_id.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        r = write_stored_metadata_to_file(db, fid)
        assert r["status"] == "skipped"
        assert r["error"] == "metadata_missing"

    def test_missing_file_returns_error(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """물리 파일 없으면 status='error', error='missing_file'."""
        gid, fid, img = self._setup(db, tmp_path)
        img.unlink()  # 물리 파일 삭제

        r = write_stored_metadata_to_file(db, fid)
        assert r["status"] == "error"
        assert r["error"] == "missing_file"

    def test_clear_first_when_existing_status(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """기존 등록 상태(full/json_only 등)에서 Phase 2 실행 시 clear-first=True."""
        gid, fid, _ = self._setup(db, tmp_path, sync_status="full")

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool",
                   return_value=True) as mock_xmp:
            write_stored_metadata_to_file(db, fid, exiftool_path="/fake/exiftool")

        call_kwargs = mock_xmp.call_args.kwargs
        assert call_kwargs.get("clear_windows_xp_fields_before_write") is True

    def test_embed_failed_sets_metadata_write_failed(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """write_aru_metadata 실패 → sync_status='metadata_write_failed', status='error'."""
        gid, fid, _ = self._setup(db, tmp_path)

        with patch("core.metadata_enricher.write_aru_metadata",
                   side_effect=OSError("disk full")):
            r = write_stored_metadata_to_file(db, fid)

        assert r["status"] == "error"
        assert r["error"] == "embed_failed"
        assert r["sync_status"] == "metadata_write_failed"

    def test_xmp_write_failed_status(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """XMP 기록 실패 → sync_status='xmp_write_failed'."""
        from core.metadata_writer import XmpWriteError
        gid, fid, _ = self._setup(db, tmp_path)

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool",
                   side_effect=XmpWriteError("exiftool failed")):
            r = write_stored_metadata_to_file(db, fid, exiftool_path="/fake/exiftool")

        assert r["sync_status"] == "xmp_write_failed"


# ---------------------------------------------------------------------------
# TestEnrichWrapper — 기존 enrich_file_from_pixiv wrapper 호환
# ---------------------------------------------------------------------------

class TestEnrichWrapper:
    def test_wrapper_success_returns_success_status(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """wrapper 성공 → status='success', sync_status='json_only' (no exiftool)."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        with patch("core.metadata_enricher.write_aru_metadata"):
            r = enrich_file_from_pixiv(db, fid, adapter=_make_adapter())

        assert r["status"] == "success"
        assert r["sync_status"] == "json_only"
        assert "message" in r

    def test_wrapper_phase1_network_error_returns_network_error(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 네트워크 오류 → wrapper status='network_error'."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivNetworkError("timeout")
        r = enrich_file_from_pixiv(db, fid, adapter=adapter)

        assert r["status"] == "network_error"
        assert "message" in r

    def test_wrapper_phase2_embed_failed_returns_embed_failed(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 2 파일 쓰기 실패 → wrapper status='embed_failed'."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        with patch("core.metadata_enricher.write_aru_metadata",
                   side_effect=OSError("disk full")):
            r = enrich_file_from_pixiv(db, fid, adapter=_make_adapter())

        assert r["status"] == "embed_failed"
        assert "sync_status" in r
        assert "message" in r

    def test_wrapper_preserves_all_required_keys(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """wrapper 반환 dict에 status/sync_status/message 키가 모두 있다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        with patch("core.metadata_enricher.write_aru_metadata"):
            r = enrich_file_from_pixiv(db, fid, adapter=_make_adapter())

        for key in ("status", "sync_status", "message"):
            assert key in r, f"key '{key}' missing from enrich_file_from_pixiv result"

    def test_wrapper_not_found_file_id(self, db: sqlite3.Connection) -> None:
        """file_id 없으면 status='not_found'."""
        r = enrich_file_from_pixiv(db, "nonexistent-id")
        assert r["status"] == "not_found"

    def test_wrapper_full_sync_status_with_exiftool(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """exiftool 제공 + 모두 성공 → sync_status='full'."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool",
                   return_value=True):
            r = enrich_file_from_pixiv(
                db, fid, adapter=_make_adapter(), exiftool_path="/fake/exiftool"
            )

        assert r["status"] == "success"
        assert r["sync_status"] == "full"


# ---------------------------------------------------------------------------
# TestJsonOnlyClassificationCompat — json_only 분류 미리보기 호환
# ---------------------------------------------------------------------------

class TestJsonOnlyClassificationCompat:
    def test_json_only_has_series_and_character_tags(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 완료 후 json_only 상태에서도 series/character_tags_json이 DB에 있다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_file(db, fid, gid, str(img))

        fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())

        row = db.execute(
            "SELECT metadata_sync_status, series_tags_json, character_tags_json "
            "FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()

        assert row["metadata_sync_status"] == "json_only"
        series = json.loads(row["series_tags_json"] or "[]")
        chars  = json.loads(row["character_tags_json"] or "[]")
        # Phase 1에서 저장된 태그로 분류 미리보기가 가능해야 함
        assert isinstance(series, list)
        assert isinstance(chars, list)
        assert len(series) > 0 or len(chars) > 0
