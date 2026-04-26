"""
core/workflow_summary.build_dictionary_status_summary +
classify_workflow_warnings + compute_preview_risk_level 테스트.
"""
from __future__ import annotations

import pytest

from db.database import initialize_database
from core.workflow_summary import (
    build_dictionary_status_summary,
    classify_workflow_warnings,
    compute_preview_risk_level,
)


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = initialize_database(str(db))
    yield c
    c.close()


def _add_alias(conn, alias, canonical, tag_type="character", parent_series="", enabled=1):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, confidence_score, enabled, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'test', 1.0, ?, ?, ?)",
        (alias, canonical, tag_type, parent_series, enabled, now, now),
    )


def _add_localization(conn, canonical, locale, display_name, enabled=1):
    from datetime import datetime, timezone
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO tag_localizations "
        "(localization_id, canonical, tag_type, parent_series, locale, display_name, "
        " enabled, created_at, updated_at) "
        "VALUES (?, ?, 'character', '', ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), canonical, locale, display_name, enabled, now, now),
    )


def _add_candidate(conn, candidate_id, raw_tag, status="pending", source="pixiv_tags"):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO tag_candidates "
        "(candidate_id, raw_tag, suggested_canonical, suggested_type, status, source, "
        " confidence_score, created_at, updated_at) "
        "VALUES (?, ?, ?, 'character', ?, ?, 0.9, ?, ?)",
        (candidate_id, raw_tag, raw_tag, status, source, now, now),
    )


def _add_external_entry(conn, entry_id, canonical, status="staged"):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO external_dictionary_entries "
        "(entry_id, source, canonical, tag_type, confidence_score, status, "
        " imported_at, updated_at) "
        "VALUES (?, 'danbooru', ?, 'character', 0.8, ?, ?, ?)",
        (entry_id, canonical, status, now, now),
    )


class TestBuildDictionaryStatusSummary:
    def test_empty_db_returns_zeros(self, conn):
        s = build_dictionary_status_summary(conn)
        assert s["tag_aliases_count"] == 0
        assert s["tag_localizations_count"] == 0
        assert s["pending_candidates"] == 0
        assert s["staged_external_entries"] == 0
        assert s["accepted_external_entries"] == 0
        assert s["classification_failure_candidates"] == 0

    def test_alias_counts(self, conn):
        _add_alias(conn, "ワカモ", "狐坂ワカモ", "character")
        _add_alias(conn, "Wakamo", "狐坂ワカモ", "character")
        _add_alias(conn, "BA", "Blue Archive", "series")
        conn.commit()
        s = build_dictionary_status_summary(conn)
        assert s["tag_aliases_count"] == 3
        assert s["character_aliases_count"] == 2
        assert s["series_aliases_count"] == 1

    def test_disabled_aliases_excluded(self, conn):
        _add_alias(conn, "ワカモ",  "狐坂ワカモ", enabled=1)
        _add_alias(conn, "Wakamo", "狐坂ワカモ", enabled=0)
        conn.commit()
        s = build_dictionary_status_summary(conn)
        assert s["tag_aliases_count"] == 1

    def test_localization_count(self, conn):
        _add_localization(conn, "狐坂ワカモ", "ko", "와카모")
        _add_localization(conn, "狐坂ワカモ", "en", "Wakamo")
        conn.commit()
        s = build_dictionary_status_summary(conn)
        assert s["tag_localizations_count"] == 2

    def test_pending_candidates(self, conn):
        _add_candidate(conn, "c1", "ワカモ(正月)", "pending")
        _add_candidate(conn, "c2", "アル",         "accepted")
        _add_candidate(conn, "c3", "ヒフミ",        "pending")
        conn.commit()
        s = build_dictionary_status_summary(conn)
        assert s["pending_candidates"] == 2

    def test_staged_and_accepted_external(self, conn):
        _add_external_entry(conn, "e1", "狐坂ワカモ", "staged")
        _add_external_entry(conn, "e2", "アル",       "staged")
        _add_external_entry(conn, "e3", "ヒフミ",      "accepted")
        conn.commit()
        s = build_dictionary_status_summary(conn)
        assert s["staged_external_entries"] == 2
        assert s["accepted_external_entries"] == 1

    def test_classification_failure_candidates(self, conn):
        _add_candidate(conn, "c1", "unknown_tag", "pending", "classification_failure")
        _add_candidate(conn, "c2", "ワカモ",       "pending", "pixiv_tags")
        conn.commit()
        s = build_dictionary_status_summary(conn)
        assert s["classification_failure_candidates"] == 1


