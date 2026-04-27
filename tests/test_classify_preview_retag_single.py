"""
단일 미리보기 재분류(retag) 경로 테스트.

retag_groups_from_existing_tags()가 tags_json을 기반으로 classify_pixiv_tags()를
다시 실행해 series_tags_json / character_tags_json을 갱신하는 것을 검증한다.

핵심 시나리오:
  '陸八魔アル(正月)', 'アル(ブルアカ)', '晴れ着' 태그를 가진 그룹이
  Author Fallback(character_tags_json=NULL)으로 저장되어 있을 때
  retag를 실행하면 陸八魔アル / Blue Archive로 재분류된다.
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


@pytest.fixture(scope="session")
def enriched_pack_data():
    from pathlib import Path
    import json as _json
    src = Path(__file__).resolve().parents[1] / "docs" / "tag_pack_export_localized_ko_ja.json"
    if not src.exists():
        pytest.skip(f"Source JSON not found: {src}")
    raw = _json.loads(src.read_text(encoding="utf-8"))
    from tools.enrich_tag_pack_aliases import enrich_pack
    enriched, _ = enrich_pack(raw, use_danbooru=False)
    return enriched


@pytest.fixture
def seeded_conn(conn, enriched_pack_data, tmp_path):
    path = tmp_path / "enriched.json"
    path.write_text(json.dumps(enriched_pack_data, ensure_ascii=False), encoding="utf-8")
    from core.tag_pack_loader import import_localized_tag_pack
    import_localized_tag_pack(conn, path)
    return conn


def _insert_group(conn, tags: list[str]) -> str:
    group_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, tags_json, character_tags_json, series_tags_json, "
        "downloaded_at, indexed_at) VALUES (?, ?, ?, NULL, NULL, ?, ?)",
        (group_id, f"art_{group_id[:8]}", json.dumps(tags, ensure_ascii=False), now, now),
    )
    conn.commit()
    return group_id


# ---------------------------------------------------------------------------
# Retag 후 character / series 태그 갱신 검증
# ---------------------------------------------------------------------------

class TestRetagSingle:
    def test_retag_updates_character_tags_from_variant(self, seeded_conn):
        """Author Fallback 그룹에 retag를 실행하면 character_tags_json이 갱신된다."""
        group_id = _insert_group(seeded_conn, ["陸八魔アル(正月)", "アル(ブルアカ)", "晴れ着"])

        from core.tag_reclassifier import retag_groups_from_existing_tags
        result = retag_groups_from_existing_tags(seeded_conn, [group_id])
        assert result["updated"] == 1

        row = seeded_conn.execute(
            "SELECT character_tags_json, series_tags_json FROM artwork_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        char_tags   = json.loads(row["character_tags_json"] or "[]")
        series_tags = json.loads(row["series_tags_json"] or "[]")
        assert "陸八魔アル" in char_tags, \
            "retag should classify 陸八魔アル(正月)/アル(ブルアカ) → 陸八魔アル"
        assert "Blue Archive" in series_tags

    def test_retag_no_duplicate_characters(self, seeded_conn):
        """同じキャラを指す複数の変形タグが重複なく1エントリに集約される。"""
        group_id = _insert_group(seeded_conn, ["陸八魔アル(正月)", "アル(ブルアカ)"])

        from core.tag_reclassifier import retag_groups_from_existing_tags
        retag_groups_from_existing_tags(seeded_conn, [group_id])

        row = seeded_conn.execute(
            "SELECT character_tags_json FROM artwork_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        char_tags = json.loads(row["character_tags_json"] or "[]")
        assert char_tags.count("陸八魔アル") == 1, "No duplicate character entries"

    def test_retag_general_tags_stay_unchanged(self, seeded_conn):
        """tags_json 원본은 변경되지 않는다."""
        original_tags = ["陸八魔アル(正月)", "晴れ着"]
        group_id = _insert_group(seeded_conn, original_tags)

        from core.tag_reclassifier import retag_groups_from_existing_tags
        retag_groups_from_existing_tags(seeded_conn, [group_id])

        row = seeded_conn.execute(
            "SELECT tags_json FROM artwork_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        assert json.loads(row["tags_json"]) == original_tags, \
            "tags_json must not be mutated by retag"

    def test_retag_builtin_alias_only_no_db(self, conn):
        """DB tag pack 없어도 built-in alias (陸八魔アル) はvariant stripping で再分類。"""
        group_id = _insert_group(conn, ["陸八魔アル(正月)", "晴れ着"])

        from core.tag_reclassifier import retag_groups_from_existing_tags
        retag_groups_from_existing_tags(conn, [group_id])

        row = conn.execute(
            "SELECT character_tags_json, series_tags_json FROM artwork_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        assert "陸八魔アル" in json.loads(row["character_tags_json"] or "[]")
        assert "Blue Archive" in json.loads(row["series_tags_json"] or "[]")
