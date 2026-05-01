"""repair_mojibake_db.py — Safe mojibake DB repair tool.

Identifies charset-corrupted rows in ``tag_aliases`` and ``tag_localizations``
and either reports a repair plan (dry-run, the default) or applies it
(``--apply``, requires ``--backup``).

**The default mode is dry-run.** Pass ``--apply`` explicitly to write to the DB.

Protection policy (rows in these sources are NEVER modified):
  - source = 'user_confirmed'
  - source LIKE 'built_in_pack:%'
  - source = 'external:safebooru'
  - source IS NULL or empty string

Only rows with ``source = 'imported_localized_pack'`` are repair candidates.

Action classification:
  A. update_localization  — a clean replacement value exists in the same table
                            for the same (canonical, locale) combination
  B. delete_alias         — complete information loss (???, _____ patterns) in
                            tag_aliases with source='imported_localized_pack'
  C. manual_review        — suspected but no safe automatic fix available
  D. protected_skip       — protected source; counted but not touched

Exit codes
----------
0  Normal completion (dry-run or apply success).
1  Argument error / safety guard violation (missing --backup, backup collision,
   DB not found).
2  DB access failure / transaction failure (rollback performed).

Usage
-----
python tools/repair_mojibake_db.py --db PATH
python tools/repair_mojibake_db.py --db PATH --json plan.json --limit 20
python tools/repair_mojibake_db.py --db PATH --apply --backup PATH.bak.db
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Heuristic logic is centralised in core/mojibake_heuristics.py (PR-6).
# Importing directly from core avoids a tools→tools dependency.
from core.mojibake_heuristics import is_suspected_mojibake


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The only source that repair touches.
_REPAIR_SOURCE = "imported_localized_pack"

# Sources whose rows must never be modified (checked in precedence order).
_PROTECTED_SOURCE_EXACT = frozenset({
    "user_confirmed",
    "external:safebooru",
})

# Prefix match for built_in_pack:* family.
_BUILT_IN_PACK_PREFIX = "built_in_pack:"

# Patterns that indicate complete information loss.
_COMPLETE_LOSS_PATTERNS = ("???", "___")

# Source priority for replacement candidate selection (lower = better).
_SOURCE_PRIORITY: dict[str, int] = {
    "user_confirmed": 0,
    "external:safebooru": 2,
    "imported_localized_pack": 3,
}


# ---------------------------------------------------------------------------
# Protection helpers
# ---------------------------------------------------------------------------

def _is_protected_source(source: Optional[str]) -> bool:
    """Return True when *source* is in the protected set."""
    if not source:
        return True  # NULL / empty → unknown, protect by default
    if source in _PROTECTED_SOURCE_EXACT:
        return True
    if source.startswith(_BUILT_IN_PACK_PREFIX):
        return True
    return False


def _is_complete_loss(value: Optional[str]) -> bool:
    """Return True when *value* is a pure placeholder with no recoverable info."""
    if not value:
        return False
    return any(pattern in value for pattern in _COMPLETE_LOSS_PATTERNS)


def _source_priority(source: Optional[str]) -> int:
    if not source:
        return 99
    if source.startswith(_BUILT_IN_PACK_PREFIX):
        return 1
    return _SOURCE_PRIORITY.get(source, 5)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _open_rw(db_path: Path) -> sqlite3.Connection:
    """Open *db_path* for read-write (used only during --apply)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open *db_path* in SQLite read-only URI mode."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.OperationalError:
        pass
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Replacement candidate lookup
# ---------------------------------------------------------------------------

def _find_clean_localization(
    conn: sqlite3.Connection,
    canonical: str,
    locale: str,
    exclude_rowid: int,
) -> Optional[tuple[str, str]]:
    """Find the best clean display_name for the given canonical + locale.

    Searches all rows matching (canonical, locale) regardless of tag_type or
    parent_series.  The UNIQUE constraint on tag_localizations is
    (canonical, tag_type, parent_series, locale), so searching across tag_type
    variants allows finding a clean reference even when the corrupted row is
    the only row for a particular tag_type.

    Locale is matched exactly — never falls back to 'en' for 'ko'/'ja'.

    Returns (display_name, source) of the best candidate, or None.
    Skips the row identified by *exclude_rowid* (the broken row itself).
    """
    rows = conn.execute(
        "SELECT rowid, display_name, source FROM tag_localizations"
        " WHERE canonical=? AND locale=?"
        "   AND enabled=1 AND rowid != ?",
        (canonical, locale, exclude_rowid),
    ).fetchall()

    best: Optional[tuple[str, str, int]] = None  # (display_name, source, priority)
    for row in rows:
        display_name = row["display_name"]
        source = row["source"]
        suspected, _ = is_suspected_mojibake(display_name, locale=locale)
        if suspected:
            continue  # candidate itself is corrupted
        pri = _source_priority(source)
        if best is None or pri < best[2]:
            best = (display_name, source, pri)

    if best is None:
        return None
    return best[0], best[1]


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------

