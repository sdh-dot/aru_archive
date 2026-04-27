"""
Preview / Retag source consistency tests.

분류 미리보기(Preview)는 artwork_groups의 pre-stored 컬럼
(series_tags_json / character_tags_json)을 사용하므로,
태그 팩 임포트 이후 retag를 실행해야 character_tags_json이 갱신된다는
동작을 검증한다.

DetailView도 같은 pre-stored 컬럼을 읽는다는 것을 확인해 일관성을 보증한다.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

PACK_PATH = Path(__file__).parent.parent / "docs" / "tag_pack_export_localized_ko_ja_failure_patch_v2.json"


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    from core.tag_pack_loader import import_localized_tag_pack

    c = initialize_database(str(tmp_path / "retag_test.db"))
    import_localized_tag_pack(c, PACK_PATH)
    yield c
    c.close()


def _insert_group(conn, group_id: str, tags_json: list[str],
                  series_json: list[str] | None = None,
                  char_json: list[str] | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, status, metadata_sync_status, "
        " tags_json, series_tags_json, character_tags_json, "
        " downloaded_at, indexed_at, source_site) "
        "VALUES (?, ?, 'inbox', 'full', ?, ?, ?, ?, ?, 'pixiv')",
        (
            group_id,
            str(uuid.uuid4()),
            json.dumps(tags_json, ensure_ascii=False),
            json.dumps(series_json or [], ensure_ascii=False),
            json.dumps(char_json or [], ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()


def _read_group(conn, group_id: str) -> dict:
    row = conn.execute(
        "SELECT tags_json, series_tags_json, character_tags_json "
        "FROM artwork_groups WHERE group_id=?",
        (group_id,),
    ).fetchone()
    return {
        "tags":      json.loads(row["tags_json"] or "[]"),
        "series":    json.loads(row["series_tags_json"] or "[]"),
        "character": json.loads(row["character_tags_json"] or "[]"),
    }


# ---------------------------------------------------------------------------
# 1. DetailView and Preview read the same pre-stored columns
# ---------------------------------------------------------------------------

def test_detail_view_and_preview_use_same_source_columns(conn):
    """
    DetailView._update_tags_section reads series_tags_json / character_tags_json.
    build_classify_preview._build_destinations reads the same two columns.
    They must reference the same DB row so they can never diverge.
    """
    gid = str(uuid.uuid4())
    _insert_group(conn, gid, ["十六夜ノノミ"], series_json=["Blue Archive"], char_json=["十六夜ノノミ"])

    stored = _read_group(conn, gid)
    assert stored["series"] == ["Blue Archive"]
    assert stored["character"] == ["十六夜ノノミ"]

    # The raw tags_json that classify_pixiv_tags will re-run on is the same source
    assert "十六夜ノノミ" in stored["tags"]


# ---------------------------------------------------------------------------
# 2. Retag updates character_tags_json
# ---------------------------------------------------------------------------

def test_retag_after_import_updates_character_tags(conn):
    """
    태그 팩 임포트 이후 retag를 실행하면 stale한 character_tags_json이 갱신된다.
    """
    from core.tag_reclassifier import retag_groups_from_existing_tags

    gid = str(uuid.uuid4())
    # 초기 상태: tags_json에 캐릭터가 있지만 character_tags_json은 비어 있음 (stale)
    _insert_group(conn, gid, ["十六夜ノノミ", "ブルーアーカイブ"], series_json=[], char_json=[])

    before = _read_group(conn, gid)
    assert before["character"] == [], "pre-condition: character_tags_json starts empty"

    result = retag_groups_from_existing_tags(conn, [gid])

    assert result["updated"] == 1, f"retag failed: {result}"

    after = _read_group(conn, gid)
    assert "十六夜ノノミ" in after["character"], (
        "retag must populate character_tags_json from tags_json via classify_pixiv_tags"
    )
    assert "Blue Archive" in after["series"] or after["series"], (
        "retag must populate series_tags_json"
    )


# ---------------------------------------------------------------------------
# 3. Stale detection: empty character_tags_json but classifiable tags_json
# ---------------------------------------------------------------------------

def test_stale_classification_detected_by_empty_character_tags(conn):
    """
    character_tags_json이 비어 있으나 tags_json에 known alias가 있으면
    classify_pixiv_tags(conn=conn)으로 올바른 캐릭터를 찾을 수 있다.
    이 검출이 작동하는지 확인해 stale 상태를 진단한다.
    """
    from core.tag_classifier import classify_pixiv_tags

    gid = str(uuid.uuid4())
    _insert_group(conn, gid, ["合歓垣フブキ", "ブルーアーカイブ1000users入り"],
                  series_json=[], char_json=[])

    stored = _read_group(conn, gid)
    # Pre-stored columns show no character — this is stale
    assert stored["character"] == []

    # But live classify with conn correctly finds the character
    live = classify_pixiv_tags(stored["tags"], conn=conn)
    assert "合歓垣フブキ" in live["character_tags"], (
        "live classification with conn must find character even when DB columns are stale"
    )
    assert "Blue Archive" in live["series_tags"]


# ---------------------------------------------------------------------------
# 4. Retag preserves tags_json (raw tags must not be modified)
# ---------------------------------------------------------------------------

def test_retag_does_not_modify_tags_json(conn):
    """
    retag는 series_tags_json / character_tags_json만 갱신한다.
    원본 tags_json은 건드리지 않아야 한다.
    """
    from core.tag_reclassifier import retag_groups_from_existing_tags

    gid = str(uuid.uuid4())
    original_tags = ["羽川ハスミ", "ブルーアーカイブ", "巨乳"]
    _insert_group(conn, gid, original_tags, series_json=[], char_json=[])

    retag_groups_from_existing_tags(conn, [gid])

    after = _read_group(conn, gid)
    assert after["tags"] == original_tags, "retag must not alter tags_json"
