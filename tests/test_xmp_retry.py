"""tests/test_xmp_retry.py — xmp_retry 모듈 단위 테스트."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from core.xmp_retry import (
    retry_xmp_for_all,
    retry_xmp_for_group,
    retry_xmp_for_groups,
    select_xmp_target_file,
)

# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------

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
    metadata_sync_status TEXT DEFAULT 'json_only',
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

CREATE TABLE no_metadata_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   TEXT,
    reason     TEXT,
    created_at TEXT
);
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _insert_group(conn, group_id="g1", status="json_only", **kwargs):
    defaults = {
        "artwork_id": "12345",
        "artwork_title": "테스트",
        "artist_id": "artist1",
        "artist_name": "작가",
        "artist_url": "",
        "artwork_url": "https://www.pixiv.net/artworks/12345",
        "source_site": "pixiv",
        "description": "",
        "tags_json": '["tag1"]',
        "series_tags_json": '[]',
        "character_tags_json": '[]',
    }
    defaults.update(kwargs)
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, metadata_sync_status, artwork_id, artwork_title, artist_id,
            artist_name, artist_url, artwork_url, source_site, description,
            tags_json, series_tags_json, character_tags_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            group_id, status,
            defaults["artwork_id"], defaults["artwork_title"], defaults["artist_id"],
            defaults["artist_name"], defaults["artist_url"], defaults["artwork_url"],
            defaults["source_site"], defaults["description"],
            defaults["tags_json"], defaults["series_tags_json"], defaults["character_tags_json"],
        ),
    )
    conn.commit()


def _insert_file(
    conn,
    file_id="f1",
    group_id="g1",
    file_path="/tmp/test_12345.jpg",
    file_format="jpg",
    file_role="original",
    file_status="present",
    page_index=0,
):
    conn.execute(
        "INSERT INTO artwork_files (file_id, group_id, file_path, file_format, "
        "file_role, file_status, page_index) VALUES (?,?,?,?,?,?,?)",
        (file_id, group_id, file_path, file_format, file_role, file_status, page_index),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# select_xmp_target_file
# ---------------------------------------------------------------------------

def test_select_jpeg_original():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_format="jpg", file_role="original")
    result = select_xmp_target_file(conn, "g1")
    assert result is not None
    assert result["file_format"] == "jpg"


def test_select_managed_preferred_over_original():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_id="f1", file_format="bmp", file_role="original")
    _insert_file(conn, file_id="f2", file_path="/tmp/test_12345_managed.png",
                 file_format="png", file_role="managed")
    result = select_xmp_target_file(conn, "g1")
    assert result is not None
    assert result["file_role"] == "managed"
    assert result["file_format"] == "png"


def test_select_skips_bmp_original():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_format="bmp", file_role="original")
    result = select_xmp_target_file(conn, "g1")
    assert result is None


def test_select_skips_gif_original():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_format="gif", file_role="original")
    result = select_xmp_target_file(conn, "g1")
    assert result is None


def test_select_skips_zip_original():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_format="zip", file_role="original")
    result = select_xmp_target_file(conn, "g1")
    assert result is None


def test_select_skips_sidecar_files():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_role="sidecar", file_format="json")
    result = select_xmp_target_file(conn, "g1")
    assert result is None


def test_select_skips_missing_files():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_format="jpg", file_role="original", file_status="missing")
    result = select_xmp_target_file(conn, "g1")
    assert result is None


def test_select_png_original_included():
    conn = _make_conn()
    _insert_group(conn)
    _insert_file(conn, file_format="png", file_role="original")
    result = select_xmp_target_file(conn, "g1")
    assert result is not None
    assert result["file_format"] == "png"


# ---------------------------------------------------------------------------
# retry_xmp_for_group
# ---------------------------------------------------------------------------

def test_retry_group_no_exiftool():
    conn = _make_conn()
    _insert_group(conn)
    result = retry_xmp_for_group(conn, "g1", exiftool_path=None)
    assert result["status"] == "no_exiftool"


def test_retry_group_no_target_file():
    conn = _make_conn()
    _insert_group(conn)
    # GIF만 있어서 대상 없음
    _insert_file(conn, file_format="gif", file_role="original")
    result = retry_xmp_for_group(conn, "g1", exiftool_path="/usr/bin/exiftool")
    assert result["status"] == "no_target"


def test_retry_group_success_sets_full():
    conn = _make_conn()
    _insert_group(conn, status="json_only")
    _insert_file(conn, file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        result = retry_xmp_for_group(conn, "g1", exiftool_path="/usr/bin/exiftool")
    assert result["status"] == "success"
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id='g1'"
    ).fetchone()
    assert row[0] == "full"


def test_retry_group_xmp_error_sets_xmp_write_failed():
    from core.metadata_writer import XmpWriteError
    conn = _make_conn()
    _insert_group(conn, status="json_only")
    _insert_file(conn, file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool",
               side_effect=XmpWriteError("tool broke")):
        result = retry_xmp_for_group(conn, "g1", exiftool_path="/usr/bin/exiftool")
    assert result["status"] == "failed"
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id='g1'"
    ).fetchone()
    assert row[0] == "xmp_write_failed"


def test_xmp_write_failed_not_in_no_metadata_queue():
    """XMP 실패는 no_metadata_queue에 삽입되지 않아야 한다."""
    from core.metadata_writer import XmpWriteError
    conn = _make_conn()
    _insert_group(conn, status="json_only")
    _insert_file(conn, file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool",
               side_effect=XmpWriteError("tool broke")):
        retry_xmp_for_group(conn, "g1", exiftool_path="/usr/bin/exiftool")
    count = conn.execute(
        "SELECT COUNT(*) FROM no_metadata_queue WHERE group_id='g1'"
    ).fetchone()[0]
    assert count == 0


def test_retry_group_xmp_write_failed_can_recover_to_full():
    """xmp_write_failed 상태에서도 retry_xmp_for_group이 full로 전환해야 한다."""
    conn = _make_conn()
    _insert_group(conn, status="xmp_write_failed")
    _insert_file(conn, file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        result = retry_xmp_for_group(conn, "g1", exiftool_path="/usr/bin/exiftool")
    assert result["status"] == "success"
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id='g1'"
    ).fetchone()
    assert row[0] == "full"


def test_retry_group_header_extension_mismatch_is_skipped_and_keeps_status():
    conn = _make_conn()
    _insert_group(conn, status="json_only")
    _insert_file(conn, file_format="jpg", file_path="/tmp/mismatch.jpg")
    with patch(
        "core.metadata_writer.detect_header_extension_mismatch",
        return_value=("jpg", "webp"),
    ):
        result = retry_xmp_for_group(conn, "g1", exiftool_path="/usr/bin/exiftool")
    assert result["status"] == "skipped"
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id='g1'"
    ).fetchone()
    assert row[0] == "json_only"


# ---------------------------------------------------------------------------
# retry_xmp_for_all
# ---------------------------------------------------------------------------

def test_retry_all_returns_summary():
    conn = _make_conn()
    for i in range(3):
        _insert_group(conn, group_id=f"g{i}", status="json_only")
        _insert_file(conn, file_id=f"f{i}", group_id=f"g{i}", file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        summary = retry_xmp_for_all(conn, exiftool_path="/usr/bin/exiftool")
    assert summary["total"] == 3
    assert summary["success"] == 3
    assert summary["failed"] == 0


def test_retry_all_counts_failures():
    from core.metadata_writer import XmpWriteError
    conn = _make_conn()
    for i in range(2):
        _insert_group(conn, group_id=f"g{i}", status="json_only")
        _insert_file(conn, file_id=f"f{i}", group_id=f"g{i}", file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool",
               side_effect=XmpWriteError("tool broke")):
        summary = retry_xmp_for_all(conn, exiftool_path="/usr/bin/exiftool")
    assert summary["total"] == 2
    assert summary["failed"] == 2
    assert len(summary["errors"]) == 2


def test_retry_all_skips_uneligible_statuses():
    conn = _make_conn()
    _insert_group(conn, group_id="g_full", status="full")
    _insert_group(conn, group_id="g_json", status="json_only")
    _insert_file(conn, file_id="f1", group_id="g_json", file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        summary = retry_xmp_for_all(conn, exiftool_path="/usr/bin/exiftool")
    # 'full' 상태는 기본 statuses에 포함되지 않음 → total=1
    assert summary["total"] == 1
    assert summary["success"] == 1


def test_retry_all_includes_xmp_write_failed():
    conn = _make_conn()
    _insert_group(conn, group_id="g1", status="xmp_write_failed")
    _insert_file(conn, file_id="f1", group_id="g1", file_format="jpg")
    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        summary = retry_xmp_for_all(conn, exiftool_path="/usr/bin/exiftool")
    assert summary["total"] == 1
    assert summary["success"] == 1


def test_retry_all_no_exiftool_all_skipped():
    conn = _make_conn()
    for i in range(2):
        _insert_group(conn, group_id=f"g{i}", status="json_only")
    summary = retry_xmp_for_all(conn, exiftool_path=None)
    assert summary["total"] == 2
    assert summary["skipped"] == 2
    assert summary["success"] == 0


# ---------------------------------------------------------------------------
# retry_xmp_for_groups
# ---------------------------------------------------------------------------

def test_retry_groups_only_selected_items():
    conn = _make_conn()
    for i in range(3):
        _insert_group(conn, group_id=f"g{i}", status="json_only")
        _insert_file(conn, file_id=f"f{i}", group_id=f"g{i}", file_format="jpg")

    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        summary = retry_xmp_for_groups(conn, ["g0", "g2"], "/usr/bin/exiftool")

    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["group_ids"] == ["g0", "g2"]

    rows = conn.execute(
        "SELECT group_id, metadata_sync_status FROM artwork_groups ORDER BY group_id"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        ("g0", "full"),
        ("g1", "json_only"),
        ("g2", "full"),
    ]


def test_retry_groups_deduplicates_selected_items_and_reports_progress():
    conn = _make_conn()
    _insert_group(conn, group_id="g1", status="json_only")
    _insert_file(conn, file_id="f1", group_id="g1", file_format="jpg")
    progress = []

    with patch("core.metadata_writer.write_xmp_metadata_with_exiftool", return_value=True):
        summary = retry_xmp_for_groups(
            conn,
            ["g1", "g1"],
            "/usr/bin/exiftool",
            progress_fn=lambda *args: progress.append(args),
        )

    assert summary["total"] == 1
    assert summary["success"] == 1
    assert summary["group_ids"] == ["g1"]
    assert progress == [
        (0, 1, "g1", "running"),
        (1, 1, "g1", "success"),
    ]
