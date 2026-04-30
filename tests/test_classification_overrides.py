"""
classification_overrides CRUD 및 preview 적용 테스트.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    c = initialize_database(str(tmp_path / "overrides_test.db"))
    yield c
    c.close()


def _insert_group(conn, group_id: str, artist_name: str = "testartist") -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, status, metadata_sync_status, "
        " series_tags_json, character_tags_json, artist_name, "
        " downloaded_at, indexed_at, source_site) "
        "VALUES (?, ?, 'inbox', 'full', '[]', '[]', ?, ?, ?, 'pixiv')",
        (group_id, str(uuid.uuid4()), artist_name, now, now),
    )
    conn.commit()


def _make_preview(group_id: str, classified_dir: str = "/Classified") -> dict:
    return {
        "group_id":       group_id,
        "source_path":    f"/Inbox/{group_id}_p0.jpg",
        "source_file_id": str(uuid.uuid4()),
        "destinations": [
            {
                "rule_type": "author_fallback",
                "dest_path": f"{classified_dir}/ByAuthor/testartist/{group_id}_p0.jpg",
                "conflict":  "none",
                "will_copy": True,
            }
        ],
        "estimated_copies": 1,
        "estimated_bytes":  100000,
        "folder_locale":    "canonical",
    }


# ---------------------------------------------------------------------------
# 1. set_override_for_group 저장
# ---------------------------------------------------------------------------

def test_set_override_stores_record(conn):
    from core.classification_overrides import get_override_for_group, set_override_for_group

    gid = str(uuid.uuid4())
    _insert_group(conn, gid)

    oid = set_override_for_group(
        conn,
        group_id=gid,
        series_canonical="Blue Archive",
        character_canonical="伊落マリー",
        folder_locale="ko",
        reason="제목에만 캐릭터명 있음",
    )
    assert oid

    override = get_override_for_group(conn, gid)
    assert override is not None
    assert override["series_canonical"] == "Blue Archive"
    assert override["character_canonical"] == "伊落マリー"
    assert override["folder_locale"] == "ko"
    assert override["reason"] == "제목에만 캐릭터명 있음"
    assert override["source"] == "manual"
    assert override["enabled"] == 1


# ---------------------------------------------------------------------------
# 2. get_override_for_group 조회
# ---------------------------------------------------------------------------

def test_get_override_returns_none_when_absent(conn):
    from core.classification_overrides import get_override_for_group

    result = get_override_for_group(conn, "nonexistent-group")
    assert result is None


def test_get_override_returns_latest_active(conn):
    from core.classification_overrides import get_override_for_group, set_override_for_group

    gid = str(uuid.uuid4())
    _insert_group(conn, gid)

    set_override_for_group(conn, group_id=gid, series_canonical="Series A", character_canonical=None)
    set_override_for_group(conn, group_id=gid, series_canonical="Series B", character_canonical="Char B")

    override = get_override_for_group(conn, gid)
    assert override is not None
    assert override["series_canonical"] == "Series B"

    # 이전 override는 비활성화됐어야 함
    rows = conn.execute(
        "SELECT series_canonical, enabled FROM classification_overrides WHERE group_id=?",
        (gid,),
    ).fetchall()
    enabled_rows    = [r for r in rows if r["enabled"] == 1]
    disabled_rows   = [r for r in rows if r["enabled"] == 0]
    assert len(enabled_rows) == 1
    assert len(disabled_rows) == 1
    assert disabled_rows[0]["series_canonical"] == "Series A"


# ---------------------------------------------------------------------------
# 3. clear_override_for_group 비활성화
# ---------------------------------------------------------------------------

def test_clear_override_disables_record(conn):
    from core.classification_overrides import (
        clear_override_for_group,
        get_override_for_group,
        set_override_for_group,
    )

    gid = str(uuid.uuid4())
    _insert_group(conn, gid)
    set_override_for_group(conn, group_id=gid, series_canonical="Blue Archive", character_canonical="十六夜ノノミ")

    assert get_override_for_group(conn, gid) is not None

    clear_override_for_group(conn, gid)

    assert get_override_for_group(conn, gid) is None

    row = conn.execute(
        "SELECT enabled FROM classification_overrides WHERE group_id=?",
        (gid,),
    ).fetchone()
    assert row is not None
    assert row["enabled"] == 0


# ---------------------------------------------------------------------------
# 4. apply_override_to_preview_item: rule_type → manual_override
# ---------------------------------------------------------------------------

def test_apply_override_changes_rule_type(conn):
    from core.classification_overrides import apply_override_to_preview_item

    gid     = str(uuid.uuid4())
    preview = _make_preview(gid)
    override = {
        "series_canonical":    "Blue Archive",
        "character_canonical": "伊落マリー",
        "folder_locale":       "canonical",
    }

    result = apply_override_to_preview_item(conn, preview, override, config={"classified_dir": "/Classified"})

    assert len(result["destinations"]) >= 1
    for dest in result["destinations"]:
        assert dest["rule_type"] == "manual_override"


def test_apply_override_preserves_group_id(conn):
    from core.classification_overrides import apply_override_to_preview_item

    gid     = str(uuid.uuid4())
    preview = _make_preview(gid)
    override = {"series_canonical": "Blue Archive", "character_canonical": "十六夜ノノミ", "folder_locale": "canonical"}

    result = apply_override_to_preview_item(conn, preview, override, config={"classified_dir": "/Classified"})

    assert result["group_id"] == gid


# ---------------------------------------------------------------------------
# 5. destination path가 locale 기준으로 재계산됨
# ---------------------------------------------------------------------------

def test_apply_override_dest_contains_series_and_character(conn):
    from core.classification_overrides import apply_override_to_preview_item

    gid     = str(uuid.uuid4())
    preview = _make_preview(gid)
    override = {
        "series_canonical":    "Blue Archive",
        "character_canonical": "伊落マリー",
        "folder_locale":       "canonical",
    }

    result = apply_override_to_preview_item(conn, preview, override, config={"classified_dir": "/Classified"})

    assert result["destinations"]
    dest_path = result["destinations"][0]["dest_path"]
    assert "BySeries" in dest_path
    assert "Blue Archive" in dest_path
    assert "伊落マリー" in dest_path


def test_apply_override_series_only_goes_to_uncategorized(conn):
    from core.classification_overrides import apply_override_to_preview_item

    gid     = str(uuid.uuid4())
    preview = _make_preview(gid)
    override = {"series_canonical": "Blue Archive", "character_canonical": None, "folder_locale": "canonical"}

    result = apply_override_to_preview_item(conn, preview, override, config={"classified_dir": "/Classified"})

    dest_path = result["destinations"][0]["dest_path"]
    assert "_uncategorized" in dest_path
    assert "Blue Archive" in dest_path


def test_apply_override_infers_classified_dir_from_existing_dest(conn):
    from core.classification_overrides import apply_override_to_preview_item

    gid     = str(uuid.uuid4())
    preview = _make_preview(gid, classified_dir="/MyClassified")
    override = {"series_canonical": "Blue Archive", "character_canonical": "伊落マリー", "folder_locale": "canonical"}

    # config를 전달하지 않아도 기존 dest에서 classified_dir를 추론해야 함
    result = apply_override_to_preview_item(conn, preview, override)

    dest_path = result["destinations"][0]["dest_path"]
    assert dest_path.startswith("/MyClassified") or "MyClassified" in dest_path
