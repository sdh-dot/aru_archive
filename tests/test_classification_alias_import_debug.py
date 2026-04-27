"""
DB alias import debug tests.

태그 팩 임포트 후 분류기가 올바른 DB 알리아스를 로드하는지 검증한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


PACK_PATH = Path(__file__).parent.parent / "docs" / "tag_pack_export_localized_ko_ja_failure_patch_v2.json"


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    from core.tag_pack_loader import import_localized_tag_pack

    c = initialize_database(str(tmp_path / "debug.db"))
    import_localized_tag_pack(c, PACK_PATH)
    yield c
    c.close()


def _row(conn, alias: str):
    return conn.execute(
        "SELECT alias, canonical, tag_type, parent_series, enabled "
        "FROM tag_aliases WHERE alias=? AND enabled=1",
        (alias,),
    ).fetchone()


# ---------------------------------------------------------------------------
# 1. DB alias presence after import
# ---------------------------------------------------------------------------

def test_import_has_nonomi(conn):
    row = _row(conn, "十六夜ノノミ")
    assert row is not None, "十六夜ノノミ must be present after pack import"
    assert row[1] == "十六夜ノノミ"
    assert row[3] == "Blue Archive"


def test_import_has_fubuki(conn):
    row = _row(conn, "合歓垣フブキ")
    assert row is not None, "合歓垣フブキ must be present after pack import"
    assert row[1] == "合歓垣フブキ"
    assert row[3] == "Blue Archive"


# ---------------------------------------------------------------------------
# 2. classify_pixiv_tags with DB conn
# ---------------------------------------------------------------------------

def test_classify_nonomi_with_conn(conn):
    from core.tag_classifier import classify_pixiv_tags

    result = classify_pixiv_tags(["十六夜ノノミ"], conn=conn)
    assert "十六夜ノノミ" in result["character_tags"], f"got: {result}"
    assert "Blue Archive" in result["series_tags"], f"got: {result}"


def test_classify_fubuki_with_conn(conn):
    from core.tag_classifier import classify_pixiv_tags

    result = classify_pixiv_tags(["合歓垣フブキ"], conn=conn)
    assert "合歓垣フブキ" in result["character_tags"], f"got: {result}"
    assert "Blue Archive" in result["series_tags"], f"got: {result}"


# ---------------------------------------------------------------------------
# 3. Pixiv popularity hint — series only, no character
# ---------------------------------------------------------------------------

def test_popularity_tag_no_conn_resolves_blue_archive(conn):
    from core.tag_classifier import classify_pixiv_tags

    result = classify_pixiv_tags(["ブルーアーカイブ10000users入り"], conn=conn)
    assert result["series_tags"] == ["Blue Archive"], f"got: {result}"
    assert result["character_tags"] == [], f"got: {result}"


# ---------------------------------------------------------------------------
# 4. Title-only candidate does not auto-confirm character
# ---------------------------------------------------------------------------

def test_title_only_marie_not_auto_confirmed(conn):
    """'マリーちゃん' is a title hint, not a tag — must not appear in character_tags."""
    from core.tag_classifier import classify_pixiv_tags

    result = classify_pixiv_tags(["マリーちゃん"], conn=conn)
    assert "伊落マリー" not in result["character_tags"], (
        "title-only candidate must not be auto-confirmed as a character tag"
    )
