"""
기존 tags_json에서 series_tags_json / character_tags_json을 재계산한다.

원본 tags_json은 변경하지 않는다.
series_tags_json / character_tags_json / tags 테이블만 갱신한다.

사용 사례:
  - 일괄 분류 전 태그 재분류 실행 옵션
  - [🏷 태그 재분류] 수동 액션
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def retag_groups_from_existing_tags(
    conn: sqlite3.Connection,
    group_ids: list[str],
) -> dict:
    """
    기존 tags_json을 기반으로 classify_pixiv_tags(conn=conn)를 재실행해
    series_tags_json / character_tags_json / tags table을 갱신한다.

    원본 tags_json은 변경하지 않는다.

    반환:
        {
            "total": N,
            "updated": M,
            "errors": [str, ...]
        }
    """
    from core.tag_classifier import classify_pixiv_tags

    now = datetime.now(timezone.utc).isoformat()
    total = 0
    updated = 0
    errors: list[str] = []

    for group_id in group_ids:
        total += 1
        try:
            row = conn.execute(
                "SELECT tags_json FROM artwork_groups WHERE group_id = ?",
                (group_id,),
            ).fetchone()
            if not row:
                errors.append(f"{group_id[:8]}: not_found")
                continue

            raw_tags: list[str] = []
            try:
                raw_tags = json.loads(row["tags_json"] or "[]")
            except Exception:
                pass

            result = classify_pixiv_tags(raw_tags, conn=conn)

            conn.execute(
                """UPDATE artwork_groups SET
                    series_tags_json    = ?,
                    character_tags_json = ?,
                    updated_at          = ?
                WHERE group_id = ?""",
                (
                    json.dumps(result["series_tags"], ensure_ascii=False),
                    json.dumps(result["character_tags"], ensure_ascii=False),
                    now,
                    group_id,
                ),
            )

            conn.execute(
                "DELETE FROM tags WHERE group_id = ? AND tag_type IN ('series', 'character')",
                (group_id,),
            )
            for tag in result["series_tags"]:
                conn.execute(
                    "INSERT OR IGNORE INTO tags (group_id, tag, tag_type) "
                    "VALUES (?, ?, 'series')",
                    (group_id, tag),
                )
            for tag in result["character_tags"]:
                conn.execute(
                    "INSERT OR IGNORE INTO tags (group_id, tag, tag_type) "
                    "VALUES (?, ?, 'character')",
                    (group_id, tag),
                )

            updated += 1
        except Exception as exc:
            logger.error("retag 실패 (group=%s): %s", group_id, exc)
            errors.append(f"{group_id[:8]}: {exc}")

    conn.commit()
    return {"total": total, "updated": updated, "errors": errors}
