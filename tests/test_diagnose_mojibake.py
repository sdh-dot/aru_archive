"""tests/test_diagnose_mojibake.py — Unit tests for tools/diagnose_mojibake.py.

Tests are grouped into:
  1. Heuristic function unit tests (is_suspected_mojibake)
  2. Diagnose function tests using in-memory SQLite DBs
  3. JSON output structure tests
  4. CLI compatibility tests
  5. Read-only guarantee tests
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

from tools.diagnose_mojibake import (
    diagnose,
    is_suspected_mojibake,
    main,
)

# ---------------------------------------------------------------------------
# Helpers — in-memory DB factory
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


def _make_mem_db(*, with_aliases: bool = True, with_localizations: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    if with_aliases:
        conn.execute(_TAG_ALIASES_DDL)
    if with_localizations:
        conn.execute(_TAG_LOCALIZATIONS_DDL)
    conn.commit()
    return conn


def _insert_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    tag_type: str = "character",
    parent_series: str = "Blue Archive",
    source: str = "built_in",
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO tag_aliases"
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
    source: str = "built_in",
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO tag_localizations"
        " (localization_id, canonical, tag_type, parent_series, locale,"
        "  display_name, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00Z')",
        (str(uuid.uuid4()), canonical, tag_type, parent_series, locale,
         display_name, source),
    )
    conn.commit()


def _db_to_file(conn: sqlite3.Connection, tmp_path: Path) -> Path:
    """Persist an in-memory SQLite DB to a temp file and return the path."""
    db_file = tmp_path / "test.db"
    dest = sqlite3.connect(str(db_file))
    conn.backup(dest)
    dest.close()
    return db_file


# ---------------------------------------------------------------------------
# 1. Heuristic unit tests
# ---------------------------------------------------------------------------

class TestIsSuspectedMojibake:
    def test_replacement_char_is_suspected(self):
        suspected, reasons = is_suspected_mojibake("abc�def")
        assert suspected
        assert "replacement-char" in reasons

    def test_white_square_is_suspected(self):
        suspected, reasons = is_suspected_mojibake("abc□def")
        assert suspected
        assert "replacement-char" in reasons

    def test_question_marks_run_is_suspected(self):
        suspected, reasons = is_suspected_mojibake("???")
        assert suspected
        assert "?-runs" in reasons

    def test_two_question_marks_not_suspected(self):
        # Two '?' without a run of three should NOT trigger ?-runs
        _, reasons = is_suspected_mojibake("ab??cd")
        # Should not have ?-runs (no triple run)
        assert "?-runs" not in reasons

    def test_underscore_placeholder_is_suspected(self):
        # "___" with almost no alphanumeric content
        suspected, reasons = is_suspected_mojibake("__-___")
        assert suspected
        assert "underscore-placeholder" in reasons

    def test_underscore_with_lots_of_alnum_not_placeholder(self):
        # "___" but surrounded by many alphanumeric chars — should NOT flag
        _, reasons = is_suspected_mojibake("hello___world_more_text_here_123")
        assert "underscore-placeholder" not in reasons

    def test_clean_korean_not_suspected(self):
        suspected, _ = is_suspected_mojibake("블루 아카이브", locale="ko")
        assert not suspected

    def test_clean_japanese_not_suspected(self):
        suspected, _ = is_suspected_mojibake("伊落マリー", locale="ja")
        assert not suspected

    def test_clean_english_not_suspected(self):
        suspected, _ = is_suspected_mojibake("Blue Archive", locale="en")
        assert not suspected

    def test_locale_mismatch_ko_ascii_text(self):
        # ASCII-only text with locale='ko' should trigger locale-mismatch
        suspected, reasons = is_suspected_mojibake("Trickcal", locale="ko")
        assert suspected
        assert "locale-mismatch" in reasons

    def test_locale_mismatch_ja_latin_text(self):
        suspected, reasons = is_suspected_mojibake("some latin text only", locale="ja")
        assert suspected
        assert "locale-mismatch" in reasons

    def test_punctuation_heavy_is_suspected(self):
        suspected, reasons = is_suspected_mojibake("!?!?!?!?")
        assert suspected
        assert "punctuation-heavy" in reasons

    def test_latin1_mojibake_chars(self):
        # Typical Latin-1 mojibake from UTF-8 misread as ISO-8859-1
        suspected, reasons = is_suspected_mojibake("Ã¢Â¥")
        assert suspected
        assert "latin1-mojibake" in reasons

    def test_empty_string_not_suspected(self):
        suspected, reasons = is_suspected_mojibake("")
        assert not suspected
        assert reasons == []

    def test_none_not_suspected(self):
        # Pass None to exercise the defensive isinstance guard in the function.
        from typing import Optional
        none_val: Optional[str] = None
        suspected, reasons = is_suspected_mojibake(none_val)
        assert not suspected
        assert reasons == []

    def test_returns_tuple(self):
        result = is_suspected_mojibake("test")
        assert isinstance(result, tuple)
        assert len(result) == 2
        suspected, reasons = result
        assert isinstance(suspected, bool)
        assert isinstance(reasons, list)


# ---------------------------------------------------------------------------
# 2. Diagnose function tests (in-memory DB via file)
# ---------------------------------------------------------------------------

class TestDiagnoseCleanDb:
    def test_zero_suspected_clean_aliases(self, tmp_path):
        conn = _make_mem_db()
        # Insert 50 clean records — each alias must be unique (alias is part of PK)
        for i in range(50):
            _insert_alias(
                conn,
                alias=f"clean_alias_{i:03d}",
                canonical=f"Clean Canonical {i % 10}",
                tag_type="general",
                parent_series="",
                source="built_in",
            )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        assert result["summary"]["tag_aliases"]["suspected"] == 0
        assert result["summary"]["tag_aliases"]["inspected"] == 50

    def test_zero_suspected_clean_localizations(self, tmp_path):
        conn = _make_mem_db()
        clean_locals = [
            ("伊落マリー", "ko", "이오치 마리"),
            ("伊落マリー", "ja", "伊落マリー"),
            ("砂狼シロコ", "ko", "스나오카미 시로코"),
            ("砂狼シロコ", "ja", "砂狼シロコ"),
            ("Blue Archive", "ko", "블루 아카이브"),
        ] * 10  # 50 total (using upsert semantics — UNIQUE prevents exact dupes)
        inserted = set()
        for canonical, locale, display_name in clean_locals:
            key = (canonical, locale)
            if key not in inserted:
                _insert_localization(conn, canonical, locale, display_name)
                inserted.add(key)
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        assert result["summary"]["tag_localizations"]["suspected"] == 0


class TestDiagnosePollutedDb:
    def test_polluted_aliases_counted(self, tmp_path):
        conn = _make_mem_db()
        # 90 clean records
        for i in range(90):
            _insert_alias(
                conn,
                alias=f"clean_alias_{i}",
                canonical=f"Clean Canonical {i}",
                tag_type="general",
                parent_series="",
                source="built_in",
            )
        # 10 polluted records (replacement char)
        for i in range(10):
            _insert_alias(
                conn,
                alias=f"polluted�_{i}",
                canonical=f"Canonical {i}",
                tag_type="general",
                parent_series="",
                source="import",
            )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        assert result["summary"]["tag_aliases"]["inspected"] == 100
        assert result["summary"]["tag_aliases"]["suspected"] == 10

    def test_polluted_localizations_counted(self, tmp_path):
        conn = _make_mem_db()
        # 40 clean localizations
        for i in range(40):
            _insert_localization(
                conn,
                canonical=f"Series {i}",
                locale="ko",
                display_name=f"시리즈 {i}",
                tag_type="series",
                parent_series="",
            )
        # 10 mojibake localizations
        for i in range(10):
            _insert_localization(
                conn,
                canonical=f"Mojibake Series {i}",
                locale="ko",
                display_name=f"????? {i}",
                tag_type="series",
                parent_series="",
                source="import",
            )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        assert result["summary"]["tag_localizations"]["suspected"] == 10

    def test_false_positive_rate_clean_fixture(self, tmp_path):
        """False positive rate < 5 % on a purely clean 50-row fixture."""
        conn = _make_mem_db()
        clean_aliases = [
            ("伊落マリー", "伊落マリー"),
            ("이오치 마리", "伊落マリー"),
            ("Iochi Mari", "伊落マリー"),
            ("Mari Iochi", "伊落マリー"),
            ("砂狼シロコ", "砂狼シロコ"),
            ("스나오카미 시로코", "砂狼シロコ"),
            ("Shiroko", "砂狼シロ코"),
            ("Blue Archive", "Blue Archive"),
            ("블루 아카이브", "Blue Archive"),
            ("ブルーアーカイブ", "Blue Archive"),
        ] * 5  # 50 total
        inserted = set()
        for alias, canonical in clean_aliases:
            if alias not in inserted:
                _insert_alias(conn, alias, canonical, tag_type="general", parent_series="")
                inserted.add(alias)
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        n = result["summary"]["tag_aliases"]["inspected"]
        m = result["summary"]["tag_aliases"]["suspected"]
        # false positive rate must be < 5 %
        assert n > 0
        assert (m / n) < 0.05, f"False positive rate too high: {m}/{n} = {m/n:.1%}"


class TestDiagnoseGroupings:
    def test_groups_by_source(self, tmp_path):
        conn = _make_mem_db()
        # built_in: 5 clean
        for i in range(5):
            _insert_alias(
                conn, f"built_{i}", f"Canon {i}",
                tag_type="general", parent_series="", source="built_in",
            )
        # import: 3 polluted + 2 clean
        for i in range(3):
            _insert_alias(
                conn, f"bad�_{i}", f"Canon imp {i}",
                tag_type="general", parent_series="", source="import",
            )
        for i in range(2):
            _insert_alias(
                conn, f"good_import_{i}", f"Canon imp good {i}",
                tag_type="general", parent_series="", source="import",
            )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        by_source = result["by_source"]["tag_aliases"]
        assert by_source["built_in"]["suspected"] == 0
        assert by_source["built_in"]["inspected"] == 5
        assert by_source["import"]["suspected"] == 3
        assert by_source["import"]["inspected"] == 5

    def test_groups_by_locale(self, tmp_path):
        conn = _make_mem_db()
        # ko: 3 clean + 2 polluted
        for i in range(3):
            _insert_localization(conn, f"Series KO {i}", "ko", f"시리즈 {i}",
                                 tag_type="series", parent_series="")
        for i in range(2):
            _insert_localization(conn, f"Mojibake KO {i}", "ko", f"????? {i}",
                                 tag_type="series", parent_series="")
        # ja: 4 clean
        for i in range(4):
            _insert_localization(conn, f"Series JA {i}", "ja", f"シリーズ{i}",
                                 tag_type="series", parent_series="")
        # en: 3 clean
        for i in range(3):
            _insert_localization(conn, f"Series EN {i}", "en", f"Series {i}",
                                 tag_type="series", parent_series="")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        by_locale = result["by_locale"]["tag_localizations"]
        assert by_locale["ko"]["inspected"] == 5
        assert by_locale["ko"]["suspected"] == 2
        assert by_locale["ja"]["inspected"] == 4
        assert by_locale["ja"]["suspected"] == 0
        assert by_locale["en"]["inspected"] == 3
        assert by_locale["en"]["suspected"] == 0


class TestDiagnoseSamples:
    def test_samples_limited(self, tmp_path):
        conn = _make_mem_db()
        # Insert 20 polluted aliases
        for i in range(20):
            _insert_alias(
                conn, f"bad�_{i}", f"Canon {i}",
                tag_type="general", parent_series="", source="import",
            )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file, limit_samples=5)
        assert len(result["samples"]) <= 5

    def test_samples_default_limit(self, tmp_path):
        conn = _make_mem_db()
        for i in range(50):
            _insert_alias(
                conn, f"bad�_{i}", f"Canon {i}",
                tag_type="general", parent_series="", source="import",
            )
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)
        assert len(result["samples"]) <= 20


class TestDiagnoseDoesNotWrite:
    def test_row_count_unchanged_after_diagnose(self, tmp_path):
        """Running diagnose must not modify any row in the database."""
        conn = _make_mem_db()
        _insert_alias(conn, "伊落マリー", "伊落マリー")
        _insert_alias(conn, "bad�", "Some Canon", tag_type="general",
                      parent_series="", source="import")
        _insert_localization(conn, "Blue Archive", "ko", "블루 아카이브",
                              tag_type="series", parent_series="")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        # Count rows before
        check_conn = sqlite3.connect(str(db_file))
        before_alias = check_conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        before_local = check_conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]
        check_conn.close()

        # Run diagnosis
        diagnose(db_file)

        # Count rows after
        check_conn = sqlite3.connect(str(db_file))
        after_alias = check_conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        after_local = check_conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]
        check_conn.close()

        assert before_alias == after_alias
        assert before_local == after_local


# ---------------------------------------------------------------------------
# 3. JSON output tests
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_json_output_structure(self, tmp_path):
        conn = _make_mem_db()
        _insert_alias(conn, "伊落マリー", "伊落マリー")
        _insert_localization(conn, "Blue Archive", "ko", "블루 아카이브",
                              tag_type="series", parent_series="")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        result = diagnose(db_file)

        # Required top-level keys
        for key in ("db_path", "inspected_at", "summary", "by_source", "by_locale", "samples"):
            assert key in result, f"Missing key: {key}"

        # Summary sub-keys
        for tbl in ("tag_aliases", "tag_localizations"):
            assert tbl in result["summary"]
            assert "inspected" in result["summary"][tbl]
            assert "suspected" in result["summary"][tbl]

        # by_source / by_locale structure
        assert "tag_aliases" in result["by_source"]
        assert "tag_localizations" in result["by_locale"]

        assert isinstance(result["samples"], list)

    def test_json_output_utf8_preserved(self, tmp_path):
        """Korean/Japanese text must survive JSON serialization without escaping.

        Insert suspected rows whose text contains Japanese/Korean characters,
        so they end up in the samples list, then check that the serialized JSON
        preserves those characters unescaped (ensure_ascii=False).
        """
        conn = _make_mem_db()
        # Suspected alias — Japanese characters plus ??? run triggers heuristic.
        _insert_alias(
            conn,
            alias="伊落マリー???",
            canonical="伊落マリー???",
        )
        # Suspected localization — Korean display_name plus ??? run triggers heuristic.
        _insert_localization(
            conn,
            canonical="이오치 마리???",
            locale="ko",
            display_name="이오치 마리???",
            tag_type="character",
            parent_series="Blue Archive",
            source="import",
        )
        db_file = _db_to_file(conn, tmp_path)
        json_out = tmp_path / "report.json"
        conn.close()

        result = diagnose(db_file, limit_samples=5)

        # Serialize with ensure_ascii=False (as the tool does)
        serialized = json.dumps(result, ensure_ascii=False, indent=2)
        # Both the Japanese alias and Korean display_name must appear unescaped
        # in the suspected samples section.
        assert "伊落マリー" in serialized
        assert "이오치 마리" in serialized

        # Also write to file and re-read
        json_out.write_text(serialized, encoding="utf-8")
        reloaded = json.loads(json_out.read_text(encoding="utf-8"))
        assert reloaded["db_path"] == str(db_file)

    def test_json_file_written_by_main(self, tmp_path):
        conn = _make_mem_db()
        _insert_alias(conn, "伊落マリー", "伊落マリー")
        db_file = _db_to_file(conn, tmp_path)
        json_out = tmp_path / "out.json"
        conn.close()

        exit_code = main(["--db", str(db_file), "--json", str(json_out)])
        assert exit_code == 0
        assert json_out.exists()
        data = json.loads(json_out.read_text(encoding="utf-8"))
        assert "summary" in data


# ---------------------------------------------------------------------------
# 4. CLI compatibility tests
# ---------------------------------------------------------------------------

class TestCli:
    def test_missing_db_raises(self, tmp_path):
        nonexistent = tmp_path / "no_such_db.db"
        exit_code = main(["--db", str(nonexistent)])
        assert exit_code == 2

    def test_missing_table_skips_gracefully(self, tmp_path):
        """DB with neither tag_aliases nor tag_localizations must not crash."""
        db_file = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        # Should exit 0 (warns to stderr, does not crash)
        exit_code = main(["--db", str(db_file)])
        assert exit_code == 0

    def test_limit_samples_respected_via_cli(self, tmp_path):
        conn = _make_mem_db()
        for i in range(30):
            _insert_alias(conn, f"bad�_{i}", f"Canon {i}",
                          tag_type="general", parent_series="", source="import")
        db_file = _db_to_file(conn, tmp_path)
        json_out = tmp_path / "limited.json"
        conn.close()

        exit_code = main([
            "--db", str(db_file),
            "--json", str(json_out),
            "--limit-samples", "3",
        ])
        assert exit_code == 0
        data = json.loads(json_out.read_text(encoding="utf-8"))
        assert len(data["samples"]) <= 3

    def test_valid_db_exits_zero(self, tmp_path):
        conn = _make_mem_db()
        _insert_alias(conn, "伊落マリー", "伊落マリー")
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        exit_code = main(["--db", str(db_file)])
        assert exit_code == 0


# ---------------------------------------------------------------------------
# 5. Read-only guarantee tests
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_diagnose_uses_readonly_uri(self, tmp_path, monkeypatch):
        """sqlite3.connect must be called with a URI containing 'mode=ro'."""
        import tools.diagnose_mojibake as mod

        captured_args: list[tuple] = []
        captured_kwargs: list[dict] = []
        original_connect = sqlite3.connect

        def patched_connect(*args, **kwargs):
            captured_args.append(args)
            captured_kwargs.append(kwargs)
            return original_connect(*args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", patched_connect)
        # Also patch in the module's namespace so the import is intercepted
        monkeypatch.setattr(mod.sqlite3, "connect", patched_connect)

        conn = _make_mem_db()
        db_file = _db_to_file(conn, tmp_path)
        conn.close()

        diagnose(db_file)

        # At least one connect call must use mode=ro URI
        found_ro = any(
            "mode=ro" in str(args[0]) and kwargs.get("uri") is True
            for args, kwargs in zip(captured_args, captured_kwargs)
        )
        assert found_ro, (
            "diagnose() must open the database with a read-only URI (mode=ro, uri=True). "
            f"Calls observed: {list(zip(captured_args, captured_kwargs))}"
        )

    def test_no_write_keywords_in_source(self):
        """Source of diagnose_mojibake must not contain write SQL keywords."""
        source_path = Path(__file__).parent.parent / "tools" / "diagnose_mojibake.py"
        source = source_path.read_text(encoding="utf-8")

        # We expect these DML/DDL keywords to be absent from actual SQL strings.
        # The detection is simple: check for the keywords as bare words that would
        # appear in SQL (not in comments or string literals that are part of this
        # guard check itself).
        forbidden = ["INSERT ", "UPDATE ", "DELETE ", "REPLACE ", "CREATE TABLE",
                     "DROP TABLE", "ALTER TABLE"]
        for kw in forbidden:
            # A basic check — the keyword must not appear outside of comment lines.
            non_comment_lines = [
                line for line in source.splitlines()
                if not line.lstrip().startswith("#")
            ]
            hit_lines = [ln for ln in non_comment_lines if kw in ln]
            assert not hit_lines, (
                f"Forbidden SQL keyword {kw!r} found in diagnose_mojibake.py:\n"
                + "\n".join(hit_lines)
            )
