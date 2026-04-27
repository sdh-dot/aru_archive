"""
character alias의 parent_series로부터 series를 역추론하는 기능 테스트.

핵심 원칙:
  - series raw tag 없이 character alias만으로 series_tags 보강 가능
  - ambiguous alias는 series context 없으면 자동 확정 금지
  - series context가 있으면 ambiguous alias에서 해당 series character 확정
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.tag_classifier import classify_pixiv_tags


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    """ワカモ aliases가 등록된 DB."""
    from db.database import initialize_database
    db = initialize_database(str(tmp_path / "test.db"))
    db.row_factory = sqlite3.Row
    db.executemany(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, source, created_at) "
        "VALUES (?, ?, ?, ?, 1, 'user', ?)",
        [
            ("ワカモ(正月)",    "狐坂ワカモ",   "character", "Blue Archive", _now()),
            ("浅黄ワカモ(正月)", "狐坂ワカモ",  "character", "Blue Archive", _now()),
            ("狐坂ワカモ",      "狐坂ワカモ",   "character", "Blue Archive", _now()),
            ("ブルアカ",        "Blue Archive", "series",    "",             _now()),
        ],
    )
    db.commit()
    return db


@pytest.fixture()
def ambiguous_conn(tmp_path: Path) -> sqlite3.Connection:
    """マリー → 2개 series로 ambiguous한 DB."""
    from db.database import initialize_database
    db = initialize_database(str(tmp_path / "ambiguous.db"))
    db.row_factory = sqlite3.Row
    db.executemany(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, enabled, source, created_at) "
        "VALUES (?, ?, ?, ?, 1, 'user', ?)",
        [
            ("マリー", "伊落マリー",  "character", "Blue Archive",  _now()),
            ("マリー", "Other Marie", "character", "Other Series",  _now()),
            ("ブルアカ", "Blue Archive", "series",  "",             _now()),
        ],
    )
    db.commit()
    return db


class TestCharacterOnlyInfersSeries:
    def test_character_alias_only_infers_series(self, conn):
        """character alias만 있어도 parent_series로 series_tags가 보강된다."""
        result = classify_pixiv_tags(["ワカモ(正月)"], conn=conn)
        assert result["character_tags"] == ["狐坂ワカモ"]
        assert "Blue Archive" in result["series_tags"]

    def test_character_alias_with_general_tag_infers_series(self, conn):
        """character alias + 일반 태그 조합에서도 series 보강이 된다."""
        result = classify_pixiv_tags(["ワカモ(正月)", "晴着", "正月"], conn=conn)
        assert result["character_tags"] == ["狐坂ワカモ"]
        assert "Blue Archive" in result["series_tags"]
        assert "晴着" in result["tags"]
        assert "正月" in result["tags"]

    def test_series_direct_and_character_alias(self, conn):
        """series direct match + character alias → series_tags에 중복 없이 추가."""
        result = classify_pixiv_tags(["ブルアカ", "ワカモ(正月)"], conn=conn)
        assert "Blue Archive" in result["series_tags"]
        assert result["character_tags"] == ["狐坂ワカモ"]
        assert result["series_tags"].count("Blue Archive") == 1

    def test_multiple_aliases_same_canonical_dedup(self, conn):
        """같은 canonical로 귀결되는 여러 alias가 character_tags에서 dedupe된다."""
        result = classify_pixiv_tags(
            ["ワカモ(正月)", "浅黄ワカモ(正月)", "狐坂ワカモ"], conn=conn
        )
        assert result["character_tags"] == ["狐坂ワカモ"]
        assert "Blue Archive" in result["series_tags"]
        assert result["character_tags"].count("狐坂ワカモ") == 1

    def test_no_series_alias_present_but_series_inferred(self, conn):
        """raw_tags에 series alias가 없어도 character alias로 series가 추가된다."""
        result = classify_pixiv_tags(["ワカモ(正月)"], conn=conn)
        # raw_tags에 ブルアカ 없음
        assert "Blue Archive" not in ["ワカモ(正月)"]
        assert "Blue Archive" in result["series_tags"]


class TestAmbiguousAliasHandling:
    def test_ambiguous_alias_without_series_context_not_confirmed(self, ambiguous_conn):
        """series context 없이 ambiguous alias는 자동 확정되지 않는다."""
        result = classify_pixiv_tags(["マリー"], conn=ambiguous_conn)
        assert result["character_tags"] == []
        assert result["series_tags"] == []
        assert len(result["ambiguous"]) == 1
        amb = result["ambiguous"][0]
        assert amb["raw_tag"] == "マリー"
        assert amb["reason"] == "ambiguous_character_alias"
        assert len(amb["candidates"]) == 2

    def test_ambiguous_alias_with_series_context_disambiguated(self, ambiguous_conn):
        """series context가 있으면 ambiguous alias에서 해당 series character가 확정된다."""
        result = classify_pixiv_tags(["マリー", "ブルアカ"], conn=ambiguous_conn)
        assert "伊落マリー" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]
        assert result["ambiguous"] == []

    def test_ambiguous_alias_candidates_structure(self, ambiguous_conn):
        """ambiguous 항목의 candidates 구조가 올바르다."""
        result = classify_pixiv_tags(["マリー"], conn=ambiguous_conn)
        candidates = result["ambiguous"][0]["candidates"]
        series_set = {c["parent_series"] for c in candidates}
        assert "Blue Archive" in series_set
        assert "Other Series" in series_set


class TestEvidenceTracking:
    def test_inferred_series_in_evidence(self, conn):
        """character alias로부터 역추론된 series는 evidence에 기록된다."""
        result = classify_pixiv_tags(["ワカモ(正月)"], conn=conn)
        ev_series = result["evidence"]["series"]
        assert any(
            ev["source"] == "inferred_from_character"
            and ev["canonical"] == "Blue Archive"
            for ev in ev_series
        )

    def test_inferred_evidence_contains_matched_character(self, conn):
        """inferred series evidence에 matched_character와 matched_raw_tag가 있다."""
        result = classify_pixiv_tags(["ワカモ(正月)"], conn=conn)
        ev = result["evidence"]["series"][0]
        assert ev["matched_character"] == "狐坂ワカモ"
        assert ev["matched_raw_tag"] == "ワカモ(正月)"

    def test_direct_series_not_in_inferred_evidence(self, conn):
        """direct series match는 inferred_from_character evidence에 나타나지 않는다."""
        result = classify_pixiv_tags(["ブルアカ", "ワカモ(正月)"], conn=conn)
        ev_series = result["evidence"]["series"]
        # Blue Archive는 ブルアカ로 direct match → inferred에 없어야 함
        assert all(ev["canonical"] != "Blue Archive" for ev in ev_series)

    def test_character_evidence_contains_match_info(self, conn):
        """character evidence에 canonical, source, matched_raw_tag가 있다."""
        result = classify_pixiv_tags(["ワカモ(正月)"], conn=conn)
        ev_chars = result["evidence"]["characters"]
        assert any(
            ev["canonical"] == "狐坂ワカモ"
            and ev["source"] == "tag_aliases"
            and ev["matched_raw_tag"] == "ワカモ(正月)"
            for ev in ev_chars
        )

    def test_evidence_keys_always_present(self):
        """evidence, ambiguous 키는 항상 반환된다 (empty input 포함)."""
        result = classify_pixiv_tags([])
        assert "evidence" in result
        assert "series" in result["evidence"]
        assert "characters" in result["evidence"]
        assert "ambiguous" in result

    def test_builtin_character_alias_infers_series_no_conn(self):
        """conn=None에서 built-in character alias도 parent_series를 보강한다."""
        result = classify_pixiv_tags(["伊落マリー"])
        assert "伊落マリー" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]
