"""
태그 후보 승인/거부/무시 액션 모듈.

accept_tag_candidate : 후보 → tag_aliases 등록, status='accepted'
reject_tag_candidate : status='rejected' (tag_aliases 미등록)
ignore_tag_candidate : status='ignored' (다시 표시하지 않음)

accept는 status='pending'인 후보에만 동작한다.
이미 처리된 후보에 accept를 시도하면 ValueError를 발생시킨다.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def accept_tag_candidate(conn: sqlite3.Connection, candidate_id: str) -> None:
    """
    후보를 승인하여 tag_aliases에 등록하고 status를 'accepted'로 변경한다.
    status='pending'이 아닌 후보는 ValueError를 발생시킨다.
    """
    row = conn.execute(
        "SELECT * FROM tag_candidates WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"후보 없음: {candidate_id}")
    if row["status"] != "pending":
        raise ValueError(
            f"이미 처리된 후보: {candidate_id} (status={row['status']})"
        )

    now = datetime.now(timezone.utc).isoformat()
    canonical = row["suggested_canonical"] or row["raw_tag"]

    conn.execute(
        """INSERT OR REPLACE INTO tag_aliases
           (alias, canonical, tag_type, parent_series, source,
            confidence_score, enabled, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'candidate_accepted', ?, 1, ?, ?)""",
        (
            row["raw_tag"],
            canonical,
            row["suggested_type"],
            row["suggested_parent_series"],
            row["confidence_score"],
            now,
            now,
        ),
    )
    conn.execute(
        "UPDATE tag_candidates SET status='accepted', updated_at=? WHERE candidate_id=?",
        (now, candidate_id),
    )
    conn.commit()
    logger.info("태그 후보 승인: %s → %s", row["raw_tag"], row["suggested_type"])


def reject_tag_candidate(conn: sqlite3.Connection, candidate_id: str) -> None:
    """후보를 거부한다 (tag_aliases에 등록하지 않음)."""
    _set_status(conn, candidate_id, "rejected")


def ignore_tag_candidate(conn: sqlite3.Connection, candidate_id: str) -> None:
    """후보를 무시한다 (다시 표시하지 않음)."""
    _set_status(conn, candidate_id, "ignored")


def _set_status(conn: sqlite3.Connection, candidate_id: str, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    result = conn.execute(
        "UPDATE tag_candidates SET status=?, updated_at=? WHERE candidate_id=?",
        (status, now, candidate_id),
    )
    if result.rowcount == 0:
        raise ValueError(f"후보 없음: {candidate_id}")
    conn.commit()
