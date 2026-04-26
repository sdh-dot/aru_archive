"""
XMP 메타데이터 재처리 함수.

역할:
  1. XMP 기록 대상 파일 선택 (포맷별 정책)
  2. group 단위 XMP 재시도
  3. 전체 json_only / xmp_write_failed 일괄 재처리

상태 전이:
  json_only + 성공  → full
  json_only + 실패  → xmp_write_failed  (no_metadata_queue에 INSERT하지 않음)
  xmp_write_failed + 성공 → full
  static GIF / BMP original / ZIP original → skipped (json_only 유지)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

# XMP 직접 기록 불가 포맷 (original 전용)
_ORIGINAL_XMP_SKIP_FORMATS = frozenset({"bmp", "gif", "zip"})


def select_xmp_target_file(
    conn: sqlite3.Connection,
    group_id: str,
) -> Optional[dict]:
    """
    XMP 기록 대상 파일을 선택한다.

    우선순위:
      1. managed present 파일 (BMP→PNG, GIF→WebP managed)
      2. original present 파일 (JPEG/PNG/WebP)

    제외:
      - BMP original    (PNG managed 생성 후 그 파일에 기록)
      - static GIF original (sidecar 정책 — json_only 유지)
      - ZIP original    (사이드카 정책)
      - sidecar, classified_copy
    """
    rows = conn.execute(
        """
        SELECT file_id, file_path, file_format, file_role, file_status
        FROM artwork_files
        WHERE group_id = ?
          AND file_status = 'present'
          AND file_role NOT IN ('sidecar', 'classified_copy')
        ORDER BY
          CASE file_role WHEN 'managed' THEN 0 ELSE 1 END,
          page_index
        """,
        (group_id,),
    ).fetchall()

    for row in rows:
        d = dict(row)
        fmt  = (d.get("file_format") or "").lower()
        role = d.get("file_role", "")

        if role == "original" and fmt in _ORIGINAL_XMP_SKIP_FORMATS:
            continue

        return d

    return None


def _read_metadata_for_xmp(
    conn: sqlite3.Connection,
    group_id: str,
) -> dict:
    """artwork_groups 요약 컬럼에서 XMP 기록용 metadata dict를 조합한다."""
    row = conn.execute(
        "SELECT * FROM artwork_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if not row:
        return {}
    r = dict(row)

    def _json_list(key: str) -> list:
        raw = r.get(key)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    return {
        "artwork_title":  r.get("artwork_title") or "",
        "artist_name":    r.get("artist_name") or "",
        "artist_id":      r.get("artist_id") or "",
        "artwork_url":    r.get("artwork_url") or "",
        "artwork_id":     r.get("artwork_id") or "",
        "source_site":    r.get("source_site") or "",
        "description":    r.get("description") or "",
        "tags":           _json_list("tags_json"),
        "series_tags":    _json_list("series_tags_json"),
        "character_tags": _json_list("character_tags_json"),
    }


def retry_xmp_for_group(
    conn: sqlite3.Connection,
    group_id: str,
    exiftool_path: Optional[str],
) -> dict:
    """
    group의 DB 메타데이터를 읽고 XMP 기록을 시도한다.

    Returns:
        {
          "status":  "success" | "no_target" | "no_exiftool" | "failed" | "skipped",
          "message": str,
        }
    """
    if not exiftool_path:
        return {
            "status":  "no_exiftool",
            "message": "ExifTool 경로 없음 — json_only 유지",
        }

    target = select_xmp_target_file(conn, group_id)
    if target is None:
        return {
            "status":  "no_target",
            "message": f"XMP 기록 대상 파일 없음: {group_id}",
        }

    metadata  = _read_metadata_for_xmp(conn, group_id)
    file_path = target["file_path"]

    from core.metadata_writer import XmpWriteError, write_xmp_metadata_with_exiftool

    try:
        ok = write_xmp_metadata_with_exiftool(file_path, metadata, exiftool_path)
    except XmpWriteError as exc:
        _set_sync_status(conn, group_id, "xmp_write_failed")
        logger.warning("XMP 기록 실패 (group=%s): %s", group_id, exc)
        return {"status": "failed", "message": str(exc)}

    if ok:
        _set_sync_status(conn, group_id, "full")
        return {"status": "success", "message": f"XMP 기록 완료: {file_path}"}

    return {
        "status":  "no_exiftool",
        "message": "ExifTool 실행 불가 — json_only 유지",
    }


def retry_xmp_for_all(
    conn: sqlite3.Connection,
    exiftool_path: Optional[str],
    statuses: tuple[str, ...] = ("json_only", "xmp_write_failed"),
    progress_fn: Optional[Callable[[int, int, str, str], None]] = None,
) -> dict:
    """
    json_only / xmp_write_failed 그룹 전체에 XMP 기록을 재시도한다.

    Returns:
        {
          "total":   int,
          "success": int,
          "failed":  int,
          "skipped": int,
          "errors":  list[str],
        }
    """
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT group_id FROM artwork_groups "
        f"WHERE metadata_sync_status IN ({placeholders})",
        statuses,
    ).fetchall()

    group_ids = [row[0] for row in rows]
    return retry_xmp_for_groups(conn, group_ids, exiftool_path, progress_fn=progress_fn)


def retry_xmp_for_groups(
    conn: sqlite3.Connection,
    group_ids: Sequence[str],
    exiftool_path: Optional[str],
    progress_fn: Optional[Callable[[int, int, str, str], None]] = None,
) -> dict:
    """
    선택된 group_id 목록에 대해 XMP 기록을 일괄 재시도한다.

    Returns:
        {
          "total":     int,
          "success":   int,
          "failed":    int,
          "skipped":   int,
          "errors":    list[str],
          "group_ids": list[str],
        }
    """
    ids     = list(dict.fromkeys(group_ids))
    total   = len(ids)
    success = 0
    failed  = 0
    skipped = 0
    errors: list[str] = []

    for index, gid in enumerate(ids, start=1):
        if progress_fn:
            progress_fn(index - 1, total, gid, "running")
        result = retry_xmp_for_group(conn, gid, exiftool_path)
        s      = result["status"]
        if s == "success":
            success += 1
        elif s in ("no_target", "no_exiftool", "skipped"):
            skipped += 1
        else:
            failed += 1
            errors.append(f"{gid[:8]}: {result.get('message', '')}")
        if progress_fn:
            progress_fn(index, total, gid, s)

    return {
        "total":     total,
        "success":   success,
        "failed":    failed,
        "skipped":   skipped,
        "errors":    errors,
        "group_ids": ids,
    }


def _set_sync_status(
    conn: sqlite3.Connection,
    group_id: str,
    status: str,
) -> None:
    conn.execute(
        "UPDATE artwork_groups SET metadata_sync_status=?, updated_at=? WHERE group_id=?",
        (status, datetime.now(timezone.utc).isoformat(), group_id),
    )
    conn.commit()
