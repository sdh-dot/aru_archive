#!/usr/bin/env python3
"""
Tag pack integrity validator.

태그 팩 JSON의 구조와 데이터 무결성을 정적으로 검사한다.

사용법:
    python tools/validate_tag_pack_integrity.py <path>
    python tools/validate_tag_pack_integrity.py <path> --strict
    python tools/validate_tag_pack_integrity.py <path> --json

검사 항목:
    - JSON parse / 최상위 필수 필드 (pack_id, name, version, series, characters)
    - 각 series/character의 필수 필드
    - 모지베이크(mojibake) — ASCII '?' 비율 >30% 또는 U+FFFD 등장
    - alias 충돌 — 같은 alias가 둘 이상의 series/character canonical에 매핑
    - parent_series orphan — character.parent_series가 series.canonical 집합 밖
    - duplicate canonical — series 내 / (canonical, parent_series) 내
    - 빈 alias / null canonical
    - 누락 ko / ja localization
    - _review 큐 크기

종료 코드:
    0 — 깨끗함 (또는 비-strict 모드에서 fatal 0건)
    1 — fatal 오류 (JSON 파싱, 필수 필드, 구조)
    2 — --strict 모드에서 경고 1건 이상

본 스크립트는 read-only — 입력 파일을 수정하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REQUIRED_TOP_LEVEL_KEYS = ("pack_id", "name", "version", "series", "characters")
REQUIRED_SERIES_KEYS = ("canonical",)
REQUIRED_CHARACTER_KEYS = ("canonical", "parent_series")


def is_mojibake(value: Any) -> bool:
    """주어진 값이 mojibake 의심 문자열인지 판정."""
    if not isinstance(value, str) or not value:
        return False
    if "�" in value:
        return True
    qc = value.count("?")
    if qc >= 2 and (qc / len(value)) > 0.3:
        return True
    return False


def collect_fatals(data: dict) -> list[str]:
    """파싱 후 fatal 구조 오류만 모은다."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["top-level is not an object"]

    for k in REQUIRED_TOP_LEVEL_KEYS:
        if k not in data:
            errors.append(f"missing required top-level key: {k!r}")

    series = data.get("series", [])
    chars = data.get("characters", [])
    if not isinstance(series, list):
        errors.append("'series' is not a list")
    if not isinstance(chars, list):
        errors.append("'characters' is not a list")

    if isinstance(series, list):
        for i, s in enumerate(series):
            if not isinstance(s, dict):
                errors.append(f"series[{i}] is not an object")
                continue
            for k in REQUIRED_SERIES_KEYS:
                if k not in s or not s[k]:
                    errors.append(f"series[{i}] missing required key: {k!r}")
    if isinstance(chars, list):
        for i, c in enumerate(chars):
            if not isinstance(c, dict):
                errors.append(f"characters[{i}] is not an object")
                continue
            for k in REQUIRED_CHARACTER_KEYS:
                if k not in c or not c[k]:
                    errors.append(f"characters[{i}] missing required key: {k!r}")

    return errors


