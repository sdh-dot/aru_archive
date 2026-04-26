"""
core/tag_pack_exporter.py 테스트.

export_public_tag_pack, export_dictionary_backup, save_to_file
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE tag_aliases (
            alias         TEXT NOT NULL,
            canonical     TEXT NOT NULL,
            tag_type      TEXT NOT NULL DEFAULT 'general',
            parent_series TEXT NOT NULL DEFAULT '',
            source        TEXT,
            confidence_score REAL,
            enabled       INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL,
            updated_at    TEXT,
            PRIMARY KEY (alias, tag_type, parent_series)
        );
        CREATE TABLE tag_localizations (
            localization_id TEXT PRIMARY KEY,
            canonical       TEXT NOT NULL,
            tag_type        TEXT NOT NULL,
            parent_series   TEXT NOT NULL DEFAULT '',
            locale          TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            source          TEXT,
            enabled         INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT,
            UNIQUE(canonical, tag_type, parent_series, locale)
        );
        CREATE TABLE external_dictionary_entries (
            entry_id      TEXT PRIMARY KEY,
            source        TEXT NOT NULL,
            canonical     TEXT NOT NULL,
            tag_type      TEXT NOT NULL,
            parent_series TEXT NOT NULL DEFAULT '',
            alias         TEXT,
            confidence_score REAL,
            status        TEXT NOT NULL DEFAULT 'staged',
            imported_at   TEXT NOT NULL,
            updated_at    TEXT
        );
    """)
    yield db
    db.close()


def _seed_alias(db, alias, canonical, tag_type, parent_series="", enabled=1):
    db.execute(
        "INSERT INTO tag_aliases (alias, canonical, tag_type, parent_series, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, '2024-01-01')",
        (alias, canonical, tag_type, parent_series, enabled),
    )
    db.commit()


def _seed_loc(db, canonical, tag_type, locale, display_name, parent_series=""):
    import uuid
    db.execute(
        "INSERT INTO tag_localizations "
        "(localization_id, canonical, tag_type, parent_series, locale, display_name, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, '2024-01-01')",
        (str(uuid.uuid4()), canonical, tag_type, parent_series, locale, display_name),
    )
    db.commit()


# ---------------------------------------------------------------------------
# export_public_tag_pack
# ---------------------------------------------------------------------------

class TestExportPublicTagPack:
    def test_basic_structure(self, conn) -> None:
        from core.tag_pack_exporter import export_public_tag_pack
        pack = export_public_tag_pack(conn, "test", "Test Pack")
        assert pack["pack_id"] == "test"
        assert pack["name"] == "Test Pack"
        assert "series" in pack
        assert "characters" in pack
        assert "exported_at" in pack

    def test_empty_db_empty_lists(self, conn) -> None:
        from core.tag_pack_exporter import export_public_tag_pack
        pack = export_public_tag_pack(conn, "test", "Test Pack")
        assert pack["series"] == []
        assert pack["characters"] == []

    def test_exports_series_aliases(self, conn) -> None:
        from core.tag_pack_exporter import export_public_tag_pack
        _seed_alias(conn, "ブルアカ", "Blue Archive", "series")
        _seed_alias(conn, "BlueArchive", "Blue Archive", "series")
        pack = export_public_tag_pack(conn, "test", "Test Pack")
        assert len(pack["series"]) == 1
        assert pack["series"][0]["canonical"] == "Blue Archive"
        assert "ブルアカ" in pack["series"][0]["aliases"]
        assert "BlueArchive" in pack["series"][0]["aliases"]

    def test_exports_character_aliases(self, conn) -> None:
        from core.tag_pack_exporter import export_public_tag_pack
        _seed_alias(conn, "ワカモ", "狐坂ワカモ", "character", "Blue Archive")
        _seed_alias(conn, "Wakamo", "狐坂ワカモ", "character", "Blue Archive")
        pack = export_public_tag_pack(conn, "test", "Test Pack")
        assert len(pack["characters"]) == 1
        char = pack["characters"][0]
        assert char["canonical"] == "狐坂ワカモ"
        assert char["parent_series"] == "Blue Archive"
        assert "ワカモ" in char["aliases"]
        assert "Wakamo" in char["aliases"]

    def test_exports_localizations(self, conn) -> None:
        from core.tag_pack_exporter import export_public_tag_pack
        _seed_alias(conn, "ワカモ", "狐坂ワカモ", "character", "Blue Archive")
        _seed_loc(conn, "狐坂ワカモ", "character", "ko", "코사카 와카모", "Blue Archive")
        _seed_loc(conn, "狐坂ワカモ", "character", "en", "Wakamo", "Blue Archive")
        pack = export_public_tag_pack(conn, "test", "Test Pack")
        char = pack["characters"][0]
        assert char["localizations"]["ko"] == "코사카 와카모"
        assert char["localizations"]["en"] == "Wakamo"

    def test_disabled_aliases_excluded(self, conn) -> None:
        from core.tag_pack_exporter import export_public_tag_pack
        _seed_alias(conn, "OldAlias", "OldCanonical", "character", enabled=0)
        pack = export_public_tag_pack(conn, "test", "Test Pack")
        assert pack["characters"] == []

    def test_version_passed_through(self, conn) -> None:
        from core.tag_pack_exporter import export_public_tag_pack
        pack = export_public_tag_pack(conn, "test", "Test Pack", version="2.0.0")
        assert pack["version"] == "2.0.0"


