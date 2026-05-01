"""repair_mojibake_via_v2.py — Mojibake localization repair via v2 cross-reference.

Backfills ko/ja localizations in a v3 raw draft using clean values from the
active v2 dataset.  Only canonical-exact matches with a non-review, non-mojibake
v2 entry are applied.  Alias mojibake, alias conflicts, parent_series orphans,
and characters without a suitable v2 reference are left untouched and documented
in the repair report.

Usage
-----
python tools/repair_mojibake_via_v2.py \\
    docs/tag_packs/drafts/tag_pack_export_20260430.raw.json \\
    --reference docs/tag_pack_export_localized_ko_ja_failure_patch_v2.json \\
    --output   docs/tag_packs/drafts/tag_pack_export_20260430.repaired.json \\
    --report   docs/tag_packs/drafts/tag_pack_export_20260430.repair_report.json

Optional flags
--------------
--dry-run   Run analysis only; do not write --output or --report files.
--quiet     Suppress progress output to stdout.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Mojibake detection
# ---------------------------------------------------------------------------

def is_mojibake(value: Any) -> bool:
    """Return True when *value* looks like a charset-corrupted string.

    Heuristics (in order):
    1. Contains U+FFFD REPLACEMENT CHARACTER or U+25A1 WHITE SQUARE.
    2. Contains at least 2 literal question-marks that make up more than 30 %
       of the string length (catches ``??????`` style corruption).
    """
    if not isinstance(value, str) or not value:
        return False
    if "�" in value or "□" in value:
        return True
    qc = value.count("?")
    if qc >= 2 and (qc / len(value)) > 0.3:
        return True
    return False


def _needs_repair(value: Any) -> bool:
    """True when a localization slot is absent, empty, or mojibake."""
    return value is None or value == "" or is_mojibake(value)


# ---------------------------------------------------------------------------
# Repair logic
# ---------------------------------------------------------------------------

_REPAIR_LOCALES = ("ko", "ja")

# Reasons a repair could not be completed for a given locale
_REASON_NOT_FOUND = "v2_canonical_not_found"
_REASON_REVIEW    = "v2_review_marker"
_REASON_MOJIBAKE  = "v2_value_mojibake"
_REASON_MISSING   = "v2_value_missing"


def _build_ref_index(reference_data: dict) -> dict[str, dict]:
    """Return ``{canonical: char_dict}`` from the reference (v2) dataset."""
    return {ch["canonical"]: ch for ch in reference_data.get("characters", [])}


def _resolve_repair_reason(ref_ch: dict | None, locale: str) -> tuple[str | None, str]:
    """Determine why a locale slot cannot be repaired, or return the repair value.

    Returns ``(ref_value, reason)`` where *ref_value* is the clean replacement
    string when repair is possible, or ``None`` accompanied by a reason constant
    when it is not.
    """
    if ref_ch is None:
        return None, _REASON_NOT_FOUND
    if "_review" in ref_ch:
        return None, _REASON_REVIEW
    ref_val = ref_ch.get("localizations", {}).get(locale)
    if ref_val is None or ref_val == "":
        return None, _REASON_MISSING
    if is_mojibake(ref_val):
        return None, _REASON_MOJIBAKE
    return ref_val, ""


def _merge_review_marker(
    ch: dict,
    missing_locales: list[str],
    first_reason: str | None,
) -> None:
    """Attach or update a ``_review`` marker on *ch* for unrepaired locales."""
    existing = ch.get("_review", {})
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged["needs_external_localization_source"] = True
    merged["missing_locales"] = list(
        dict.fromkeys(merged.get("missing_locales", []) + missing_locales)
    )
    if "repair_reason" not in merged and first_reason:
        merged["repair_reason"] = first_reason
    ch["_review"] = merged


def _classify_raw_value(raw_val: Any, counts: dict, locale: str) -> bool:
    """Increment the appropriate found-counter and return True when repair is needed."""
    if raw_val is None or raw_val == "":
        counts[locale]["missing_found"] += 1
        return True
    if is_mojibake(raw_val):
        counts[locale]["mojibake_found"] += 1
        return True
    return False


def _apply_repair(
    canonical: str,
    locale: str,
    raw_val: Any,
    ref_val: str,
    locs: dict,
    counts: dict,
    repaired_list: list,
    quiet: bool,
) -> None:
    """Write *ref_val* into *locs* and record the repair entry."""
    locs[locale] = ref_val
    counts[locale]["repaired"] += 1
    repaired_list.append(
        {"canonical": canonical, "locale": locale,
         "before": raw_val, "after": ref_val, "source": "v2"}
    )
    if not quiet:
        print(
            f"  repaired  {canonical!r:<40} [{locale}]"
            f"  {raw_val!r} -> {ref_val!r}"
        )


def _process_locale(
    canonical: str,
    locale: str,
    locs: dict,
    ref_ch: dict | None,
    counts: dict,
    repaired_list: list,
    not_repaired_list: list,
    quiet: bool,
) -> str | None:
    """Process one locale slot for one character.

    Returns the failure reason string when the slot could not be repaired, or
    ``None`` when the value was already clean or repair succeeded.
    """
    raw_val = locs.get(locale)
    if not _classify_raw_value(raw_val, counts, locale):
        return None  # already clean — nothing to do

    ref_val, reason = _resolve_repair_reason(ref_ch, locale)

    if ref_val is not None:
        _apply_repair(canonical, locale, raw_val, ref_val,
                      locs, counts, repaired_list, quiet)
        return None

    counts[locale]["not_repaired"] += 1
    not_repaired_list.append(
        {"canonical": canonical, "locale": locale, "reason": reason}
    )
    return reason


def repair(
    raw_data: dict,
    reference_data: dict,
    input_path: str,
    reference_path: str,
    *,
    quiet: bool = False,
) -> tuple[dict, dict]:
    """Repair *raw_data* using *reference_data* and return ``(repaired, report)``.

    Neither input dict is mutated; the returned *repaired* dict is a deep copy
    with only localizations overwritten where safe to do so.
    """
    ref_index = _build_ref_index(reference_data)
    output    = copy.deepcopy(raw_data)
    now_iso   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    counts: dict[str, dict[str, int]] = {
        locale: {"mojibake_found": 0, "missing_found": 0,
                 "repaired": 0, "not_repaired": 0}
        for locale in _REPAIR_LOCALES
    }
    repaired_per_character:     list[dict] = []
    not_repaired_per_character: list[dict] = []
    alias_mojibake_found = 0
    alias_repair_skipped = 0
    total_characters     = len(output.get("characters", []))

    for ch in output.get("characters", []):
        canonical = ch["canonical"]
        locs      = ch.setdefault("localizations", {})
        ref_ch    = ref_index.get(canonical)

        for alias in ch.get("aliases", []):
            if is_mojibake(alias):
                alias_mojibake_found += 1
                alias_repair_skipped += 1

        missing_locales: list[str] = []
        first_reason:    str | None = None

        for locale in _REPAIR_LOCALES:
            failure = _process_locale(
                canonical, locale, locs, ref_ch,
                counts, repaired_per_character, not_repaired_per_character,
                quiet,
            )
            if failure is not None:
                missing_locales.append(locale)
                if first_reason is None:
                    first_reason = failure

        if missing_locales:
            _merge_review_marker(ch, missing_locales, first_reason)

    output["repaired_at"]             = now_iso
    output["source"]                  = "v3_draft_mojibake_repaired_via_v2"
    output["repaired_from"]           = str(input_path)
    output["repaired_with_reference"] = str(reference_path)

    report = {
        "input":      str(input_path),
        "reference":  str(reference_path),
        "output":     "",  # filled in by caller
        "repaired_at": now_iso,
        "summary": {
            "total_characters":    total_characters,
            "ko_mojibake_found":   counts["ko"]["mojibake_found"],
            "ko_missing_found":    counts["ko"]["missing_found"],
            "ko_repaired":         counts["ko"]["repaired"],
            "ko_not_repaired":     counts["ko"]["not_repaired"],
            "ja_mojibake_found":   counts["ja"]["mojibake_found"],
            "ja_missing_found":    counts["ja"]["missing_found"],
            "ja_repaired":         counts["ja"]["repaired"],
            "ja_not_repaired":     counts["ja"]["not_repaired"],
            "alias_mojibake_found": alias_mojibake_found,
            "alias_repair_skipped": alias_repair_skipped,
        },
        "repaired_per_character":     repaired_per_character,
        "not_repaired_per_character": not_repaired_per_character,
    }

    return output, report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair mojibake localizations in a v3 raw draft using v2 reference data."
    )
    parser.add_argument(
        "input",
        help="Path to the v3 raw draft JSON file.",
    )
    parser.add_argument(
        "--reference",
        required=True,
        metavar="PATH",
        help="Path to the v2 active reference JSON file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="PATH",
        help="Destination path for the repaired JSON output.",
    )
    parser.add_argument(
        "--report",
        required=True,
        metavar="PATH",
        help="Destination path for the repair report JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run analysis only; do not write --output or --report files.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-character progress output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    input_path     = Path(args.input)
    reference_path = Path(args.reference)
    output_path    = Path(args.output)
    report_path    = Path(args.report)

    # --- Load inputs --------------------------------------------------------
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 1
    if not reference_path.exists():
        print(f"ERROR: reference file not found: {reference_path}", file=sys.stderr)
        return 1

    try:
        raw_data = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: cannot parse input JSON: {exc}", file=sys.stderr)
        return 1

    try:
        reference_data = json.loads(reference_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: cannot parse reference JSON: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"Input     : {input_path}")
        print(f"Reference : {reference_path}")
        print(f"Output    : {output_path}")
        print(f"Report    : {report_path}")
        if args.dry_run:
            print("Mode      : dry-run (no files written)")
        print()

    # --- Repair -------------------------------------------------------------
    repaired_data, report = repair(
        raw_data,
        reference_data,
        str(input_path),
        str(reference_path),
        quiet=args.quiet,
    )

    # Patch output path into report
    report["output"] = str(output_path)

    # --- Summary ------------------------------------------------------------
    s = report["summary"]
    if not args.quiet:
        print()
        print("=== Repair Summary ===")
        print(f"  Total characters   : {s['total_characters']}")
        print(f"  ko mojibake found  : {s['ko_mojibake_found']}")
        print(f"  ko missing found   : {s['ko_missing_found']}")
        print(f"  ko repaired        : {s['ko_repaired']}")
        print(f"  ko not repaired    : {s['ko_not_repaired']}")
        print(f"  ja mojibake found  : {s['ja_mojibake_found']}")
        print(f"  ja missing found   : {s['ja_missing_found']}")
        print(f"  ja repaired        : {s['ja_repaired']}")
        print(f"  ja not repaired    : {s['ja_not_repaired']}")
        print(f"  alias mojibake     : {s['alias_mojibake_found']} (skipped)")
        print()

    # --- Write outputs (unless dry-run) -------------------------------------
    if not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(repaired_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not args.quiet:
            print(f"Written: {output_path}")
            print(f"Written: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
