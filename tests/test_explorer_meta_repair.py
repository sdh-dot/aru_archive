from __future__ import annotations

import sqlite3
from unittest.mock import patch

from core.explorer_meta_repair import (
    repair_explorer_meta_for_group,
    repair_explorer_meta_for_groups,
)


_SCHEMA = """
CREATE TABLE artwork_groups (
    group_id             TEXT PRIMARY KEY,
    artwork_id           TEXT,
    artwork_title        TEXT,
    artist_id            TEXT,
    artist_name          TEXT,
    artist_url           TEXT,
    artwork_url          TEXT,
    source_site          TEXT DEFAULT 'pixiv',
    description          TEXT,
    tags_json            TEXT DEFAULT '[]',
    series_tags_json     TEXT DEFAULT '[]',
    character_tags_json  TEXT DEFAULT '[]',
    metadata_sync_status TEXT DEFAULT 'full',
    updated_at           TEXT
);

CREATE TABLE artwork_files (
    file_id           TEXT PRIMARY KEY,
    group_id          TEXT,
    file_path         TEXT,
    file_format       TEXT,
    file_role         TEXT DEFAULT 'original',
    file_status       TEXT DEFAULT 'present',
    page_index        INTEGER DEFAULT 0,
    metadata_embedded INTEGER DEFAULT 0
);
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _insert_group(conn, group_id="g1", status="full"):
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, metadata_sync_status, artwork_id, artwork_title, artist_id,
            artist_name, artist_url, artwork_url, source_site, description,
            tags_json, series_tags_json, character_tags_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            group_id,
            status,
            "12345",
            "Hasumi",
            "artist1",
            "rikiddo",
            "",
            "https://www.pixiv.net/artworks/12345",
            "pixiv",
            "",
            '["tag1","tag2"]',
            '["Blue Archive"]',
            '["Hasumi"]',
        ),
    )
    conn.commit()


def _insert_file(
    conn,
    *,
    file_id="f1",
    group_id="g1",
    file_path="/tmp/test.jpg",
    file_format="jpg",
    file_role="original",
    file_status="present",
):
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, file_path, file_format, file_role, file_status)
           VALUES (?,?,?,?,?,?)""",
        (file_id, group_id, file_path, file_format, file_role, file_status),
    )
    conn.commit()


def test_repair_group_success_on_full_status():
    conn = _make_conn()
    _insert_group(conn, status="full")
    _insert_file(conn)

    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        result = repair_explorer_meta_for_group(conn, "g1", "/usr/bin/exiftool")

    assert result["status"] == "success"
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id='g1'"
    ).fetchone()
    assert row[0] == "full"


def test_repair_group_header_mismatch_is_skipped():
    conn = _make_conn()
    _insert_group(conn, status="full")
    _insert_file(conn, file_path="/tmp/mismatch.jpg")

    with patch(
        "core.metadata_writer.detect_header_extension_mismatch",
        return_value=("jpg", "webp"),
    ):
        result = repair_explorer_meta_for_group(conn, "g1", "/usr/bin/exiftool")

    assert result["status"] == "skipped"
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id='g1'"
    ).fetchone()
    assert row[0] == "full"


def test_repair_groups_deduplicates_and_reports_progress():
    conn = _make_conn()
    _insert_group(conn, group_id="g1", status="full")
    _insert_group(conn, group_id="g2", status="json_only")
    _insert_file(conn, file_id="f1", group_id="g1")
    _insert_file(conn, file_id="f2", group_id="g2", file_path="/tmp/test2.jpg")
    progress: list[tuple[int, int, str, str]] = []

    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        result = repair_explorer_meta_for_groups(
            conn,
            ["g1", "g2", "g1"],
            "/usr/bin/exiftool",
            progress_fn=lambda *args: progress.append(args),
        )

    assert result["total"] == 2
    assert result["success"] == 2
    assert result["group_ids"] == ["g1", "g2"]
    assert progress == [
        (0, 2, "g1", "running"),
        (1, 2, "g1", "success"),
        (1, 2, "g2", "running"),
        (2, 2, "g2", "success"),
    ]
