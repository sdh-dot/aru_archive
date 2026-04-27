"""
workflow tag reclassification 경로에서 character → series inference가 적용되는지 테스트.

- retag_groups_from_existing_tags() 호출 후 series_tags_json이 올바르게 갱신됨
- ambiguous alias가 있으면 tag_candidates에 후보가 생성됨 (자동 확정 금지)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.tag_reclassifier import retag_groups_from_existing_tags


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row

    conn.executemany(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, source, created_at) "
        "VALUES (?, ?, ?, ?, 1, 'user', ?)",
        [
            ("ワカモ(正月)", "狐坂ワカモ", "character", "Blue Archive", _now()),
            ("ブルアカ",     "Blue Archive", "series",  "",             _now()),
            # ambiguous aliases
            ("マリー", "伊落マリー",  "character", "Blue Archive", _now()),
            ("マリー", "Other Marie", "character", "Other Series",  _now()),
        ],
    )
    conn.commit()
    return conn


def _insert_group(conn: sqlite3.Connection, raw_tags: list[str]) -> str:
    gid = str(uuid.uuid4())
    aid = str(uuid.uuid4())[:8]
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artist_name,
            series_tags_json, character_tags_json, tags_json,
            metadata_sync_status, status, indexed_at, updated_at, downloaded_at)
           VALUES (?, 'pixiv', ?, 'Artist', '[]', '[]', ?, 'json_only', 'pending', ?, ?, ?)""",
        (gid, aid, json.dumps(raw_tags, ensure_ascii=False), _now(), _now(), _now()),
    )
    conn.commit()
    return gid


class TestRetagInference:
    def test_retag_infers_series_from_character_alias(self, db):
        """retag 후 character alias의 parent_series가 series_tags_json에 반영된다."""
        gid = _insert_group(db, ["ワカモ(正月)", "晴着"])
        result = retag_groups_from_existing_tags(db, [gid])
        assert result["updated"] == 1

        row = db.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        series_tags    = json.loads(row["series_tags_json"])
        character_tags = json.loads(row["character_tags_json"])

        assert "Blue Archive" in series_tags
        assert "狐坂ワカモ" in character_tags

    def test_retag_does_not_infer_character_from_series(self, db):
        """series raw tag만 있을 때 character를 자동 추론하지 않는다."""
        gid = _insert_group(db, ["ブルアカ", "オリジナル"])
        retag_groups_from_existing_tags(db, [gid])

        row = db.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        character_tags = json.loads(row["character_tags_json"])
        assert character_tags == []

    def test_retag_ambiguous_alias_creates_candidates(self, db):
        """ambiguous alias가 있으면 tag_candidates에 후보가 생성된다."""
        gid = _insert_group(db, ["マリー"])
        retag_groups_from_existing_tags(db, [gid])

        # character_tags는 비어 있어야 함 (ambiguous → 자동 확정 금지)
        row = db.execute(
            "SELECT character_tags_json FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        assert json.loads(row["character_tags_json"]) == []

        # tag_candidates에 마리 후보 2개 생성
        candidates = db.execute(
            "SELECT raw_tag, suggested_type, suggested_parent_series, source "
            "FROM tag_candidates WHERE raw_tag = ? AND source = 'ambiguous_alias'",
            ("マリー",),
        ).fetchall()
        parent_series_set = {r["suggested_parent_series"] for r in candidates}
        assert "Blue Archive" in parent_series_set
        assert "Other Series" in parent_series_set

    def test_retag_with_series_context_disambiguates(self, db):
        """series raw tag가 있으면 ambiguous alias를 해당 series로 확정한다."""
        gid = _insert_group(db, ["マリー", "ブルアカ"])
        retag_groups_from_existing_tags(db, [gid])

        row = db.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups WHERE group_id = ?",
            (gid,),
        ).fetchone()
        series_tags    = json.loads(row["series_tags_json"])
        character_tags = json.loads(row["character_tags_json"])

        assert "Blue Archive" in series_tags
        assert "伊落マリー" in character_tags
        # ambiguous candidates는 생성되지 않아야 함
        cands = db.execute(
            "SELECT COUNT(*) FROM tag_candidates WHERE raw_tag = ? AND source = 'ambiguous_alias'",
            ("マリー",),
        ).fetchone()[0]
        assert cands == 0

    def test_retag_multiple_groups(self, db):
        """여러 group에 대한 일괄 retag가 올바르게 동작한다."""
        gid1 = _insert_group(db, ["ワカモ(正月)"])
        gid2 = _insert_group(db, ["ブルアカ"])

        result = retag_groups_from_existing_tags(db, [gid1, gid2])
        assert result["total"] == 2
        assert result["updated"] == 2
        assert result["errors"] == []

        row1 = db.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups WHERE group_id = ?",
            (gid1,),
        ).fetchone()
        row2 = db.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups WHERE group_id = ?",
            (gid2,),
        ).fetchone()

        assert "Blue Archive" in json.loads(row1["series_tags_json"])
        assert "狐坂ワカモ" in json.loads(row1["character_tags_json"])
        assert "Blue Archive" in json.loads(row2["series_tags_json"])
        assert json.loads(row2["character_tags_json"]) == []
