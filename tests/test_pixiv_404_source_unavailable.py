"""Pixiv 404 → source_unavailable 영구 실패 분기 회귀 테스트.

검증 대상:
- core.adapters.pixiv.PixivNotFoundError 신규 클래스
- core.metadata_enricher.enrich_file_from_pixiv의 PixivNotFoundError 분기
- artwork_groups.metadata_sync_status 갱신 → 'source_unavailable'
- Workflow Wizard enrichment SQL이 source_unavailable을 큐에서 제외
- 기존 PixivRestrictedError(403) 흐름 무영향 (회귀 가드)
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# 픽스처 / 헬퍼 (test_metadata_enricher.py 패턴 재사용)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    db_path = str(tmp_path / "pixiv404_test.db")
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


# Workflow Wizard _EnrichThread.run의 SQL과 동일 조건
_ENRICHMENT_QUEUE_SQL = (
    "SELECT af.file_id FROM artwork_files af "
    "JOIN artwork_groups ag ON ag.group_id = af.group_id "
    "WHERE ag.metadata_sync_status = 'metadata_missing' "
    "  AND (ag.artwork_id IS NOT NULL AND ag.artwork_id != '') "
    "  AND af.file_role = 'original' "
    "ORDER BY ag.indexed_at DESC"
)


# ---------------------------------------------------------------------------
# Test 1 — 404 시 status/sync_status/DB 갱신
# ---------------------------------------------------------------------------

class TestPixiv404SetsSourceUnavailable:
    def test_pixiv_404_sets_source_unavailable_status(
        self, db: sqlite3.Connection, tmp_path: Path,
    ) -> None:
        """PixivNotFoundError raise 시 result + DB 모두 source_unavailable로 표시."""
        from core.adapters.pixiv import PixivNotFoundError
        from core.metadata_enricher import enrich_file_from_pixiv

        img = tmp_path / "12345678_p0.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")  # 최소 JPEG signature

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img), "jpg")

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivNotFoundError(
            "Pixiv 아트워크를 찾을 수 없음 (404, 영구 실패): artwork_id=12345678"
        )

        result = enrich_file_from_pixiv(db, fid, adapter=adapter)

        assert result["status"] == "not_found_at_source"
        assert result["sync_status"] == "source_unavailable"
        assert "12345678" in result["message"] or "404" in result["message"]

        # DB artwork_groups.metadata_sync_status 갱신 확인
        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        assert row["metadata_sync_status"] == "source_unavailable"


# ---------------------------------------------------------------------------
# Test 2 — source_unavailable 상태 group이 큐에서 제외
# ---------------------------------------------------------------------------

class TestSourceUnavailableExcludedFromQueue:
    def test_source_unavailable_excluded_from_enrichment_queue(
        self, db: sqlite3.Connection, tmp_path: Path,
    ) -> None:
        """Workflow Wizard enrichment SQL에서 source_unavailable 그룹은 제외되어야 한다."""
        # group A: metadata_missing → 큐에 포함되어야 함
        gid_a = str(uuid.uuid4())
        fid_a = str(uuid.uuid4())
        img_a = tmp_path / "11111111_p0.jpg"
        img_a.write_bytes(b"\xff\xd8\xff\xd9")
        _insert_group(db, gid_a, "11111111")
        _insert_file(db, fid_a, gid_a, str(img_a), "jpg")

        # group B: 처음에는 metadata_missing이었으나 PixivNotFoundError로 source_unavailable로 전이
        from core.adapters.pixiv import PixivNotFoundError
        from core.metadata_enricher import enrich_file_from_pixiv

        gid_b = str(uuid.uuid4())
        fid_b = str(uuid.uuid4())
        img_b = tmp_path / "22222222_p0.jpg"
        img_b.write_bytes(b"\xff\xd8\xff\xd9")
        _insert_group(db, gid_b, "22222222")
        _insert_file(db, fid_b, gid_b, str(img_b), "jpg")

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivNotFoundError(
            "Pixiv 아트워크를 찾을 수 없음 (404, 영구 실패): artwork_id=22222222"
        )
        result_b = enrich_file_from_pixiv(db, fid_b, adapter=adapter)
        assert result_b["sync_status"] == "source_unavailable"

        # 큐 SELECT — group A만 매칭되고 group B는 제외되어야 함
        queue_rows = db.execute(_ENRICHMENT_QUEUE_SQL).fetchall()
        queue_file_ids = {r["file_id"] for r in queue_rows}

        assert fid_a in queue_file_ids, (
            "metadata_missing 상태 그룹 A가 enrichment 큐에서 누락됨"
        )
        assert fid_b not in queue_file_ids, (
            "source_unavailable 상태 그룹 B가 큐에서 제외되지 않음 — 무한 재시도 위험"
        )

    def test_source_unavailable_in_status_priority(self) -> None:
        """METADATA_SYNC_STATUSES + METADATA_STATUS_PRIORITY 등록 회귀."""
        from core.constants import METADATA_SYNC_STATUSES, METADATA_STATUS_PRIORITY

        assert "source_unavailable" in METADATA_SYNC_STATUSES
        assert "source_unavailable" in METADATA_STATUS_PRIORITY

        # priority가 metadata_missing보다는 낮고 db_update_failed보다 높아야 한다
        # (metadata_missing > source_unavailable > db_update_failed)
        prio = METADATA_STATUS_PRIORITY
        assert prio["source_unavailable"] < prio["metadata_missing"]
        assert prio["source_unavailable"] > prio["db_update_failed"]


# ---------------------------------------------------------------------------
# Test 3 — 403 (PixivRestrictedError) 회귀
# ---------------------------------------------------------------------------

class TestRestrictedStillUsesMetadataWriteFailed:
    def test_restricted_still_uses_metadata_write_failed(
        self, db: sqlite3.Connection, tmp_path: Path,
    ) -> None:
        """PixivRestrictedError(403)는 여전히 metadata_write_failed로 처리되어야 한다."""
        from core.adapters.pixiv import PixivRestrictedError
        from core.metadata_enricher import enrich_file_from_pixiv

        img = tmp_path / "33333333_p0.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")

        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "33333333")
        _insert_file(db, fid, gid, str(img), "jpg")

        adapter = MagicMock()
        adapter.fetch_metadata.side_effect = PixivRestrictedError(
            "Pixiv 접근 제한 (403): artwork_id=33333333"
        )

        result = enrich_file_from_pixiv(db, fid, adapter=adapter)

        # 기존 동작: status=restricted, sync_status=metadata_write_failed
        assert result["status"] == "restricted"
        assert result["sync_status"] == "metadata_write_failed", (
            "403 흐름이 변경됨 — 기존 metadata_write_failed 유지되어야 함"
        )
        assert result["sync_status"] != "source_unavailable", (
            "403이 source_unavailable로 잘못 분기됨"
        )

        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        assert row["metadata_sync_status"] == "metadata_write_failed"
