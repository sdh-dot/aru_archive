"""
태그 후보 승인/거부/무시 액션 모듈.

accept_tag_candidate               : 후보 → tag_aliases 등록 (suggested_canonical 사용)
merge_tag_candidate_into_canonical : 후보 → 지정 canonical로 병합
accept_tag_candidate_as_general    : 후보 → general 태그로 처리 (alias = canonical = raw_tag)
reject_tag_candidate               : status='rejected'
ignore_tag_candidate               : status='ignored'

accept 계열 함수는 status='pending'인 후보에만 동작한다.
이미 처리된 후보에 시도하면 ValueError를 발생시킨다.
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


def merge_tag_candidate_into_canonical(
    conn: sqlite3.Connection,
    candidate_id: str,
    target_canonical: str,
    tag_type: str,
    parent_series: str = "",
) -> None:
    """
    후보의 raw_tag를 target_canonical에 alias로 병합한다.

    suggested_canonical 대신 target_canonical을 사용한다.
    status → 'accepted'.
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
    conn.execute(
        """INSERT OR REPLACE INTO tag_aliases
           (alias, canonical, tag_type, parent_series, source,
            confidence_score, enabled, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'candidate_merged', ?, 1, ?, ?)""",
        (
            row["raw_tag"],
            target_canonical,
            tag_type or row["suggested_type"],
            parent_series,
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
    logger.info("태그 후보 병합: %s → %s (%s)", row["raw_tag"], target_canonical, tag_type)


def accept_tag_candidate_as_general(
    conn: sqlite3.Connection,
    candidate_id: str,
) -> None:
    """
    후보를 general 태그로 처리한다.

    alias = canonical = raw_tag, tag_type = 'general'.
    status → 'accepted'.
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
    conn.execute(
        """INSERT OR REPLACE INTO tag_aliases
           (alias, canonical, tag_type, parent_series, source,
            confidence_score, enabled, created_at, updated_at)
           VALUES (?, ?, 'general', '', 'candidate_general', ?, 1, ?, ?)""",
        (
            row["raw_tag"],
            row["raw_tag"],
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
    logger.info("태그 후보 general 처리: %s", row["raw_tag"])


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
