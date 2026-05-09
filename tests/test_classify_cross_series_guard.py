"""Cross-series guard 및 classification source priority 회귀 테스트.

픽스:
- Hu Tao (Genshin Impact) 캐릭터가 Blue Archive 시리즈 폴더에 분류되는 버그 방지
- character_tags_json 피드백 루프 차단 (raw_tags_json 우선)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _seed_alias(conn, alias, canonical, tag_type, parent_series=""):
    conn.execute(
        "INSERT OR REPLACE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 'test', 1, ?)",
        (alias, canonical, tag_type, parent_series, _now()),
    )
    conn.commit()


def _insert_group(
    conn,
    *,
    group_id: str,
    raw_tags: list[str] | None = None,
    tags: list[str] | None = None,
    series: list[str] | None = None,
    character: list[str] | None = None,
    sync_status: str = "json_only",
    artist: str = "test_artist",
) -> None:
    artwork_id = group_id[:12]
    now = _now()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artwork_title, artist_name,
            artwork_kind, total_pages, downloaded_at, indexed_at,
            status, metadata_sync_status, tags_json,
            series_tags_json, character_tags_json, raw_tags_json, schema_version)
           VALUES (?, 'pixiv', ?, 'Test', ?,
                   'single_image', 1, ?, ?,
                   'inbox', ?, ?, ?, ?, ?, '1.0')""",
        (
            group_id, artwork_id, artist,
            now, now,
            sync_status,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
            json.dumps(raw_tags, ensure_ascii=False) if raw_tags is not None else None,
        ),
    )
    conn.commit()


