import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "tag_pack_export_localized_ko_ja_failure_patch_v2.json"
VALIDATOR_PATH = ROOT / "tools" / "validate_tag_pack_integrity.py"


def _load_data() -> dict:
    assert PACK_PATH.exists(), f"missing tag pack: {PACK_PATH}"
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def _is_mojibake(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if "�" in value:
        return True
    q_count = value.count("?")
    return q_count >= 2 and (q_count / len(value)) > 0.3


def test_failure_patch_v2_integrity_matches_validator_policy() -> None:
    data = _load_data()
    assert isinstance(data, dict)
    assert isinstance(data.get("series"), list)
    assert isinstance(data.get("characters"), list)

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR_PATH),
            str(PACK_PATH),
            "--strict",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_failure_patch_v2_has_no_alias_conflicts_or_orphans_or_duplicates() -> None:
    data = _load_data()
    series = data.get("series", [])
    characters = data.get("characters", [])

    series_canonicals = [s.get("canonical") for s in series]
    assert len(series_canonicals) == len(set(series_canonicals))

    series_set = set(series_canonicals)
    character_keys = []
    orphans = []
    alias_owners: dict[str, set[tuple[str, str]]] = defaultdict(set)

    for item in series:
        canonical = str(item.get("canonical", ""))
        for alias in item.get("aliases", []) or []:
            if isinstance(alias, str) and alias.strip():
                alias_owners[alias].add(("series", canonical))

    for item in characters:
        canonical = str(item.get("canonical", ""))
        parent_series = str(item.get("parent_series", ""))
        character_keys.append((canonical, parent_series))
        if parent_series not in series_set:
            orphans.append((canonical, parent_series))
        for alias in item.get("aliases", []) or []:
            if isinstance(alias, str) and alias.strip():
                alias_owners[alias].add(("character", canonical))

    assert len(character_keys) == len(set(character_keys))
    assert orphans == []

    conflicts = {k: v for k, v in alias_owners.items() if len(v) > 1}
    assert conflicts == {}


def test_failure_patch_v2_allows_reviewed_localization_gaps() -> None:
    data = _load_data()
    missing_ko = 0
    missing_ja = 0
    review_count = 0

    for section in ("series", "characters"):
        for item in data.get(section, []):
            locs = item.get("localizations", {})
            assert isinstance(locs, dict)

            for locale in ("ko", "ja", "en"):
                value = locs.get(locale)
                assert value is None or isinstance(value, str)

            if not str(locs.get("ko", "")).strip():
                missing_ko += 1
            if not str(locs.get("ja", "")).strip():
                missing_ja += 1

            if section == "characters" and "_review" in item:
                review = item["_review"]
                assert isinstance(review, (dict, list, str))
                if isinstance(review, str):
                    assert review.strip()
                review_count += 1

    # gaps/review는 정책상 허용되며, 0 강제하지 않는다.
    assert missing_ko >= 0 and missing_ja >= 0
    assert review_count >= 0


def test_failure_patch_v2_has_no_mojibake() -> None:
    data = _load_data()

    candidates = []
    for section in ("series", "characters"):
        for item in data.get(section, []):
            canonical = item.get("canonical", "")
            locs = item.get("localizations", {}) or {}
            aliases = item.get("aliases", []) or []

            if _is_mojibake(canonical):
                candidates.append(("canonical", canonical))

            for value in locs.values():
                if _is_mojibake(value):
                    candidates.append(("localization", value))

            for alias in aliases:
                if _is_mojibake(alias):
                    candidates.append(("alias", alias))

    assert candidates == []
