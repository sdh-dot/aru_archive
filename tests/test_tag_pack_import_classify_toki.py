"""
Tag Pack Import → classify_pixiv_tags E2E 테스트.

enriched pack을 DB에 seed한 후 classify_pixiv_tags로 검증한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_JSON = ROOT / "docs" / "tag_pack_export_localized_ko_ja.json"


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


@pytest.fixture(scope="session")
def enriched_pack_data():
    """enriched pack을 session scope로 한 번만 생성."""
    if not SOURCE_JSON.exists():
        pytest.skip(f"Source JSON not found: {SOURCE_JSON}")
    raw = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    from tools.enrich_tag_pack_aliases import enrich_pack
    enriched, _ = enrich_pack(raw, use_danbooru=False)
    return enriched


@pytest.fixture
def seeded_conn(conn, enriched_pack_data, tmp_path):
    """enriched pack을 import_localized_tag_pack으로 DB에 seed."""
    enriched_path = tmp_path / "enriched_test.json"
    enriched_path.write_text(
        json.dumps(enriched_pack_data, ensure_ascii=False),
        encoding="utf-8",
    )
    from core.tag_pack_loader import import_localized_tag_pack
    import_localized_tag_pack(conn, enriched_path)
    return conn


# ---------------------------------------------------------------------------
# トキ alias → classify
# ---------------------------------------------------------------------------

class TestClassifyToki:
    def test_katakana_toki_classifies_to_japanese_canonical(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["トキ"], conn=seeded_conn)
        assert "飛鳥馬トキ" in result["character_tags"], \
            "トキ는 飛鳥馬トキ로 분류되어야 함"

    def test_katakana_toki_infers_blue_archive_series(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["トキ"], conn=seeded_conn)
        assert "Blue Archive" in result["series_tags"], \
            "飛鳥馬トキ의 parent_series로 Blue Archive가 추론되어야 함"

    def test_danbooru_tag_classifies_to_japanese_canonical(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["toki_(blue_archive)"], conn=seeded_conn)
        assert "飛鳥馬トキ" in result["character_tags"]

    def test_english_toki_classifies_to_japanese_canonical(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Toki"], conn=seeded_conn)
        assert "飛鳥馬トキ" in result["character_tags"]

    def test_asuma_toki_classifies_to_japanese_canonical(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Asuma Toki"], conn=seeded_conn)
        assert "飛鳥馬トキ" in result["character_tags"]

    def test_korean_toki_classifies_to_japanese_canonical(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["아스마 토키"], conn=seeded_conn)
        assert "飛鳥馬トキ" in result["character_tags"]

    def test_school_uniform_variant_classifies_to_base(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Toki (school Uniform)"], conn=seeded_conn)
        assert "飛鳥馬トキ" in result["character_tags"], \
            "variant alias 'Toki (school Uniform)'이 base canonical로 분류되어야 함"

    def test_school_uniform_danbooru_tag_classifies_to_base(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(
            ["toki_(school_uniform)_(blue_archive)"], conn=seeded_conn
        )
        assert "飛鳥馬トキ" in result["character_tags"]

    def test_full_japanese_name_classifies(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["飛鳥馬トキ"], conn=seeded_conn)
        assert "飛鳥馬トキ" in result["character_tags"]


# ---------------------------------------------------------------------------
# Tsubasa classify
# ---------------------------------------------------------------------------

class TestClassifyTsubasa:
    def test_tsubasa_classifies_to_japanese_canonical(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Tsubasa"], conn=seeded_conn)
        assert "小鳥遊ツバサ" in result["character_tags"]

    def test_tsubasa_danbooru_tag_classifies(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["tsubasa_(blue_archive)"], conn=seeded_conn)
        assert "小鳥遊ツバサ" in result["character_tags"]


# ---------------------------------------------------------------------------
# 기존 정규화된 캐릭터 회귀 테스트
# ---------------------------------------------------------------------------

class TestExistingCharactersNotBroken:
    def test_arona_still_classifies(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["arona_(blue_archive)"], conn=seeded_conn)
        assert "アロナ" in result["character_tags"]

    def test_hina_still_classifies(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["hina_(blue_archive)"], conn=seeded_conn)
        assert "空崎ヒナ" in result["character_tags"]

    def test_mari_idol_variant_still_classifies(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["mari_(idol)_(blue_archive)"], conn=seeded_conn)
        assert "伊落マリー" in result["character_tags"]
