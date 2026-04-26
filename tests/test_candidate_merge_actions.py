"""
tag_candidate_actions.py 의 merge/general 확장 테스트.

merge_tag_candidate_into_canonical
accept_tag_candidate_as_general
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE tag_candidates (
            candidate_id            TEXT PRIMARY KEY,
            raw_tag                 TEXT NOT NULL,
            translated_tag          TEXT,
            suggested_canonical     TEXT,
            suggested_type          TEXT NOT NULL,
            suggested_parent_series TEXT NOT NULL DEFAULT '',
            media_type              TEXT,
            confidence_score        REAL NOT NULL DEFAULT 0,
            evidence_count          INTEGER NOT NULL DEFAULT 1,
            source                  TEXT NOT NULL,
            evidence_json           TEXT,
            status                  TEXT NOT NULL DEFAULT 'pending',
            created_at              TEXT NOT NULL,
            updated_at              TEXT,
            UNIQUE (raw_tag, suggested_type, suggested_parent_series)
        );
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
    """)
    yield db
    db.close()


def _make_candidate(db, raw_tag="ワカモ(正月)", suggested_canonical="狐坂ワカモ",
                    suggested_type="character", status="pending"):
    cid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO tag_candidates (candidate_id, raw_tag, suggested_canonical, "
        "suggested_type, confidence_score, source, status, created_at) "
        "VALUES (?, ?, ?, ?, 0.8, 'test', ?, '2024-01-01')",
        (cid, raw_tag, suggested_canonical, suggested_type, status),
    )
    db.commit()
    return cid


# ---------------------------------------------------------------------------
# merge_tag_candidate_into_canonical
# ---------------------------------------------------------------------------

class TestMergeTagCandidateIntoCanonical:
    def test_creates_alias_with_target_canonical(self, conn) -> None:
        from core.tag_candidate_actions import merge_tag_candidate_into_canonical
        cid = _make_candidate(conn)
        merge_tag_candidate_into_canonical(
            conn, cid, "狐坂ワカモ", "character", "Blue Archive"
        )
        row = conn.execute(
            "SELECT canonical, tag_type, parent_series, source "
            "FROM tag_aliases WHERE alias='ワカモ(正月)'"
        ).fetchone()
        assert row is not None
        assert row["canonical"] == "狐坂ワカモ"
        assert row["tag_type"] == "character"
        assert row["parent_series"] == "Blue Archive"

    def test_source_is_candidate_merged(self, conn) -> None:
        from core.tag_candidate_actions import merge_tag_candidate_into_canonical
        cid = _make_candidate(conn)
        merge_tag_candidate_into_canonical(conn, cid, "狐坂ワカモ", "character")
        row = conn.execute(
            "SELECT source FROM tag_aliases WHERE alias='ワカモ(正月)'"
        ).fetchone()
        assert row["source"] == "candidate_merged"

    def test_status_becomes_accepted(self, conn) -> None:
        from core.tag_candidate_actions import merge_tag_candidate_into_canonical
        cid = _make_candidate(conn)
        merge_tag_candidate_into_canonical(conn, cid, "狐坂ワカモ", "character")
        status = conn.execute(
            "SELECT status FROM tag_candidates WHERE candidate_id=?", (cid,)
        ).fetchone()["status"]
        assert status == "accepted"

    def test_raises_for_unknown_id(self, conn) -> None:
        from core.tag_candidate_actions import merge_tag_candidate_into_canonical
        with pytest.raises(ValueError, match="후보 없음"):
            merge_tag_candidate_into_canonical(conn, "nonexistent", "X", "character")

    def test_raises_for_already_processed(self, conn) -> None:
        from core.tag_candidate_actions import merge_tag_candidate_into_canonical
        cid = _make_candidate(conn, status="rejected")
        with pytest.raises(ValueError, match="이미 처리된"):
            merge_tag_candidate_into_canonical(conn, cid, "狐坂ワカモ", "character")

    def test_target_canonical_overrides_suggested(self, conn) -> None:
        from core.tag_candidate_actions import merge_tag_candidate_into_canonical
        cid = _make_candidate(conn, suggested_canonical="틀린캐릭터")
        merge_tag_candidate_into_canonical(
            conn, cid, "올바른캐릭터", "character", "Blue Archive"
        )
        row = conn.execute(
            "SELECT canonical FROM tag_aliases WHERE alias='ワカモ(正月)'"
        ).fetchone()
        assert row["canonical"] == "올바른캐릭터"


# ---------------------------------------------------------------------------
# accept_tag_candidate_as_general
# ---------------------------------------------------------------------------

class TestAcceptTagCandidateAsGeneral:
    def test_creates_general_alias_with_raw_tag_canonical(self, conn) -> None:
        from core.tag_candidate_actions import accept_tag_candidate_as_general
        cid = _make_candidate(conn, raw_tag="킬링파트", suggested_type="character")
        accept_tag_candidate_as_general(conn, cid)
        row = conn.execute(
            "SELECT canonical, tag_type, parent_series FROM tag_aliases WHERE alias='킬링파트'"
        ).fetchone()
        assert row is not None
        assert row["canonical"] == "킬링파트"
        assert row["tag_type"] == "general"
        assert row["parent_series"] == ""

    def test_source_is_candidate_general(self, conn) -> None:
        from core.tag_candidate_actions import accept_tag_candidate_as_general
        cid = _make_candidate(conn, raw_tag="TestTag")
        accept_tag_candidate_as_general(conn, cid)
        row = conn.execute(
            "SELECT source FROM tag_aliases WHERE alias='TestTag'"
        ).fetchone()
        assert row["source"] == "candidate_general"

    def test_status_becomes_accepted(self, conn) -> None:
        from core.tag_candidate_actions import accept_tag_candidate_as_general
        cid = _make_candidate(conn)
        accept_tag_candidate_as_general(conn, cid)
        status = conn.execute(
            "SELECT status FROM tag_candidates WHERE candidate_id=?", (cid,)
        ).fetchone()["status"]
        assert status == "accepted"

    def test_raises_for_unknown_id(self, conn) -> None:
        from core.tag_candidate_actions import accept_tag_candidate_as_general
        with pytest.raises(ValueError, match="후보 없음"):
            accept_tag_candidate_as_general(conn, "nonexistent")

    def test_raises_for_already_processed(self, conn) -> None:
        from core.tag_candidate_actions import accept_tag_candidate_as_general
        cid = _make_candidate(conn, status="accepted")
        with pytest.raises(ValueError, match="이미 처리된"):
            accept_tag_candidate_as_general(conn, cid)
