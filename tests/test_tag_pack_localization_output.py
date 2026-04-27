from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "docs" / "tag_pack_export.json"
OUTPUT = ROOT / "docs" / "tag_pack_export_localized_ko_ja.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_localized_tag_pack_output_exists_and_is_valid_json() -> None:
    assert OUTPUT.exists()
    data = _load(OUTPUT)
    assert isinstance(data.get("characters"), list)
    assert isinstance(data.get("series"), list)


def test_localized_tag_pack_preserves_counts_and_identity_fields() -> None:
    original = _load(INPUT)
    localized = _load(OUTPUT)

    assert len(localized["characters"]) <= len(original["characters"])
    assert len(localized["series"]) == len(original["series"])

    localized_entries = localized["characters"]
    for old in original["characters"]:
        assert any(
            new["canonical"] == old["canonical"] or old["canonical"] in new.get("aliases", [])
            for new in localized_entries
            if new.get("parent_series") == old.get("parent_series")
        )

    for old, new in zip(original["series"], localized["series"]):
        assert new["canonical"] == old["canonical"]


def test_localized_tag_pack_preserves_existing_aliases_and_localizations() -> None:
    original = _load(INPUT)
    localized = _load(OUTPUT)

    for section in ("series",):
        for old, new in zip(original[section], localized[section]):
            old_aliases = old.get("aliases", [])
            assert new.get("aliases", [])[: len(old_aliases)] == old_aliases
            assert len(new.get("aliases", [])) >= len(old_aliases)

            old_locs = old.get("localizations", {})
            new_locs = new.get("localizations", {})
            for locale in ("en", "ko", "ja"):
                if locale in old_locs:
                    assert new_locs.get(locale) == old_locs[locale]

    localized_entries = localized["characters"]
    for old in original["characters"]:
        candidates = [
            new
            for new in localized_entries
            if new.get("parent_series") == old.get("parent_series")
            and (new["canonical"] == old["canonical"] or old["canonical"] in new.get("aliases", []))
        ]
        assert candidates
        new = candidates[0]
        for alias in old.get("aliases", []):
            assert alias in new.get("aliases", [])
        for locale in ("ko", "ja"):
            if locale in old.get("localizations", {}):
                assert new.get("localizations", {}).get(locale) == old["localizations"][locale]


def test_localized_tag_pack_has_expected_review_annotations() -> None:
    localized = _load(OUTPUT)
    characters = {
        (entry.get("parent_series"), entry["canonical"]): entry
        for entry in localized["characters"]
    }

    assert "Mari" in characters[("Blue Archive", "伊落マリー")]["aliases"]
    assert characters[("Blue Archive", "空崎ヒナ")]["_review"]["merged_variants"]
    assert (
        characters[("Blue Archive", "Gourmet Research Society")]["_review"][
            "suggested_tag_type"
        ]
        == "group"
    )
    assert (
        characters[("Blue Archive", "タイツ")]["_review"]["suggested_tag_type"]
        == "general"
    )
