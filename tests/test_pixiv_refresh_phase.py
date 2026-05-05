"""enrich_file_from_pixiv() status transition 테스트 (PR #127).

검증 항목:
- full 상태에서 PixivRestrictedError/PixivNotFoundError가 발생해도 DB status 유지
- full 이외 상태에서 fetch 실패 시 정상 downgrade
- previous_status에 따른 clear_windows_xp_fields_before_write 분기
- _get_previous_status() helper
- _EXISTING_REGISTRATION_STATUSES frozenset 내용
"""
from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import MagicMock, patch

import pytest

from core.metadata_enricher import (
    _EXISTING_REGISTRATION_STATUSES,
    _get_previous_status,
    enrich_file_from_pixiv,
)


# ---------------------------------------------------------------------------
# 공통 픽스처 헬퍼
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""
        CREATE TABLE artwork_groups (
            group_id              TEXT PRIMARY KEY,
            source_site           TEXT NOT NULL DEFAULT 'pixiv',
            artwork_id            TEXT,
            artwork_url           TEXT,
            artwork_title         TEXT,
            artist_id             TEXT,
            artist_name           TEXT,
            artist_url            TEXT,
            total_pages           INTEGER,
            tags_json             TEXT,
            series_tags_json      TEXT,
            character_tags_json   TEXT,
            raw_tags_json         TEXT,
            metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
            indexed_at            TEXT NOT NULL DEFAULT '2024-01-01T00:00:00+00:00',
            updated_at            TEXT,
            downloaded_at         TEXT NOT NULL DEFAULT '2024-01-01T00:00:00+00:00',
            schema_version        TEXT NOT NULL DEFAULT '1.0'
        )
    """)
    conn.execute("""
        CREATE TABLE artwork_files (
            file_id           TEXT PRIMARY KEY,
            group_id          TEXT NOT NULL,
            page_index        INTEGER NOT NULL DEFAULT 0,
            file_role         TEXT NOT NULL DEFAULT 'original',
            file_path         TEXT NOT NULL DEFAULT '',
            file_format       TEXT NOT NULL DEFAULT 'jpg',
            file_status       TEXT NOT NULL DEFAULT 'present',
            metadata_embedded INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL DEFAULT '2024-01-01T00:00:00+00:00'
        )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS tags (group_id TEXT, tag TEXT, tag_type TEXT)")
    conn.commit()
    return conn


def _insert_group(conn: sqlite3.Connection, sync_status: str, artwork_id: str = "12345678") -> str:
    group_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO artwork_groups (group_id, artwork_id, metadata_sync_status) VALUES (?, ?, ?)",
        (group_id, artwork_id, sync_status),
    )
    conn.commit()
    return group_id


def _insert_file(conn: sqlite3.Connection, group_id: str, file_path: str) -> str:
    file_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO artwork_files (file_id, group_id, file_path) VALUES (?, ?, ?)",
        (file_id, group_id, file_path),
    )
    conn.commit()
    return file_id


def _get_sync_status(conn: sqlite3.Connection, group_id: str) -> str | None:
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    return row["metadata_sync_status"] if row else None


# ---------------------------------------------------------------------------
# _get_previous_status helper
# ---------------------------------------------------------------------------

class TestGetPreviousStatus:
    def test_returns_existing_status(self):
        conn = _make_conn()
        gid = _insert_group(conn, "full")
        assert _get_previous_status(conn, gid) == "full"

    def test_returns_none_for_missing_group(self):
        conn = _make_conn()
        assert _get_previous_status(conn, "nonexistent-id") is None

    def test_returns_metadata_missing(self):
        conn = _make_conn()
        gid = _insert_group(conn, "metadata_missing")
        assert _get_previous_status(conn, gid) == "metadata_missing"


# ---------------------------------------------------------------------------
# _EXISTING_REGISTRATION_STATUSES contents
# ---------------------------------------------------------------------------

class TestExistingRegistrationStatuses:
    def test_full_is_member(self):
        assert "full" in _EXISTING_REGISTRATION_STATUSES

    def test_json_only_is_member(self):
        assert "json_only" in _EXISTING_REGISTRATION_STATUSES

    def test_xmp_write_failed_is_member(self):
        assert "xmp_write_failed" in _EXISTING_REGISTRATION_STATUSES

    def test_metadata_write_failed_is_member(self):
        assert "metadata_write_failed" in _EXISTING_REGISTRATION_STATUSES

    def test_metadata_missing_not_member(self):
        assert "metadata_missing" not in _EXISTING_REGISTRATION_STATUSES

    def test_pending_not_member(self):
        assert "pending" not in _EXISTING_REGISTRATION_STATUSES


# ---------------------------------------------------------------------------
# Downgrade prevention — full + fetch error
# ---------------------------------------------------------------------------

