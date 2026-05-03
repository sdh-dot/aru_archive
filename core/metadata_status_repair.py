"""metadata_sync_status 정합성 복구 도구.

DB 컬럼 ``artwork_groups.metadata_sync_status`` 가 실제 파일 상태
(``artwork_files.metadata_embedded``) 와 어긋난 group 을 찾아 안전하게
``json_only`` 로 복구한다.

배경:
    어떤 경로에서 group 의 ``metadata_sync_status`` 가 ``metadata_missing``
    으로 강등됐지만, 같은 group 의 original 파일은 ``metadata_embedded=1``
    (Aru JSON 임베딩 완료) 로 남아 있는 inconsistent 상태가 관찰됐다.
    이 상태에서는 classifier 가 group 을 silent exclude 해 사용자에게
    "metadata 가 있는데 분류 안 됨" 으로 보인다.

정책:
    - 자동 실행 금지. 호출자가 dry_run 결과를 확인한 뒤에만 execute.
    - ``full`` 또는 ``xmp_write_failed`` 로 격상하지 않는다. XMP write
      성공 여부를 검증하지 않으므로 ``json_only`` 가 가장 보수적이다.
    - file 을 읽거나 ExifTool 을 호출하지 않는다. DB 만 본다.

후보 조건 (AND):
    - artwork_groups.metadata_sync_status = 'metadata_missing'
    - 같은 group 에 file_role='original' AND metadata_embedded=1 인
      artwork_files row 가 1개 이상 존재
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional, TypedDict


REPAIR_TARGET_STATUS: str = "metadata_missing"
REPAIRED_STATUS: str = "json_only"


class RepairCandidate(TypedDict):
    group_id: str
    source_site: str
    artwork_id: str
    artwork_title: str
    metadata_sync_status: str
    has_tags: bool
    has_series: bool
    has_character: bool
    has_classified_copy: bool


class RepairResult(TypedDict):
    dry_run: bool
    candidate_count: int
    updated_count: int
    candidates: list[RepairCandidate]


_FIND_SQL = """
SELECT g.group_id,
       g.source_site,
       g.artwork_id,
       COALESCE(g.artwork_title, '')         AS artwork_title,
       g.metadata_sync_status,
       g.tags_json,
       g.series_tags_json,
       g.character_tags_json,
       (SELECT 1 FROM artwork_files cf
        WHERE cf.group_id = g.group_id
          AND cf.file_role = 'classified_copy'
        LIMIT 1)                              AS has_classified_copy
FROM artwork_groups g
WHERE g.metadata_sync_status = ?
  AND EXISTS (
        SELECT 1
        FROM artwork_files af
        WHERE af.group_id = g.group_id
          AND af.file_role = 'original'
          AND af.metadata_embedded = 1
  )
ORDER BY g.indexed_at DESC
"""


def _is_populated_json(value: Optional[str]) -> bool:
    """JSON 컬럼이 '비어 있지 않은 array' 인지 가볍게 확인한다.

    완전한 파싱은 하지 않는다. NULL / '' / '[]' / '   []   ' 만 빈 것으로 본다.
    실제 데이터에서 character/series 가 빈 list 면 stripped == '[]'.
    """
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return stripped != "[]"


def _row_to_candidate(row) -> RepairCandidate:
    return {
        "group_id":             row["group_id"],
        "source_site":          row["source_site"] or "",
        "artwork_id":           row["artwork_id"] or "",
        "artwork_title":        row["artwork_title"] or "",
        "metadata_sync_status": row["metadata_sync_status"],
        "has_tags":             _is_populated_json(row["tags_json"]),
        "has_series":           _is_populated_json(row["series_tags_json"]),
        "has_character":        _is_populated_json(row["character_tags_json"]),
        "has_classified_copy":  bool(row["has_classified_copy"]),
    }


def find_metadata_status_repair_candidates(
    conn: sqlite3.Connection,
    *,
    limit: Optional[int] = None,
) -> list[RepairCandidate]:
    """``metadata_missing`` 인데 실제로는 Aru JSON 이 박힌 group 후보 목록.

    DB 만 SELECT 한다. 어떠한 UPDATE 도 하지 않는다.
    """
    sql = _FIND_SQL
    params: tuple = (REPAIR_TARGET_STATUS,)
    if limit is not None and limit > 0:
        sql = sql + " LIMIT ?"
        params = (REPAIR_TARGET_STATUS, int(limit))

    cur = conn.execute(sql, params)
    rows = cur.fetchall()

    candidates: list[RepairCandidate] = []
    for row in rows:
        if isinstance(row, sqlite3.Row):
            candidates.append(_row_to_candidate(row))
        else:
            wrapped = {
                "group_id":             row[0],
                "source_site":          row[1],
                "artwork_id":           row[2],
                "artwork_title":        row[3],
                "metadata_sync_status": row[4],
                "tags_json":            row[5],
                "series_tags_json":     row[6],
                "character_tags_json":  row[7],
                "has_classified_copy":  row[8],
            }
            candidates.append(_row_to_candidate(wrapped))
    return candidates


def repair_metadata_sync_status(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = True,
    limit: Optional[int] = None,
) -> RepairResult:
    """후보 group 들의 metadata_sync_status 를 ``json_only`` 로 복구한다.

    dry_run=True (기본값) 면 DB 에 어떠한 변경도 가하지 않는다.
    dry_run=False 일 때만 UPDATE 를 실행하고 commit 한다.

    UPDATE 대상은 find_metadata_status_repair_candidates 가 반환한
    group_id 집합으로 한정된다. WHERE 절에 status = 'metadata_missing'
    가드를 함께 두어 race condition 을 방지한다.
    """
    candidates = find_metadata_status_repair_candidates(conn, limit=limit)
    result: RepairResult = {
        "dry_run":         bool(dry_run),
        "candidate_count": len(candidates),
        "updated_count":   0,
        "candidates":      candidates,
    }
    if dry_run or not candidates:
        return result

    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for cand in candidates:
        cur = conn.execute(
            "UPDATE artwork_groups SET metadata_sync_status = ?, updated_at = ? "
            "WHERE group_id = ? AND metadata_sync_status = ?",
            (REPAIRED_STATUS, now, cand["group_id"], REPAIR_TARGET_STATUS),
        )
        if cur.rowcount:
            updated += int(cur.rowcount)
    conn.commit()
    result["updated_count"] = updated
    return result
