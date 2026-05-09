"""Pixiv mixed-post classification policy tests — Issue #133.

build_classify_preview() 의 mixed-post 정책 검증:
1. mixed Pixiv post tags only → needs_review
2. mixed post + image-level Mika clue → Blue Archive / Mika
3. mixed post + image-level Hu Tao clue → Genshin Impact / Hu Tao
4. parent folder path does not override artwork_title metadata
5. single-series post → classified normally, mixed_post.detected=False
6. mixed post does not reuse stale character_tags_json as input
7. cross_series_blocked remains exposed regardless of mixed-post state
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
           sync_status="json_only", artist="a", title="Title"):
    now = _now()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id,source_site,artwork_id,artwork_title,artist_name,
            artwork_kind,total_pages,downloaded_at,indexed_at,
            status,metadata_sync_status,tags_json,
            series_tags_json,character_tags_json,raw_tags_json,schema_version)
           VALUES (?,?,?,?,'test','single_image',1,?,?,'inbox',?,?,?,?,?,'1.0')""",
        (
            gid, "pixiv", gid[:12], title, now, now,
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


def _cfg(tmp_path):
    return {"classified_dir": str(tmp_path / "c"), "classification": {}}


# Both series + characters from two different series
MIXED_TAGS = ["ブルーアーカイブ", "原神", "聖園ミカ", "胡桃"]


class TestPixivMixedPost:

    def _setup_aliases(self, db):
        _alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _alias(db, "原神", "Genshin Impact", "series")
        _alias(db, "聖園ミカ", "Mika", "character", "Blue Archive")
        _alias(db, "胡桃", "Hu Tao", "character", "Genshin Impact")

    def test_mixed_tags_only_needs_review(self, db, tmp_path):
        """Mixed Pixiv post tags with no image-level clue → needs_review, no char confirmed."""
        from core.classifier import build_classify_preview
        self._setup_aliases(db)
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=MIXED_TAGS, title="Title")
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, _cfg(tmp_path))
        assert preview is not None
        dbg = preview["classification_debug"]
        assert dbg["mixed_post"]["detected"] is True
        assert "Blue Archive" in dbg["mixed_post"]["series_candidates"]
        assert "Genshin Impact" in dbg["mixed_post"]["series_candidates"]
        assert dbg["image_level_decision"]["status"] == "needs_review"
        # No high-confidence single-character destination
        assert dbg["selected"]["characters"] == [], (
            f"Expected no confirmed character, got {dbg['selected']['characters']}"
        )
        # Post-level candidates are preserved in debug
        assert "Blue Archive" in dbg["post_level_candidates"]["series"]
        assert "Genshin Impact" in dbg["post_level_candidates"]["series"]

    def test_mixed_post_with_mika_clue(self, db, tmp_path):
        """Mixed post + artwork_title=Mika alias → Blue Archive / Mika confirmed."""
        from core.classifier import build_classify_preview
        self._setup_aliases(db)
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=MIXED_TAGS, title="聖園ミカ")
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, _cfg(tmp_path))
        assert preview is not None
        dbg = preview["classification_debug"]
        assert dbg["mixed_post"]["detected"] is True
        assert dbg["image_level_decision"]["status"] == "confirmed"
        assert "Mika" in dbg["selected"]["characters"]
        assert "Blue Archive" in dbg["selected"]["series"]
        assert "Hu Tao" not in dbg["selected"]["characters"]
        # No Blue Archive/Hu Tao destination generated
        for dest in preview["destinations"]:
            assert "Hu Tao" not in dest["dest_path"], (
                f"Unexpected Hu Tao dest: {dest['dest_path']}"
            )

    def test_mixed_post_with_hutao_clue(self, db, tmp_path):
        """Mixed post + artwork_title=Hu Tao alias → Genshin Impact / Hu Tao confirmed."""
        from core.classifier import build_classify_preview
        self._setup_aliases(db)
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=MIXED_TAGS, title="胡桃")
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, _cfg(tmp_path))
        assert preview is not None
        dbg = preview["classification_debug"]
        assert dbg["mixed_post"]["detected"] is True
        assert dbg["image_level_decision"]["status"] == "confirmed"
        assert "Hu Tao" in dbg["selected"]["characters"]
        assert "Genshin Impact" in dbg["selected"]["series"]
        assert "Mika" not in dbg["selected"]["characters"]
        for dest in preview["destinations"]:
            assert "Mika" not in dest["dest_path"], (
                f"Unexpected Mika dest: {dest['dest_path']}"
            )

    def test_parent_folder_does_not_override_artwork_title(self, db, tmp_path):
        """Source path under /Hu Tao/ folder + artwork_title=Mika → Blue Archive / Mika."""
        from core.classifier import build_classify_preview
        self._setup_aliases(db)
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=MIXED_TAGS, title="聖園ミカ")
        # File lives inside a folder named "Hu Tao" — must not affect classification.
        hu_tao_dir = tmp_path / "Hu Tao"
        hu_tao_dir.mkdir(parents=True, exist_ok=True)
        src = hu_tao_dir / "f.png"
        src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, _cfg(tmp_path))
        assert preview is not None
        dbg = preview["classification_debug"]
        assert "Mika" in dbg["selected"]["characters"]
        assert "Blue Archive" in dbg["selected"]["series"]
        assert "Hu Tao" not in dbg["selected"]["characters"]

    def test_single_series_post_not_mixed(self, db, tmp_path):
        """Single-series Pixiv post → classified normally, mixed_post.detected=False."""
        from core.classifier import build_classify_preview
        self._setup_aliases(db)
        gid = str(uuid.uuid4())
        _group(db, gid=gid, raw_tags=["ブルーアーカイブ", "聖園ミカ"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, _cfg(tmp_path))
        assert preview is not None
        dbg = preview["classification_debug"]
        assert dbg["mixed_post"]["detected"] is False
        assert "Mika" in dbg["selected"]["characters"]
        assert "Blue Archive" in dbg["selected"]["series"]

    def test_mixed_post_does_not_reuse_stale_character_json(self, db, tmp_path):
        """Stale character_tags_json (Hu Tao) not re-injected when raw_tags present."""
        from core.classifier import build_classify_preview
        self._setup_aliases(db)
        gid = str(uuid.uuid4())
        # raw_tags has Blue Archive + Mika only; character_json has stale Hu Tao
        _group(db, gid=gid,
               raw_tags=["ブルーアーカイブ", "聖園ミカ"],
               character=["Hu Tao"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, _cfg(tmp_path))
        assert preview is not None
        dbg = preview["classification_debug"]
        assert dbg["legacy_fallback_used"] is False
        assert "Hu Tao" not in dbg["selected"]["characters"]
        assert "Mika" in dbg["selected"]["characters"]

    def test_cross_series_blocked_still_exposed(self, db, tmp_path):
        """Single-series + cross-series char → blocked.cross_series populated."""
        from core.classifier import build_classify_preview
        self._setup_aliases(db)
        gid = str(uuid.uuid4())
        # Blue Archive series + Hu Tao (parent: Genshin Impact) = cross-series conflict
        _group(db, gid=gid, raw_tags=["ブルーアーカイブ", "胡桃"])
        src = tmp_path / "f.png"; src.write_bytes(b"P")
        _file(db, gid, str(src))
        preview = build_classify_preview(db, gid, _cfg(tmp_path))
        assert preview is not None
        blocked = preview["classification_debug"]["blocked"]["cross_series"]
        assert any(
            b["series"] == "Blue Archive" and b["character"] == "Hu Tao"
            for b in blocked
        ), f"Expected Blue Archive×Hu Tao in blocked, got {blocked}"
        # No impossible Blue Archive / Hu Tao destination
        for dest in preview["destinations"]:
            path = dest["dest_path"]
            assert not ("Blue Archive" in path and "Hu Tao" in path), (
                f"Impossible destination generated: {path}"
            )
