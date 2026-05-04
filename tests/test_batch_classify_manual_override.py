"""
BatchClassify 수동 override 통합 테스트.
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
    from core.tag_pack_loader import import_localized_tag_pack

    c = initialize_database(str(tmp_path / "override_batch.db"))
    pack = Path(__file__).parent.parent / "docs" / "tag_pack_export_localized_ko_ja_failure_patch_v2.json"
    if pack.exists():
        try:
            import_localized_tag_pack(c, pack)
        except Exception:
            pass
    yield c
    c.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_group(conn, group_id: str, *, tags_json=None,
                  series_json="[]", char_json="[]",
                  artist_name="test_artist", title="",
                  sync_status="full") -> None:
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, status, metadata_sync_status, "
        " tags_json, series_tags_json, character_tags_json, "
        " artwork_title, artist_name, downloaded_at, indexed_at, source_site) "
        "VALUES (?, ?, 'inbox', ?, ?, ?, ?, ?, ?, ?, ?, 'pixiv')",
        (
            group_id, str(uuid.uuid4()), sync_status,
            json.dumps(tags_json or [], ensure_ascii=False),
            series_json, char_json,
            title, artist_name, _now(), _now(),
        ),
    )
    conn.commit()


def _insert_file(conn, group_id: str, file_path: str) -> str:
    file_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, "
        " file_format, file_status, metadata_embedded, created_at) "
        "VALUES (?, ?, 0, 'managed', ?, 'jpg', 'present', 1, ?)",
        (file_id, group_id, file_path, _now()),
    )
    conn.commit()
    return file_id


def _make_config(tmp_path) -> dict:
    return {
        "classified_dir": str(tmp_path / "Classified"),
        "classification": {
            "primary_strategy":         "by_series_character",
            "folder_locale":            "canonical",
            "enable_localized_folder_names": False,
            "fallback_by_author":       True,
        },
    }


# ---------------------------------------------------------------------------
# 1. author_fallback → override 적용 → series_character 처리
# ---------------------------------------------------------------------------

def test_override_turns_author_fallback_into_series_character(conn, tmp_path):
    from core.batch_classifier import build_classify_batch_preview
    from core.classification_overrides import set_override_for_group

    gid = str(uuid.uuid4())
    _insert_group(conn, gid, series_json="[]", char_json="[]")
    src = tmp_path / "Inbox" / f"{gid}_p0.jpg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")
    _insert_file(conn, gid, str(src))

    set_override_for_group(
        conn,
        group_id=gid,
        series_canonical="Blue Archive",
        character_canonical="伊落マリー",
    )

    config = _make_config(tmp_path)
    result = build_classify_batch_preview(conn, [gid], config)

    assert result["total_groups"] == 1
    previews = result["previews"]
    assert len(previews) == 1

    dest_rule_types = [d["rule_type"] for d in previews[0]["destinations"]]
    assert "manual_override" in dest_rule_types, f"got: {dest_rule_types}"

    dest_path = previews[0]["destinations"][0]["dest_path"]
    assert "Series" in dest_path
    assert "Blue Archive" in dest_path
    assert "伊落マリー" in dest_path


# ---------------------------------------------------------------------------
# 2. series_uncategorized → override 적용 → destination 갱신
# ---------------------------------------------------------------------------

def test_override_updates_destination_for_series_uncategorized(conn, tmp_path):
    from core.batch_classifier import build_classify_batch_preview
    from core.classification_overrides import set_override_for_group

    gid = str(uuid.uuid4())
    _insert_group(conn, gid, series_json='["Blue Archive"]', char_json="[]")
    src = tmp_path / "Inbox" / f"{gid}_p0.jpg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")
    _insert_file(conn, gid, str(src))

    set_override_for_group(
        conn,
        group_id=gid,
        series_canonical="Blue Archive",
        character_canonical="十六夜ノノミ",
    )

    config = _make_config(tmp_path)
    result = build_classify_batch_preview(conn, [gid], config)

    previews = result["previews"]
    assert previews
    dest_path = previews[0]["destinations"][0]["dest_path"]
    assert "十六夜ノノミ" in dest_path


# ---------------------------------------------------------------------------
# 3. execute 시 override destination을 사용
# ---------------------------------------------------------------------------

def test_execute_uses_override_destination(conn, tmp_path):
    from core.batch_classifier import build_classify_batch_preview, execute_classify_batch
    from core.classification_overrides import set_override_for_group

    gid = str(uuid.uuid4())
    _insert_group(conn, gid, series_json="[]", char_json="[]")
    src = tmp_path / "Inbox" / f"{gid}_p0.jpg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake image data")
    _insert_file(conn, gid, str(src))

    set_override_for_group(
        conn,
        group_id=gid,
        series_canonical="Blue Archive",
        character_canonical="伊落マリー",
    )

    config = _make_config(tmp_path)
    batch_preview = build_classify_batch_preview(conn, [gid], config)
    result = execute_classify_batch(conn, batch_preview, config)

    assert result["success"]
    assert result["copied"] >= 1

    # 복사된 파일 경로에 override series/character 포함 확인
    copy_records = conn.execute(
        "SELECT dest_path FROM copy_records WHERE rule_id = 'manual_override'"
    ).fetchall()
    assert len(copy_records) >= 1
    dest = copy_records[0]["dest_path"]
    assert "Blue Archive" in dest
    assert "伊落マリー" in dest


# ---------------------------------------------------------------------------
# 4. title-only candidate는 override 없이 자동 character 확정 안 됨
# ---------------------------------------------------------------------------

def test_title_only_candidate_not_auto_confirmed(conn, tmp_path):
    from core.batch_classifier import build_classify_batch_preview

    gid = str(uuid.uuid4())
    _insert_group(
        conn, gid,
        tags_json=["ブルーアーカイブ10000users入り", "チャイナドレス"],
        series_json="[]",
        char_json="[]",
        title="マリーちゃん",
    )
    src = tmp_path / "Inbox" / f"{gid}_p0.jpg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")
    _insert_file(conn, gid, str(src))

    config = _make_config(tmp_path)
    result = build_classify_batch_preview(conn, [gid], config)

    previews = result["previews"]
    assert previews
    for dest in previews[0]["destinations"]:
        rule = dest.get("rule_type", "")
        # 자동으로 series_character로 분류되면 안 됨 (override 없음)
        assert rule != "series_character", (
            f"title-only candidate가 자동으로 series_character로 분류됨: {dest}"
        )
