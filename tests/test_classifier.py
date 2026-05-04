"""
분류 엔진 테스트 — core/classifier.py, core/path_utils.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from core.classifier import (
    CLASSIFIABLE_STATUSES,
    build_classify_preview,
    execute_classify_preview,
    resolve_copy_destination,
    select_classify_target,
)
from core.path_utils import sanitize_path_component


# ===========================================================================
# path_utils
# ===========================================================================

class TestSanitizePathComponent:
    def test_removes_windows_forbidden_chars(self) -> None:
        assert sanitize_path_component('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"

    def test_removes_control_chars(self) -> None:
        assert sanitize_path_component("ab\x00cd\x1fef") == "ab_cd_ef"

    def test_strips_leading_trailing_spaces(self) -> None:
        assert sanitize_path_component("  hello  ") == "hello"

    def test_strips_trailing_dots(self) -> None:
        assert sanitize_path_component("filename.") == "filename"

    def test_empty_string_returns_fallback(self) -> None:
        assert sanitize_path_component("") == "_unknown"

    def test_only_forbidden_returns_fallback(self) -> None:
        assert sanitize_path_component("???") == "___"

    def test_custom_fallback(self) -> None:
        assert sanitize_path_component("", fallback="_unknown_artist") == "_unknown_artist"

    def test_normal_string_unchanged(self) -> None:
        assert sanitize_path_component("伊落マリー") == "伊落マリー"

    def test_spaces_inside_preserved(self) -> None:
        result = sanitize_path_component("Blue Archive")
        assert result == "Blue Archive"


# ===========================================================================
# DB 픽스처
# ===========================================================================

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _insert_group(
    conn: sqlite3.Connection,
    group_id: str,
    artwork_id: str = "99999",
    artist_name: str = "작가",
    sync_status: str = "json_only",
    tags_json: str | None = None,
    character_tags_json: str | None = None,
    series_tags_json: str | None = None,
) -> None:
    now = _now()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, artist_name, downloaded_at, indexed_at,
            metadata_sync_status, tags_json, character_tags_json, series_tags_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (group_id, artwork_id, artist_name, now, now,
         sync_status, tags_json, character_tags_json, series_tags_json),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection,
    file_id: str,
    group_id: str,
    file_path: str,
    file_format: str = "jpg",
    file_role: str = "original",
    file_status: str = "present",
    file_size: int = 1024,
    metadata_embedded: int = 0,
) -> None:
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_size, metadata_embedded, file_status, created_at)
           VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, group_id, file_role, file_path,
         file_format, file_size, metadata_embedded, file_status, _now()),
    )
    conn.commit()


def _make_file(path: Path, size: int = 512) -> Path:
    """더미 파일 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _config(tmp_path: Path) -> dict:
    classified = tmp_path / "Classified"
    classified.mkdir(exist_ok=True)
    return {
        "classified_dir": str(classified),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": True,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
        },
    }


# ===========================================================================
# select_classify_target
# ===========================================================================