def _insert_file(conn, group_id: str, file_path: str) -> str:
    file_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_hash, file_size, metadata_embedded, file_status, created_at)
           VALUES (?, ?, 0, 'original', ?, 'png', 'abc123', 1024, 1, 'present', ?)""",
        (file_id, group_id, file_path, now),
    )
    conn.commit()
    return file_id


class TestCrossSeriesGuard:
    """_build_destinations cross-series guard 테스트."""

    def test_cross_series_character_blocked_from_wrong_series(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Hu Tao (Genshin Impact)가 Blue Archive 시리즈 폴더에 분류되지 않아야 한다."""
        from core.classifier import build_classify_preview

        # Setup: Blue Archive + Genshin Impact series, Hu Tao character (Genshin only)
        _seed_alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _seed_alias(db, "原神", "Genshin Impact", "series")
        _seed_alias(db, "胡桃", "Hu Tao", "character", "Genshin Impact")

        gid = str(uuid.uuid4())
        _insert_group(
            db,
            group_id=gid,
            raw_tags=["ブルーアーカイブ", "原神", "胡桃"],
            series=["Blue Archive", "Genshin Impact"],
            character=["Hu Tao"],
        )
        src = tmp_path / "file.png"
        src.write_bytes(b"PNG")
        _insert_file(db, gid, str(src))

        classified_dir = str(tmp_path / "classified")
        config = {"classified_dir": classified_dir, "classification": {}}

        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        dest_paths = [d["dest_path"] for d in preview["destinations"]]
        # Blue Archive/Hu Tao must NOT appear (Hu Tao is Genshin only)
        assert not any("Blue Archive" in p and "Hu Tao" in p for p in dest_paths), (
            f"Expected no Blue Archive/Hu Tao destination, got: {dest_paths}"
        )
        # Genshin Impact/Hu Tao SHOULD appear
        assert any("Genshin Impact" in p and "Hu Tao" in p for p in dest_paths), (
            f"Expected Genshin Impact/Hu Tao destination, got: {dest_paths}"
        )

    def test_cross_series_blocked_appears_in_preview(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """cross_series_blocked 필드가 차단된 조합을 담아야 한다."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _seed_alias(db, "原神", "Genshin Impact", "series")
        _seed_alias(db, "胡桃", "Hu Tao", "character", "Genshin Impact")

        gid = str(uuid.uuid4())
        _insert_group(
            db,
            group_id=gid,
            raw_tags=["ブルーアーカイブ", "原神", "胡桃"],
            series=["Blue Archive", "Genshin Impact"],
            character=["Hu Tao"],
        )
        src = tmp_path / "file.png"
        src.write_bytes(b"PNG")
        _insert_file(db, gid, str(src))

        classified_dir = str(tmp_path / "classified")
        config = {"classified_dir": classified_dir, "classification": {}}

        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        blocked = preview.get("cross_series_blocked", [])
        # Blue Archive × Hu Tao should be blocked
        assert any(
            b["series"] == "Blue Archive" and b["character"] == "Hu Tao"
            for b in blocked
        ), f"Expected Blue Archive×Hu Tao in cross_series_blocked, got: {blocked}"

    def test_correct_series_character_pair_not_blocked(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """캐릭터의 parent_series와 일치하는 시리즈는 차단되지 않아야 한다."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _seed_alias(db, "ミカ", "Mika", "character", "Blue Archive")

        gid = str(uuid.uuid4())
        _insert_group(
            db,
            group_id=gid,
            raw_tags=["ブルーアーカイブ", "ミカ"],
            series=["Blue Archive"],
            character=["Mika"],
        )
        src = tmp_path / "file.png"
        src.write_bytes(b"PNG")
        _insert_file(db, gid, str(src))

        classified_dir = str(tmp_path / "classified")
        config = {"classified_dir": classified_dir, "classification": {}}

        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        dest_paths = [d["dest_path"] for d in preview["destinations"]]
        assert any("Blue Archive" in p and "Mika" in p for p in dest_paths), (
            f"Expected Blue Archive/Mika destination, got: {dest_paths}"
        )
        blocked = preview.get("cross_series_blocked", [])
        assert not blocked, f"Expected no blocked combos, got: {blocked}"

    def test_character_no_parent_series_not_filtered(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """parent_series 가 없는 캐릭터는 크로스 시리즈 가드에 의해 필터링되지 않아야 한다."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        # Character with NO parent_series (empty string)
        _seed_alias(db, "テスト", "TestChar", "character", "")

        gid = str(uuid.uuid4())
        _insert_group(
            db,
            group_id=gid,
            raw_tags=["ブルーアーカイブ", "テスト"],
            series=["Blue Archive"],
            character=["TestChar"],
        )
        src = tmp_path / "file.png"
        src.write_bytes(b"PNG")
        _insert_file(db, gid, str(src))

        classified_dir = str(tmp_path / "classified")
        config = {"classified_dir": classified_dir, "classification": {}}

        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        dest_paths = [d["dest_path"] for d in preview["destinations"]]
        # Blue Archive/TestChar should be allowed (no parent_series to conflict with)
        assert any("Blue Archive" in p and "TestChar" in p for p in dest_paths), (
            f"Expected Blue Archive/TestChar destination, got: {dest_paths}"
        )

    def test_raw_tags_priority_over_stale_character_json(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """raw_tags_json 에서 Mika 가 찾아지면 stale character_tags_json 의 Hu Tao 는 무시된다."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "ブルーアーカイブ", "Blue Archive", "series")
        _seed_alias(db, "ミカ", "Mika", "character", "Blue Archive")
        _seed_alias(db, "Hu Tao", "Hu Tao", "character", "Genshin Impact")

        gid = str(uuid.uuid4())
        # Stale state: character_tags_json wrongly says Hu Tao, but raw_tags has Mika
        _insert_group(
            db,
            group_id=gid,
            raw_tags=["ブルーアーカイブ", "ミカ"],
            tags=[],
            series=["Blue Archive"],
            character=["Hu Tao"],  # STALE / WRONG
        )
        src = tmp_path / "file.png"
        src.write_bytes(b"PNG")
        _insert_file(db, gid, str(src))

        classified_dir = str(tmp_path / "classified")
        config = {"classified_dir": classified_dir, "classification": {}}

        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        dest_paths = [d["dest_path"] for d in preview["destinations"]]
        # Should classify as Blue Archive/Mika (from raw_tags), NOT Hu Tao
        assert any("Mika" in p for p in dest_paths), (
            f"Expected Mika destination from raw_tags, got: {dest_paths}"
        )
        assert not any("Hu Tao" in p for p in dest_paths), (
            f"Stale Hu Tao should not appear in destinations, got: {dest_paths}"
        )
