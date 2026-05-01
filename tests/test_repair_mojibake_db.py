"""tests/test_repair_mojibake_db.py — Unit tests for tools/repair_mojibake_db.py.

Tests are grouped into:
  1. Default dry-run + safety guards
  2. Protection policy (user_confirmed, built_in_pack:*, external:safebooru, NULL)
  3. Action classification (delete_alias, update_localization, manual_review)
  4. Apply + transaction
  5. JSON output structure
  6. No auto user_confirmed creation
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

import pytest

from tools.repair_mojibake_db import (
    _is_protected_source,
    apply_plan,
    build_plan,
    main,
)


# ---------------------------------------------------------------------------
# Shared DDL (matches schema.sql)
# ---------------------------------------------------------------------------

_TAG_ALIASES_DDL = """
CREATE TABLE IF NOT EXISTS tag_aliases (
    alias            TEXT NOT NULL,
    canonical        TEXT NOT NULL,
    tag_type         TEXT NOT NULL DEFAULT 'general',
    parent_series    TEXT NOT NULL DEFAULT '',
    media_type       TEXT,
    source           TEXT,
    confidence_score REAL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_by       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT,
    PRIMARY KEY (alias, tag_type, parent_series)
);
"""

_TAG_LOCALIZATIONS_DDL = """
CREATE TABLE IF NOT EXISTS tag_localizations (
    localization_id TEXT PRIMARY KEY,
    canonical       TEXT NOT NULL,
    tag_type        TEXT NOT NULL,
    parent_series   TEXT NOT NULL DEFAULT '',
    locale          TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    sort_name       TEXT,
    source          TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    UNIQUE(canonical, tag_type, parent_series, locale)
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mem_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_TAG_ALIASES_DDL)
    conn.execute(_TAG_LOCALIZATIONS_DDL)
    conn.commit()
    return conn


def _insert_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    tag_type: str = "character",
    parent_series: str = "Blue Archive",
    source: str = "imported_localized_pack",
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tag_aliases"
        " (alias, canonical, tag_type, parent_series, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, '2026-01-01T00:00:00Z')",
        (alias, canonical, tag_type, parent_series, source),
    )
    conn.commit()


def _insert_localization(
    conn: sqlite3.Connection,
    canonical: str,
    locale: str,
    display_name: str,
    tag_type: str = "character",
    parent_series: str = "Blue Archive",
    source: str = "imported_localized_pack",
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tag_localizations"
        " (localization_id, canonical, tag_type, parent_series, locale,"
        "  display_name, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00Z')",
        (str(uuid.uuid4()), canonical, tag_type, parent_series, locale,
         display_name, source),
    )
    conn.commit()


