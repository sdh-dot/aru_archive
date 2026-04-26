"""
태그 alias 병합 서비스.

N개의 raw tag를 하나의 canonical로 병합한다.
예: ワカモ(正月) + 浅黄ワカモ + Wakamo → 狐坂ワカモ

merge_alias_into_canonical  : aliases → target canonical 등록
list_existing_canonicals    : DB 내 canonical 목록 조회
find_canonical_alias_conflicts : alias 충돌 감지
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def list_existing_canonicals(
    conn: sqlite3.Connection,
    tag_type: str | None = None,
) -> list[dict]:
    """
    tag_aliases에서 distinct canonical 목록을 반환한다.
    반환: [{"canonical": ..., "tag_type": ..., "parent_series": ...}]
    """
    if tag_type:
        rows = conn.execute(
            "SELECT DISTINCT canonical, tag_type, parent_series "
            "FROM tag_aliases WHERE enabled=1 AND tag_type=? "
            "ORDER BY canonical",
            (tag_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT canonical, tag_type, parent_series "
            "FROM tag_aliases WHERE enabled=1 "
            "ORDER BY tag_type, canonical",
        ).fetchall()
    return [dict(r) for r in rows]


def find_canonical_alias_conflicts(
    conn: sqlite3.Connection,
    aliases: list[str],
    target_canonical: str,
    tag_type: str,
) -> list[dict]:
    """
    aliases 중 이미 다른 canonical에 등록된 항목을 반환한다.
    target_canonical에 이미 등록된 alias는 충돌로 보지 않는다.

    반환: [{"alias": ..., "existing_canonical": ..., "tag_type": ...}]
    """
    conflicts = []
    for alias in aliases:
        rows = conn.execute(
            "SELECT alias, canonical, tag_type, parent_series "
            "FROM tag_aliases "
            "WHERE alias=? AND tag_type=? AND canonical != ? AND enabled=1",
            (alias, tag_type, target_canonical),
        ).fetchall()
        conflicts.extend(
            {
                "alias":              r["alias"],
                "existing_canonical": r["canonical"],
                "tag_type":           r["tag_type"],
                "parent_series":      r["parent_series"],
            }
            for r in rows
        )
    return conflicts


def merge_alias_into_canonical(
    conn: sqlite3.Connection,
    aliases: list[str],
    target_canonical: str,
    tag_type: str,
    parent_series: str = "",
    *,
    source: str = "user_merge",
    confidence_score: float = 1.0,
    overwrite_conflicts: bool = False,
) -> dict:
    """
    aliases를 target_canonical로 병합한다.

    각 alias에 대해 tag_aliases 행을 INSERT OR REPLACE.
    이미 다른 canonical에 등록된 alias는 overwrite_conflicts=True일 때만 덮어쓴다.

    반환:
        {
            "merged":    N,   # 새로 등록/교체된 수
            "skipped":   N,   # 충돌로 건너뛴 수
            "conflicts": [{"alias": ..., "existing_canonical": ...}],
        }
    """
    now = datetime.now(timezone.utc).isoformat()
    merged = 0
    skipped = 0
    conflicts: list[dict] = []

    for alias in aliases:
        existing = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias=? AND tag_type=? AND enabled=1",
            (alias, tag_type),
        ).fetchone()

        if existing and existing["canonical"] != target_canonical:
            conflicts.append(
                {"alias": alias, "existing_canonical": existing["canonical"]}
            )
            if not overwrite_conflicts:
                skipped += 1
                continue

        conn.execute(
            """INSERT OR REPLACE INTO tag_aliases
               (alias, canonical, tag_type, parent_series, source,
                confidence_score, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                alias, target_canonical, tag_type, parent_series,
                source, confidence_score, now, now,
            ),
        )
        merged += 1
        logger.info("alias 병합: %s → %s (%s)", alias, target_canonical, tag_type)

    conn.commit()
    return {"merged": merged, "skipped": skipped, "conflicts": conflicts}