class TestSelectClassifyTarget:
    def test_prefers_managed_over_original(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid  = str(uuid.uuid4())
        orig = _make_file(tmp_path / "orig.jpg")
        mng  = _make_file(tmp_path / "mng.png")
        _insert_group(db, gid)
        _insert_file(db, str(uuid.uuid4()), gid, str(orig), "jpg", "original")
        _insert_file(db, str(uuid.uuid4()), gid, str(mng),  "png", "managed")

        result = select_classify_target(db, gid)
        assert result is not None
        assert result["file_role"] == "managed"

    def test_returns_original_when_no_managed(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid  = str(uuid.uuid4())
        orig = _make_file(tmp_path / "orig.jpg")
        _insert_group(db, gid)
        _insert_file(db, str(uuid.uuid4()), gid, str(orig), "jpg", "original")

        result = select_classify_target(db, gid)
        assert result is not None
        assert result["file_role"] == "original"

    def test_excludes_bmp_original(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        bmp = _make_file(tmp_path / "img.bmp")
        _insert_group(db, gid)
        _insert_file(db, str(uuid.uuid4()), gid, str(bmp), "bmp", "original")

        assert select_classify_target(db, gid) is None

    def test_bmp_original_with_png_managed(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        bmp = _make_file(tmp_path / "img.bmp")
        png = _make_file(tmp_path / "img.png")
        _insert_group(db, gid)
        _insert_file(db, str(uuid.uuid4()), gid, str(bmp), "bmp", "original")
        _insert_file(db, str(uuid.uuid4()), gid, str(png), "png", "managed")

        result = select_classify_target(db, gid)
        assert result is not None
        assert result["file_format"] == "png"
        assert result["file_role"] == "managed"

    def test_excludes_sidecar(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid     = str(uuid.uuid4())
        sidecar = _make_file(tmp_path / "img.jpg.aru.json")
        _insert_group(db, gid)
        _insert_file(db, str(uuid.uuid4()), gid, str(sidecar), "json", "sidecar")

        assert select_classify_target(db, gid) is None

    def test_excludes_missing_files(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        _insert_group(db, gid)
        _insert_file(db, str(uuid.uuid4()), gid,
                     str(tmp_path / "missing.jpg"), "jpg", "original",
                     file_status="missing")

        assert select_classify_target(db, gid) is None


# ===========================================================================
# build_classify_preview
# ===========================================================================

class TestBuildClassifyPreview:
    def test_metadata_missing_excluded(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "img.jpg")
        _insert_group(db, gid, sync_status="metadata_missing")
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        assert build_classify_preview(db, gid, _config(tmp_path)) is None

    def test_pending_excluded(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "img.jpg")
        _insert_group(db, gid, sync_status="pending")
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        assert build_classify_preview(db, gid, _config(tmp_path)) is None

    def test_json_only_included(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "img.jpg")
        _insert_group(db, gid, sync_status="json_only", artist_name="작가A")
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        assert preview["estimated_copies"] >= 1

    def test_full_status_included(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "img.jpg")
        _insert_group(db, gid, sync_status="full", artist_name="작가B")
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        assert build_classify_preview(db, gid, _config(tmp_path)) is not None

    def test_by_author_path(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid  = str(uuid.uuid4())
        img  = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, artist_name="伊落マリー")
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        by_author = [d for d in preview["destinations"] if d["rule_type"] == "author_fallback"]
        assert len(by_author) == 1
        assert "Author" in by_author[0]["dest_path"]
        assert "伊落マリー" in by_author[0]["dest_path"]
        assert by_author[0]["dest_path"].endswith("file.jpg")

    def test_by_series_path(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, series_tags_json='["ブルーアーカイブ"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        by_series = [d for d in preview["destinations"] if d["rule_type"] == "series_uncategorized"]
        assert len(by_series) == 1
        assert "Series" in by_series[0]["dest_path"]
        assert "ブルーアーカイブ" in by_series[0]["dest_path"]
        assert "Uncategorized" in by_series[0]["dest_path"]

    def test_by_character_path(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, character_tags_json='["マリー"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        by_char = [d for d in preview["destinations"] if d["rule_type"] == "character"]
        assert len(by_char) == 1
        assert "Character" in by_char[0]["dest_path"]

    def test_by_tag_disabled_by_default(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, tags_json='["オリジナル", "風景"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        by_tag = [d for d in preview["destinations"] if d["rule_type"] == "by_tag"]
        assert len(by_tag) == 0

    def test_by_tag_enabled_via_config(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, tags_json='["オリジナル"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        cfg = _config(tmp_path)
        cfg["classification"]["enable_by_tag"] = True
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        by_tag = [d for d in preview["destinations"] if d["rule_type"] == "by_tag"]
        assert len(by_tag) == 1

    def test_no_classified_dir_returns_none(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid)
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        cfg = _config(tmp_path)
        cfg["classified_dir"] = ""
        assert build_classify_preview(db, gid, cfg) is None

    def test_missing_artist_uses_unknown(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, artist_name="")
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        by_author = [d for d in preview["destinations"] if d["rule_type"] == "author_fallback"]
        assert len(by_author) == 1
        assert "_unknown_artist" in by_author[0]["dest_path"]

    def test_estimated_bytes(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg", size=2048)
        _insert_group(db, gid, artist_name="작가")
        _insert_file(db, str(uuid.uuid4()), gid, str(img), file_size=2048)

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        assert preview["estimated_bytes"] == 2048 * preview["estimated_copies"]

    def test_series_character_path(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid,
                      series_tags_json='["Blue Archive"]',
                      character_tags_json='["伊落マリー"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        sc = [d for d in preview["destinations"] if d["rule_type"] == "series_character"]
        assert len(sc) == 1
        assert "Series" in sc[0]["dest_path"]
        assert "Blue Archive" in sc[0]["dest_path"]
        assert "伊落マリー" in sc[0]["dest_path"]
        assert sc[0]["dest_path"].endswith("file.jpg")

    def test_series_only_uncategorized(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, series_tags_json='["Blue Archive"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        su = [d for d in preview["destinations"] if d["rule_type"] == "series_uncategorized"]
        assert len(su) == 1
        assert "_uncategorized" in su[0]["dest_path"]
        assert "Blue Archive" in su[0]["dest_path"]

    def test_no_author_when_series_char_present(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, artist_name="작가",
                      series_tags_json='["Blue Archive"]',
                      character_tags_json='["伊落マリー"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        preview = build_classify_preview(db, gid, _config(tmp_path))
        assert preview is not None
        author_dests = [
            d for d in preview["destinations"]
            if d["rule_type"] in ("author_fallback", "author")
        ]
        assert len(author_dests) == 0

    def test_enable_by_author_adds_extra(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = _make_file(tmp_path / "file.jpg")
        _insert_group(db, gid, artist_name="작가",
                      series_tags_json='["Blue Archive"]',
                      character_tags_json='["伊落マリー"]')
        _insert_file(db, str(uuid.uuid4()), gid, str(img))

        cfg = _config(tmp_path)
        cfg["classification"]["enable_by_author"] = True
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        sc     = [d for d in preview["destinations"] if d["rule_type"] == "series_character"]
        author = [d for d in preview["destinations"] if d["rule_type"] == "author"]
        assert len(sc) == 1
        assert len(author) == 1


# ===========================================================================
# resolve_copy_destination
# ===========================================================================

class TestResolveCopyDestination:
    def test_no_conflict(self, tmp_path: Path) -> None:
        dest = tmp_path / "new_file.jpg"
        path, conflict = resolve_copy_destination(dest)
        assert path == dest
        assert conflict == "none"

    def test_rename_on_conflict(self, tmp_path: Path) -> None:
        dest = tmp_path / "file.jpg"
        dest.write_bytes(b"existing")

        path, conflict = resolve_copy_destination(dest, on_conflict="rename")
        assert conflict == "renamed"
        assert path.name == "file_1.jpg"
        assert path != dest

    def test_rename_increments(self, tmp_path: Path) -> None:
        dest = tmp_path / "file.jpg"
        dest.write_bytes(b"existing")
        (tmp_path / "file_1.jpg").write_bytes(b"existing1")

        path, conflict = resolve_copy_destination(dest, on_conflict="rename")
        assert conflict == "renamed"
        assert path.name == "file_2.jpg"

    def test_skip_on_conflict(self, tmp_path: Path) -> None:
        dest = tmp_path / "file.jpg"
        dest.write_bytes(b"existing")

        path, conflict = resolve_copy_destination(dest, on_conflict="skip")
        assert conflict == "skipped"
        assert path == dest


# ===========================================================================
# execute_classify_preview
# ===========================================================================

class TestExecuteClassifyPreview:
    def test_copies_files_and_creates_records(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())

        src = _make_file(tmp_path / "Inbox" / "99999_p0.jpg", size=256)
        _insert_group(db, gid, artwork_id="99999",
                      artist_name="TestArtist", sync_status="json_only")
        _insert_file(db, fid, gid, str(src), "jpg", file_size=256)

        cfg     = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        result = execute_classify_preview(db, preview, cfg)

        # 기본 결과
        assert result["success"] is True
        assert result["copied"] >= 1
        assert result["entry_id"]

        # 원본 파일 보존
        assert src.exists()

        # 복사본 실제 존재 확인
        for path_str in result["copy_log"]:
            assert Path(path_str).exists(), f"복사본 없음: {path_str}"

        # copy_records 생성 확인
        rec_count = db.execute(
            "SELECT COUNT(*) FROM copy_records WHERE entry_id = ?",
            (result["entry_id"],),
        ).fetchone()[0]
        assert rec_count == result["copied"]

        # undo_entries 생성 확인
        undo = db.execute(
            "SELECT * FROM undo_entries WHERE entry_id = ?",
            (result["entry_id"],),
        ).fetchone()
        assert undo is not None
        assert undo["operation_type"] == "classify"
        assert undo["undo_status"] == "pending"

        # artwork_files classified_copy 추가 확인
        cc_count = db.execute(
            "SELECT COUNT(*) FROM artwork_files "
            "WHERE group_id = ? AND file_role = 'classified_copy'",
            (gid,),
        ).fetchone()[0]
        assert cc_count == result["copied"]

        # artwork_groups.status 갱신 확인
        status = db.execute(
            "SELECT status FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()["status"]
        assert status == "classified"

    def test_skip_conflict(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        src = _make_file(tmp_path / "Inbox" / "file.jpg", size=128)
        _insert_group(db, gid, artist_name="SkipArtist", sync_status="json_only")
        _insert_file(db, fid, gid, str(src), "jpg", file_size=128)

        cfg = _config(tmp_path)
        cfg["classification"]["on_conflict"] = "skip"

        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        # 먼저 한번 실행해 파일 생성
        execute_classify_preview(db, preview, cfg)

        # 재실행: 모두 skip
        preview2 = build_classify_preview(db, gid, cfg)
        assert preview2 is not None
        result2 = execute_classify_preview(db, preview2, cfg)
        assert result2["skipped"] == len(
            [d for d in preview2["destinations"] if not d["will_copy"]]
        ) + result2["copied"]  # will_copy=False가 전부 skip

    def test_classified_statuses_constant(self) -> None:
        assert "full"            in CLASSIFIABLE_STATUSES
        assert "json_only"       in CLASSIFIABLE_STATUSES
        assert "xmp_write_failed" in CLASSIFIABLE_STATUSES
        assert "metadata_missing" not in CLASSIFIABLE_STATUSES
        assert "pending"          not in CLASSIFIABLE_STATUSES
        assert "metadata_write_failed" not in CLASSIFIABLE_STATUSES

    def test_classified_copy_inherits_metadata_embedded_zero(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """원본이 metadata_embedded=0이면 classified_copy도 0이어야 한다."""
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        src = _make_file(tmp_path / "Inbox" / "src.jpg", size=128)
        _insert_group(db, gid, artist_name="ZeroArtist", sync_status="json_only")
        _insert_file(db, fid, gid, str(src), "jpg", file_size=128,
                     metadata_embedded=0)

        cfg = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        result = execute_classify_preview(db, preview, cfg)
        assert result["success"] is True
        assert result["copied"] >= 1

        rows = db.execute(
            "SELECT metadata_embedded FROM artwork_files "
            "WHERE group_id = ? AND file_role = 'classified_copy'",
            (gid,),
        ).fetchall()
        assert rows, "classified_copy 행이 만들어지지 않았다"
        for row in rows:
            assert row["metadata_embedded"] == 0, (
                "원본이 0이면 classified_copy도 0이어야 한다"
            )

    def test_classified_copy_inherits_metadata_embedded_one(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """원본이 metadata_embedded=1이면 classified_copy도 1이어야 한다."""
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        src = _make_file(tmp_path / "Inbox" / "src.jpg", size=128)
        _insert_group(db, gid, artist_name="OneArtist", sync_status="full")
        _insert_file(db, fid, gid, str(src), "jpg", file_size=128,
                     metadata_embedded=1)

        cfg = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        result = execute_classify_preview(db, preview, cfg)
        assert result["success"] is True
        assert result["copied"] >= 1

        rows = db.execute(
            "SELECT metadata_embedded FROM artwork_files "
            "WHERE group_id = ? AND file_role = 'classified_copy'",
            (gid,),
        ).fetchall()
        assert rows
        for row in rows:
            assert row["metadata_embedded"] == 1, (
                "원본이 1이면 classified_copy도 1이어야 한다"
            )
