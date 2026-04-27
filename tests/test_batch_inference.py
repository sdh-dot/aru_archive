"""
batch preview에서 character alias → inferred series가 올바르게 반영되는지 테스트.

- character-only raw tag group이 retag 후 BySeries로 분류됨
- batch preview의 author_fallback_count가 감소함
- inferred series가 있는 group은 series_uncategorized가 아닌 series_character로 분류됨
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.batch_classifier import build_classify_batch_preview


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
    series_tags: list[str],
    character_tags: list[str],
    raw_tags: list[str],
    sync_status: str = "json_only",
    artist_name: str = "TestArtist",
) -> str:
    gid = str(uuid.uuid4())
    aid = str(uuid.uuid4())[:8]
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artist_name,
            series_tags_json, character_tags_json, tags_json,
            metadata_sync_status, status, indexed_at, updated_at, downloaded_at)
           VALUES (?, 'pixiv', ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (
            gid, aid, artist_name,
            json.dumps(series_tags, ensure_ascii=False),
            json.dumps(character_tags, ensure_ascii=False),
            json.dumps(raw_tags, ensure_ascii=False),
            sync_status, _now(), _now(), _now(),
        ),
    )
    fid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_hash, file_size, metadata_embedded,
            file_status, created_at)
           VALUES (?, ?, 0, 'original', ?, 'jpg', 'hash', 1024, 1, 'present', ?)""",
        (fid, gid, f"inbox/{gid}_p0.jpg", _now()),
    )
    conn.commit()
    return gid


class TestBatchInference:
    def test_character_only_group_goes_to_byseries_after_retag(self, db, tmp_path):
        """retag=True 옵션으로 batch preview 시 character alias group이 BySeries로 분류됨."""
        gid = _insert_group(
            db,
            series_tags=[],      # 아직 retag 전이라 empty
            character_tags=[],
            raw_tags=["ワカモ(正月)"],
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {
                "retag_before_batch_preview": True,
                "enable_series_character": True,
                "fallback_by_author": True,
            },
        }
        result = build_classify_batch_preview(db, [gid], config)
        assert result["classifiable_groups"] == 1

        preview = result["previews"][0]
        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "series_character" in rule_types
        assert "author_fallback" not in rule_types

    def test_author_fallback_count_is_zero_when_character_inferred(self, db, tmp_path):
        """character alias로 series가 inferred된 group은 author_fallback_count에 포함 안 됨."""
        # 이미 retag된 상태 (series/character 모두 있음)
        gid = _insert_group(
            db,
            series_tags=["Blue Archive"],
            character_tags=["狐坂ワカモ"],
            raw_tags=["ワカモ(正月)"],
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {"fallback_by_author": True},
        }
        result = build_classify_batch_preview(db, [gid], config)
        assert result["author_fallback_count"] == 0

    def test_two_groups_one_inferred_one_fallback(self, db, tmp_path):
        """inferred series group 1개 + fallback group 1개 → author_fallback_count=1."""
        gid_inferred = _insert_group(
            db,
            series_tags=["Blue Archive"],
            character_tags=["狐坂ワカモ"],
            raw_tags=["ワカモ(正月)"],
        )
        gid_fallback = _insert_group(
            db,
            series_tags=[],
            character_tags=[],
            raw_tags=["オリジナル"],
            artist_name="SomeArtist",
        )
        config = {
            "classified_dir": str(tmp_path / "classified"),
            "classification": {"fallback_by_author": True},
        }
        result = build_classify_batch_preview(db, [gid_inferred, gid_fallback], config)
        assert result["classifiable_groups"] == 2
        assert result["author_fallback_count"] == 1
