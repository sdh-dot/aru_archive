from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "normalize_tag_pack_ko_ja.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("normalize_tag_pack_ko_ja", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_official_canonical_localization_overrides_seeded_fallback() -> None:
    module = _load_module()
    official = module.BLUE_ARCHIVE_NAMES["Shiroko"]

    data = {
        "characters": [
            {
                "aliases": ["shiroko_(blue_archive)"],
                "canonical": "Shiroko",
                "localizations": {"en": "Shiroko"},
                "parent_series": "Blue Archive",
            },
            {
                "aliases": ["Shiroko"],
                "canonical": official["canonical"],
                "localizations": {
                    "en": "Shiroko",
                    "ko": "스나오카미 시로코",
                    "ja": official["ja"],
                },
                "parent_series": "Blue Archive",
            },
        ],
        "series": [],
    }

    output, report = module.normalize(data)
    module.validate(data, output, report)

    shiroko = output["characters"][0]
    assert shiroko["canonical"] == official["canonical"]
    assert shiroko["localizations"]["ko"] == "스나오카미 시로코"
    assert any(
        warning["type"] == "official_localization_preferred_from_official_canonical"
        and warning["locale"] == "ko"
        for warning in report["warnings"]
    )
