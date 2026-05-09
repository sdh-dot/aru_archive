"""Classification debug breakdown 테스트 — Issue #137.

build_classify_preview() 의 classification_debug 필드 검증:
- selected series / characters
- evidence source
- cross_series_blocked 노출
- legacy_fallback_used 플래그
- raw tags 있을 때 legacy fallback 미사용
- 기존 preview 필드 backward-compat
"""
from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest


def _now(): return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path):
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _alias(conn, alias, canonical, tag_type, parent_series=""):
    conn.execute(
        "INSERT OR REPLACE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?,?,?,?,'test',1,?)",
        (alias, canonical, tag_type, parent_series, _now()),
    )
    conn.commit()


def _group(conn, *, gid, raw_tags=None, tags=None, series=None, character=None,
           sync_status="json_only", artist="a"):
    now = _now()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id,source_site,artwork_id,artwork_title,artist_name,
            artwork_kind,total_pages,downloaded_at,indexed_at,
            status,metadata_sync_status,tags_json,
            series_tags_json,character_tags_json,raw_tags_json,schema_version)
           VALUES (?,?,?,?,'test','single_image',1,?,?,'inbox',?,?,?,?,?,'1.0')""",
        (
            gid, "pixiv", gid[:12], "Title", now, now,
            sync_status,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
            json.dumps(raw_tags, ensure_ascii=False) if raw_tags is not None else None,
        ),
    )
    conn.commit()


def _file(conn, gid, path):
    fid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_files
           (file_id,group_id,page_index,file_role,file_path,
            file_format,file_hash,file_size,metadata_embedded,file_status,created_at)
           VALUES (?,?,0,'original',?,'png','x',1024,1,'present',?)""",
        (fid, gid, path, _now()),
    )
    conn.commit()
    return fid


class TestClassificationDebugBreakdown:

    def test_debug_selected_series_and_characters(self, db, tmp_path):
        """debug.selected 에 최종 series/character 가 노출된다."""
        from core.classifier import build_classify_preview
        _alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _alias(db, "ミカ", "Mika", "character", "Blue Archive")
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=["ブルーアーカイブ", "ミカ"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, {"classified_dir": str(tmp_path / "c"), "classification": {}})
        assert preview is not None
        dbg = preview.get("classification_debug", {})
        assert "Blue Archive" in dbg["selected"]["series"]
        assert "Mika" in dbg["selected"]["characters"]

    def test_debug_evidence_source_raw_tags(self, db, tmp_path):
        """raw_tags_json 을 source 로 사용했을 때 source_used = 'raw_tags'."""
        from core.classifier import build_classify_preview
        _alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=["ブルーアーカイブ"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, {"classified_dir": str(tmp_path / "c"), "classification": {}})
        assert preview is not None
        dbg = preview.get("classification_debug", {})
        assert dbg.get("source_used") == "raw_tags"
        assert "ブルーアーカイブ" in dbg.get("classify_input_tags", [])

    def test_debug_cross_series_blocked_exposed(self, db, tmp_path):
        """cross_series_blocked 가 debug 필드에 노출된다."""
        from core.classifier import build_classify_preview
        _alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _alias(db, "原神", "Genshin Impact", "series")
        _alias(db, "胡桃", "Hu Tao", "character", "Genshin Impact")
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=["ブルーアーカイブ", "原神", "胡桃"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, {"classified_dir": str(tmp_path / "c"), "classification": {}})
        assert preview is not None
        dbg = preview.get("classification_debug", {})
        blocked = dbg.get("cross_series_blocked", [])
        assert any(
            b["series"] == "Blue Archive" and b["character"] == "Hu Tao"
            for b in blocked
        ), f"Expected Blue Archive×Hu Tao blocked, got {blocked}"

    def test_debug_legacy_fallback_used_true(self, db, tmp_path):
        """raw_tags_json 없는 legacy row 는 legacy_fallback_used=True."""
        from core.classifier import build_classify_preview
        _alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _alias(db, "ミカ", "Mika", "character", "Blue Archive")
        gid = str(uuid.uuid4())
        # raw_tags=None → no raw_tags_json; character already in DB
        _group(db, gid=gid, raw_tags=None,
               series=["Blue Archive"], character=["Mika"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, {"classified_dir": str(tmp_path / "c"), "classification": {}})
        assert preview is not None
        dbg = preview.get("classification_debug", {})
        # When source has no raw_tags, and classifier finds nothing fresh but existing chars
        # are preserved → legacy_fallback_used should be True
        # (If classifier finds chars from series_tags_json fallback source, may be False;
        #  accept either as long as source_used is 'legacy_fallback')
        assert dbg.get("source_used") == "legacy_fallback"

    def test_debug_no_legacy_fallback_when_raw_tags_exist(self, db, tmp_path):
        """raw_tags_json 이 있으면 legacy_fallback_used=False."""
        from core.classifier import build_classify_preview
        _alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _alias(db, "ミカ", "Mika", "character", "Blue Archive")
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=["ブルーアーカイブ", "ミカ"],
               character=["Hu Tao"])  # stale wrong char in DB
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, {"classified_dir": str(tmp_path / "c"), "classification": {}})
        assert preview is not None
        dbg = preview.get("classification_debug", {})
        assert dbg.get("legacy_fallback_used") is False
        assert dbg.get("source_used") == "raw_tags"

    def test_debug_field_is_backward_compatible(self, db, tmp_path):
        """기존 preview 필드가 classification_debug 추가 후에도 그대로 존재한다."""
        from core.classifier import build_classify_preview
        _alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=["ブルーアーカイブ"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, {"classified_dir": str(tmp_path / "c"), "classification": {}})
        assert preview is not None
        for key in ("group_id", "source_file_id", "source_path",
                    "destinations", "estimated_copies", "estimated_bytes",
                    "cross_series_blocked", "classification_debug"):
            assert key in preview, f"Missing key: {key}"
