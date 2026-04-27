"""
Series hint / failure reason regression tests.

사용자가 요청한 정확한 함수명으로 작성된 회귀 테스트.
patch_conn fixture는 _PATCH_CHARACTERS를 tag_aliases에 삽입한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    from tools.apply_failure_tag_patch import _PATCH_CHARACTERS, _VARIANT_MERGES_FROM_FAILURES

    c = initialize_database(str(tmp_path / "regression.db"))
    now = datetime.now(timezone.utc).isoformat()

    for char in _PATCH_CHARACTERS:
        canonical = char["canonical"]
        parent_series = char.get("parent_series", "")
        for alias in char.get("aliases", []):
            c.execute(
                "INSERT OR IGNORE INTO tag_aliases "
                "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
                "VALUES (?, ?, 'character', ?, 1, ?, ?)",
                (alias, canonical, parent_series, now, now),
            )

    for variant_tag, merge_info in _VARIANT_MERGES_FROM_FAILURES.items():
        c.execute(
            "INSERT OR IGNORE INTO tag_aliases "
            "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
            "VALUES (?, ?, 'character', 'Blue Archive', 1, ?, ?)",
            (variant_tag, merge_info["base_canonical"], now, now),
        )

    c.execute(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
        "VALUES ('ブルーアーカイブ', 'Blue Archive', 'series', '', 1, ?, ?)",
        (now, now),
    )
    c.commit()
    yield c
    c.close()


def _classify(tags, conn):
    from core.tag_classifier import classify_pixiv_tags
    return classify_pixiv_tags(tags, conn=conn)


# ---------------------------------------------------------------------------
# 1. Pixiv popularity tag → Blue Archive series hint
# ---------------------------------------------------------------------------

def test_pixiv_popularity_tag_infers_blue_archive(conn):
    result = _classify(["ブルーアーカイブ5000users入り"], conn)
    assert result["series_tags"] == ["Blue Archive"]
    assert result["character_tags"] == []


def test_pixiv_popularity_tag_not_in_general(conn):
    result = _classify(["ブルーアーカイブ5000users入り"], conn)
    assert "ブルーアーカイブ5000users入り" not in result["tags"]


def test_pixiv_popularity_variants_all_infer_series(conn):
    from core.tag_classifier import classify_pixiv_tags
    tags = [
        "ブルーアーカイブ100users入り",
        "ブルーアーカイブ500users入り",
        "ブルーアーカイブ1000users入り",
        "ブルーアーカイブ10000users入り",
        "ブルーアーカイブ30000users入り",
    ]
    for tag in tags:
        r = classify_pixiv_tags([tag], conn=conn)
        assert "Blue Archive" in r["series_tags"], f"popularity tag not resolved: {tag}"
        assert r["character_tags"] == [], f"unexpected character for: {tag}"


# ---------------------------------------------------------------------------
# 2. character parent_series inference
# ---------------------------------------------------------------------------

def test_character_parent_series_inference_hasumi(conn):
    result = _classify(["羽川ハスミ"], conn)
    assert result["character_tags"] == ["羽川ハスミ"]
    assert result["series_tags"] == ["Blue Archive"]


def test_character_parent_series_inference_koyuki(conn):
    result = _classify(["黒崎コユキ"], conn)
    assert "黒崎コユキ" in result["character_tags"]
    assert "Blue Archive" in result["series_tags"]


def test_character_short_alias_resolves_with_series(conn):
    result = _classify(["ハスミ"], conn)
    assert "羽川ハスミ" in result["character_tags"]
    assert "Blue Archive" in result["series_tags"]


# ---------------------------------------------------------------------------
# 3. character + popularity series hint combined
# ---------------------------------------------------------------------------

def test_character_with_popularity_series_hint(conn):
    result = _classify(["羽川ハスミ", "ブルーアーカイブ5000users入り"], conn)
    assert result["character_tags"] == ["羽川ハスミ"]
    assert result["series_tags"] == ["Blue Archive"]


def test_character_with_popularity_no_duplicate_series(conn):
    result = _classify(["羽川ハスミ", "ブルーアーカイブ1000users入り"], conn)
    assert result["series_tags"].count("Blue Archive") == 1


# ---------------------------------------------------------------------------
# 4. general tags do not create character entries
# ---------------------------------------------------------------------------

def test_general_tags_do_not_create_character(conn):
    result = _classify(["巨乳", "女の子", "おっぱい"], conn)
    assert result["character_tags"] == []


def test_general_tags_stay_in_general_bucket(conn):
    result = _classify(["巨乳", "女の子"], conn)
    assert "巨乳" in result["tags"]
    assert "女の子" in result["tags"]


def test_group_tag_not_classified_as_character(conn):
    result = _classify(["便利屋68", "ブルーアーカイブ5000users入り"], conn)
    assert result["character_tags"] == []
    assert "Blue Archive" in result["series_tags"]


# ---------------------------------------------------------------------------
# 5. normalize_pixiv_popularity_tag helper
# ---------------------------------------------------------------------------

def test_normalize_pixiv_popularity_tag_known_series():
    from core.tag_classifier import normalize_pixiv_popularity_tag
    result = normalize_pixiv_popularity_tag("ブルーアーカイブ5000users入り")
    assert result is not None
    assert result["base_tag"] == "ブルーアーカイブ"
    assert result["tag_kind"] == "popularity_series_hint"
    assert result["canonical_series"] == "Blue Archive"


def test_normalize_pixiv_popularity_tag_unknown_series():
    from core.tag_classifier import normalize_pixiv_popularity_tag
    result = normalize_pixiv_popularity_tag("東方Project10000users入り")
    assert result is not None
    assert result["base_tag"] == "東方Project"
    assert result["tag_kind"] == "popularity_series_hint"
    assert result["canonical_series"] is None


def test_normalize_pixiv_popularity_tag_not_popularity():
    from core.tag_classifier import normalize_pixiv_popularity_tag
    assert normalize_pixiv_popularity_tag("ブルーアーカイブ") is None
    assert normalize_pixiv_popularity_tag("羽川ハスミ") is None
    assert normalize_pixiv_popularity_tag("巨乳") is None
