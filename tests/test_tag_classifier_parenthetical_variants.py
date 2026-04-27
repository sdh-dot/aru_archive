"""
Parenthetical Variant Alias 매칭 테스트.

'陸八魔アル(正月)', 'アル(ブルアカ)' 등 괄호 접미사를 가진 태그를
base character alias로 매칭하는 기능을 검증한다.

Pass 1b: 괄호 내용이 series alias면 series_set에 추가
Pass 2 fallback: 괄호 접미사 제거 후 base로 character 매칭 재시도
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
    if not SOURCE_JSON.exists():
        pytest.skip(f"Source JSON not found: {SOURCE_JSON}")
    raw = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    from tools.enrich_tag_pack_aliases import enrich_pack
    enriched, _ = enrich_pack(raw, use_danbooru=False)
    return enriched


@pytest.fixture
def seeded_conn(conn, enriched_pack_data, tmp_path):
    enriched_path = tmp_path / "enriched_test.json"
    enriched_path.write_text(
        json.dumps(enriched_pack_data, ensure_ascii=False),
        encoding="utf-8",
    )
    from core.tag_pack_loader import import_localized_tag_pack
    import_localized_tag_pack(conn, enriched_path)
    return conn


# ---------------------------------------------------------------------------
# _parse_parenthetical helper
# ---------------------------------------------------------------------------

class TestParseParenthetical:
    def test_ascii_paren(self):
        from core.tag_classifier import _parse_parenthetical
        assert _parse_parenthetical("陸八魔アル(正月)") == ("陸八魔アル", "正月")

    def test_fullwidth_paren(self):
        from core.tag_classifier import _parse_parenthetical
        assert _parse_parenthetical("陸八魔アル（正月）") == ("陸八魔アル", "正月")

    def test_ascii_bracket(self):
        from core.tag_classifier import _parse_parenthetical
        assert _parse_parenthetical("アル[Blue Archive]") == ("アル", "Blue Archive")

    def test_space_before_paren(self):
        from core.tag_classifier import _parse_parenthetical
        base, inner = _parse_parenthetical("Toki (school Uniform)")
        assert base == "Toki" and inner == "school Uniform"

    def test_no_paren_returns_original(self):
        from core.tag_classifier import _parse_parenthetical
        assert _parse_parenthetical("陸八魔アル") == ("陸八魔アル", "")

    def test_empty_base_returns_original(self):
        """'(正月)' alone: base would be empty → return original tag unchanged."""
        from core.tag_classifier import _parse_parenthetical
        assert _parse_parenthetical("(正月)") == ("(正月)", "")


# ---------------------------------------------------------------------------
# classify_pixiv_tags — variant_stripped matching (built-in aliases, no DB)
# ---------------------------------------------------------------------------

class TestVariantStrippedBuiltin:
    """陸八魔アル is in built-in CHARACTER_ALIASES, so no DB seed is needed."""

    def test_ascii_paren_variant_matches_character(self):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["陸八魔アル(正月)"])
        assert "陸八魔アル" in result["character_tags"], \
            "陸八魔アル(正月) should strip to 陸八魔アル via variant_stripped"

    def test_fullwidth_paren_variant_matches_character(self):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["陸八魔アル（正月）"])
        assert "陸八魔アル" in result["character_tags"]

    def test_variant_infers_series(self):
        """series tag is inferred from character's parent_series."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["陸八魔アル(正月)"])
        assert "Blue Archive" in result["series_tags"]

    def test_variant_evidence_match_type_is_variant_stripped(self):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["陸八魔アル(正月)"])
        char_ev = result["evidence"]["characters"]
        assert any(
            ev["match_type"] == "variant_stripped" and ev["canonical"] == "陸八魔アル"
            for ev in char_ev
        ), "Evidence should record match_type='variant_stripped'"

    def test_variant_evidence_has_variant_field(self):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["陸八魔アル(正月)"])
        char_ev = result["evidence"]["characters"]
        aru_ev = next(
            (ev for ev in char_ev if ev["canonical"] == "陸八魔アル"),
            None,
        )
        assert aru_ev is not None, "No evidence entry for 陸八魔アル"
        assert aru_ev.get("variant") == "正月", \
            f"Expected variant='正月', got {aru_ev.get('variant')!r}"

    def test_unrelated_tag_stays_in_general(self):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["晴れ着"])
        assert "晴れ着" in result["tags"]
        assert not result["character_tags"]


# ---------------------------------------------------------------------------
# classify_pixiv_tags — Pass 1b series hint + variant stripping (DB required)
# ---------------------------------------------------------------------------

class TestVariantWithSeriesHint:
    """アル(ブルアカ) requires the アル alias from the imported tag pack."""

    def test_aru_with_series_disambiguator_matches_character(self, seeded_conn):
        """アル(ブルアカ) → Pass 1b adds Blue Archive → base=アル matches 陸八魔アル."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["アル(ブルアカ)"], conn=seeded_conn)
        assert "陸八魔アル" in result["character_tags"]

    def test_aru_with_series_disambiguator_infers_series(self, seeded_conn):
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["アル(ブルアカ)"], conn=seeded_conn)
        assert "Blue Archive" in result["series_tags"]

    def test_aru_variant_only_no_explicit_series_tag(self, seeded_conn):
        """アル(正月) has no series disambiguator — series inferred from character."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["アル(正月)"], conn=seeded_conn)
        assert "陸八魔アル" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_combined_tags_from_screenshot(self, seeded_conn):
        """陸八魔アル(正月) + アル(ブルアカ) + 晴れ着 — not Author Fallback."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(
            ["陸八魔アル(正月)", "アル(ブルアカ)", "晴れ着"],
            conn=seeded_conn,
        )
        assert "陸八魔アル" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]
        assert "晴れ着" in result["tags"]
        assert result["character_tags"].count("陸八魔アル") == 1, "No duplicate character"
