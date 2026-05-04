"""
character_tags_json / series_tags_json 중복 제거 + classifier 목적지 dedupe 테스트.

core/classifier._build_destinations() 경로 dedupe 검증.
core/tag_pack_loader.seed_tag_pack() conflict 보고 검증.
"""
from __future__ import annotations

import sqlite3
import json
import uuid

import pytest


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

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
            media_type    TEXT,
            kind          TEXT NOT NULL DEFAULT '',
            source        TEXT,
            confidence_score REAL,
            enabled       INTEGER NOT NULL DEFAULT 1,
            created_by    TEXT,
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
            sort_name       TEXT,
            source          TEXT,
            enabled         INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT,
            UNIQUE(canonical, tag_type, parent_series, locale)
        );
    """)
    yield db
    db.close()


# ---------------------------------------------------------------------------
# classifier destination dedupe
# ---------------------------------------------------------------------------

class TestClassifierDestinationDedupe:
    def _build_group_row(self, series_tags, char_tags):
        return {
            "group_id":             str(uuid.uuid4()),
            "series_tags_json":     json.dumps(series_tags),
            "character_tags_json":  json.dumps(char_tags),
            "artist_name":          "TestArtist",
            "tags_json":            "[]",
        }

    def _build_source(self):
        return {
            "file_id":   str(uuid.uuid4()),
            "file_path": "/tmp/test.jpg",
            "file_role": "managed",
        }

    def _cfg(self):
        return {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": True,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
            "folder_locale":                   "canonical",
            "fallback_locale":                 "canonical",
            "enable_localized_folder_names":   False,
        }

    def test_duplicate_char_tags_deduped(self, conn) -> None:
        """character_tags_json에 같은 canonical이 두 번 있으면 목적지 1개만 생성."""
        from core.classifier import _build_destinations
        group = self._build_group_row(
            series_tags=["Blue Archive"],
            char_tags=["狐坂ワカモ", "狐坂ワカモ"],  # 중복
        )
        dests = _build_destinations(
            group, self._build_source(), "/classified", self._cfg()
        )
        paths = [d["dest_path"] for d in dests if "狐坂ワカモ" in d["dest_path"]]
        assert len(paths) == 1

    def test_no_duplicate_series_tags(self, conn) -> None:
        """series_tags_json에 같은 canonical이 중복 없으면 dedupe 동작 투명."""
        from core.classifier import _build_destinations
        group = self._build_group_row(
            series_tags=["Blue Archive"],
            char_tags=["狐坂ワカモ"],
        )
        dests = _build_destinations(
            group, self._build_source(), "/classified", self._cfg()
        )
        assert len(dests) == 1

    def test_duplicate_series_deduped(self, conn) -> None:
        """series_tags_json에 같은 값이 두 번 → 목적지 dedupe."""
        from core.classifier import _build_destinations
        group = self._build_group_row(
            series_tags=["Blue Archive", "Blue Archive"],  # 중복
            char_tags=[],
        )
        dests = _build_destinations(
            group, self._build_source(), "/classified", self._cfg()
        )
        uncategorized_paths = [d["dest_path"] for d in dests if "_uncategorized" in d["dest_path"]]
        assert len(set(uncategorized_paths)) == len(uncategorized_paths)

    def test_two_different_chars_two_dests(self, conn) -> None:
        """다른 canonical 두 개 → 목적지 두 개."""
        from core.classifier import _build_destinations
        group = self._build_group_row(
            series_tags=["Blue Archive"],
            char_tags=["狐坂ワカモ", "陸八魔アル"],
        )
        dests = _build_destinations(
            group, self._build_source(), "/classified", self._cfg()
        )
        assert len(dests) == 2


# ---------------------------------------------------------------------------
# tag_pack_loader conflict report
# ---------------------------------------------------------------------------

class TestTagPackLoaderConflict:
    def _make_pack(self, pack_id="test", series=None, characters=None):
        return {
            "pack_id": pack_id,
            "name":    "Test Pack",
            "version": "1.0.0",
            "series":  series or [],
            "characters": characters or [],
        }

    def test_no_conflict_returns_empty_conflicts(self, conn) -> None:
        from core.tag_pack_loader import seed_tag_pack
        pack = self._make_pack(characters=[{
            "canonical":     "狐坂ワカモ",
            "parent_series": "Blue Archive",
            "aliases":       ["ワカモ"],
            "localizations": {},
        }])
        result = seed_tag_pack(conn, pack)
        assert result["conflicts"] == []
        assert result["character_aliases"] == 1

    def test_conflict_detected_and_skipped(self, conn) -> None:
        from core.tag_pack_loader import seed_tag_pack
        # 먼저 ワカモ → OtherCharacter 등록
        conn.execute(
            "INSERT INTO tag_aliases (alias, canonical, tag_type, parent_series, enabled, created_at) "
            "VALUES ('ワカモ', 'OtherCharacter', 'character', '', 1, '2024-01-01')"
        )
        conn.commit()

        pack = self._make_pack(characters=[{
            "canonical":     "狐坂ワカモ",
            "parent_series": "Blue Archive",
            "aliases":       ["ワカモ"],
            "localizations": {},
        }])
        result = seed_tag_pack(conn, pack)
        assert len(result["conflicts"]) == 1
        conflict = result["conflicts"][0]
        assert conflict["alias"] == "ワカモ"
        assert conflict["existing_canonical"] == "OtherCharacter"
        assert conflict["pack_canonical"] == "狐坂ワカモ"
        # 충돌 alias는 등록되지 않아야 함
        row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias='ワカモ'"
        ).fetchone()
        assert row["canonical"] == "OtherCharacter"

    def test_series_conflict_detected(self, conn) -> None:
        from core.tag_pack_loader import seed_tag_pack
        conn.execute(
            "INSERT INTO tag_aliases (alias, canonical, tag_type, parent_series, enabled, created_at) "
            "VALUES ('BA', 'SomeSeries', 'series', '', 1, '2024-01-01')"
        )
        conn.commit()
        pack = self._make_pack(series=[{
            "canonical":     "Blue Archive",
            "aliases":       ["BA"],
            "localizations": {},
        }])
        result = seed_tag_pack(conn, pack)
        assert any(c["alias"] == "BA" for c in result["conflicts"])

    def test_same_canonical_no_conflict(self, conn) -> None:
        from core.tag_pack_loader import seed_tag_pack
        conn.execute(
            "INSERT INTO tag_aliases (alias, canonical, tag_type, parent_series, enabled, created_at) "
            "VALUES ('ワカモ', '狐坂ワカモ', 'character', 'Blue Archive', 1, '2024-01-01')"
        )
        conn.commit()
        pack = self._make_pack(characters=[{
            "canonical":     "狐坂ワカモ",
            "parent_series": "Blue Archive",
            "aliases":       ["ワカモ", "Wakamo"],
            "localizations": {},
        }])
        result = seed_tag_pack(conn, pack)
        assert result["conflicts"] == []
