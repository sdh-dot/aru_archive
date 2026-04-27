"""
character alias → parent_series inference가 분류 미리보기에 반영되는지 테스트.

- character alias만 있는 group이 BySeries/{series}/{char}로 분류됨 (author_fallback 아님)
- preview에 inferred_series_evidence가 포함됨
- series와 character 모두 있으면 classification_info가 None
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.classifier import build_classify_preview


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row

    # ワカモ alias 등록
    conn.executemany(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, source, created_at) "
        "VALUES (?, ?, ?, ?, 1, 'user', ?)",
        [
            ("ワカモ(正月)", "狐坂ワカモ", "character", "Blue Archive", _now()),
            ("ブルアカ",     "Blue Archive", "series",  "",             _now()),
        ],
    )
    conn.commit()
    return conn


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: str | None = None,
    series_tags: list[str],
    character_tags: list[str],
    raw_tags: list[str] | None = None,
    sync_status: str = "json_only",
    artist_name: str = "TestArtist",
    classified_file: str | None = None,
) -> str:
    gid = group_id or str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artist_name,
            series_tags_json, character_tags_json, tags_json,
            metadata_sync_status, status, indexed_at, updated_at, downloaded_at)
           VALUES (?, 'pixiv', '12345', ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (
            gid, artist_name,
            json.dumps(series_tags, ensure_ascii=False),
            json.dumps(character_tags, ensure_ascii=False),
            json.dumps(raw_tags or [], ensure_ascii=False),
            sync_status, _now(), _now(), _now(),
        ),
    )
    file_path = classified_file or str(Path("inbox") / f"{gid}_p0.jpg")
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_hash, file_size, metadata_embedded,
            file_status, created_at)
           VALUES (?, ?, 0, 'original', ?, 'jpg', 'abc', 1024, 1, 'present', ?)""",
        (str(uuid.uuid4()), gid, file_path, _now()),
    )
    conn.commit()
    return gid


class TestInferredSeriesInPreview:
    def test_character_only_goes_to_byseries_not_author_fallback(self, db, tmp_path):
        """character tag가 있고 series가 inferred이면 BySeries로 분류됨."""
        gid = _insert_group(
            db,
            series_tags=["Blue Archive"],   # retag 후 inferred series가 반영된 상태
            character_tags=["狐坂ワカモ"],
            raw_tags=["ワカモ(正月)"],
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {"enable_series_character": True},
        }
        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "series_character" in rule_types
        assert "author_fallback" not in rule_types

    def test_inferred_series_evidence_in_preview(self, db, tmp_path):
        """preview에 inferred_series_evidence가 포함된다."""
        gid = _insert_group(
            db,
            series_tags=["Blue Archive"],
            character_tags=["狐坂ワカモ"],
            raw_tags=["ワカモ(正月)"],
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {},
        }
        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        ev = preview.get("inferred_series_evidence", [])
        assert any(
            e["source"] == "inferred_from_character"
            and e["canonical"] == "Blue Archive"
            for e in ev
        )

    def test_no_inferred_evidence_when_series_direct_matched(self, db, tmp_path):
        """series raw tag가 있는 경우 inferred_series_evidence는 비어 있다."""
        gid = _insert_group(
            db,
            series_tags=["Blue Archive"],
            character_tags=["狐坂ワカモ"],
            raw_tags=["ブルアカ", "ワカモ(正月)"],  # ブルアカ = direct series match
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {},
        }
        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        ev = preview.get("inferred_series_evidence", [])
        assert ev == []

    def test_classification_info_none_when_series_and_char_both_present(self, db, tmp_path):
        """series + character 모두 있으면 classification_info가 None이다."""
        gid = _insert_group(
            db,
            series_tags=["Blue Archive"],
            character_tags=["狐坂ワカモ"],
            raw_tags=["ワカモ(正月)"],
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {},
        }
        preview = build_classify_preview(db, gid, config)
        assert preview is not None
        assert preview["classification_info"] is None

    def test_author_fallback_when_no_series_no_char(self, db, tmp_path):
        """series/character 모두 없으면 author_fallback으로 간다."""
        gid = _insert_group(
            db,
            series_tags=[],
            character_tags=[],
            raw_tags=["オリジナル", "風景"],
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {"fallback_by_author": True},
        }
        preview = build_classify_preview(db, gid, config)
        assert preview is not None

        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "author_fallback" in rule_types