def collect_warnings(data: dict) -> dict[str, Any]:
    """비-fatal 경고를 카운트한다."""
    series = data.get("series", []) or []
    chars = data.get("characters", []) or []

    moji_loc = 0
    moji_alias = 0
    empty_alias = 0
    null_canonical = 0

    for it in series + chars:
        for v in (it.get("localizations") or {}).values():
            if is_mojibake(v):
                moji_loc += 1
        for a in it.get("aliases", []) or []:
            if not isinstance(a, str) or not a.strip():
                empty_alias += 1
                continue
            if is_mojibake(a):
                moji_alias += 1
        if it.get("canonical") in (None, ""):
            null_canonical += 1

    series_canons = {s["canonical"] for s in series if s.get("canonical")}
    orphans = sum(
        1
        for c in chars
        if c.get("canonical") and c.get("parent_series") not in series_canons
    )

    alias_owners: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for s in series:
        for a in s.get("aliases", []) or []:
            if isinstance(a, str) and a.strip():
                alias_owners[a].add(("series", s.get("canonical", "")))
    for c in chars:
        for a in c.get("aliases", []) or []:
            if isinstance(a, str) and a.strip():
                alias_owners[a].add(("character", c.get("canonical", "")))
    conflicts = sum(1 for owners in alias_owners.values() if len(owners) > 1)

    series_canon_counts: dict[str, int] = defaultdict(int)
    char_key_counts: dict[tuple[str, str], int] = defaultdict(int)
    for s in series:
        canon = s.get("canonical")
        if canon:
            series_canon_counts[canon] += 1
    for c in chars:
        canon = c.get("canonical")
        parent = c.get("parent_series", "")
        if canon:
            char_key_counts[(canon, parent)] += 1
    dup_series = sum(1 for v in series_canon_counts.values() if v > 1)
    dup_char = sum(1 for v in char_key_counts.values() if v > 1)

    missing_ko = sum(
        1 for c in chars if not (c.get("localizations") or {}).get("ko")
    )
    missing_ja = sum(
        1 for c in chars if not (c.get("localizations") or {}).get("ja")
    )

    review_count = sum(1 for c in chars if c.get("_review"))

    return {
        "series": len(series),
        "characters": len(chars),
        "mojibake_localizations": moji_loc,
        "mojibake_aliases": moji_alias,
        "empty_aliases": empty_alias,
        "null_canonicals": null_canonical,
        "parent_series_orphans": orphans,
        "alias_conflicts": conflicts,
        "duplicate_series_canonicals": dup_series,
        "duplicate_character_keys": dup_char,
        "missing_ko": missing_ko,
        "missing_ja": missing_ja,
        "characters_with_review": review_count,
    }


def has_warning_over_threshold(warnings: dict[str, Any]) -> bool:
    """strict 모드에서 non-zero로 보고할 경고를 판정."""
    keys = (
        "mojibake_localizations",
        "mojibake_aliases",
        "empty_aliases",
        "null_canonicals",
        "parent_series_orphans",
        "alias_conflicts",
        "duplicate_series_canonicals",
        "duplicate_character_keys",
    )
    return any(warnings.get(k, 0) > 0 for k in keys)


def render_text(data: dict, fatals: list[str], warnings: dict[str, Any]) -> str:
    lines = []
    lines.append(f"pack_id: {data.get('pack_id')}")
    lines.append(f"name:    {data.get('name')}")
    lines.append(f"version: {data.get('version')}")
    lines.append(f"source:  {data.get('source')}")
    lines.append("")
    if fatals:
        lines.append("=== FATAL ===")
        for e in fatals:
            lines.append(f"  - {e}")
        lines.append("")
    lines.append("=== counts ===")
    for k in ("series", "characters"):
        lines.append(f"  {k}: {warnings.get(k, 0)}")
    lines.append("")
    lines.append("=== integrity warnings ===")
    for k in (
        "mojibake_localizations",
        "mojibake_aliases",
        "empty_aliases",
        "null_canonicals",
        "parent_series_orphans",
        "alias_conflicts",
        "duplicate_series_canonicals",
        "duplicate_character_keys",
    ):
        lines.append(f"  {k}: {warnings.get(k, 0)}")
    lines.append("")
    lines.append("=== localization gaps ===")
    for k in ("missing_ko", "missing_ja", "characters_with_review"):
        lines.append(f"  {k}: {warnings.get(k, 0)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate tag pack JSON integrity (read-only)"
    )
    parser.add_argument("path", type=Path, help="path to tag pack JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero (2) when integrity warnings exist",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON report on stdout",
    )
    args = parser.parse_args()

    path: Path = args.path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"FATAL: file not found: {path}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FATAL: cannot read {path}: {exc}", file=sys.stderr)
        return 1

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"FATAL: JSON parse error in {path}: {exc}", file=sys.stderr)
        return 1

    fatals = collect_fatals(data)
    warnings = collect_warnings(data) if not isinstance(fatals, list) or not any(
        e.startswith("top-level is not an object") for e in fatals
    ) else {}

    if args.json:
        report = {
            "path": str(path),
            "fatal": fatals,
            "warnings": warnings,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(data if isinstance(data, dict) else {}, fatals, warnings))

    if fatals:
        return 1
    if args.strict and has_warning_over_threshold(warnings):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
