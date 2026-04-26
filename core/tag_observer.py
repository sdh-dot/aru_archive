"""
Pixiv 태그 관측 기록 모듈.

Pixiv 메타데이터 보강 시 각 raw_tag를 tag_observations 테이블에 기록한다.
동일 (source_site, artwork_id, raw_tag) 조합은 INSERT OR IGNORE로 중복 삽입하지 않는다.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def record_tag_observations(
    conn: sqlite3.Connection,
    source_site: str,
    artwork_id: str,
    group_id: str | None,
    tags: list[str],
    translated_tags: dict[str, str] | None = None,
    artist_id: str | None = None,
) -> None:
    """
    tags 목록을 tag_observations에 기록한다.
    동일 (source_site, artwork_id, raw_tag) 행은 중복 삽입하지 않는다.

    translated_tags: {raw_tag: translated_tag} 매핑 (옵션)
    """
    now = datetime.now(timezone.utc).isoformat()
    co_tags_json = json.dumps(tags, ensure_ascii=False)
    for tag in tags:
        translated_tag = (translated_tags or {}).get(tag)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO tag_observations
                   (observation_id, source_site, artwork_id, group_id,
                    raw_tag, translated_tag, co_tags_json, artist_id, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    source_site,
                    artwork_id,
                    group_id,
                    tag,
                    translated_tag,
                    co_tags_json,
                    artist_id,
                    now,
                ),
            )
        except Exception as exc:
            logger.debug("tag_observations 삽입 실패 (무시): %s — %s", tag, exc)