def _make_record(
    action: str,
    table: str,
    rowid: int,
    field: Optional[str],
    old_value: Optional[str],
    new_value: Optional[str],
    reasons: list[str],
    source: Optional[str],
    locale: Optional[str],
    **extras: object,
) -> dict:
    """Build a canonical action record dict."""
    rec: dict = {
        "action": action,
        "table": table,
        "id": rowid,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "reasons": reasons,
        "source": source,
        "locale": locale,
    }
    rec.update(extras)
    return rec


def _classify_alias_row(row: sqlite3.Row) -> Optional[dict]:
    """Return an action record for one tag_aliases row, or None if clean."""
    source = row["source"]
    rowid = row["rowid"]

    if _is_protected_source(source):
        return _make_record(
            "protected_skip", "tag_aliases", rowid,
            None, None, None, ["protected_source"], source, None,
        )

    alias = row["alias"]
    canonical = row["canonical"]
    parent_series = row["parent_series"]

    for col, val in (("alias", alias), ("canonical", canonical), ("parent_series", parent_series)):
        if not val:
            continue
        suspected, reasons = is_suspected_mojibake(val)
        if not suspected:
            continue

        action = (
            "delete_alias"
            if _is_complete_loss(alias) or _is_complete_loss(canonical)
            else "manual_review"
        )
        return _make_record(
            action, "tag_aliases", rowid,
            col, val, None, reasons, source, None,
        )

    return None  # clean row


def _plan_tag_aliases(conn: sqlite3.Connection) -> list[dict]:
    """Build action records for tag_aliases."""
    if not _table_exists(conn, "tag_aliases"):
        return []

    rows = conn.execute(
        "SELECT rowid, alias, canonical, tag_type, parent_series, source, enabled"
        " FROM tag_aliases"
    ).fetchall()

    records: list[dict] = []
    for row in rows:
        rec = _classify_alias_row(row)
        if rec is not None:
            records.append(rec)
    return records


def _classify_localization_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> Optional[dict]:
    """Return an action record for one tag_localizations row, or None if clean."""
    source = row["source"]
    rowid = row["rowid"]
    locale = row["locale"] or "unknown"

    if _is_protected_source(source):
        return _make_record(
            "protected_skip", "tag_localizations", rowid,
            None, None, None, ["protected_source"], source, locale,
        )

    display_name = row["display_name"]
    canonical = row["canonical"]

    # Check display_name with locale hint
    if display_name:
        suspected, reasons = is_suspected_mojibake(display_name, locale=locale)
        if suspected:
            replacement = _find_clean_localization(conn, canonical, locale, rowid)
            if replacement is not None:
                new_display, new_source = replacement
                return _make_record(
                    "update_localization", "tag_localizations", rowid,
                    "display_name", display_name, new_display, reasons, source, locale,
                    _replacement_source=new_source,
                )
            return _make_record(
                "manual_review", "tag_localizations", rowid,
                "display_name", display_name, None, reasons, source, locale,
            )

    # Check canonical itself (no locale hint)
    if canonical:
        suspected, reasons = is_suspected_mojibake(canonical)
        if suspected:
            return _make_record(
                "manual_review", "tag_localizations", rowid,
                "canonical", canonical, None, reasons, source, locale,
            )

    return None  # clean row


def _plan_tag_localizations(conn: sqlite3.Connection) -> list[dict]:
    """Build action records for tag_localizations."""
    if not _table_exists(conn, "tag_localizations"):
        return []

    rows = conn.execute(
        "SELECT rowid, localization_id, canonical, tag_type, parent_series,"
        "       locale, display_name, source, enabled"
        " FROM tag_localizations"
    ).fetchall()

    records: list[dict] = []
    for row in rows:
        rec = _classify_localization_row(conn, row)
        if rec is not None:
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Full plan
# ---------------------------------------------------------------------------

