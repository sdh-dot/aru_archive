"""diagnose_mojibake.py — Read-only mojibake diagnosis tool.

Inspects ``tag_aliases`` and ``tag_localizations`` tables in an Aru Archive
SQLite database and reports rows that appear to contain charset-corrupted
(mojibake) text.

**This tool never writes to the database.**  It opens the file in SQLite
read-only URI mode and additionally issues ``PRAGMA query_only = ON``.

Usage
-----
python tools/diagnose_mojibake.py --db path/to/aru_archive.db
python tools/diagnose_mojibake.py --db path/to/aru_archive.db --json report.json
python tools/diagnose_mojibake.py --db path/to/aru_archive.db --json report.json --limit-samples 50

Exit codes
----------
0  Completed normally (suspected count may be > 0).
1  Input / argument error (missing file, bad args).
2  DB access failure.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Mojibake heuristics
# ---------------------------------------------------------------------------

# Latin-1 / CP932 mojibake indicator characters that appear when
# UTF-8 multi-byte sequences are misread as ISO-8859-1 or CP1252.
_LATIN1_MOJIBAKE_CHARS = frozenset("ÃÂãâ¢¥ÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáäåæçèéêëìíîïðñòóôõöøùúûüýþÿ")

# U+FFFD REPLACEMENT CHARACTER
_REPLACEMENT_CHAR = "�"

# U+25A1 WHITE SQUARE (also used in some mojibake contexts)
_WHITE_SQUARE = "□"


def is_suspected_mojibake(
    text: Optional[str],
    locale: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Determine whether *text* looks like a charset-corrupted string.

    Parameters
    ----------
    text:
        The string to check.
    locale:
        Optional locale hint (``"ko"``, ``"ja"``, ``"en"``, etc.).
        Used for locale-mismatch heuristics.

    Returns
    -------
    (suspected, reasons)
        *suspected* is True when at least one heuristic fired.
        *reasons* is a list of short reason keys (see below).

    Reason keys
    -----------
    ``replacement-char``      U+FFFD or U+25A1 found.
    ``latin1-mojibake``       Latin-1 / CP932 indicator characters found.
    ``?-runs``                Three or more consecutive ``?`` characters.
    ``underscore-placeholder``Three or more consecutive ``_`` with < 30 % alphanumeric.
    ``locale-mismatch``       Expected locale script is under-represented.
    ``punctuation-heavy``     ASCII punctuation accounts for > 50 % of characters.
    """
    if not isinstance(text, str) or not text:
        return False, []

    reasons: list[str] = []

    # 1. Replacement character
    if _REPLACEMENT_CHAR in text or _WHITE_SQUARE in text:
        reasons.append("replacement-char")

    # 2. Latin-1 / CP932 mojibake characters
    latin1_count = sum(1 for ch in text if ch in _LATIN1_MOJIBAKE_CHARS)
    if latin1_count >= 2:
        reasons.append("latin1-mojibake")

    # 3. Three or more consecutive '?'
    if "???" in text:
        reasons.append("?-runs")

    # 4. Underscore placeholder: 3+ consecutive '_' AND < 30 % alphanumeric
    if "___" in text:
        alnum_ratio = sum(1 for ch in text if ch.isalnum()) / max(len(text), 1)
        if alnum_ratio < 0.30:
            reasons.append("underscore-placeholder")

    # 5. Locale mismatch
    if locale in ("ko", "ja"):
        total = max(len(text), 1)
        if locale == "ko":
            ko_count = sum(1 for ch in text if "가" <= ch <= "힣")
            if (ko_count / total) < 0.30:
                reasons.append("locale-mismatch")
        elif locale == "ja":
            ja_count = sum(
                1 for ch in text
                if ("぀" <= ch <= "ゟ")   # hiragana
                or ("゠" <= ch <= "ヿ")   # katakana
                or ("一" <= ch <= "鿿")   # CJK unified (kanji)
            )
            if (ja_count / total) < 0.30:
                reasons.append("locale-mismatch")

    # 6. Punctuation-heavy: ASCII punctuation > 50 %
    ascii_punct_count = sum(
        1 for ch in text
        if 0x21 <= ord(ch) <= 0x7e and not ch.isalnum()
    )
    if (ascii_punct_count / max(len(text), 1)) > 0.50:
        reasons.append("punctuation-heavy")

    return bool(reasons), reasons


# ---------------------------------------------------------------------------
# Database helpers (read-only)
# ---------------------------------------------------------------------------

