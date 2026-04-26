"""
core/tag_candidate_actions.py 테스트.
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from db.database import initialize_database


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _insert_candidate(conn, raw_tag="テスト", suggested_type="character",
                       suggested_series="Blue Archive", status="pending",
                       suggested_canonical=None):
    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO tag_candidates
           (candidate_id, raw_tag, suggested_canonical, suggested_type,
            suggested_parent_series, confidence_score, evidence_count,
            source, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 0.70, 1, 'test', ?, ?, ?)""",
        (cid, raw_tag, suggested_canonical, suggested_type,
         suggested_series, status, now, now),
    )
    conn.commit()
    return cid


# ---------------------------------------------------------------------------
# accept
# ---------------------------------------------------------------------------

def test_accept_promotes_to_tag_aliases(conn):
    """승인 시 tag_aliases에 행이 생성된다."""
    from core.tag_candidate_actions import accept_tag_candidate

    cid = _insert_candidate(conn, raw_tag="新キャラ", suggested_canonical="新キャラ")
    accept_tag_candidate(conn, cid)

    alias_row = conn.execute(
        "SELECT * FROM tag_aliases WHERE alias = '新キャラ'"
    ).fetchone()
    assert alias_row is not None
    assert alias_row["tag_type"] == "character"
    assert alias_row["source"] == "candidate_accepted"


def test_accept_sets_status_accepted(conn):
    """승인 후 status='accepted'."""
    from core.tag_candidate_actions import accept_tag_candidate

    cid = _insert_candidate(conn)
    accept_tag_candidate(conn, cid)

    row = conn.execute(
        "SELECT status FROM tag_candidates WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert row["status"] == "accepted"


def test_accept_double_raises_value_error(conn):
    """이미 accepted인 후보에 accept 재시도 시 ValueError."""
    from core.tag_candidate_actions import accept_tag_candidate

    cid = _insert_candidate(conn)
    accept_tag_candidate(conn, cid)

    with pytest.raises(ValueError, match="이미 처리된 후보"):
        accept_tag_candidate(conn, cid)


def test_accept_nonexistent_raises(conn):
    """존재하지 않는 candidate_id → ValueError."""
    from core.tag_candidate_actions import accept_tag_candidate

    with pytest.raises(ValueError, match="후보 없음"):
        accept_tag_candidate(conn, "nonexistent-id")


def test_accept_uses_raw_tag_as_canonical_fallback(conn):
    """suggested_canonical이 None이면 raw_tag를 canonical로 사용한다."""
    from core.tag_candidate_actions import accept_tag_candidate

    cid = _insert_candidate(conn, raw_tag="キャラX", suggested_canonical=None)
    accept_tag_candidate(conn, cid)

    alias_row = conn.execute(
        "SELECT canonical FROM tag_aliases WHERE alias = 'キャラX'"
    ).fetchone()
    assert alias_row["canonical"] == "キャラX"


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------

def test_reject_sets_status(conn):
    """거부 후 status='rejected', tag_aliases에 행 없음."""
    from core.tag_candidate_actions import reject_tag_candidate

    cid = _insert_candidate(conn, raw_tag="不要タグ")
    reject_tag_candidate(conn, cid)

    row = conn.execute(
        "SELECT status FROM tag_candidates WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert row["status"] == "rejected"

    alias = conn.execute(
        "SELECT * FROM tag_aliases WHERE alias = '不要タグ'"
    ).fetchone()
    assert alias is None


def test_reject_nonexistent_raises(conn):
    from core.tag_candidate_actions import reject_tag_candidate

    with pytest.raises(ValueError):
        reject_tag_candidate(conn, "no-such-id")


# ---------------------------------------------------------------------------
# ignore
# ---------------------------------------------------------------------------

def test_ignore_sets_status(conn):
    """무시 후 status='ignored'."""
    from core.tag_candidate_actions import ignore_tag_candidate

    cid = _insert_candidate(conn, raw_tag="無視タグ")
    ignore_tag_candidate(conn, cid)

    row = conn.execute(
        "SELECT status FROM tag_candidates WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert row["status"] == "ignored"


def test_ignore_nonexistent_raises(conn):
    from core.tag_candidate_actions import ignore_tag_candidate

    with pytest.raises(ValueError):
        ignore_tag_candidate(conn, "no-such-id")
