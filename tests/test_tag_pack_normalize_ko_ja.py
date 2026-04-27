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

    canonical_changed_entries = [
        entry
        for entry in normalized.values()
        if any(alias.endswith("_(blue_archive)") for alias in entry.get("aliases", []))
        and any(alias != entry["canonical"] for alias in entry.get("aliases", []))
    ]

    assert canonical_changed_entries
    assert any(entry.get("localizations", {}).get("en") for entry in canonical_changed_entries)


def test_variant_and_duplicate_aliases_are_preserved_in_merged_entries() -> None:
    normalized = _characters_by_key(_load(OUTPUT))

    merged_variant_entries = [
        entry
        for entry in normalized.values()
        if entry.get("_review", {}).get("merged_variants")
    ]

    assert merged_variant_entries
    for entry in merged_variant_entries:
        merged_variants = entry["_review"]["merged_variants"]
        assert isinstance(merged_variants, list)
        assert all("source_canonical" in item for item in merged_variants)


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
        item["parent_series"] == "Blue Archive"
        and item["reason"] == "canonical"
        and item["from"] != item["to"]
        for item in report["canonical_changes"]
    )
    assert any(
        item["type"] == "canonical_merge"
        and item["parent_series"] == "Blue Archive"
        and "variant/costume tag merged into base character" in item["reason"]
        for item in report["merges"]
    )