class TestClassifyWorkflowWarnings:
    def test_no_warnings_when_clean(self):
        fs = {"metadata_status_counts": {}, "classifiable": 10, "total_groups": 10}
        ds = {"pending_candidates": 0, "staged_external_entries": 0}
        warnings = classify_workflow_warnings(fs, ds)
        assert warnings == []

    def test_metadata_missing_warning(self):
        fs = {"metadata_status_counts": {"metadata_missing": 5}, "classifiable": 10, "total_groups": 15}
        ds = {"pending_candidates": 0, "staged_external_entries": 0}
        warnings = classify_workflow_warnings(fs, ds)
        codes = [w["code"] for w in warnings]
        assert "metadata_missing" in codes
        w = next(w for w in warnings if w["code"] == "metadata_missing")
        assert w["level"] == "warning"

    def test_pending_candidates_info(self):
        fs = {"metadata_status_counts": {}, "classifiable": 5, "total_groups": 5}
        ds = {"pending_candidates": 3, "staged_external_entries": 0}
        warnings = classify_workflow_warnings(fs, ds)
        codes = [w["code"] for w in warnings]
        assert "pending_candidates" in codes
        w = next(w for w in warnings if w["code"] == "pending_candidates")
        assert w["level"] == "info"

    def test_staged_external_info(self):
        fs = {"metadata_status_counts": {}, "classifiable": 5, "total_groups": 5}
        ds = {"pending_candidates": 0, "staged_external_entries": 2}
        warnings = classify_workflow_warnings(fs, ds)
        codes = [w["code"] for w in warnings]
        assert "staged_external_entries" in codes

    def test_no_classifiable_danger(self):
        fs = {"metadata_status_counts": {"metadata_missing": 10}, "classifiable": 0, "total_groups": 10}
        ds = {"pending_candidates": 0, "staged_external_entries": 0}
        warnings = classify_workflow_warnings(fs, ds)
        codes = [w["code"] for w in warnings]
        assert "no_classifiable" in codes
        w = next(w for w in warnings if w["code"] == "no_classifiable")
        assert w["level"] == "danger"

    def test_no_classifiable_not_triggered_when_total_zero(self):
        fs = {"metadata_status_counts": {}, "classifiable": 0, "total_groups": 0}
        ds = {"pending_candidates": 0, "staged_external_entries": 0}
        warnings = classify_workflow_warnings(fs, ds)
        codes = [w["code"] for w in warnings]
        assert "no_classifiable" not in codes


class TestComputePreviewRiskLevel:
    def test_empty_returns_low(self):
        assert compute_preview_risk_level({"total_groups": 0}) == "low"

    def test_low_risk(self):
        summary = {
            "total_groups": 100,
            "excluded_count": 5,
            "author_fallback_count": 10,
            "conflict_count": 2,
        }
        assert compute_preview_risk_level(summary) == "low"

    def test_high_risk_failure_ratio(self):
        summary = {
            "total_groups": 100,
            "excluded_count": 40,
            "author_fallback_count": 5,
            "conflict_count": 0,
        }
        assert compute_preview_risk_level(summary) == "high"

    def test_high_risk_conflict_ratio(self):
        summary = {
            "total_groups": 100,
            "excluded_count": 0,
            "author_fallback_count": 5,
            "conflict_count": 25,
        }
        assert compute_preview_risk_level(summary) == "high"

    def test_medium_risk_fallback_ratio(self):
        summary = {
            "total_groups": 100,
            "excluded_count": 0,
            "author_fallback_count": 25,
            "conflict_count": 3,
        }
        assert compute_preview_risk_level(summary) == "medium"

    def test_medium_risk_large_total(self):
        summary = {
            "total_groups": 600,
            "excluded_count": 0,
            "author_fallback_count": 10,
            "conflict_count": 0,
        }
        assert compute_preview_risk_level(summary) == "medium"

    def test_medium_risk_conflict_ratio(self):
        summary = {
            "total_groups": 100,
            "excluded_count": 0,
            "author_fallback_count": 10,
            "conflict_count": 10,
        }
        assert compute_preview_risk_level(summary) == "medium"