class TestDowngradePrevention:
    """full 상태는 fetch 실패로 downgrade되지 않아야 한다."""

    def _make_adapter_restricted(self):
        from core.adapters.pixiv import PixivRestrictedError
        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivRestrictedError("restricted")
        return adapter

    def _make_adapter_not_found(self):
        from core.adapters.pixiv import PixivNotFoundError
        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivNotFoundError("not found")
        return adapter

    def test_full_plus_restricted_keeps_full(self, tmp_path):
        conn = _make_conn()
        gid = _insert_group(conn, "full")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        result = enrich_file_from_pixiv(conn, _get_file_id(conn, gid), adapter=self._make_adapter_restricted())

        assert result["status"] == "restricted"
        assert _get_sync_status(conn, gid) == "full"

    def test_full_plus_not_found_keeps_full(self, tmp_path):
        conn = _make_conn()
        gid = _insert_group(conn, "full")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        result = enrich_file_from_pixiv(conn, _get_file_id(conn, gid), adapter=self._make_adapter_not_found())

        assert result["status"] == "not_found_at_source"
        assert _get_sync_status(conn, gid) == "full"

    def test_metadata_missing_plus_restricted_downgrades(self, tmp_path):
        conn = _make_conn()
        gid = _insert_group(conn, "metadata_missing")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        enrich_file_from_pixiv(conn, _get_file_id(conn, gid), adapter=self._make_adapter_restricted())

        assert _get_sync_status(conn, gid) == "metadata_write_failed"

    def test_metadata_missing_plus_not_found_downgrades(self, tmp_path):
        conn = _make_conn()
        gid = _insert_group(conn, "metadata_missing")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        enrich_file_from_pixiv(conn, _get_file_id(conn, gid), adapter=self._make_adapter_not_found())

        assert _get_sync_status(conn, gid) == "source_unavailable"

    def test_json_only_plus_restricted_downgrades(self, tmp_path):
        conn = _make_conn()
        gid = _insert_group(conn, "json_only")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        enrich_file_from_pixiv(conn, _get_file_id(conn, gid), adapter=self._make_adapter_restricted())

        assert _get_sync_status(conn, gid) == "metadata_write_failed"

    def test_full_restricted_sync_status_in_result_is_none(self, tmp_path):
        """full + restricted → result["sync_status"] is None (DB 변경 없음)."""
        conn = _make_conn()
        gid = _insert_group(conn, "full")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        result = enrich_file_from_pixiv(conn, _get_file_id(conn, gid), adapter=self._make_adapter_restricted())

        assert result["sync_status"] is None

    def test_full_not_found_sync_status_in_result_is_none(self, tmp_path):
        """full + not_found → result["sync_status"] is None (DB 변경 없음)."""
        conn = _make_conn()
        gid = _insert_group(conn, "full")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        result = enrich_file_from_pixiv(conn, _get_file_id(conn, gid), adapter=self._make_adapter_not_found())

        assert result["sync_status"] is None


# ---------------------------------------------------------------------------
# clear-first XMP write 분기
# ---------------------------------------------------------------------------

class TestClearFirstBranch:
    """previous_status에 따라 clear_windows_xp_fields_before_write가 올바르게 전달된다."""

    def _make_success_adapter(self):
        from core.models import AruMetadata
        adapter = MagicMock()
        adapter.fetch_metadata.return_value = {"tags": {"tags": []}}
        adapter.to_aru_metadata.return_value = AruMetadata(
            artwork_id="12345678",
            artwork_title="Test",
            artist_id="artist1",
            artist_name="Artist",
            artist_url="",
            tags=[],
            series_tags=[],
            character_tags=[],
        )
        return adapter

    def test_existing_status_uses_clear_first(self, tmp_path):
        """previous_status=json_only → clear_windows_xp_fields_before_write=True."""
        conn = _make_conn()
        gid = _insert_group(conn, "json_only")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool", return_value=True) as mock_xmp:
            enrich_file_from_pixiv(
                conn, _get_file_id(conn, gid),
                adapter=self._make_success_adapter(),
                exiftool_path="/fake/exiftool",
            )

        mock_xmp.assert_called_once()
        _, kwargs = mock_xmp.call_args[0], mock_xmp.call_args[1]
        assert kwargs.get("clear_windows_xp_fields_before_write") is True

    def test_new_registration_no_clear_first(self, tmp_path):
        """previous_status=metadata_missing → clear_windows_xp_fields_before_write=False."""
        conn = _make_conn()
        gid = _insert_group(conn, "metadata_missing")
        f = tmp_path / "12345678_p0.jpg"
        f.write_bytes(b"x")
        _insert_file(conn, gid, str(f))

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool", return_value=True) as mock_xmp:
            enrich_file_from_pixiv(
                conn, _get_file_id(conn, gid),
                adapter=self._make_success_adapter(),
                exiftool_path="/fake/exiftool",
            )

        mock_xmp.assert_called_once()
        _, kwargs = mock_xmp.call_args[0], mock_xmp.call_args[1]
        assert kwargs.get("clear_windows_xp_fields_before_write") is False


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _get_file_id(conn: sqlite3.Connection, group_id: str) -> str:
    row = conn.execute(
        "SELECT file_id FROM artwork_files WHERE group_id = ? LIMIT 1",
        (group_id,),
    ).fetchone()
    assert row is not None, f"no file for group {group_id}"
    return row["file_id"]