def _open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open *db_path* in SQLite read-only URI mode.

    Raises
    ------
    FileNotFoundError
        When the file does not exist at *db_path*.
    sqlite3.OperationalError
        When SQLite cannot open the file (propagated to caller).
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    # Belt-and-suspenders: also set query_only PRAGMA.
    # This may fail on older SQLite versions — that is acceptable because
    # the URI read-only mode already prevents writes at the OS level.
    try:
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.OperationalError:
        pass  # pragma not supported — URI mode still protects us

    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Per-table inspectors
# ---------------------------------------------------------------------------

def _inspect_tag_aliases(
    conn: sqlite3.Connection,
    limit_samples: int,
    samples: list[dict],
) -> dict:
    """Inspect ``tag_aliases`` and return summary dict."""
    if not _table_exists(conn, "tag_aliases"):
        print("WARNING: table 'tag_aliases' not found — skipping.", file=sys.stderr)
        return {"inspected": 0, "suspected": 0, "skipped": True}

    # Text columns to check
    TEXT_COLS = ("alias", "canonical", "parent_series")

    rows = conn.execute(
        "SELECT rowid, alias, canonical, tag_type, parent_series, source"
        " FROM tag_aliases"
    ).fetchall()

    by_source: dict[str, dict[str, int]] = {}
    suspected_count = 0

    for row in rows:
        rowid = row["rowid"]
        source = row["source"] or "unknown"
        if source not in by_source:
            by_source[source] = {"inspected": 0, "suspected": 0}
        by_source[source]["inspected"] += 1

        row_suspected = False
        for col in TEXT_COLS:
            val = row[col]
            if not val:
                continue
            # For alias/canonical, no locale hint; parent_series also no locale
            suspected, reasons = is_suspected_mojibake(val)
            if suspected:
                row_suspected = True
                if len(samples) < limit_samples:
                    samples.append({
                        "table": "tag_aliases",
                        "row_id": rowid,
                        "column": col,
                        "value": val,
                        "tag_type": row["tag_type"],
                        "source": source,
                        "reasons": reasons,
                    })

        if row_suspected:
            suspected_count += 1
            by_source[source]["suspected"] += 1

    return {
        "inspected": len(rows),
        "suspected": suspected_count,
        "by_source": by_source,
    }


def _inspect_tag_localizations(
    conn: sqlite3.Connection,
    limit_samples: int,
    samples: list[dict],
) -> dict:
    """Inspect ``tag_localizations`` and return summary dict."""
    if not _table_exists(conn, "tag_localizations"):
        print("WARNING: table 'tag_localizations' not found — skipping.", file=sys.stderr)
        return {"inspected": 0, "suspected": 0, "skipped": True}

    rows = conn.execute(
        "SELECT rowid, canonical, tag_type, parent_series, locale, display_name, source"
        " FROM tag_localizations"
    ).fetchall()

    by_locale: dict[str, dict[str, int]] = {}
    suspected_count = 0

    for row in rows:
        rowid = row["rowid"]
        locale = row["locale"] or "unknown"
        if locale not in by_locale:
            by_locale[locale] = {"inspected": 0, "suspected": 0}
        by_locale[locale]["inspected"] += 1

        row_suspected = False

        # Check display_name with locale hint
        display_name = row["display_name"]
        if display_name:
            suspected, reasons = is_suspected_mojibake(display_name, locale=locale)
            if suspected:
                row_suspected = True
                if len(samples) < limit_samples:
                    samples.append({
                        "table": "tag_localizations",
                        "row_id": rowid,
                        "column": "display_name",
                        "value": display_name,
                        "locale": locale,
                        "canonical": row["canonical"],
                        "source": row["source"] or "unknown",
                        "reasons": reasons,
                    })

        # Also check canonical (no locale hint)
        canonical = row["canonical"]
        if canonical and not row_suspected:
            suspected, reasons = is_suspected_mojibake(canonical)
            if suspected:
                row_suspected = True
                if len(samples) < limit_samples:
                    samples.append({
                        "table": "tag_localizations",
                        "row_id": rowid,
                        "column": "canonical",
                        "value": canonical,
                        "locale": locale,
                        "source": row["source"] or "unknown",
                        "reasons": reasons,
                    })

        if row_suspected:
            suspected_count += 1
            by_locale[locale]["suspected"] += 1

    return {
        "inspected": len(rows),
        "suspected": suspected_count,
        "by_locale": by_locale,
    }


# ---------------------------------------------------------------------------
# Main diagnose function
# ---------------------------------------------------------------------------

