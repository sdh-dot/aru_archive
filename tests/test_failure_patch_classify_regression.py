"""
Failure patch classify regression tests.

patch 적용 후 classify_pixiv_tags가 새 캐릭터를 정확히 분류하는지 검증한다.

테스트 DB에 _PATCH_CHARACTERS를 tag_aliases로 직접 삽입하여 classify_pixiv_tags(conn=...) 호출.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# fixture: patch가 적용된 DB 연결
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_conn(tmp_path):
    from db.database import initialize_database
    from tools.apply_failure_tag_patch import _PATCH_CHARACTERS, _VARIANT_MERGES_FROM_FAILURES

    conn = initialize_database(str(tmp_path / "patch_test.db"))
    now = datetime.now(timezone.utc).isoformat()

    # Insert patch characters as tag_aliases (character type)
    for char in _PATCH_CHARACTERS:
        canonical = char["canonical"]
        parent_series = char.get("parent_series", "")
        for alias in char.get("aliases", []):
            conn.execute(
                "INSERT OR IGNORE INTO tag_aliases "
                "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
                "VALUES (?, ?, 'character', ?, 1, ?, ?)",
                (alias, canonical, parent_series, now, now),
            )

    # Insert variant tags as additional aliases to base characters
    for variant_tag, merge_info in _VARIANT_MERGES_FROM_FAILURES.items():
        base_canonical = merge_info["base_canonical"]
        conn.execute(
            "INSERT OR IGNORE INTO tag_aliases "
            "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
            "VALUES (?, ?, 'character', 'Blue Archive', 1, ?, ?)",
            (variant_tag, base_canonical, now, now),
        )

    # Insert Blue Archive series alias
    conn.execute(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, created_at, updated_at) "
        "VALUES ('ブルーアーカイブ', 'Blue Archive', 'series', '', 1, ?, ?)",
        (now, now),
    )

    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------

def _classify(tags, conn):
    from core.tag_classifier import classify_pixiv_tags
    return classify_pixiv_tags(tags, conn=conn)


# ---------------------------------------------------------------------------
# 1. 羽川ハスミ → character=羽川ハスミ, series=Blue Archive
# ---------------------------------------------------------------------------

class TestHasumiClassify:
    def test_full_name(self, patch_conn):
        r = _classify(["羽川ハスミ"], patch_conn)
        assert "羽川ハスミ" in r["character_tags"]
        assert "Blue Archive" in r["series_tags"]

    def test_short_alias(self, patch_conn):
        r = _classify(["ハスミ"], patch_conn)
        assert "羽川ハスミ" in r["character_tags"]
        assert "Blue Archive" in r["series_tags"]

    def test_variant_stripped(self, patch_conn):
        """羽川ハスミ(体操服) → canonical 羽川ハスミ via variant_stripped fallback."""
        r = _classify(["羽川ハスミ(体操服)"], patch_conn)
        assert "羽川ハスミ" in r["character_tags"]
        assert "Blue Archive" in r["series_tags"]


# ---------------------------------------------------------------------------
# 2. 猫塚ヒビキ(応援団) → character=猫塚ヒビキ, series=Blue Archive
# ---------------------------------------------------------------------------

class TestNekozukaHibikiClassify:
    def test_variant_tag(self, patch_conn):
        r = _classify(["猫塚ヒビキ(応援団)"], patch_conn)
        assert "猫塚ヒビキ" in r["character_tags"]
        assert "Blue Archive" in r["series_tags"]

    def test_base_tag(self, patch_conn):
        r = _classify(["猫塚ヒビキ"], patch_conn)
        assert "猫塚ヒビキ" in r["character_tags"]


# ---------------------------------------------------------------------------
# 3. 黒崎コユキ(バニーガール) → character=黒崎コユキ
# ---------------------------------------------------------------------------

class TestKoyukiVariantClassify:
    def test_bunny_girl_variant(self, patch_conn):
        r = _classify(["黒崎コユキ(バニーガール)"], patch_conn)
        assert "黒崎コユキ" in r["character_tags"]
        assert "Blue Archive" in r["series_tags"]


# ---------------------------------------------------------------------------
# 4. ブルーアーカイブ5000users入り → series=Blue Archive, character_tags=[]
# ---------------------------------------------------------------------------

class TestPopularityTagClassify:
    def test_popularity_becomes_series_hint(self, patch_conn):
        r = _classify(["ブルーアーカイブ5000users入り"], patch_conn)
        assert "Blue Archive" in r["series_tags"]
        assert r["character_tags"] == []

    def test_popularity_not_in_general(self, patch_conn):
        r = _classify(["ブルーアーカイブ5000users入り"], patch_conn)
        assert "ブルーアーカイブ5000users入り" not in r["tags"]

    def test_popularity_variants(self, patch_conn):
        for tag in (
            "ブルーアーカイブ1000users入り",
            "ブルーアーカイブ10000users入り",
            "ブルーアーカイブ30000users入り",
        ):
            r = _classify([tag], patch_conn)
            assert "Blue Archive" in r["series_tags"], f"Failed for {tag}"
            assert r["character_tags"] == [], f"Failed for {tag}"


# ---------------------------------------------------------------------------
# 5. 巨乳 → general only, character_tags=[]
# ---------------------------------------------------------------------------

class TestGeneralTagNotClassified:
    def test_general_tag_stays_general(self, patch_conn):
        r = _classify(["巨乳"], patch_conn)
        assert r["character_tags"] == []
        assert "巨乳" in r["tags"]

    def test_multiple_general_tags(self, patch_conn):
        r = _classify(["巨乳", "女の子", "おっぱい"], patch_conn)
        assert r["character_tags"] == []


# ---------------------------------------------------------------------------
# 6. Series disambiguator サツキ(ブルーアーカイブ) → 京極サツキ
# ---------------------------------------------------------------------------

class TestSeriesDisambiguatorClassify:
    def test_satsuki_disambiguator(self, patch_conn):
        r = _classify(["サツキ(ブルーアーカイブ)"], patch_conn)
        assert "京極サツキ" in r["character_tags"]
        assert "Blue Archive" in r["series_tags"]

    def test_kisaki_disambiguator(self, patch_conn):
        r = _classify(["キサキ(ブルーアーカイブ)"], patch_conn)
        assert "竜華キサキ" in r["character_tags"]

    def test_kirara_disambiguator(self, patch_conn):
        r = _classify(["キララ(ブルーアーカイブ)"], patch_conn)
        assert "夜桜キララ" in r["character_tags"]


# ---------------------------------------------------------------------------
# 7. Combined scenario: character + popularity + general
# ---------------------------------------------------------------------------

class TestCombinedScenario:
    def test_hasumi_with_popularity_and_general(self, patch_conn):
        tags = ["羽川ハスミ", "ブルーアーカイブ5000users入り", "体操服", "巨乳"]
        r = _classify(tags, patch_conn)
        assert "羽川ハスミ" in r["character_tags"]
        assert "Blue Archive" in r["series_tags"]
        # Popularity tag consumed, not in general
        assert "ブルーアーカイブ5000users入り" not in r["tags"]
        # General tags remain
        assert "体操服" in r["tags"]
        assert "巨乳" in r["tags"]

    def test_no_character_tags_for_group_tag(self, patch_conn):
        """便利屋68 は character_tags に入らない."""
        r = _classify(["便利屋68", "ブルーアーカイブ5000users入り"], patch_conn)
        assert r["character_tags"] == []
        assert "Blue Archive" in r["series_tags"]
        assert "便利屋68" in r["tags"]
