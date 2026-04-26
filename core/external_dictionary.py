"""
외부 사전 후보(external_dictionary_entries) 관리 서비스.

핵심 원칙:
  - 외부 데이터는 자동 확정하지 않는다.
  - staged 후보는 사용자 승인 후 tag_aliases / tag_localizations로만 승격한다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _deterministic_entry_id(entry: dict) -> str:
    """
    (source, canonical, tag_type, parent_series, alias, locale) 조합으로
    결정론적 entry_id를 생성한다. 동일 내용은 항상 같은 ID를 갖는다.
    """
    key = "|".join([
        entry.get("source", ""),
        entry.get("canonical", ""),
        entry.get("tag_type", ""),
        entry.get("parent_series", "") or "",
        entry.get("alias", "") or "",
        entry.get("locale", "") or "",
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# confidence_score 계산
# ---------------------------------------------------------------------------

def calculate_external_dictionary_confidence(
    *,
    danbooru_category_match: bool = False,
    parent_series_matched: bool = False,
    pixiv_observation_matched: bool = False,
    alias_relation_found: bool = False,
    implication_found: bool = False,
    localization_found: bool = False,
    short_alias_penalty: bool = False,
    multi_series_penalty: bool = False,
    general_blacklist_penalty: bool = False,
) -> float:
    """
    외부 사전 후보 신뢰도 점수 계산. 반환값: 0.0 ~ 1.0.

    base = 0.20
    +0.35  Danbooru category가 character/copyright로 명확함
    +0.25  parent series가 확인됨
    +0.20  Pixiv observation과 같은 series에서 반복 등장
    +0.15  Danbooru alias 관계 존재
    +0.15  Danbooru implication/related 정보 존재
    +0.10  localization 후보 존재

    -0.30  alias가 너무 짧음 (≤ 3자)
    -0.40  여러 series에서 동시 등장
    -0.50  general blacklist 태그
    """
    score = 0.20
    if danbooru_category_match:
        score += 0.35
    if parent_series_matched:
        score += 0.25
    if pixiv_observation_matched:
        score += 0.20
    if alias_relation_found:
        score += 0.15
    if implication_found:
        score += 0.15
    if localization_found:
        score += 0.10
    if short_alias_penalty:
        score -= 0.30
    if multi_series_penalty:
        score -= 0.40
    if general_blacklist_penalty:
        score -= 0.50
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def import_external_entries(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
) -> dict[str, int]:
    """
    external_dictionary_entries에 staged 상태로 삽입한다.

    중복 (source, alias, canonical, tag_type, parent_series, locale) 은
    INSERT OR IGNORE로 건너뛴다.

    반환: {"inserted": N, "skipped": M}
    """
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0

    for entry in entries:
        entry_id = entry.get("entry_id") or _deterministic_entry_id(entry)
        evidence = entry.get("evidence_json")
        if isinstance(evidence, dict):
            evidence = json.dumps(evidence, ensure_ascii=False)

        try:
            conn.execute(
                """INSERT OR IGNORE INTO external_dictionary_entries
                   (entry_id, source, source_version, source_url,
                    danbooru_tag, danbooru_category,
                    canonical, tag_type, parent_series,
                    alias, locale, display_name,
                    confidence_score, evidence_json,
                    status, imported_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged', ?, ?)""",
                (
                    entry_id,
                    entry.get("source", "unknown"),
                    entry.get("source_version"),
                    entry.get("source_url"),
                    entry.get("danbooru_tag"),
                    entry.get("danbooru_category"),
                    entry["canonical"],
                    entry["tag_type"],
                    entry.get("parent_series", ""),
                    entry.get("alias"),
                    entry.get("locale"),
                    entry.get("display_name"),
                    float(entry.get("confidence_score", 0.0)),
                    evidence,
                    entry.get("imported_at", now),
                    now,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.warning("external_dictionary INSERT 실패: %s — %s", entry.get("alias"), exc)
            skipped += 1

    conn.commit()
    return {"inserted": inserted, "skipped": skipped}


def list_external_entries(
    conn: sqlite3.Connection,
    *,
    status: str | None = "staged",
    source: str | None = None,
    tag_type: str | None = None,
    parent_series: str | None = None,
    min_confidence: float | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    external_dictionary_entries 목록을 조회한다.

    필터:
      status         — staged | accepted | rejected | ignored | None(=all)
      source         — danbooru | None(=all)
      tag_type       — series | character | general | None(=all)
      parent_series  — 정확 일치 | None(=all)
      min_confidence — 최소 신뢰도
    """
    conditions: list[str] = []
    params: list = []

    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if source is not None:
        conditions.append("source = ?")
        params.append(source)
    if tag_type is not None:
        conditions.append("tag_type = ?")
        params.append(tag_type)
    if parent_series is not None:
        conditions.append("parent_series = ?")
        params.append(parent_series)
    if min_confidence is not None:
        conditions.append("confidence_score >= ?")
        params.append(min_confidence)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM external_dictionary_entries {where} "
        f"ORDER BY confidence_score DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def accept_external_entry(conn: sqlite3.Connection, entry_id: str) -> None:
    """
    entry를 승인하고 tag_aliases / tag_localizations로 승격한다.

    승격 정책:
      alias가 있으면  → tag_aliases INSERT OR IGNORE
      locale + display_name 있으면 → tag_localizations INSERT OR IGNORE
    """
    row = conn.execute(
        "SELECT * FROM external_dictionary_entries WHERE entry_id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"entry_id 없음: {entry_id}")
    if row["status"] not in ("staged", "ignored"):
        raise ValueError(f"승인 불가 상태: {row['status']}")

    now = datetime.now(timezone.utc).isoformat()

    # 1. tag_aliases 승격
    if row["alias"]:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO tag_aliases
                   (alias, canonical, tag_type, parent_series,
                    source, confidence_score, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    row["alias"],
                    row["canonical"],
                    row["tag_type"],
                    row["parent_series"] or "",
                    f"external:{row['source']}",
                    row["confidence_score"],
                    now,
                ),
            )
        except Exception as exc:
            logger.error("tag_aliases 승격 실패 (%s): %s", row["alias"], exc)
            raise

    # 2. tag_localizations 승격
    if row["locale"] and row["display_name"]:
        try:
            loc_id = str(uuid.uuid4())
            conn.execute(
                """INSERT OR IGNORE INTO tag_localizations
                   (localization_id, canonical, tag_type, parent_series,
                    locale, display_name, source, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    loc_id,
                    row["canonical"],
                    row["tag_type"],
                    row["parent_series"] or "",
                    row["locale"],
                    row["display_name"],
                    f"external:{row['source']}",
                    now,
                ),
            )
        except Exception as exc:
            logger.error(
                "tag_localizations 승격 실패 (%s/%s): %s",
                row["canonical"], row["locale"], exc,
            )
            raise

    conn.execute(
        "UPDATE external_dictionary_entries SET status='accepted', updated_at=? "
        "WHERE entry_id=?",
        (now, entry_id),
    )
    conn.commit()


def accept_external_entry_with_override_canonical(
    conn: sqlite3.Connection,
    entry_id: str,
    override_canonical: str,
    override_tag_type: str,
    override_parent_series: str = "",
) -> None:
    """
    entry를 승인하되 canonical / tag_type / parent_series를 지정값으로 덮어쓴다.

    기존 canonical 병합 시 사용: entry의 alias를 다른 canonical에 등록한다.
    localization은 별도 locale 정보가 있을 때만 승격한다.
    """
    row = conn.execute(
        "SELECT * FROM external_dictionary_entries WHERE entry_id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"entry_id 없음: {entry_id}")
    if row["status"] not in ("staged", "ignored"):
        raise ValueError(f"승인 불가 상태: {row['status']}")

    now = datetime.now(timezone.utc).isoformat()

    if row["alias"]:
        try:
            conn.execute(
                """INSERT OR REPLACE INTO tag_aliases
                   (alias, canonical, tag_type, parent_series,
                    source, confidence_score, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    row["alias"],
                    override_canonical,
                    override_tag_type,
                    override_parent_series,
                    f"external:{row['source']}:merged",
                    row["confidence_score"],
                    now,
                    now,
                ),
            )
        except Exception as exc:
            logger.error("tag_aliases 승격(override) 실패 (%s): %s", row["alias"], exc)
            raise

    conn.execute(
        "UPDATE external_dictionary_entries SET status='accepted', updated_at=? "
        "WHERE entry_id=?",
        (now, entry_id),
    )
    conn.commit()


def reject_external_entry(conn: sqlite3.Connection, entry_id: str) -> None:
    """entry를 거부 처리한다."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE external_dictionary_entries SET status='rejected', updated_at=? "
        "WHERE entry_id=?",
        (now, entry_id),
    )
    conn.commit()


def ignore_external_entry(conn: sqlite3.Connection, entry_id: str) -> None:
    """entry를 무시 처리한다."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE external_dictionary_entries SET status='ignored', updated_at=? "
        "WHERE entry_id=?",
        (now, entry_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 고수준 import helper
# ---------------------------------------------------------------------------

def import_danbooru_candidates_for_series(
    conn: sqlite3.Connection,
    series_query: str,
    *,
    source_adapter=None,
) -> dict[str, Any]:
    """
    Danbooru에서 series_query 소속 캐릭터 후보를 수집해 staging한다.

    source_adapter가 None이면 DanbooruSourceAdapter()를 기본 사용한다.

    반환:
        {"imported": N, "updated": 0, "skipped": M, "source": "danbooru"}
    """
    if source_adapter is None:
        from core.dictionary_sources.danbooru_source import DanbooruSourceAdapter
        source_adapter = DanbooruSourceAdapter()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # series tag 이름을 snake_case로 변환 (danbooru 검색용)
    series_slug = series_query.lower().replace(" ", "_")

    char_candidates = source_adapter.fetch_character_candidates(series_slug)
    series_candidates = source_adapter.fetch_series_candidates(series_query)

    entries: list[dict] = []
    for c in series_candidates + char_candidates:
        entries.append({**c, "imported_at": now})

    result = import_external_entries(conn, entries)
    return {
        "imported": result["inserted"],
        "updated":  0,
        "skipped":  result["skipped"],
        "source":   "danbooru",
    }