def diagnose(
    db_path: Path,
    *,
    limit_samples: int = 20,
) -> dict:
    """Run full mojibake diagnosis on *db_path* (read-only).

    Returns a dict with the structure documented in the module docstring.
    Raises ``FileNotFoundError`` or ``sqlite3.OperationalError`` on open
    failure.
    """
    conn = _open_readonly(db_path)
    samples: list[dict] = []

    try:
        aliases_result = _inspect_tag_aliases(conn, limit_samples, samples)
        localizations_result = _inspect_tag_localizations(conn, limit_samples, samples)
    finally:
        conn.close()

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result: dict = {
        "db_path": str(db_path),
        "inspected_at": now_iso,
        "summary": {
            "tag_aliases": {
                "inspected": aliases_result.get("inspected", 0),
                "suspected": aliases_result.get("suspected", 0),
            },
            "tag_localizations": {
                "inspected": localizations_result.get("inspected", 0),
                "suspected": localizations_result.get("suspected", 0),
            },
        },
        "by_source": {
            "tag_aliases": aliases_result.get("by_source", {}),
        },
        "by_locale": {
            "tag_localizations": localizations_result.get("by_locale", {}),
        },
        "samples": samples[:limit_samples],
    }

    return result


# ---------------------------------------------------------------------------
# Human-readable stdout formatter
# ---------------------------------------------------------------------------

def _format_report(result: dict) -> str:
    lines: list[str] = []
    app = lines.append

    app("=== Mojibake Diagnosis Report ===")
    app(f"DB: {result['db_path']}")
    app(f"Inspected at: {result['inspected_at']}")
    app("")
    app("[Summary]")

    for tbl in ("tag_aliases", "tag_localizations"):
        info = result["summary"].get(tbl, {})
        n = info.get("inspected", 0)
        m = info.get("suspected", 0)
        pct = f" ({m / n * 100:.1f}%)" if n > 0 and m > 0 else ""
        app(f"- {tbl} inspected: {n} rows")
        app(f"- {tbl} suspected: {m} rows{pct}")

    app("")
    app("[By tag_aliases.source]")
    by_source = result.get("by_source", {}).get("tag_aliases", {})
    if by_source:
        for src, counts in sorted(by_source.items()):
            n = counts["inspected"]
            m = counts["suspected"]
            pct = f" ({m / n * 100:.1f}%)" if n > 0 and m > 0 else ""
            app(f"- {src}: {m} / {n} suspected{pct}")
    else:
        app("- (no data)")

    app("")
    app("[By tag_localizations.locale]")
    by_locale = result.get("by_locale", {}).get("tag_localizations", {})
    if by_locale:
        for loc, counts in sorted(by_locale.items()):
            n = counts["inspected"]
            m = counts["suspected"]
            pct = f" ({m / n * 100:.1f}%)" if n > 0 and m > 0 else ""
            app(f"- {loc}: {m} / {n} suspected{pct}")
    else:
        app("- (no data)")

    app("")
    samples = result.get("samples", [])
    app(f"[Suspected samples (top {len(samples)})]")
    if samples:
        for i, s in enumerate(samples, 1):
            tbl = s.get("table", "?")
            rid = s.get("row_id", "?")
            col = s.get("column", "?")
            val = s.get("value", "")
            reasons = s.get("reasons", [])
            locale = s.get("locale", "")
            source = s.get("source", "")
            extra = []
            if locale:
                extra.append(f"locale={locale}")
            if source:
                extra.append(f"source={source}")
            extra_str = " " + " ".join(extra) if extra else ""
            app(
                f"{i:3d}. table={tbl} id={rid} col={col!r}"
                f"{extra_str} value={val!r} reasons={reasons}"
            )
    else:
        app("(none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only mojibake diagnosis tool for Aru Archive SQLite databases.\n"
            "Inspects tag_aliases and tag_localizations for charset corruption.\n"
            "Never writes to the database."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        required=True,
        metavar="PATH",
        help="Path to the Aru Archive SQLite database (required).",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        default=None,
        help="Write the full JSON report to this path (optional).",
    )
    parser.add_argument(
        "--limit-samples",
        metavar="N",
        type=int,
        default=20,
        help="Maximum number of suspect samples to include in output (default: 20).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = Path(args.db)
    json_path = Path(args.json) if args.json else None
    limit_samples = max(1, args.limit_samples)

    # --- Run diagnosis ------------------------------------------------------
    try:
        result = diagnose(db_path, limit_samples=limit_samples)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as exc:
        print(f"ERROR: Cannot open database: {exc}", file=sys.stderr)
        return 2

    # --- Stdout report ------------------------------------------------------
    print(_format_report(result))

    # --- Optional JSON output -----------------------------------------------
    if json_path is not None:
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nJSON report written to: {json_path}")
        except OSError as exc:
            print(f"ERROR: Cannot write JSON report: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
