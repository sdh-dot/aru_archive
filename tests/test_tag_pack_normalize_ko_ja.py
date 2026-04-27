from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "docs" / "tag_pack_export.json"
OUTPUT = ROOT / "docs" / "tag_pack_export_localized_ko_ja.json"
REPORT = ROOT / "docs" / "tag_pack_export_localized_ko_ja_report.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _characters_by_key(data: dict) -> dict[tuple[str, str], dict]:
    return {
        (entry.get("parent_series", ""), entry["canonical"]): entry
        for entry in data["characters"]
    }


def test_normalized_tag_pack_output_and_report_exist() -> None:
    assert OUTPUT.exists()
    assert REPORT.exists()
    assert isinstance(_load(OUTPUT)["characters"], list)
    assert isinstance(_load(REPORT)["summary"], dict)


def test_existing_ko_ja_localizations_are_preserved_after_merge() -> None:
    original = _load(INPUT)
    normalized = _characters_by_key(_load(OUTPUT))

    for source in original["characters"]:
        old_locs = source.get("localizations", {})
        for locale in ("ko", "ja"):
            if locale not in old_locs:
                continue
            target = None
            for entry in normalized.values():
                if source["canonical"] == entry["canonical"] or source["canonical"] in entry.get("aliases", []):
                    target = entry
                    break
            assert target is not None
            assert target.get("localizations", {}).get(locale) == old_locs[locale]


def test_old_canonical_and_aliases_are_preserved_when_canonical_changes() -> None:
    normalized = _characters_by_key(_load(OUTPUT))

    aru = normalized[("Blue Archive", "陸八魔アル")]
    assert "Aru" in aru["aliases"]
    assert "aru_(blue_archive)" in aru["aliases"]
    assert aru["localizations"]["en"] == "Rikuhachima Aru"

    yuuka = normalized[("Blue Archive", "早瀬ユウカ")]
    assert "Yuuka" in yuuka["aliases"]
    assert "yuuka_(blue_archive)" in yuuka["aliases"]
    assert yuuka["localizations"]["ko"] == "하야세 유우카"


def test_variant_and_duplicate_aliases_are_preserved_in_merged_entries() -> None:
    normalized = _characters_by_key(_load(OUTPUT))

    hina = normalized[("Blue Archive", "空崎ヒナ")]
    assert "Hina (dress)" in hina["aliases"]
    assert "hina_(dress)_(blue_archive)" in hina["aliases"]
    assert hina["_review"]["merged_variants"]

    mari = normalized[("Blue Archive", "伊落マリー")]
    assert "Mari" in mari["aliases"]
    assert "mari_(idol)_(blue_archive)" in mari["aliases"]
    assert "伊落マリー(体操服)" in mari["aliases"]


def test_review_fields_do_not_break_import_shape() -> None:
    data = _load(OUTPUT)
    for entry in data["characters"]:
        assert "canonical" in entry
        assert "aliases" in entry
        assert "parent_series" in entry
        assert isinstance(entry.get("localizations", {}), dict)
        if "_review" in entry:
            assert isinstance(entry["_review"], dict)


def test_report_contains_expected_summary_and_merge_records() -> None:
    report = _load(REPORT)
    summary = report["summary"]
    assert summary["canonical_changed"] > 0
    assert summary["entities_merged"] > 0
    assert summary["review_items"] > 0
    assert any(
        item["from"] == "Aru" and item["to"] == "陸八魔アル"
        for item in report["canonical_changes"]
    )
    assert any(
        item["from"] == "Hina (dress)" and item["to"] == "空崎ヒナ"
        for item in report["merges"]
    )
