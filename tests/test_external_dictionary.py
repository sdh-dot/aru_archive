"""
core/external_dictionary.py 테스트.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from db.database import initialize_database


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _entry(
    canonical="Wakamo",
    tag_type="character",
    parent_series="Blue Archive",
    alias="ワカモ(正月)",
    locale=None,
    display_name=None,
    source="danbooru",
    confidence=0.75,
) -> dict:
    return {
        "source":            source,
        "danbooru_tag":      "wakamo_(blue_archive)",
        "danbooru_category": "character",
        "canonical":         canonical,
        "tag_type":          tag_type,
        "parent_series":     parent_series,
        "alias":             alias,
        "locale":            locale,
        "display_name":      display_name,
        "confidence_score":  confidence,
        "evidence_json":     None,
        "imported_at":       datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# calculate_external_dictionary_confidence
# ---------------------------------------------------------------------------

class TestConfidenceCalculation:
    def test_base_score(self) -> None:
        from core.external_dictionary import calculate_external_dictionary_confidence
        score = calculate_external_dictionary_confidence()
        assert abs(score - 0.20) < 1e-9

    def test_all_positive(self) -> None:
        from core.external_dictionary import calculate_external_dictionary_confidence
        score = calculate_external_dictionary_confidence(
            danbooru_category_match=True,
            parent_series_matched=True,
            pixiv_observation_matched=True,
            alias_relation_found=True,
            implication_found=True,
            localization_found=True,
        )
        assert score == 1.0  # clamped

    def test_short_alias_penalty(self) -> None:
        from core.external_dictionary import calculate_external_dictionary_confidence
        score_normal = calculate_external_dictionary_confidence(danbooru_category_match=True)
        score_short  = calculate_external_dictionary_confidence(
            danbooru_category_match=True, short_alias_penalty=True
        )
        assert score_short < score_normal

    def test_general_blacklist_penalty(self) -> None:
        from core.external_dictionary import calculate_external_dictionary_confidence
        score = calculate_external_dictionary_confidence(general_blacklist_penalty=True)
        assert score == 0.0  # 0.20 - 0.50 clamped to 0

    def test_multi_series_penalty(self) -> None:
        from core.external_dictionary import calculate_external_dictionary_confidence
        score = calculate_external_dictionary_confidence(
            danbooru_category_match=True, multi_series_penalty=True
        )
        assert score >= 0.0


# ---------------------------------------------------------------------------
# import_external_entries
# ---------------------------------------------------------------------------

class TestImportExternalEntries:
    def test_inserts_staged_row(self, conn) -> None:
        from core.external_dictionary import import_external_entries
        result = import_external_entries(conn, [_entry()])
        assert result["inserted"] == 1
        assert result["skipped"] == 0

        rows = conn.execute("SELECT * FROM external_dictionary_entries").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "staged"
        assert rows[0]["canonical"] == "Wakamo"

    def test_duplicate_skipped(self, conn) -> None:
        from core.external_dictionary import import_external_entries
        e = _entry()
        import_external_entries(conn, [e])
        result = import_external_entries(conn, [e])
        assert result["inserted"] == 0
        assert result["skipped"] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM external_dictionary_entries"
        ).fetchone()[0] == 1

    def test_multiple_entries(self, conn) -> None:
        from core.external_dictionary import import_external_entries
        entries = [_entry(alias=f"tag_{i}") for i in range(5)]
        result = import_external_entries(conn, entries)
        assert result["inserted"] == 5


# ---------------------------------------------------------------------------
# list_external_entries
# ---------------------------------------------------------------------------

class TestListExternalEntries:
    def test_filter_by_status(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries, reject_external_entry
        import_external_entries(conn, [_entry(alias="tag_a"), _entry(alias="tag_b")])
        rows_all = list_external_entries(conn, status=None)
        assert len(rows_all) == 2

        eid = rows_all[0]["entry_id"]
        reject_external_entry(conn, eid)
        staged = list_external_entries(conn, status="staged")
        rejected = list_external_entries(conn, status="rejected")
        assert len(staged) == 1
        assert len(rejected) == 1

    def test_filter_by_tag_type(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries
        import_external_entries(conn, [
            _entry(alias="s1", tag_type="series", canonical="BA"),
            _entry(alias="c1", tag_type="character", canonical="Wakamo"),
        ])
        chars = list_external_entries(conn, tag_type="character", status=None)
        series = list_external_entries(conn, tag_type="series", status=None)
        assert len(chars) == 1
        assert len(series) == 1

    def test_filter_by_min_confidence(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries
        import_external_entries(conn, [
            _entry(alias="low", confidence=0.3),
            _entry(alias="high", confidence=0.9),
        ])
        high = list_external_entries(conn, min_confidence=0.8, status=None)
        assert len(high) == 1
        assert high[0]["alias"] == "high"

    def test_filter_by_parent_series(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries
        import_external_entries(conn, [
            _entry(alias="w1", parent_series="Blue Archive"),
            _entry(alias="w2", parent_series="Other Game", canonical="Other"),
        ])
        ba = list_external_entries(conn, parent_series="Blue Archive", status=None)
        assert len(ba) == 1


# ---------------------------------------------------------------------------
# accept_external_entry
# ---------------------------------------------------------------------------

class TestAcceptExternalEntry:
    def test_accept_promotes_alias_to_tag_aliases(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries, accept_external_entry
        import_external_entries(conn, [_entry(alias="ワカモ(正月)")])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        alias_row = conn.execute(
            "SELECT * FROM tag_aliases WHERE alias = 'ワカモ(正月)'"
        ).fetchone()
        assert alias_row is not None
        assert alias_row["canonical"] == "Wakamo"
        assert alias_row["tag_type"] == "character"
        assert alias_row["parent_series"] == "Blue Archive"
        assert "external" in alias_row["source"]

    def test_accept_promotes_localization(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries, accept_external_entry
        import_external_entries(conn, [
            _entry(alias=None, locale="ja", display_name="ワカモ")
        ])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        loc_row = conn.execute(
            "SELECT * FROM tag_localizations WHERE canonical = 'Wakamo' AND locale = 'ja'"
        ).fetchone()
        assert loc_row is not None
        assert loc_row["display_name"] == "ワカモ"

    def test_accept_sets_status_accepted(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries, accept_external_entry
        import_external_entries(conn, [_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        accept_external_entry(conn, eid)

        row = conn.execute(
            "SELECT status FROM external_dictionary_entries WHERE entry_id = ?", (eid,)
        ).fetchone()
        assert row["status"] == "accepted"

    def test_accept_nonexistent_raises(self, conn) -> None:
        from core.external_dictionary import accept_external_entry
        with pytest.raises(ValueError):
            accept_external_entry(conn, "nonexistent-id")

    def test_accept_already_rejected_raises(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries, accept_external_entry, reject_external_entry
        import_external_entries(conn, [_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        reject_external_entry(conn, eid)
        with pytest.raises(ValueError):
            accept_external_entry(conn, eid)


# ---------------------------------------------------------------------------
# reject / ignore
# ---------------------------------------------------------------------------

class TestRejectIgnore:
    def test_reject_sets_status(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries, reject_external_entry
        import_external_entries(conn, [_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        reject_external_entry(conn, eid)
        row = conn.execute(
            "SELECT status FROM external_dictionary_entries WHERE entry_id=?", (eid,)
        ).fetchone()
        assert row["status"] == "rejected"

    def test_ignore_sets_status(self, conn) -> None:
        from core.external_dictionary import import_external_entries, list_external_entries, ignore_external_entry
        import_external_entries(conn, [_entry()])
        eid = list_external_entries(conn)[0]["entry_id"]
        ignore_external_entry(conn, eid)
        row = conn.execute(
            "SELECT status FROM external_dictionary_entries WHERE entry_id=?", (eid,)
        ).fetchone()
        assert row["status"] == "ignored"
