"""build_enrichment_queue() 모드별 필터 테스트.

In-memory SQLite + 합성 fixture 사용.
schema.sql과 호환되는 컬럼명/타입을 정확히 사용한다 (schema 변경 금지).
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from db.database import initialize_database
from core.metadata_enricher import build_enrichment_queue


# ---------------------------------------------------------------------------
# 공통 픽스처 헬퍼
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """In-memory DB + 스키마 초기화 + row_factory 설정."""
    # initialize_database는 파일 경로를 받으므로 임시 파일 방식 사용 불가.
    # 대신 직접 in-memory connection에 schema를 부트스트랩한다.
    # artwork_id는 실제 schema에서 NOT NULL이지만, NULL 필터 테스트를 위해
    # 테스트 픽스처 테이블에서는 NULL 허용으로 정의한다.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artwork_groups (
            group_id              TEXT PRIMARY KEY,
            source_site           TEXT NOT NULL DEFAULT 'pixiv',
            artwork_id            TEXT,
            artwork_url           TEXT,
            artwork_title         TEXT,
            artist_id             TEXT,
            artist_name           TEXT,
            artist_url            TEXT,
            status                TEXT NOT NULL DEFAULT 'inbox',
            total_pages           INTEGER NOT NULL DEFAULT 1,
            cover_file_id         TEXT,
            tags_json             TEXT,
            series_tags_json      TEXT,
            character_tags_json   TEXT,
            downloaded_at         TEXT NOT NULL DEFAULT '2024-01-01T00:00:00+00:00',
            indexed_at            TEXT NOT NULL DEFAULT '2024-01-01T00:00:00+00:00',
            updated_at            TEXT,
            metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
            schema_version        TEXT NOT NULL DEFAULT '1.0'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artwork_files (
            file_id               TEXT PRIMARY KEY,
            group_id              TEXT NOT NULL,
            page_index            INTEGER NOT NULL DEFAULT 0,
            file_role             TEXT NOT NULL,
            file_path             TEXT NOT NULL DEFAULT '',
            file_format           TEXT NOT NULL DEFAULT 'jpg',
            file_status           TEXT NOT NULL DEFAULT 'present',
            file_size             INTEGER,
            file_hash             TEXT,
            metadata_embedded     INTEGER NOT NULL DEFAULT 0,
            created_at            TEXT NOT NULL DEFAULT '2024-01-01T00:00:00+00:00',
            last_seen_at          TEXT,
            source_file_id        TEXT,
            classify_rule_id      TEXT
        )
    """)
    conn.commit()
    return conn


def _insert_group(
    conn: sqlite3.Connection,
    *,
    artwork_id: str = "12345678",
    sync_status: str = "metadata_missing",
    indexed_at: str = "2024-01-01T00:00:00+00:00",
) -> str:
    group_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, metadata_sync_status, indexed_at, downloaded_at)
           VALUES (?, ?, ?, ?, '2024-01-01T00:00:00+00:00')""",
        (group_id, artwork_id, sync_status, indexed_at),
    )
    conn.commit()
    return group_id


def _insert_file(
    conn: sqlite3.Connection,
    group_id: str,
    *,
    file_role: str = "original",
) -> str:
    file_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, file_role, file_path, file_format, created_at)
           VALUES (?, ?, ?, '/dummy/file.jpg', 'jpg', '2024-01-01T00:00:00+00:00')""",
        (file_id, group_id, file_role),
    )
    conn.commit()
    return file_id


# ---------------------------------------------------------------------------
# missing_only 모드
# ---------------------------------------------------------------------------

class TestMissingOnlyMode:
    def test_includes_metadata_missing(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="metadata_missing")
        fid = _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert fid in result

    def test_excludes_source_unavailable(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="source_unavailable")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == []

    def test_excludes_full(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="full")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == []

    def test_excludes_json_only(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="json_only")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == []

    def test_excludes_metadata_write_failed(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="metadata_write_failed")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == []

    def test_excludes_pending(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="pending")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == []

    def test_excludes_xmp_write_failed(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="xmp_write_failed")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == []


# ---------------------------------------------------------------------------
# all_pixiv 모드
# ---------------------------------------------------------------------------

class TestAllPixivMode:
    def test_includes_metadata_missing(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="metadata_missing")
        fid = _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="all_pixiv")
        assert fid in result

    def test_includes_metadata_write_failed(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="metadata_write_failed")
        fid = _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="all_pixiv")
        assert fid in result

    def test_includes_xmp_write_failed(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="xmp_write_failed")
        fid = _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="all_pixiv")
        assert fid in result

    def test_includes_json_only(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="json_only")
        fid = _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="all_pixiv")
        assert fid in result

    def test_excludes_full(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="full")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="all_pixiv")
        assert result == []

    def test_excludes_source_unavailable(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="source_unavailable")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="all_pixiv")
        assert result == []

    def test_excludes_pending(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="pending")
        _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="all_pixiv")
        assert result == []


# ---------------------------------------------------------------------------
# 공통 필터 (양 모드 동일)
# ---------------------------------------------------------------------------

class TestCommonFilters:
    def test_excludes_null_artwork_id(self):
        conn = _make_conn()
        # artwork_id가 NULL인 경우 — 직접 INSERT
        group_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO artwork_groups
               (group_id, artwork_id, metadata_sync_status, indexed_at, downloaded_at)
               VALUES (?, NULL, 'metadata_missing', '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00')""",
            (group_id,),
        )
        conn.commit()
        _insert_file(conn, group_id)
        assert build_enrichment_queue(conn, mode="missing_only") == []
        assert build_enrichment_queue(conn, mode="all_pixiv") == []

    def test_excludes_empty_artwork_id(self):
        conn = _make_conn()
        gid = _insert_group(conn, artwork_id="", sync_status="metadata_missing")
        _insert_file(conn, gid)
        assert build_enrichment_queue(conn, mode="missing_only") == []
        assert build_enrichment_queue(conn, mode="all_pixiv") == []

    def test_only_file_role_original(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="metadata_missing")
        _insert_file(conn, gid, file_role="managed")
        _insert_file(conn, gid, file_role="classified_copy")
        _insert_file(conn, gid, file_role="sidecar")
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == []

    def test_returns_file_ids_not_group_ids(self):
        conn = _make_conn()
        gid = _insert_group(conn, sync_status="metadata_missing")
        fid = _insert_file(conn, gid)
        result = build_enrichment_queue(conn, mode="missing_only")
        assert result == [fid]
        assert gid not in result


# ---------------------------------------------------------------------------
# 모드 유효성 검사
# ---------------------------------------------------------------------------

class TestModeValidation:
    def test_invalid_mode_raises_value_error(self):
        conn = _make_conn()
        with pytest.raises(ValueError, match="invalid enrichment mode"):
            build_enrichment_queue(conn, mode="unknown")  # type: ignore[arg-type]

    def test_default_mode_is_missing_only(self):
        """기본 mode 인자가 missing_only와 동일하게 동작한다."""
        conn = _make_conn()
        # metadata_missing: 기본 모드에서 포함돼야 함
        gid_mm = _insert_group(conn, sync_status="metadata_missing")
        fid_mm = _insert_file(conn, gid_mm)
        # xmp_write_failed: 기본 모드에서 제외돼야 함
        gid_xf = _insert_group(conn, artwork_id="99999999", sync_status="xmp_write_failed")
        _insert_file(conn, gid_xf)

        result_default = build_enrichment_queue(conn)
        result_explicit = build_enrichment_queue(conn, mode="missing_only")
        assert result_default == result_explicit
        assert fid_mm in result_default
