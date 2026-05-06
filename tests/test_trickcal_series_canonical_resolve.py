from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.classifier import build_classify_preview
from core.tag_pack_loader import seed_builtin_tag_packs
from db.database import initialize_database


CANONICAL_SERIES = "Trickcal Re:VIVE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = initialize_database(str(tmp_path / "trickcal.db"))
    conn.row_factory = sqlite3.Row
    seed_builtin_tag_packs(conn)
    yield conn
    conn.close()


def _config(classified_dir: Path) -> dict:
    return {
        "classified_dir": str(classified_dir),
        "classification": {
            "enable_series_character": True,
            "enable_series_uncategorized": True,
            "enable_character_without_series": False,
            "fallback_by_author": True,
            "enable_by_author": False,
            "enable_by_tag": False,
            "on_conflict": "rename",
            "folder_locale": "ko",
            "fallback_locale": "canonical",
        },
    }


def _insert_group(conn: sqlite3.Connection, group_id: str) -> None:
    now = _now()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artwork_title, artist_name,
            downloaded_at, indexed_at, metadata_sync_status,
            tags_json, series_tags_json, character_tags_json)
           VALUES (?, 'pixiv', ?, 'trickcal test', 'artist_x',
                   ?, ?, 'json_only', '[]', '[]', '[]')""",
        (group_id, group_id[:8], now, now),
    )
    conn.commit()


def _insert_source_file(conn: sqlite3.Connection, group_id: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b"\xff\xd8\xff\xe0" * 128
    path.write_bytes(content)
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_size, metadata_embedded, file_status, created_at)
           VALUES (?, ?, 0, 'original', ?, 'jpg', ?, 0, 'present', ?)""",
        (str(uuid.uuid4()), group_id, str(path), len(content), _now()),
    )
    conn.commit()


def _insert_tag_row(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    tag: str,
    tag_type: str = "series",
    canonical: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO tags (group_id, tag, tag_type, canonical) VALUES (?, ?, ?, ?)",
        (group_id, tag, tag_type, canonical),
    )
    conn.commit()


def _build_preview_for_series_tag(
    conn: sqlite3.Connection,
    tmp_path: Path,
    *,
    tag: str,
    canonical: str | None,
) -> dict:
    group_id = str(uuid.uuid4())
    _insert_group(conn, group_id)
    _insert_source_file(conn, group_id, tmp_path / "inbox" / f"{group_id}.jpg")
    _insert_tag_row(conn, group_id=group_id, tag=tag, tag_type="series", canonical=canonical)
    preview = build_classify_preview(conn, group_id, _config(tmp_path / "Classified"))
    assert preview is not None
    return preview


class TestTrickcalSeriesCanonicalResolve:
    @pytest.mark.parametrize("raw_tag", ["Trickcal Re:VIVE", "트릭컬", "トリッカル"])
    def test_series_tag_with_null_canonical_resolves_via_tag_aliases(
        self, db: sqlite3.Connection, tmp_path: Path, raw_tag: str
    ) -> None:
        preview = _build_preview_for_series_tag(db, tmp_path, tag=raw_tag, canonical=None)

        dest = preview["destinations"][0]
        assert dest["series_canonical"] == CANONICAL_SERIES
        assert dest["series_display"] == "트릭컬 리바이브"
        assert dest["rule_type"] == "series_uncategorized"

    def test_folder_locale_ko_uses_trickcal_localization(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        preview = _build_preview_for_series_tag(db, tmp_path, tag="Trickcal Re:VIVE", canonical=None)

        dest_path = Path(preview["destinations"][0]["dest_path"])
        assert "트릭컬 리바이브" in dest_path.parts
        assert preview["destinations"][0]["series_display"] == "트릭컬 리바이브"

    def test_existing_canonical_filled_case_keeps_same_behavior(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        preview_null = _build_preview_for_series_tag(
            db, tmp_path, tag="Trickcal Re:VIVE", canonical=None
        )
        preview_filled = _build_preview_for_series_tag(
            db, tmp_path, tag="Trickcal Re:VIVE", canonical=CANONICAL_SERIES
        )

        dest_null = preview_null["destinations"][0]
        dest_filled = preview_filled["destinations"][0]
        assert dest_null["series_canonical"] == dest_filled["series_canonical"] == CANONICAL_SERIES
        assert dest_null["series_display"] == dest_filled["series_display"] == "트릭컬 리바이브"
        assert dest_null["rule_type"] == dest_filled["rule_type"] == "series_uncategorized"

    def test_unknown_series_still_falls_back_to_unidentified(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        preview = _build_preview_for_series_tag(db, tmp_path, tag="Unknown Trickcal Alias", canonical=None)

        dest = preview["destinations"][0]
        assert dest["rule_type"] == "series_unidentified_fallback"
        assert preview["classification_info"]["classification_reason"] == "series_and_character_missing"