def _tally_records(all_records: list[dict]) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Count actions by type and by table."""
    action_counts: dict[str, int] = {
        "update_localization": 0,
        "delete_alias": 0,
        "manual_review": 0,
        "protected_skip": 0,
    }
    table_counts: dict[str, dict[str, int]] = {
        "tag_aliases": {"updates": 0, "deletes": 0, "review": 0, "protected": 0},
        "tag_localizations": {"updates": 0, "deletes": 0, "review": 0, "protected": 0},
    }
    _action_to_table_key = {
        "update_localization": "updates",
        "delete_alias": "deletes",
        "manual_review": "review",
        "protected_skip": "protected",
    }
    for rec in all_records:
        action = rec["action"]
        table = rec["table"]
        action_counts[action] = action_counts.get(action, 0) + 1
        if table in table_counts:
            tkey = _action_to_table_key.get(action)
            if tkey:
                table_counts[table][tkey] += 1
    return action_counts, table_counts


def build_plan(db_path: Path) -> dict:
    """Build the full repair plan (read-only DB access).

    Returns a dict with keys:
      - db_path, planned_at
      - actions: list of action records
      - summary: counts by action and table
    """
    conn = _open_readonly(db_path)
    try:
        alias_records = _plan_tag_aliases(conn)
        local_records = _plan_tag_localizations(conn)
    finally:
        conn.close()

    all_records = alias_records + local_records
    action_counts, table_counts = _tally_records(all_records)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "db_path": str(db_path),
        "planned_at": now_iso,
        "summary": {
            "planned_updates": action_counts["update_localization"],
            "planned_deletes": action_counts["delete_alias"],
            "manual_review": action_counts["manual_review"],
            "protected_skipped": action_counts["protected_skip"],
            "by_table": table_counts,
            "by_action": action_counts,
        },
        "actions": all_records,
    }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _apply_update(conn: sqlite3.Connection, rec: dict) -> Optional[str]:
    """Apply one update_localization record. Returns an error string or None."""
    new_value = rec.get("new_value")
    rowid = rec["id"]
    if new_value is None:
        return f"update_localization id={rowid}: new_value is None, skipping"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE tag_localizations SET display_name=?, updated_at=? WHERE rowid=?",
        (new_value, now, rowid),
    )
    return None


def _apply_delete(conn: sqlite3.Connection, rec: dict) -> Optional[str]:
    """Apply one delete_alias record. Returns an error string or None."""
    rowid = rec["id"]
    check = conn.execute(
        "SELECT source FROM tag_aliases WHERE rowid=?", (rowid,)
    ).fetchone()
    if check is None:
        return f"delete_alias id={rowid}: row not found, skipping"
    if _is_protected_source(check[0]):
        return f"delete_alias id={rowid}: source={check[0]!r} is now protected, skipping"
    conn.execute("DELETE FROM tag_aliases WHERE rowid=?", (rowid,))
    return None


def _apply_one_record(
    conn: sqlite3.Connection,
    rec: dict,
    applied_updates: list[int],
    applied_deletes: list[int],
    errors: list[str],
) -> None:
    """Dispatch one action record to the appropriate apply helper."""
    action = rec["action"]
    table = rec["table"]

    if action == "update_localization" and table == "tag_localizations":
        err = _apply_update(conn, rec)
        if err:
            errors.append(err)
        else:
            applied_updates[0] += 1

    elif action == "delete_alias" and table == "tag_aliases":
        err = _apply_delete(conn, rec)
        if err:
            errors.append(err)
        else:
            applied_deletes[0] += 1

    # manual_review / protected_skip: no-op


def apply_plan(db_path: Path, plan: dict) -> dict:
    """Apply the repair plan to *db_path* within a single transaction.

    Returns {"applied_updates": N, "applied_deletes": N, "errors": [...]}.
    Raises ``sqlite3.OperationalError`` (after ROLLBACK) on transaction failure.
    """
    actions = plan["actions"]
    conn = _open_rw(db_path)
    # Use single-element lists so _apply_one_record can mutate them.
    applied_updates = [0]
    applied_deletes = [0]
    errors: list[str] = []

    try:
        conn.execute("BEGIN")
        for rec in actions:
            _apply_one_record(conn, rec, applied_updates, applied_deletes, errors)
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        raise sqlite3.OperationalError(f"Transaction failed (rolled back): {exc}") from exc

    conn.close()
    return {
        "applied_updates": applied_updates[0],
        "applied_deletes": applied_deletes[0],
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _create_backup(db_path: Path, backup_path: Path) -> None:
    """Create a verified backup of *db_path* at *backup_path*.

    Raises ``FileExistsError`` if *backup_path* already exists.
    Raises ``OSError`` if backup fails or verification fails.
    """
    if backup_path.exists():
        raise FileExistsError(
            f"Backup path already exists: {backup_path}\n"
            "Remove or rename the existing file first."
        )

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(db_path), str(backup_path))

    # Verify: table count comparison
    try:
        src_conn = sqlite3.connect(str(db_path))
        bak_conn = sqlite3.connect(str(backup_path))
        src_count = src_conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        bak_count = bak_conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        src_conn.close()
        bak_conn.close()
    except sqlite3.OperationalError as exc:
        backup_path.unlink(missing_ok=True)
        raise OSError(f"Backup verification failed (SQLite error): {exc}") from exc

    if src_count != bak_count:
        backup_path.unlink(missing_ok=True)
        raise OSError(
            f"Backup verification failed: source has {src_count} tables "
            f"but backup has {bak_count}"
        )

    # File size sanity check
    src_size = db_path.stat().st_size
    bak_size = backup_path.stat().st_size
    if bak_size < src_size * 0.9:
        backup_path.unlink(missing_ok=True)
        raise OSError(
            f"Backup file size ({bak_size}) is less than 90 % "
            f"of source ({src_size}) — backup may be incomplete."
        )


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def _format_plan(plan: dict, limit: Optional[int] = None) -> str:
    lines: list[str] = []
    app = lines.append

    app("=== Mojibake Repair Plan ===")
    app(f"DB: {plan['db_path']}")
    app(f"Planned at: {plan['planned_at']}")
    app("Mode: DRY-RUN (use --apply to execute)")
    app("")

    s = plan["summary"]
    app("[Summary]")
    app(f"- planned_updates:   {s['planned_updates']}")
    app(f"- planned_deletes:   {s['planned_deletes']}")
    app(f"- manual_review:     {s['manual_review']}")
    app(f"- protected_skipped: {s['protected_skipped']}")
    app("")

    app("[By table]")
    for tbl, counts in s["by_table"].items():
        app(
            f"- {tbl}: updates={counts['updates']} deletes={counts['deletes']}"
            f" review={counts['review']} protected={counts['protected']}"
        )
    app("")

    app("[By action]")
    for action, count in s["by_action"].items():
        app(f"- {action}: {count}")
    app("")

    non_protected = [r for r in plan["actions"] if r["action"] != "protected_skip"]
    display = non_protected[:(limit if limit is not None else 20)]

    app(f"[Sample (top {len(display)} non-protected actions)]")
    if display:
        for i, rec in enumerate(display, 1):
            locale_str = f" locale={rec['locale']!r}" if rec.get("locale") else ""
            new_str = (
                f" new={rec['new_value']!r}"
                if rec.get("new_value") is not None else ""
            )
            app(
                f"{i:3d}. action={rec['action']} table={rec['table']} id={rec['id']}"
                f" field={rec['field']!r}{locale_str}"
                f" old={rec['old_value']!r}{new_str}"
                f" source={rec['source']!r} reasons={rec['reasons']}"
            )
    else:
        app("(no non-protected actions found)")

    return "\n".join(lines)


def _format_apply_result(plan: dict, result: dict) -> str:
    lines: list[str] = []
    app = lines.append
    app("=== Mojibake Repair Applied ===")
    app(f"DB: {plan['db_path']}")
    app(f"- applied_updates: {result['applied_updates']}")
    app(f"- applied_deletes: {result['applied_deletes']}")
    if result["errors"]:
        app(f"- warnings ({len(result['errors'])}):")
        for err in result["errors"]:
            app(f"  ! {err}")
    else:
        app("- no warnings")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Safe mojibake DB repair tool for Aru Archive SQLite databases.\n"
            "Default mode is DRY-RUN. Pass --apply (with --backup) to write.\n\n"
            "Protected sources (never modified): user_confirmed, built_in_pack:*, "
            "external:safebooru, NULL/empty."
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
        "--report",
        metavar="PATH",
        default=None,
        help="PR-4 diagnose JSON report path (optional, for reference).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Plan-only mode (this is the default; flag is accepted but redundant).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply the repair plan to the DB (requires --backup).",
    )
    parser.add_argument(
        "--backup",
        metavar="PATH",
        default=None,
        help="Backup path for the DB before applying (required with --apply).",
    )
    parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        default=None,
        help="Limit the number of sample rows printed to stdout.",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        default=None,
        help="Write the full repair plan JSON to this path.",
    )
    return parser.parse_args(argv)


def _write_json_plan(plan: dict, json_path: Path) -> bool:
    """Write public (no _* keys) plan JSON. Returns False on error."""
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        public_actions = [
            {k: v for k, v in rec.items() if not k.startswith("_")}
            for rec in plan["actions"]
        ]
        public_plan = {k: v for k, v in plan.items() if k != "actions"}
        public_plan["actions"] = public_actions
        json_path.write_text(
            json.dumps(public_plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nRepair plan JSON written to: {json_path}")
        return True
    except OSError as exc:
        print(f"ERROR: Cannot write JSON plan: {exc}", file=sys.stderr)
        return False


def _run_apply(db_path: Path, backup_path: Path, plan: dict) -> int:
    """Create backup, apply plan, verify. Returns exit code."""
    print(f"\nCreating backup: {backup_path}")
    try:
        _create_backup(db_path, backup_path)
        print(f"Backup created: {backup_path} ({backup_path.stat().st_size:,} bytes)")
    except OSError as exc:
        print(f"ERROR: Backup failed: {exc}", file=sys.stderr)
        return 1

    print("\nApplying repair plan...")
    try:
        result = apply_plan(db_path, plan)
    except sqlite3.OperationalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(_format_apply_result(plan, result))

    try:
        post_plan = build_plan(db_path)
        post_u = post_plan["summary"]["planned_updates"]
        post_d = post_plan["summary"]["planned_deletes"]
        post_r = post_plan["summary"]["manual_review"]
        print(
            f"\n[Post-apply check] remaining: "
            f"updates={post_u} deletes={post_d} review={post_r}"
        )
        if result["applied_updates"] != plan["summary"]["planned_updates"]:
            print(
                f"WARNING: applied_updates={result['applied_updates']}"
                f" != planned={plan['summary']['planned_updates']}",
                file=sys.stderr,
            )
        if result["applied_deletes"] != plan["summary"]["planned_deletes"]:
            print(
                f"WARNING: applied_deletes={result['applied_deletes']}"
                f" != planned={plan['summary']['planned_deletes']}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"WARNING: Post-apply verification failed: {exc}", file=sys.stderr)

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    db_path = Path(args.db)
    backup_path = Path(args.backup) if args.backup else None
    json_path = Path(args.json) if args.json else None

    # Safety guard: --apply requires --backup
    if args.apply and backup_path is None:
        print(
            "ERROR: --apply requires --backup PATH.\n"
            "       Specify a backup destination before applying changes.",
            file=sys.stderr,
        )
        return 1

    # DB existence check
    if not db_path.exists():
        print(f"ERROR: Database file not found: {db_path}", file=sys.stderr)
        return 1

    # Safety guard: backup must not already exist
    if args.apply and backup_path is not None and backup_path.exists():
        print(
            f"ERROR: Backup path already exists: {backup_path}\n"
            "       Remove or rename the existing backup file first.",
            file=sys.stderr,
        )
        return 1

    # Build plan (read-only)
    try:
        plan = build_plan(db_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except sqlite3.OperationalError as exc:
        print(f"ERROR: Cannot open database: {exc}", file=sys.stderr)
        return 2

    print(_format_plan(plan, limit=args.limit))

    if json_path is not None and not _write_json_plan(plan, json_path):
        return 1

    if not args.apply:
        return 0

    return _run_apply(db_path, backup_path, plan)


if __name__ == "__main__":
    sys.exit(main())
