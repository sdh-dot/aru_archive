"""tests/test_classifier_localized.py — 분류기 다국어 폴더명 단위 테스트."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.classifier import _build_destinations, _cls_cfg, build_classify_preview
from core.tag_localizer import seed_builtin_localizations


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
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
            indexed_at            TEXT,
            updated_at            TEXT
        );
        CREATE TABLE artwork_files (
            file_id      TEXT PRIMARY KEY,
            group_id     TEXT NOT NULL,
            file_path    TEXT NOT NULL,
            file_format  TEXT,
            file_role    TEXT DEFAULT 'original',
            file_status  TEXT DEFAULT 'present',
            file_size    INTEGER DEFAULT 0,
            page_index   INTEGER DEFAULT 0
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
        CREATE INDEX idx_tag_local_canonical ON tag_localizations(canonical, tag_type);
        CREATE INDEX idx_tag_local_locale    ON tag_localizations(locale, enabled);
    """)
    seed_builtin_localizations(conn)
    yield conn
    conn.close()


@pytest.fixture
def tmp_classified(tmp_path):
    d = tmp_path / "Classified"
    d.mkdir()
    return str(d)


@pytest.fixture
def ba_group(mem_db, tmp_path):
    """Blue Archive / 陸八魔アル 그룹 + 파일 fixture."""
    gid = "test-group-ba-aru"
    src = tmp_path / "test_image.jpg"
    src.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    mem_db.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_title, artist_name, series_tags_json,
            character_tags_json, metadata_sync_status)
           VALUES (?, ?, ?, ?, ?, 'full')""",
        (gid, "テスト作品", "test_artist",
         json.dumps(["Blue Archive"]),
         json.dumps(["陸八魔アル"])),
    )
    mem_db.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, file_path, file_format, file_role, file_status, file_size)
           VALUES ('fid-ba-aru', ?, ?, 'jpg', 'original', 'present', 200)""",
        (gid, str(src)),
    )
    mem_db.commit()
    return gid, str(src)


# ---------------------------------------------------------------------------
# _build_destinations — folder_locale=ko
# ---------------------------------------------------------------------------

def _group_row_ba():
    return {
        "series_tags_json":    json.dumps(["Blue Archive"]),
        "character_tags_json": json.dumps(["陸八魔アル"]),
        "tags_json":           json.dumps([]),
        "artist_name":         "test_artist",
    }


def _source_file(path: str):
    return {"file_path": path, "file_format": "jpg", "file_size": 200, "file_role": "original"}


def test_ko_locale_generates_korean_folders(mem_db, tmp_classified):
    cfg = _cls_cfg({
        "classification": {
            "folder_locale": "ko",
            "fallback_locale": "canonical",
            "enable_localized_folder_names": True,
        }
    })
    dests = _build_destinations(
        _group_row_ba(),
        _source_file("/tmp/test.jpg"),
        tmp_classified,
        cfg,
        conn=mem_db,
    )
    assert dests, "목적지 없음"
    path = dests[0]["dest_path"]
    assert "블루 아카이브" in path, f"한국어 시리즈명 없음: {path}"
    assert "리쿠하치마 아루" in path, f"한국어 캐릭터명 없음: {path}"


def test_canonical_locale_uses_original(mem_db, tmp_classified):
    cfg = _cls_cfg({
        "classification": {
            "folder_locale": "canonical",
        }
    })
    dests = _build_destinations(
        _group_row_ba(),
        _source_file("/tmp/test.jpg"),
        tmp_classified,
        cfg,
        conn=mem_db,
    )
    assert dests
    path = dests[0]["dest_path"]
    assert "Blue Archive" in path
    assert "陸八魔アル" in path


def test_no_conn_uses_canonical(tmp_classified):
    cfg = _cls_cfg({
        "classification": {
            "folder_locale": "ko",
            "enable_localized_folder_names": True,
        }
    })
    # conn=None → localization 비활성
    dests = _build_destinations(
        _group_row_ba(),
        _source_file("/tmp/test.jpg"),
        tmp_classified,
        cfg,
        conn=None,
    )
    assert dests
    path = dests[0]["dest_path"]
    assert "Blue Archive" in path


def test_dest_has_display_fields_when_locale(mem_db, tmp_classified):
    cfg = _cls_cfg({
        "classification": {
            "folder_locale": "ko",
            "fallback_locale": "canonical",
            "enable_localized_folder_names": True,
        }
    })
    dests = _build_destinations(
        _group_row_ba(),
        _source_file("/tmp/test.jpg"),
        tmp_classified,
        cfg,
        conn=mem_db,
    )
    d = dests[0]
    assert d.get("series_canonical") == "Blue Archive"
    assert d.get("series_display") == "블루 아카이브"
    assert d.get("character_canonical") == "陸八魔アル"
    assert d.get("character_display") == "리쿠하치마 아루"
    assert d.get("used_fallback") is False


def test_fallback_tag_when_no_locale(mem_db, tmp_classified):
    cfg = _cls_cfg({
        "classification": {
            "folder_locale": "ko",
            "fallback_locale": "canonical",
            "enable_localized_folder_names": True,
        }
    })
    row = {
        "series_tags_json":    json.dumps(["UnknownSeries"]),
        "character_tags_json": json.dumps(["UnknownChar"]),
        "tags_json":           json.dumps([]),
        "artist_name":         "artist",
    }
    dests = _build_destinations(
        row, _source_file("/tmp/test.jpg"), tmp_classified, cfg, conn=mem_db,
    )
    d = dests[0]
    # fallback → canonical 그대로
    assert d.get("series_display") == "UnknownSeries"
    assert d.get("used_fallback") is True


# ---------------------------------------------------------------------------
# build_classify_preview — folder_locale 반영
# ---------------------------------------------------------------------------

def test_preview_folder_locale_field(mem_db, tmp_classified, ba_group):
    gid, _ = ba_group
    config = {
        "classified_dir": tmp_classified,
        "classification": {
            "folder_locale": "ko",
            "fallback_locale": "canonical",
            "enable_localized_folder_names": True,
        },
    }
    preview = build_classify_preview(mem_db, gid, config)
    assert preview is not None
    assert preview["folder_locale"] == "ko"


def test_preview_destinations_contain_korean_path(mem_db, tmp_classified, ba_group):
    gid, _ = ba_group
    config = {
        "classified_dir": tmp_classified,
        "classification": {
            "folder_locale": "ko",
            "fallback_locale": "canonical",
            "enable_localized_folder_names": True,
        },
    }
    preview = build_classify_preview(mem_db, gid, config)
    assert preview is not None
    paths = [d["dest_path"] for d in preview["destinations"]]
    assert any("블루 아카이브" in p for p in paths)


def test_preview_fallback_tags_empty_when_all_resolved(mem_db, tmp_classified, ba_group):
    gid, _ = ba_group
    config = {
        "classified_dir": tmp_classified,
        "classification": {
            "folder_locale": "ko",
            "fallback_locale": "canonical",
            "enable_localized_folder_names": True,
        },
    }
    preview = build_classify_preview(mem_db, gid, config)
    assert preview is not None
    # Blue Archive + 陸八魔アル 모두 builtin에 있으므로 fallback 없음
    assert preview["fallback_tags"] == []
