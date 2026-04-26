"""
Safebooru source external_dictionary 연동 테스트.

source='safebooru' 항목이 올바르게 import되고,
accept 시 tag_aliases에 source='external:safebooru'로 승격되는지 확인한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from db.database import initialize_database


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _safebooru_entry(
    canonical: str = "Wakamo",
    tag_type: str = "character",
    parent_series: str = "Blue Archive",
    alias: str = "wakamo_(blue_archive)",
    locale: str | None = None,
    display_name: str | None = None,
    confidence: float = 0.60,
) -> dict:
    return {
        "source":            "safebooru",
        "danbooru_tag":      "wakamo_(blue_archive)",
        "danbooru_category": "character",
        "canonical":         canonical,
        "tag_type":          tag_type,
        "parent_series":     parent_series,
        "alias":             alias,
        "locale":            locale,
        "display_name":      display_name,
        "confidence_score":  confidence,
        "evidence_json":     '{"source": "safebooru", "post_count": 5}',
        "imported_at":       datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

class TestSafebooruImport:
    def test_import_safebooru_entry_inserts_staged_row(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries
        result = import_external_entries(conn, [_safebooru_entry()])
        assert result["inserted"] == 1
        rows = list_external_entries(conn)
        assert len(rows) == 1
        assert rows[0]["source"] == "safebooru"
        assert rows[0]["status"] == "staged"

    def test_import_safebooru_sets_correct_fields(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries
        import_external_entries(conn, [_safebooru_entry(canonical="Wakamo", confidence=0.60)])
        row = list_external_entries(conn)[0]
        assert row["canonical"] == "Wakamo"
        assert row["tag_type"] == "character"
        assert row["parent_series"] == "Blue Archive"
        assert abs(row["confidence_score"] - 0.60) < 1e-9

    def test_duplicate_safebooru_import_skipped(self, conn) -> None:
        from core.external_dictionary import import_external_entries
        e = _safebooru_entry()
        import_external_entries(conn, [e])
        result = import_external_entries(conn, [e])
        assert result["inserted"] == 0
        assert result["skipped"] == 1
        total = conn.execute(
            "SELECT COUNT(*) FROM external_dictionary_entries"
        ).fetchone()[0]
        assert total == 1

    def test_safebooru_and_danbooru_same_alias_coexist(self, conn) -> None:
        """source가 다르므로 deterministic ID가 달라 두 항목이 공존한다."""
        from core.external_dictionary import import_external_entries, list_external_entries
        danbooru_e = {
            "source":            "danbooru",
            "danbooru_tag":      "wakamo_(blue_archive)",
            "danbooru_category": "character",
            "canonical":         "Wakamo",
            "tag_type":          "character",
            "parent_series":     "Blue Archive",
            "alias":             "wakamo_(blue_archive)",
            "locale":            None,
            "display_name":      None,
            "confidence_score":  0.75,
            "evidence_json":     None,
            "imported_at":       datetime.now(timezone.utc).isoformat(),
        }
        safebooru_e = _safebooru_entry()
        import_external_entries(conn, [danbooru_e])
        result = import_external_entries(conn, [safebooru_e])
        assert result["inserted"] == 1  # 다른 source → 다른 ID → 삽입됨
        rows = list_external_entries(conn, status=None)
        assert len(rows) == 2
        sources = {r["source"] for r in rows}
        assert sources == {"danbooru", "safebooru"}

    def test_multiple_safebooru_entries(self, conn) -> None:
        from core.external_dictionary import import_external_entries
        entries = [_safebooru_entry(alias=f"tag_{i}", canonical=f"Char{i}") for i in range(4)]
        result = import_external_entries(conn, entries)
        assert result["inserted"] == 4


# ---------------------------------------------------------------------------
# accept → tag_aliases 승격
# ---------------------------------------------------------------------------

class TestSafebooruAccept:
    def test_accept_promotes_to_tag_aliases(self, conn) -> None:
        from core.external_dictionary import (
            import_external_entries, list_external_entries, accept_external_entry,
        )
        import_external_entries(conn, [_safebooru_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        alias_row = conn.execute(
            "SELECT * FROM tag_aliases WHERE alias = 'wakamo_(blue_archive)'"
        ).fetchone()
        assert alias_row is not None
        assert alias_row["canonical"] == "Wakamo"
        assert alias_row["tag_type"] == "character"
        assert alias_row["parent_series"] == "Blue Archive"

    def test_accept_sets_source_external_safebooru(self, conn) -> None:
        from core.external_dictionary import (
            import_external_entries, list_external_entries, accept_external_entry,
        )
        import_external_entries(conn, [_safebooru_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        source_val = conn.execute(
            "SELECT source FROM tag_aliases WHERE alias = 'wakamo_(blue_archive)'"
        ).fetchone()["source"]
        assert source_val == "external:safebooru"

    def test_accept_sets_status_accepted(self, conn) -> None:
        from core.external_dictionary import (
            import_external_entries, list_external_entries, accept_external_entry,
        )
        import_external_entries(conn, [_safebooru_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        status = conn.execute(
            "SELECT status FROM external_dictionary_entries WHERE entry_id = ?", (eid,)
        ).fetchone()["status"]
        assert status == "accepted"

    def test_accept_promotes_localization_when_locale_set(self, conn) -> None:
        from core.external_dictionary import (
            import_external_entries, list_external_entries, accept_external_entry,
        )
        import_external_entries(conn, [
            _safebooru_entry(alias=None, locale="en", display_name="Wakamo")
        ])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        loc_row = conn.execute(
            "SELECT * FROM tag_localizations WHERE canonical='Wakamo' AND locale='en'"
        ).fetchone()
        assert loc_row is not None
        assert loc_row["display_name"] == "Wakamo"
        assert "external:safebooru" in loc_row["source"]

    def test_accept_alias_only_no_localization_needed(self, conn) -> None:
        """locale=None인 safebooru 항목은 tag_aliases만 생성하고 localizations는 건너뛴다."""
        from core.external_dictionary import (
            import_external_entries, list_external_entries, accept_external_entry,
        )
        import_external_entries(conn, [_safebooru_entry(locale=None, display_name=None)])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        alias_count = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        loc_count   = conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]
        assert alias_count == 1
        assert loc_count == 0


# ---------------------------------------------------------------------------
# reject / ignore
# ---------------------------------------------------------------------------

class TestSafebooruRejectIgnore:
    def test_reject_sets_status(self, conn) -> None:
        from core.external_dictionary import (
            import_external_entries, list_external_entries, reject_external_entry,
        )
        import_external_entries(conn, [_safebooru_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        reject_external_entry(conn, eid)
        status = conn.execute(
            "SELECT status FROM external_dictionary_entries WHERE entry_id=?", (eid,)
        ).fetchone()["status"]
        assert status == "rejected"

    def test_ignore_sets_status(self, conn) -> None:
        from core.external_dictionary import (
            import_external_entries, list_external_entries, ignore_external_entry,
        )
        import_external_entries(conn, [_safebooru_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        ignore_external_entry(conn, eid)
        status = conn.execute(
            "SELECT status FROM external_dictionary_entries WHERE entry_id=?", (eid,)
        ).fetchone()["status"]
        assert status == "ignored"
