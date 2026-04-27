"""
generate_alias_candidates_from_failed_tags 테스트.

character_tags_json이 비어 있는 artwork_groups (Author Fallback)의
tags_json에서 괄호 변형 패턴을 분석해 alias 후보를 생성하는 기능을 검증한다.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _insert_group(
    conn,
    tags: list[str],
    character_tags: list[str] | None = None,
) -> str:
    group_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, tags_json, character_tags_json, downloaded_at, indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            group_id,
            f"art_{group_id[:8]}",
            json.dumps(tags, ensure_ascii=False),
            json.dumps(character_tags) if character_tags is not None else None,
            now, now,
        ),
    )
    conn.commit()
    return group_id


# ---------------------------------------------------------------------------
# 기본 후보 생성
# ---------------------------------------------------------------------------

class TestGenerateCandidatesFromFailedTags:
    def test_parenthetical_base_becomes_candidate(self, conn):
        """陸八魔アル(正月) → base=陸八魔アル がまだ tag_aliases にない場合 candidate 생성."""
        _insert_group(conn, ["陸八魔アル(正月)", "晴れ着"], character_tags=None)
        from core.tag_candidate_generator import generate_alias_candidates_from_failed_tags
        result = generate_alias_candidates_from_failed_tags(conn)
        assert result["bases_found"] >= 1
        row = conn.execute(
            "SELECT * FROM tag_candidates WHERE raw_tag = '陸八魔アル' "
            "AND source = 'variant_stripped_pattern'"
        ).fetchone()
        assert row is not None, "陸八魔アル should be generated as a candidate"
        assert row["suggested_type"] == "character"

    def test_series_hint_extracted_from_inner(self, conn):
        """アル(ブルアカ) → inner=ブルアカ→Blue Archive が suggested_parent_series に入る."""
        _insert_group(conn, ["アル(ブルアカ)"], character_tags=None)
        from core.tag_candidate_generator import generate_alias_candidates_from_failed_tags
        generate_alias_candidates_from_failed_tags(conn)
        row = conn.execute(
            "SELECT * FROM tag_candidates WHERE raw_tag = 'アル' "
            "AND source = 'variant_stripped_pattern'"
        ).fetchone()
        assert row is not None
        assert row["suggested_parent_series"] == "Blue Archive", \
            "ブルアカ inner should resolve to Blue Archive as series hint"

    def test_already_classified_groups_excluded(self, conn):
        """character_tags_json が非空のグループは対象外."""
        _insert_group(
            conn,
            ["陸八魔アル(正月)"],
            character_tags=["陸八魔アル"],  # already classified
        )
        from core.tag_candidate_generator import generate_alias_candidates_from_failed_tags
        result = generate_alias_candidates_from_failed_tags(conn)
        # 分類済みグループのタグは候補にならない
        assert result["bases_found"] == 0

    def test_no_paren_tags_ignored(self, conn):
        """括弧なしタグは候補生成の対象外."""
        _insert_group(conn, ["晴れ着", "アニメ", "女の子"], character_tags=None)
        from core.tag_candidate_generator import generate_alias_candidates_from_failed_tags
        result = generate_alias_candidates_from_failed_tags(conn)
        assert result["bases_found"] == 0

    def test_confirmed_alias_base_skipped(self, conn):
        """base が tag_aliases に確定済みなら candidate は生成しない."""
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO tag_aliases "
            "(alias, canonical, tag_type, parent_series, enabled, created_at) "
            "VALUES (?, ?, 'character', 'Blue Archive', 1, ?)",
            ("陸八魔アル", "陸八魔アル", now),
        )
        conn.commit()
        _insert_group(conn, ["陸八魔アル(正月)"], character_tags=None)
        from core.tag_candidate_generator import generate_alias_candidates_from_failed_tags
        result = generate_alias_candidates_from_failed_tags(conn)
        assert result["bases_found"] == 0, \
            "Confirmed alias base should not generate a candidate"
