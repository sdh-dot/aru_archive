from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from core.metadata_enricher import (
    MetadataWriteDbOutcome,
    _apply_metadata_write_db_outcome,
    _apply_metadata_write_db_outcomes_chunk,
    _apply_metadata_write_db_outcomes_with_fallback,
)


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database

    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _insert_group(conn: sqlite3.Connection, group_id: str, artwork_id: str | None = None, artwork_url: str = "") -> None:
    if artwork_id is None:
        artwork_id = str(uuid.uuid4().int)[:8]
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artwork_url, downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, 'pixiv', ?, ?, ?, ?, 'json_only')""",
        (group_id, artwork_id, artwork_url, _now(), _now()),
    )
    conn.commit()


def _insert_file(conn: sqlite3.Connection, file_id: str, group_id: str) -> None:
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at, metadata_embedded)
           VALUES (?, ?, 0, 'original', ?, 'jpg', ?, 0)""",
        (file_id, group_id, f"{file_id}.jpg", _now()),
    )
    conn.commit()


def _make_outcome(
    *,
    group_id: str,
    file_id: str,
    sync_status: str = "full",
    artwork_id: str | None = None,
    artwork_url: str | None = None,
) -> MetadataWriteDbOutcome:
    return MetadataWriteDbOutcome(
        group_id=group_id,
        file_id=file_id,
        sync_status=sync_status,
        updated_at=_now(),
        recovered_artwork_id=artwork_id,
        recovered_artwork_url=artwork_url,
    )


def test_chunk_apply_commits_once_for_multiple_outcomes(db: sqlite3.Connection) -> None:
    gid1, fid1 = str(uuid.uuid4()), str(uuid.uuid4())
    gid2, fid2 = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_group(db, gid1)
    _insert_group(db, gid2)
    _insert_file(db, fid1, gid1)
    _insert_file(db, fid2, gid2)

    stats: dict[str, int] = {}
    outcomes = [
        _make_outcome(group_id=gid1, file_id=fid1, sync_status="full"),
        _make_outcome(group_id=gid2, file_id=fid2, sync_status="xmp_write_failed"),
    ]

    _apply_metadata_write_db_outcomes_chunk(db, outcomes, _stats=stats)

    assert stats["db_commit_count"] == 1
    rows = db.execute(
        "SELECT group_id, metadata_sync_status FROM artwork_groups WHERE group_id IN (?, ?)",
        (gid1, gid2),
    ).fetchall()
    got = {row["group_id"]: row["metadata_sync_status"] for row in rows}
    assert got[gid1] == "full"
    assert got[gid2] == "xmp_write_failed"

    file_rows = db.execute(
        "SELECT file_id, metadata_embedded FROM artwork_files WHERE file_id IN (?, ?)",
        (fid1, fid2),
    ).fetchall()
    got_files = {row["file_id"]: row["metadata_embedded"] for row in file_rows}
    assert got_files[fid1] == 1
    assert got_files[fid2] == 1


def test_chunk_fallback_replays_per_file_without_chunk_rewrite(db: sqlite3.Connection) -> None:
    gid1, fid1 = str(uuid.uuid4()), str(uuid.uuid4())
    gid2, fid2 = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_group(db, gid1)
    _insert_group(db, gid2)
    _insert_file(db, fid1, gid1)
    _insert_file(db, fid2, gid2)

    outcomes = [
        _make_outcome(group_id=gid1, file_id=fid1, sync_status="full"),
        _make_outcome(group_id=gid2, file_id=fid2, sync_status="json_only"),
    ]

    original_apply = _apply_metadata_write_db_outcome

    with patch(
        "core.metadata_enricher._apply_metadata_write_db_outcomes_chunk",
        side_effect=sqlite3.OperationalError("database is locked"),
    ) as mock_chunk, patch(
        "core.metadata_enricher._apply_metadata_write_db_outcome",
        wraps=original_apply,
    ) as mock_single:
        stats: dict[str, int] = {}
        result = _apply_metadata_write_db_outcomes_with_fallback(db, outcomes, _stats=stats)

    assert mock_chunk.call_count == 1
    assert mock_single.call_count == 2
    assert result.batch_failed is True
    assert result.persisted_count == 2
    assert result.replay_attempt_count == 2
    assert result.replay_failed_count == 0
    assert stats["db_commit_count"] == 2


def test_batch_path_keeps_artwork_group_recovery_update(db: sqlite3.Connection) -> None:
    gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_group(db, gid, artwork_id="hash-placeholder", artwork_url="")
    _insert_file(db, fid, gid)

    stats: dict[str, int] = {}
    outcome = _make_outcome(
        group_id=gid,
        file_id=fid,
        sync_status="full",
        artwork_id="12345678",
        artwork_url="https://www.pixiv.net/artworks/12345678",
    )

    _apply_metadata_write_db_outcomes_chunk(db, [outcome], _stats=stats)

    row = db.execute(
        "SELECT artwork_id, artwork_url, metadata_sync_status FROM artwork_groups WHERE group_id = ?",
        (gid,),
    ).fetchone()
    assert row["artwork_id"] == "12345678"
    assert row["artwork_url"] == "https://www.pixiv.net/artworks/12345678"
    assert row["metadata_sync_status"] == "full"
    assert stats["db_commit_count"] == 1