# ---------------------------------------------------------------------------
# export_dictionary_backup
# ---------------------------------------------------------------------------

class TestExportDictionaryBackup:
    def test_backup_type_field(self, conn) -> None:
        from core.tag_pack_exporter import export_dictionary_backup
        backup = export_dictionary_backup(conn)
        assert backup["backup_type"] == "dictionary_backup"

    def test_includes_all_alias_rows(self, conn) -> None:
        from core.tag_pack_exporter import export_dictionary_backup
        _seed_alias(conn, "ワカモ", "狐坂ワカモ", "character", "Blue Archive")
        backup = export_dictionary_backup(conn)
        assert len(backup["tag_aliases"]) == 1
        assert backup["tag_aliases"][0]["alias"] == "ワカモ"

    def test_includes_external_entries(self, conn) -> None:
        from core.tag_pack_exporter import export_dictionary_backup
        conn.execute(
            "INSERT INTO external_dictionary_entries "
            "(entry_id, source, canonical, tag_type, confidence_score, status, imported_at) "
            "VALUES ('e1', 'danbooru', 'Test', 'character', 0.8, 'staged', '2024-01-01')"
        )
        conn.commit()
        backup = export_dictionary_backup(conn)
        assert len(backup["external_dictionary_entries"]) == 1

    def test_has_exported_at(self, conn) -> None:
        from core.tag_pack_exporter import export_dictionary_backup
        backup = export_dictionary_backup(conn)
        assert "exported_at" in backup


# ---------------------------------------------------------------------------
# save_to_file
# ---------------------------------------------------------------------------

class TestSaveToFile:
    def test_writes_valid_json(self, conn, tmp_path) -> None:
        from core.tag_pack_exporter import export_public_tag_pack, save_to_file
        pack = export_public_tag_pack(conn, "test", "Test")
        out = tmp_path / "out.json"
        save_to_file(pack, out)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["pack_id"] == "test"

    def test_utf8_no_ascii_escape(self, conn, tmp_path) -> None:
        from core.tag_pack_exporter import export_public_tag_pack, save_to_file
        _seed_alias(conn, "ワカモ", "狐坂ワカモ", "character", "Blue Archive")
        pack = export_public_tag_pack(conn, "test", "Test")
        out = tmp_path / "out.json"
        save_to_file(pack, out)
        raw = out.read_text(encoding="utf-8")
        # ensure_ascii=False → 실제 일본어 문자가 그대로 써야 함
        assert "ワカモ" in raw
        assert "\\u" not in raw

    def test_trailing_newline(self, conn, tmp_path) -> None:
        from core.tag_pack_exporter import export_public_tag_pack, save_to_file
        pack = export_public_tag_pack(conn, "test", "Test")
        out = tmp_path / "out.json"
        save_to_file(pack, out)
        assert out.read_text(encoding="utf-8").endswith("\n")