def _db_to_file(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Persist an in-memory SQLite DB to a temp file."""
    db_file = tmp_path / "test.db"
    dest = sqlite3.connect(str(db_file))
    conn.backup(dest)
    dest.close()
    return db_file


def _row_count(db_file: Path, table: str) -> int:
    c = sqlite3.connect(str(db_file))
    n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    c.close()
    return n


def _get_display_name(db_file: Path, canonical: str, locale: str) -> Optional[str]:
    c = sqlite3.connect(str(db_file))
    row = c.execute(
        "SELECT display_name FROM tag_localizations WHERE canonical=? AND locale=?",
        (canonical, locale),
    ).fetchone()
    c.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 1. Default dry-run + safety guards
# ---------------------------------------------------------------------------

class TestDefaultDryRun:
    def test_default_is_dry_run(self, tmp_path):
        """No --apply → DB row count must not change."""
        conn = _make_mem_db()
        _insert_alias(conn, "??????", "??Canon??", source="imported_localized_pack")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        before = _row_count(db_file, "tag_aliases")
        code = main(["--db", str(db_file)])
        after = _row_count(db_file, "tag_aliases")

        assert code == 0
        assert before == after

    def test_dry_run_flag_does_not_modify_db(self, tmp_path):
        """--dry-run explicit flag also leaves DB unchanged."""
        conn = _make_mem_db()
        _insert_alias(conn, "?????", "Some Canon", source="imported_localized_pack")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        before = _row_count(db_file, "tag_aliases")
        code = main(["--db", str(db_file), "--dry-run"])
        after = _row_count(db_file, "tag_aliases")

        assert code == 0
        assert before == after

    def test_apply_without_backup_exits_1(self, tmp_path):
        """--apply without --backup must exit 1."""
        conn = _make_mem_db()
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        code = main(["--db", str(db_file), "--apply"])
        assert code == 1

    def test_apply_with_existing_backup_path_exits_1(self, tmp_path):
        """If the backup file already exists, exit 1 (no overwrite)."""
        conn = _make_mem_db()
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        existing_backup = tmp_path / "existing.bak.db"
        existing_backup.write_bytes(b"dummy")

        code = main(["--db", str(db_file), "--apply", "--backup", str(existing_backup)])
        assert code == 1
        # Backup file must not be replaced
        assert existing_backup.read_bytes() == b"dummy"

    def test_apply_with_backup_creates_backup_first(self, tmp_path):
        """--apply --backup new.db creates the backup file before any DB write."""
        conn = _make_mem_db()
        # Insert a complete-loss alias so there is something to delete
        _insert_alias(conn, "???????", "Canon X", source="imported_localized_pack")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        backup_file = tmp_path / "aru.bak.db"
        assert not backup_file.exists()

        code = main(["--db", str(db_file), "--apply", "--backup", str(backup_file)])
        assert code == 0
        assert backup_file.exists()
        assert backup_file.stat().st_size > 0


# ---------------------------------------------------------------------------
# 2. Protection policy
# ---------------------------------------------------------------------------

class TestProtectionPolicy:
    def _assert_all_protected_skip(self, db_file: Path, source: str):
        plan = build_plan(db_file)
        non_skip = [r for r in plan["actions"] if r["action"] != "protected_skip"]
        assert non_skip == [], (
            f"Expected all rows with source={source!r} to be protected_skip, "
            f"but got: {non_skip}"
        )

    def test_user_confirmed_protected(self, tmp_path):
        conn = _make_mem_db()
        _insert_alias(conn, "?????", "Canon", source="user_confirmed")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()
        self._assert_all_protected_skip(db_file, "user_confirmed")

    def test_built_in_pack_protected(self, tmp_path):
        conn = _make_mem_db()
        _insert_alias(conn, "?????", "Canon", source="built_in_pack:blue_archive")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()
        self._assert_all_protected_skip(db_file, "built_in_pack:blue_archive")

    def test_external_safebooru_protected(self, tmp_path):
        conn = _make_mem_db()
        _insert_alias(conn, "?????", "Canon", source="external:safebooru")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()
        self._assert_all_protected_skip(db_file, "external:safebooru")

    def test_null_source_protected(self, tmp_path):
        conn = _make_mem_db()
        # Insert with NULL source
        conn.execute(
            "INSERT OR REPLACE INTO tag_aliases"
            " (alias, canonical, tag_type, parent_series, source, created_at)"
            " VALUES ('?????', 'Canon', 'character', 'Blue Archive', NULL, '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        db_file = _db_to_file(conn, tmp_path)
        conn.close()
        self._assert_all_protected_skip(db_file, "NULL")

    def test_empty_source_protected(self, tmp_path):
        conn = _make_mem_db()
        conn.execute(
            "INSERT OR REPLACE INTO tag_aliases"
            " (alias, canonical, tag_type, parent_series, source, created_at)"
            " VALUES ('?????', 'Canon', 'character', 'Blue Archive', '', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        db_file = _db_to_file(conn, tmp_path)
        conn.close()
        self._assert_all_protected_skip(db_file, "empty")

    def test_only_imported_localized_pack_modified(self, tmp_path):
        """After apply, rows with other sources must be untouched."""
        conn = _make_mem_db()
        # Protected rows (mojibake-looking alias but protected source)
        _insert_alias(conn, "?????_builtin", "Canon A", source="built_in_pack:blue_archive",
                      tag_type="character", parent_series="Test")
        _insert_alias(conn, "?????_safebooru", "Canon B", source="external:safebooru",
                      tag_type="character", parent_series="Test")
        # Repair candidate
        _insert_alias(conn, "???????", "Canon C", source="imported_localized_pack",
                      tag_type="character", parent_series="Test")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        backup = tmp_path / "backup.db"
        main(["--db", str(db_file), "--apply", "--backup", str(backup)])

        # Protected rows must still be present with their original source
        c = sqlite3.connect(str(db_file))
        row_a = c.execute(
            "SELECT source FROM tag_aliases WHERE alias='?????_builtin'"
        ).fetchone()
        row_b = c.execute(
            "SELECT source FROM tag_aliases WHERE alias='?????_safebooru'"
        ).fetchone()
        c.close()

        assert row_a is not None, "built_in_pack row must not be deleted"
        assert row_a[0] == "built_in_pack:blue_archive"
        assert row_b is not None, "external:safebooru row must not be deleted"
        assert row_b[0] == "external:safebooru"


# ---------------------------------------------------------------------------
# Helper: is_protected_source unit tests
# ---------------------------------------------------------------------------

class TestIsProtectedSource:
    def test_user_confirmed(self):
        assert _is_protected_source("user_confirmed") is True

    def test_built_in_pack_prefix(self):
        assert _is_protected_source("built_in_pack:blue_archive") is True
        assert _is_protected_source("built_in_pack:trickcal") is True

    def test_external_safebooru(self):
        assert _is_protected_source("external:safebooru") is True

    def test_null_is_protected(self):
        assert _is_protected_source(None) is True

    def test_empty_string_is_protected(self):
        assert _is_protected_source("") is True

    def test_imported_localized_pack_not_protected(self):
        assert _is_protected_source("imported_localized_pack") is False


# ---------------------------------------------------------------------------
# 3. Action classification
# ---------------------------------------------------------------------------

class TestActionClassification:
    def test_complete_loss_alias_is_delete_candidate(self, tmp_path):
        """alias='???????' with imported_localized_pack → delete_alias."""
        conn = _make_mem_db()
        _insert_alias(conn, "???????", "Canon X", source="imported_localized_pack")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        non_protected = [r for r in plan["actions"] if r["action"] != "protected_skip"]
        assert any(r["action"] == "delete_alias" for r in non_protected), (
            f"Expected delete_alias but got: {[r['action'] for r in non_protected]}"
        )

    def test_complete_loss_underscore_alias_is_delete_candidate(self, tmp_path):
        """alias='__-___' (underscore placeholder) → delete_alias."""
        conn = _make_mem_db()
        _insert_alias(conn, "__-___", "Canon Y", source="imported_localized_pack")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        non_protected = [r for r in plan["actions"] if r["action"] != "protected_skip"]
        assert any(r["action"] == "delete_alias" for r in non_protected), (
            f"Expected delete_alias but got: {[r['action'] for r in non_protected]}"
        )

    def test_localized_name_with_clean_replacement_is_update(self, tmp_path):
        """Broken display_name with a clean replacement row → update_localization."""
        conn = _make_mem_db()
        canonical = "伊落マリー"
        # Broken row (imported_localized_pack, tag_type='character')
        _insert_localization(
            conn, canonical, "ko", "?????",
            tag_type="character",
            source="imported_localized_pack",
        )
        # Clean replacement row (built_in_pack, tag_type='series')
        # Different tag_type avoids the UNIQUE(canonical, tag_type, parent_series, locale)
        # conflict that would cause INSERT OR REPLACE to delete the broken row.
        # _find_clean_localization searches across all tag_types for the same
        # canonical + locale, so this row will be found as the replacement.
        _insert_localization(
            conn, canonical, "ko", "이오치 마리",
            tag_type="series",
            source="built_in_pack:blue_archive",
        )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        updates = [r for r in plan["actions"] if r["action"] == "update_localization"]
        assert len(updates) >= 1
        assert updates[0]["new_value"] == "이오치 마리"

    def test_canonical_mojibake_is_manual_review_in_alias(self, tmp_path):
        """canonical itself is mojibake (but not complete-loss) → manual_review."""
        conn = _make_mem_db()
        # Use a latin1-mojibake canonical that is NOT a complete-loss pattern
        _insert_alias(
            conn, "SomeAlias", "Ã¢Â¥CanonÃ¢Â¥",
            source="imported_localized_pack",
        )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        non_protected = [r for r in plan["actions"] if r["action"] != "protected_skip"]
        assert any(r["action"] == "manual_review" for r in non_protected), (
            f"Expected manual_review but got: {[r['action'] for r in non_protected]}"
        )

    def test_no_replacement_candidate_is_manual_review(self, tmp_path):
        """Broken display_name, no clean replacement → manual_review."""
        conn = _make_mem_db()
        _insert_localization(
            conn, "SomeCanon", "ko", "?????",
            source="imported_localized_pack",
        )
        # No other row for same canonical+locale exists
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        reviews = [r for r in plan["actions"] if r["action"] == "manual_review"]
        assert len(reviews) >= 1

    def test_does_not_use_en_fallback_for_ko_ja(self, tmp_path):
        """Broken ko display_name must NOT be replaced with an en value."""
        conn = _make_mem_db()
        canonical = "砂狼シロコ"
        # Broken ko row
        _insert_localization(
            conn, canonical, "ko", "?????",
            source="imported_localized_pack",
        )
        # Only en replacement exists (must NOT be used)
        _insert_localization(
            conn, canonical, "en", "Shiroko",
            source="built_in_pack:blue_archive",
        )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        updates = [r for r in plan["actions"] if r["action"] == "update_localization"]
        # Must not have proposed en value as replacement for ko
        for upd in updates:
            if upd.get("locale") == "ko":
                assert upd["new_value"] != "Shiroko", (
                    "Must not replace ko broken display_name with en value"
                )

    def test_clean_row_imported_not_flagged(self, tmp_path):
        """Clean imported_localized_pack row must not appear in any action."""
        conn = _make_mem_db()
        _insert_localization(
            conn, "Blue Archive", "ko", "블루 아카이브",
            source="imported_localized_pack",
        )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        non_protected = [r for r in plan["actions"] if r["action"] != "protected_skip"]
        # Clean rows should generate no repair actions
        assert non_protected == [], (
            f"Clean row should not be flagged but got: {non_protected}"
        )

    def test_clean_alias_imported_not_flagged(self, tmp_path):
        """Clean imported_localized_pack alias must not appear in any action."""
        conn = _make_mem_db()
        _insert_alias(
            conn, "이오치 마리", "伊落マリー",
            source="imported_localized_pack",
        )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        non_protected = [r for r in plan["actions"] if r["action"] != "protected_skip"]
        assert non_protected == [], (
            f"Clean alias should not be flagged but got: {non_protected}"
        )


# ---------------------------------------------------------------------------
# 4. Apply + transaction
# ---------------------------------------------------------------------------

class TestApplyAndTransaction:
    def test_apply_executes_planned_updates(self, tmp_path):
        """apply result count matches plan."""
        conn = _make_mem_db()
        canonical = "伊落マリー"
        # Broken ko row (character) — imported_localized_pack
        _insert_localization(
            conn, canonical, "ko", "?????",
            tag_type="character",
            source="imported_localized_pack",
        )
        # Clean replacement (series) — different tag_type avoids UNIQUE conflict.
        # _find_clean_localization searches all tag_types for the same canonical+locale.
        _insert_localization(
            conn, canonical, "ko", "이오치 마리",
            tag_type="series",
            source="built_in_pack:blue_archive",
        )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        planned_updates = plan["summary"]["planned_updates"]
        assert planned_updates >= 1, "Setup must produce at least one update_localization action"

        backup = tmp_path / "backup.db"
        result = apply_plan(db_file, plan)

        assert result["applied_updates"] == planned_updates
        # Verify DB was actually updated (character row now shows the clean value)
        assert _get_display_name(db_file, canonical, "ko") == "이오치 마리"

    def test_apply_executes_planned_deletes(self, tmp_path):
        """apply deletes complete-loss alias rows."""
        conn = _make_mem_db()
        _insert_alias(conn, "???????", "Canon X", source="imported_localized_pack")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        before = _row_count(db_file, "tag_aliases")
        plan = build_plan(db_file)
        planned_deletes = plan["summary"]["planned_deletes"]

        backup = tmp_path / "backup.db"
        result = apply_plan(db_file, plan)

        assert result["applied_deletes"] == planned_deletes
        after = _row_count(db_file, "tag_aliases")
        assert after == before - planned_deletes

    def test_apply_count_matches_plan(self, tmp_path):
        """applied counts must equal planned counts."""
        conn = _make_mem_db()
        canonical = "TestCanon"
        # Different tag_types so both rows coexist (avoid UNIQUE conflict).
        _insert_localization(conn, canonical, "ko", "?????",
                             tag_type="character",
                             source="imported_localized_pack")
        _insert_localization(conn, canonical, "ko", "테스트",
                             tag_type="series",
                             source="built_in_pack:test")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        result = apply_plan(db_file, plan)

        assert result["applied_updates"] == plan["summary"]["planned_updates"]
        assert result["applied_deletes"] == plan["summary"]["planned_deletes"]

    def test_apply_rolls_back_on_error(self, tmp_path, monkeypatch):
        """If an error occurs mid-transaction, ROLLBACK is called and DB unchanged."""
        conn = _make_mem_db()
        canonical = "RollbackTestCanon"
        # Use different tag_types so INSERT OR REPLACE does not collapse two rows into one.
        _insert_localization(conn, canonical, "ko", "?????",
                             tag_type="character",
                             source="imported_localized_pack")
        _insert_localization(conn, canonical, "ko", "정상값",
                             tag_type="series",
                             source="built_in_pack:test")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        before = _row_count(db_file, "tag_localizations")
        plan = build_plan(db_file)

        # Monkey-patch _apply_update to raise mid-transaction.
        # In Python 3.14+, sqlite3.Connection.execute is read-only and cannot be
        # monkey-patched directly; patching the helper function is reliable.
        import tools.repair_mojibake_db as mod

        def failing_apply_update(conn, rec):
            raise sqlite3.OperationalError("Simulated failure")

        monkeypatch.setattr(mod, "_apply_update", failing_apply_update)

        with pytest.raises(sqlite3.OperationalError, match="Simulated failure"):
            apply_plan(db_file, plan)

        # DB must be unchanged after rollback
        after = _row_count(db_file, "tag_localizations")
        assert before == after

    def test_apply_does_not_touch_clean_rows(self, tmp_path):
        """Clean imported_localized_pack rows must survive apply unchanged."""
        conn = _make_mem_db()
        # Clean row — should be untouched
        _insert_alias(conn, "이오치 마리", "伊落マリー",
                      source="imported_localized_pack")
        # Broken row — will be deleted
        _insert_alias(conn, "???????", "Canon Bad",
                      source="imported_localized_pack",
                      tag_type="character", parent_series="Test")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        backup = tmp_path / "bak.db"
        apply_plan(db_file, plan)

        c = sqlite3.connect(str(db_file))
        clean_row = c.execute(
            "SELECT * FROM tag_aliases WHERE alias='이오치 마리'"
        ).fetchone()
        c.close()

        assert clean_row is not None, "Clean row must survive apply"


# ---------------------------------------------------------------------------
# 5. JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_json_plan_structure(self, tmp_path):
        conn = _make_mem_db()
        _insert_localization(conn, "TestCanon", "ko", "?????",
                             source="imported_localized_pack")
        db_file = _db_to_file(conn, tmp_path)
        json_out = tmp_path / "plan.json"
        conn.close()

        code = main(["--db", str(db_file), "--json", str(json_out)])
        assert code == 0
        assert json_out.exists()

        data = json.loads(json_out.read_text(encoding="utf-8"))

        for key in ("db_path", "planned_at", "summary", "actions"):
            assert key in data, f"Missing key: {key}"

        s = data["summary"]
        for k in ("planned_updates", "planned_deletes", "manual_review",
                  "protected_skipped", "by_table", "by_action"):
            assert k in s, f"Missing summary key: {k}"

        assert isinstance(data["actions"], list)

    def test_json_plan_includes_all_actions(self, tmp_path):
        """JSON plan must contain records for every classified action."""
        conn = _make_mem_db()
        canonical = "伊落マリー"
        # update_localization candidate: broken row (character) + clean replacement (series).
        # Different tag_types prevent INSERT OR REPLACE from collapsing them into one row.
        _insert_localization(conn, canonical, "ko", "?????",
                             tag_type="character",
                             source="imported_localized_pack")
        _insert_localization(conn, canonical, "ko", "이오치 마리",
                             tag_type="series",
                             source="built_in_pack:blue_archive")
        # delete_alias candidate
        _insert_alias(conn, "???????", "Canon X", source="imported_localized_pack",
                      tag_type="character", parent_series="Series X")
        # protected row
        _insert_alias(conn, "normal_alias", "Canon Y", source="built_in_pack:blue_archive",
                      tag_type="character", parent_series="Series Y")
        db_file = _db_to_file(conn, tmp_path)
        json_out = tmp_path / "plan.json"
        conn.close()

        main(["--db", str(db_file), "--json", str(json_out)])
        data = json.loads(json_out.read_text(encoding="utf-8"))

        actions_by_type: dict[str, list] = {}
        for rec in data["actions"]:
            a = rec["action"]
            actions_by_type.setdefault(a, []).append(rec)

        assert "update_localization" in actions_by_type
        assert "delete_alias" in actions_by_type
        assert "protected_skip" in actions_by_type

        # Verify action record structure
        for rec in data["actions"]:
            for field in ("action", "table", "id", "field", "old_value",
                          "new_value", "reasons", "source", "locale"):
                assert field in rec, f"Action record missing field {field!r}: {rec}"

    def test_json_private_keys_not_exported(self, tmp_path):
        """Internal _* keys (e.g. _canonical) must not appear in JSON output."""
        conn = _make_mem_db()
        canonical = "伊落マリー"
        # Different tag_types to avoid UNIQUE conflict.
        _insert_localization(conn, canonical, "ko", "?????",
                             tag_type="character",
                             source="imported_localized_pack")
        _insert_localization(conn, canonical, "ko", "이오치 마리",
                             tag_type="series",
                             source="built_in_pack:blue_archive")
        db_file = _db_to_file(conn, tmp_path)
        json_out = tmp_path / "plan.json"
        conn.close()

        main(["--db", str(db_file), "--json", str(json_out)])
        data = json.loads(json_out.read_text(encoding="utf-8"))

        for rec in data["actions"]:
            for key in rec:
                assert not key.startswith("_"), (
                    f"Private key {key!r} must not appear in JSON output"
                )


# ---------------------------------------------------------------------------
# 6. No auto user_confirmed creation
# ---------------------------------------------------------------------------

class TestNoAutoUserConfirmed:
    def test_apply_does_not_create_user_confirmed(self, tmp_path):
        """After apply, no new source='user_confirmed' rows must be created."""
        conn = _make_mem_db()
        canonical = "伊落マリー"
        # Different tag_types to avoid UNIQUE conflict.
        _insert_localization(conn, canonical, "ko", "?????",
                             tag_type="character",
                             source="imported_localized_pack")
        _insert_localization(conn, canonical, "ko", "이오치 마리",
                             tag_type="series",
                             source="built_in_pack:blue_archive")
        _insert_alias(conn, "???????", "Canon X", source="imported_localized_pack",
                      tag_type="character", parent_series="Test")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        # Count user_confirmed rows before
        c = sqlite3.connect(str(db_file))
        before_uc_aliases = c.execute(
            "SELECT COUNT(*) FROM tag_aliases WHERE source='user_confirmed'"
        ).fetchone()[0]
        before_uc_locals = c.execute(
            "SELECT COUNT(*) FROM tag_localizations WHERE source='user_confirmed'"
        ).fetchone()[0]
        c.close()

        plan = build_plan(db_file)
        apply_plan(db_file, plan)

        c = sqlite3.connect(str(db_file))
        after_uc_aliases = c.execute(
            "SELECT COUNT(*) FROM tag_aliases WHERE source='user_confirmed'"
        ).fetchone()[0]
        after_uc_locals = c.execute(
            "SELECT COUNT(*) FROM tag_localizations WHERE source='user_confirmed'"
        ).fetchone()[0]
        c.close()

        assert before_uc_aliases == after_uc_aliases, (
            "apply must not create new user_confirmed alias rows"
        )
        assert before_uc_locals == after_uc_locals, (
            "apply must not create new user_confirmed localization rows"
        )

    def test_apply_source_column_unchanged_for_updated_rows(self, tmp_path):
        """Updated rows must keep their original source, not become user_confirmed."""
        conn = _make_mem_db()
        canonical = "UpdatedCanon"
        # Use different tag_types so INSERT OR REPLACE does not collapse two rows into one.
        # The broken row (character/imported) and the clean replacement (series/built_in_pack)
        # must coexist so _find_clean_localization can find the replacement.
        _insert_localization(conn, canonical, "ko", "?????",
                             tag_type="character",
                             source="imported_localized_pack")
        _insert_localization(conn, canonical, "ko", "정상값",
                             tag_type="series",
                             source="built_in_pack:test")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        plan = build_plan(db_file)
        apply_plan(db_file, plan)

        c = sqlite3.connect(str(db_file))
        # The imported_localized_pack row should now have updated display_name
        # but source must remain imported_localized_pack (we UPDATE display_name only)
        row = c.execute(
            "SELECT source, display_name FROM tag_localizations"
            " WHERE canonical=? AND locale='ko' AND source='imported_localized_pack'",
            (canonical,),
        ).fetchone()
        c.close()

        # The row still exists (we only UPDATE, not DELETE+INSERT)
        assert row is not None, "Updated row must still exist"
        assert row[0] == "imported_localized_pack", (
            f"source must remain 'imported_localized_pack', got {row[0]!r}"
        )
        assert row[1] == "정상값", f"display_name must be updated, got {row[1]!r}"
