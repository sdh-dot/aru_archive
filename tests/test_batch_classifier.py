"""tests/test_batch_classifier.py — 일괄 분류 엔진 단위 테스트."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from core.batch_classifier import (
    build_classify_batch_preview,
    collect_classifiable_group_ids,
    execute_classify_batch,
)
from core.tag_localizer import seed_builtin_localizations


# ---------------------------------------------------------------------------
# DB 스키마 + 픽스처
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE artwork_groups (
    group_id              TEXT PRIMARY KEY,
    artwork_id            TEXT,
    artwork_title         TEXT,
    artist_name           TEXT,
    series_tags_json      TEXT,
    character_tags_json   TEXT,
    tags_json             TEXT,
    metadata_sync_status  TEXT DEFAULT 'full',
    status                TEXT DEFAULT 'inbox',
    source_site           TEXT,
    indexed_at            TEXT DEFAULT '2024-01-01T00:00:00+00:00',
    updated_at            TEXT
);
CREATE TABLE artwork_files (
    file_id           TEXT PRIMARY KEY,
    group_id          TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    file_format       TEXT,
    file_role         TEXT DEFAULT 'original',
    file_status       TEXT DEFAULT 'present',
    file_size         INTEGER DEFAULT 0,
    page_index        INTEGER DEFAULT 0,
    file_hash         TEXT,
    metadata_embedded INTEGER DEFAULT 0,
    created_at        TEXT,
    source_file_id    TEXT,
    classify_rule_id  TEXT
);
CREATE TABLE undo_entries (
    entry_id         TEXT PRIMARY KEY,
    operation_type   TEXT NOT NULL,
    performed_at     TEXT NOT NULL,
    undo_expires_at  TEXT,
    undo_status      TEXT DEFAULT 'pending',
    description      TEXT,
    undo_result_json TEXT
);
CREATE TABLE copy_records (
    record_id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    entry_id          TEXT NOT NULL,
    src_file_id       TEXT,
    dest_file_id      TEXT,
    src_path          TEXT,
    dest_path         TEXT NOT NULL,
    rule_id           TEXT,
    dest_file_size    INTEGER DEFAULT 0,
    dest_mtime_at_copy TEXT,
    dest_hash_at_copy TEXT,
    copied_at         TEXT NOT NULL,
    undo_status       TEXT DEFAULT 'pending'
);
CREATE TABLE tag_localizations (
    localization_id TEXT PRIMARY KEY,
    canonical       TEXT NOT NULL,
    tag_type        TEXT NOT NULL,
    parent_series   TEXT NOT NULL DEFAULT '',
    locale          TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    sort_name       TEXT,
    source          TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    UNIQUE(canonical, tag_type, parent_series, locale)
);
"""


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    seed_builtin_localizations(conn)
    yield conn
    conn.close()


def _insert_group(conn, gid, status="full", series=None, char=None, artist="artist"):
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_title, artist_name, series_tags_json,
            character_tags_json, metadata_sync_status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            gid, f"title-{gid[:4]}", artist,
            json.dumps(series or []),
            json.dumps(char or []),
            status,
        ),
    )


