"""
Short Alias Ambiguity 탐지 및 분류 보호 테스트.

같은 alias가 여러 parent_series에 걸치는 경우를 탐지하고,
series context 없이는 자동 확정하지 않음을 검증한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_JSON = ROOT / "docs" / "tag_pack_export_localized_ko_ja.json"


@pytest.fixture(scope="module")
def source_pack():
    if not SOURCE_JSON.exists():
        pytest.skip(f"Source JSON not found: {SOURCE_JSON}")
    return json.loads(SOURCE_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def enriched_result(source_pack):
    from tools.enrich_tag_pack_aliases import enrich_pack
    return enrich_pack(source_pack, use_danbooru=False)


@pytest.fixture(scope="module")
def enriched_pack(enriched_result):
    return enriched_result[0]


@pytest.fixture(scope="module")
def enriched_report(enriched_result):
    return enriched_result[1]


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


@pytest.fixture
def seeded_conn(conn, enriched_result, tmp_path):
    enriched, _ = enriched_result
    enriched_path = tmp_path / "enriched_test.json"
    enriched_path.write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
    from core.tag_pack_loader import import_localized_tag_pack
    import_localized_tag_pack(conn, enriched_path)
    return conn


# ---------------------------------------------------------------------------
# Ambiguous alias 탐지
# ---------------------------------------------------------------------------

class TestAmbiguousAliasDetection:
    def test_ui_alias_detected_as_ambiguous(self, enriched_report):
        """'Ui'는 Blue Archive (古関ウイ)와 Trickcal (Ui) 양쪽에 있음."""
        ambiguous_aliases = {a["alias"] for a in enriched_report["ambiguous_aliases"]}
        assert "Ui" in ambiguous_aliases, \
            "'Ui' alias는 multi-canonical이므로 ambiguous로 탐지되어야 함"

    def test_ui_ambiguous_has_both_series(self, enriched_report):
        ui_entry = next(
            (a for a in enriched_report["ambiguous_aliases"] if a["alias"] == "Ui"),
            None,
        )
        assert ui_entry is not None
        series_set = {c["parent_series"] for c in ui_entry["candidates"]}
        assert "Blue Archive" in series_set
        assert "Trickcal" in series_set

    def test_alice_alias_detected_as_ambiguous(self, enriched_report):
        """'Alice'는 Blue Archive (天童アリス)와 Trickcal (Alice) 양쪽에 있음."""
        ambiguous_aliases = {a["alias"] for a in enriched_report["ambiguous_aliases"]}
        assert "Alice" in ambiguous_aliases, \
            "'Alice' alias는 multi-canonical이므로 ambiguous로 탐지되어야 함"

    def test_ambiguous_report_format(self, enriched_report):
        """ambiguous_aliases 형식 검증."""
        for entry in enriched_report["ambiguous_aliases"]:
            assert "alias" in entry
            assert "candidates" in entry
            assert isinstance(entry["candidates"], list)
            assert len(entry["candidates"]) >= 2
            for c in entry["candidates"]:
                assert "canonical" in c
                assert "parent_series" in c


# ---------------------------------------------------------------------------
# classify_pixiv_tags ambiguous 보호
# ---------------------------------------------------------------------------

class TestClassifyAmbiguousProtection:
    def test_ui_without_series_context_is_not_auto_confirmed(self, seeded_conn):
        """series context 없이 'Ui' → ambiguous로 처리, character_tags에 자동 추가 금지."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Ui"], conn=seeded_conn)
        # 古関ウイ (BA)와 Ui (Trickcal) 중 하나를 자동 선택하면 안 됨
        assert "古関ウイ" not in result["character_tags"], \
            "series context 없이 古関ウイ 자동 확정 금지"
        assert "Ui" not in result["character_tags"], \
            "series context 없이 Trickcal Ui 자동 확정 금지"
        assert len(result["ambiguous"]) > 0, \
            "ambiguous 목록에 Ui 항목이 있어야 함"

    def test_ui_with_blue_archive_disambiguates_to_kokeki_ui(self, seeded_conn):
        """Blue Archive series context가 있으면 Ui → 古関ウイ로 disambiguation."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Ui", "ブルーアーカイブ"], conn=seeded_conn)
        assert "古関ウイ" in result["character_tags"], \
            "Blue Archive context가 있으면 Ui → 古関ウイ로 확정되어야 함"

    def test_alice_without_series_context_is_not_auto_confirmed(self, seeded_conn):
        """series context 없이 'Alice' → ambiguous 처리."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Alice"], conn=seeded_conn)
        # 天童アリス (BA)와 Alice (Trickcal) 중 하나를 자동 선택하면 안 됨
        assert len(result["ambiguous"]) > 0 or (
            "天童アリス" not in result["character_tags"]
            and "Alice" not in result["character_tags"]
        ), "series context 없이 Alice 자동 확정 금지"


# ---------------------------------------------------------------------------
# Group/general 후보는 report에만 기록
# ---------------------------------------------------------------------------

class TestGroupGeneralCandidatesReportOnly:
    GROUP_GENERAL_CANONICALS = [
        "Gourmet Research Society",
        "Problem Solver 68",
        "Rabbit Platoon",
        "Veritas",
        "Occult Studies Club",
        "Justice Task Force Member",
        "タイツ",
        "メガネ",
        "白タイツ",
    ]

    def test_group_general_candidates_in_report(self, enriched_report):
        """group/general 후보가 review_items_remaining에 기록되어야 함."""
        group_general_in_report = {
            r["canonical"]
            for r in enriched_report["review_items_remaining"]
            if r.get("reason") == "group_or_general_candidate"
        }
        for canonical in self.GROUP_GENERAL_CANONICALS:
            assert canonical in group_general_in_report, \
                f"'{canonical}'이 group_general report에 없음"

    def test_group_general_summary_count(self, enriched_report):
        assert enriched_report["summary"]["group_general_candidates"] >= len(
            self.GROUP_GENERAL_CANONICALS
        )