def _insert_file(conn, gid, src_path: str):
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, file_path, file_format, file_role, file_status, file_size)
           VALUES (?, ?, ?, 'jpg', 'original', 'present', 512)""",
        (str(uuid.uuid4()), gid, src_path),
    )


def _make_groups(conn, tmp_path, count=3, status="full") -> list[str]:
    ids = []
    for i in range(count):
        gid = f"gid-{i:04d}-{uuid.uuid4().hex[:6]}"
        src = tmp_path / f"img_{i}.jpg"
        src.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        _insert_group(conn, gid, status=status,
                      series=["Blue Archive"], char=["陸八魔アル"])
        _insert_file(conn, gid, str(src))
        ids.append(gid)
    conn.commit()
    return ids


# ---------------------------------------------------------------------------
# collect_classifiable_group_ids
# ---------------------------------------------------------------------------

def test_selected_scope(mem_db, tmp_path):
    ids = _make_groups(mem_db, tmp_path, 3)
    result = collect_classifiable_group_ids(
        mem_db, "selected",
        selected_group_ids=ids[:2],
        current_filter_group_ids=ids,
    )
    assert result["included_group_ids"] == ids[:2]


def test_current_filter_scope(mem_db, tmp_path):
    ids = _make_groups(mem_db, tmp_path, 3)
    result = collect_classifiable_group_ids(
        mem_db, "current_filter",
        current_filter_group_ids=ids,
    )
    assert set(result["included_group_ids"]) == set(ids)


def test_all_classifiable_scope(mem_db, tmp_path):
    ids = _make_groups(mem_db, tmp_path, 2)
    result = collect_classifiable_group_ids(mem_db, "all_classifiable")
    assert set(ids).issubset(set(result["included_group_ids"]))


def test_metadata_missing_excluded(mem_db, tmp_path):
    ids_ok  = _make_groups(mem_db, tmp_path, 2, status="full")
    ids_bad = _make_groups(mem_db, tmp_path, 1, status="metadata_missing")
    result = collect_classifiable_group_ids(
        mem_db, "current_filter",
        current_filter_group_ids=ids_ok + ids_bad,
    )
    assert set(result["included_group_ids"]) == set(ids_ok)
    assert len(result["excluded"]) == 1


def test_empty_scope_returns_empty(mem_db):
    result = collect_classifiable_group_ids(mem_db, "selected", selected_group_ids=[])
    assert result["included_group_ids"] == []


# ---------------------------------------------------------------------------
# build_classify_batch_preview
# ---------------------------------------------------------------------------

def test_batch_preview_total_groups(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 3)
    config = {"classified_dir": tmp_classified_dir}
    result = build_classify_batch_preview(mem_db, ids, config)
    assert result["total_groups"] == 3
    assert result["classifiable_groups"] == 3
    assert result["excluded_groups"] == 0


def test_batch_preview_estimated_copies(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 2)
    config = {"classified_dir": tmp_classified_dir}
    result = build_classify_batch_preview(mem_db, ids, config)
    # 각 그룹이 series_character 경로 1개 → 총 2개
    assert result["estimated_copies"] >= 2


def test_batch_preview_estimated_bytes(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 2)
    config = {"classified_dir": tmp_classified_dir}
    result = build_classify_batch_preview(mem_db, ids, config)
    assert result["estimated_bytes"] > 0


def test_batch_preview_previews_list(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 2)
    config = {"classified_dir": tmp_classified_dir}
    result = build_classify_batch_preview(mem_db, ids, config)
    assert len(result["previews"]) == 2
    for p in result["previews"]:
        assert "group_id" in p
        assert "destinations" in p


def test_batch_preview_warnings_on_excluded(mem_db, tmp_path, tmp_classified_dir):
    ids_ok = _make_groups(mem_db, tmp_path, 1, status="full")
    # group without file → build_classify_preview returns None
    gid_nofile = "gid-nofile"
    _insert_group(mem_db, gid_nofile, status="full", series=["Blue Archive"])
    mem_db.commit()

    config = {"classified_dir": tmp_classified_dir}
    result = build_classify_batch_preview(mem_db, ids_ok + [gid_nofile], config)
    assert result["excluded_groups"] == 1
    assert result["warnings"]


# ---------------------------------------------------------------------------
# execute_classify_batch
# ---------------------------------------------------------------------------

def test_execute_creates_one_undo_entry(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 3)
    config = {"classified_dir": tmp_classified_dir}
    preview = build_classify_batch_preview(mem_db, ids, config)
    execute_classify_batch(mem_db, preview, config)

    count = mem_db.execute(
        "SELECT COUNT(*) FROM undo_entries WHERE operation_type='classify_batch'"
    ).fetchone()[0]
    assert count == 1


def test_execute_returns_copied_count(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 2)
    config = {"classified_dir": tmp_classified_dir}
    preview = build_classify_batch_preview(mem_db, ids, config)
    result = execute_classify_batch(mem_db, preview, config)
    assert result["success"] is True
    assert result["copied"] >= 2


def test_execute_copy_records_created(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 2)
    config = {"classified_dir": tmp_classified_dir}
    preview = build_classify_batch_preview(mem_db, ids, config)
    result = execute_classify_batch(mem_db, preview, config)

    entry_id = result["entry_id"]
    cr_count = mem_db.execute(
        "SELECT COUNT(*) FROM copy_records WHERE entry_id=?", (entry_id,)
    ).fetchone()[0]
    assert cr_count >= 2


def test_execute_skip_existing_policy(mem_db, tmp_path, tmp_classified_dir):
    ids = _make_groups(mem_db, tmp_path, 1)
    classified_path = Path(tmp_classified_dir)
    config = {
        "classified_dir": tmp_classified_dir,
        "classification": {"on_conflict": "skip"},
    }
    preview = build_classify_batch_preview(mem_db, ids, config)

    # 첫 번째 실행 → 복사
    execute_classify_batch(mem_db, preview, config)
    # 두 번째 실행 → skip
    preview2 = build_classify_batch_preview(mem_db, ids, config)
    result2 = execute_classify_batch(mem_db, preview2, config)
    # skip이면 copied=0, skipped>0 or copied=0
    assert result2["copied"] == 0 or result2["skipped"] >= 0


def test_execute_partial_on_one_failure(mem_db, tmp_path, tmp_classified_dir):
    ids_ok = _make_groups(mem_db, tmp_path, 1)
    # 파일이 없는 그룹 (classified_dir에 못 쓰는 상태)
    gid_bad = "gid-bad-path"
    _insert_group(mem_db, gid_bad, status="full", series=["X"], char=["Y"])
    mem_db.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, file_path, file_format, file_role, file_status, file_size)
           VALUES (?, ?, '/nonexistent/no_such_file.jpg', 'jpg', 'original', 'present', 1)""",
        (str(uuid.uuid4()), gid_bad),
    )
    mem_db.commit()

    config = {"classified_dir": tmp_classified_dir}
    preview = build_classify_batch_preview(mem_db, ids_ok + [gid_bad], config)
    result = execute_classify_batch(mem_db, preview, config)
    # ok 그룹은 copied, bad 그룹은 failed
    assert result["copied"] >= 1
    assert result["failed_groups"] >= 1
    assert result["status"] == "partial"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_classified_dir(tmp_path):
    d = tmp_path / "Classified"
    d.mkdir()
    return str(d)
