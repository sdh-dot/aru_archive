"""
파일명 기반 Pixiv 메타데이터 보강 루프.

흐름:
  file_id → DB 조회 → 파일명에서 artwork_id 추출
  → Pixiv AJAX fetch → AruMetadata 변환
  → 파일에 JSON 기록 → DB(artwork_groups, artwork_files, tags) 갱신

이 모듈은 "외부 소스에서 가져온 메타데이터"와 "앱 내부 DB 상태"를
동기화하는 경계다. Pixiv별 파싱은 adapter에 맡기고, 여기서는 성공/실패
상태 전이와 DB 반영을 한곳에서 관리한다.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.adapters.pixiv import (
    PixivAdapter,
    PixivFetchError,
    PixivNetworkError,
    PixivParseError,
    PixivRestrictedError,
)
from core.pixiv_filename import parse_pixiv_filename
from core.metadata_writer import XmpWriteError, write_aru_metadata, write_xmp_metadata_with_exiftool

logger = logging.getLogger(__name__)


def enrich_file_from_pixiv(
    conn: sqlite3.Connection,
    file_id: str,
    adapter=None,
    exiftool_path: Optional[str] = None,
) -> dict:
    """
    file_id 기준으로 Pixiv 메타데이터를 가져와 파일에 기록하고 DB를 갱신한다.

    adapter: PixivAdapter 인스턴스 (None이면 기본 PixivAdapter 생성)

    Returns dict:
        status      : "success" | "not_found" | "no_artwork_id" | "network_error"
                      | "restricted" | "parse_error" | "embed_failed"
        sync_status : "json_only" | "metadata_write_failed" | None
        message     : 사람이 읽을 수 있는 결과 설명
    """
    if adapter is None:
        adapter = PixivAdapter()

    # 1. DB에서 파일 정보 조회
    row = conn.execute(
        "SELECT file_path, file_format, group_id, page_index "
        "FROM artwork_files WHERE file_id = ?",
        (file_id,),
    ).fetchone()
    if not row:
        return {
            "status": "not_found",
            "sync_status": None,
            "message": f"file_id 없음: {file_id}",
        }

    file_path   = row["file_path"]
    file_format = row["file_format"]
    group_id    = row["group_id"]
    page_index  = row["page_index"] or 0

    # 2. 파일명에서 artwork_id 추출
    parsed = parse_pixiv_filename(file_path)
    if parsed is None:
        return {
            "status": "no_artwork_id",
            "sync_status": None,
            "message": f"파일명에서 artwork_id 추출 불가: {Path(file_path).name}",
        }
    artwork_id = parsed.artwork_id

    # 3. Pixiv AJAX API fetch
    try:
        raw = adapter.fetch_metadata(artwork_id)
    except PixivRestrictedError as exc:
        _set_sync_status(conn, group_id, "metadata_write_failed")
        return {
            "status": "restricted",
            "sync_status": "metadata_write_failed",
            "message": str(exc),
        }
    except PixivNetworkError as exc:
        return {"status": "network_error", "sync_status": None, "message": str(exc)}
    except (PixivParseError, PixivFetchError) as exc:
        return {"status": "parse_error", "sync_status": None, "message": str(exc)}

    # 4. AruMetadata 변환
    try:
        meta = adapter.to_aru_metadata(
            raw,
            page_index=page_index,
            original_filename=Path(file_path).name,
        )
    except Exception as exc:
        logger.error("AruMetadata 변환 실패: %s", exc)
        return {
            "status": "parse_error",
            "sync_status": None,
            "message": f"메타데이터 변환 오류: {exc}",
        }

    # 5. 파일에 메타데이터 쓰기 (AruArchive JSON)
    try:
        write_aru_metadata(file_path, meta.to_dict(), file_format)
        sync_status: Optional[str] = "json_only"
        logger.info("메타데이터 기록 완료: %s → %s", Path(file_path).name, sync_status)
    except Exception as exc:
        logger.error("메타데이터 쓰기 실패: %s → %s", Path(file_path).name, exc)
        _set_sync_status(conn, group_id, "metadata_write_failed")
        _set_file_embedded(conn, file_id, 0)
        return {
            "status": "embed_failed",
            "sync_status": "metadata_write_failed",
            "message": f"파일 메타데이터 쓰기 실패: {exc}",
        }

    # 5-b. XMP 기록 시도 (ExifTool이 설정된 경우)
    if exiftool_path and sync_status == "json_only":
        try:
            ok = write_xmp_metadata_with_exiftool(file_path, meta.to_dict(), exiftool_path)
            if ok:
                sync_status = "full"
        except XmpWriteError as exc:
            logger.warning("XMP 기록 실패: %s → %s", Path(file_path).name, exc)
            sync_status = "xmp_write_failed"

    # 6. DB 갱신
    now = datetime.now(timezone.utc).isoformat()
    _update_group_from_meta(conn, group_id, meta, sync_status, now)
    _set_file_embedded(conn, file_id, 1)
    conn.commit()

    # 7. 태그 관측 기록 + 후보 생성 (실패해도 보강 결과에는 영향 없음)
    try:
        from core.tag_observer import record_tag_observations
        from core.tag_candidate_generator import generate_tag_candidates_for_group

        tags_raw_list = raw.get("tags", {}).get("tags", []) if isinstance(raw, dict) else []
        translated_tags = {
            t.get("tag", ""): (t.get("translation") or {}).get("en", "")
            for t in tags_raw_list
            if t.get("tag") and (t.get("translation") or {}).get("en")
        }
        all_tags = meta.tags + meta.series_tags + meta.character_tags
        record_tag_observations(
            conn,
            source_site="pixiv",
            artwork_id=artwork_id,
            group_id=group_id,
            tags=all_tags,
            translated_tags=translated_tags or None,
            artist_id=meta.artist_id,
        )
        generate_tag_candidates_for_group(conn, group_id)
    except Exception as exc:
        logger.debug("태그 관측 기록 실패 (무시): %s", exc)

    return {
        "status": "success",
        "sync_status": sync_status,
        "message": (
            f"보강 완료: {meta.artwork_title or artwork_id}"
            f" / {meta.artist_name or meta.artist_id}"
            f" (sync={sync_status})"
        ),
    }


# ---------------------------------------------------------------------------
# 내부 DB 헬퍼
# ---------------------------------------------------------------------------

def _set_sync_status(conn: sqlite3.Connection, group_id: str, status: str) -> None:
    conn.execute(
        "UPDATE artwork_groups SET metadata_sync_status = ?, updated_at = ? "
        "WHERE group_id = ?",
        (status, datetime.now(timezone.utc).isoformat(), group_id),
    )
    conn.commit()


def _set_file_embedded(conn: sqlite3.Connection, file_id: str, embedded: int) -> None:
    conn.execute(
        "UPDATE artwork_files SET metadata_embedded = ? WHERE file_id = ?",
        (embedded, file_id),
    )


def _update_group_from_meta(
    conn: sqlite3.Connection,
    group_id: str,
    meta,
    sync_status: str,
    now: str,
) -> None:
    """AruMetadata를 artwork_groups 요약 컬럼과 tags 정규화 테이블에 반영한다."""
    conn.execute(
        """UPDATE artwork_groups SET
            artwork_title        = ?,
            artist_id            = ?,
            artist_name          = ?,
            artist_url           = ?,
            tags_json            = ?,
            series_tags_json     = ?,
            character_tags_json  = ?,
            metadata_sync_status = ?,
            updated_at           = ?
        WHERE group_id = ?""",
        (
            meta.artwork_title,
            meta.artist_id,
            meta.artist_name,
            meta.artist_url,
            json.dumps(meta.tags, ensure_ascii=False),
            json.dumps(meta.series_tags, ensure_ascii=False),
            json.dumps(meta.character_tags, ensure_ascii=False),
            sync_status,
            now,
            group_id,
        ),
    )

    conn.execute("DELETE FROM tags WHERE group_id = ?", (group_id,))
    for tag in meta.tags:
        conn.execute(
            "INSERT INTO tags (group_id, tag, tag_type) VALUES (?, ?, 'general')",
            (group_id, tag),
        )
    for tag in meta.series_tags:
        conn.execute(
            "INSERT INTO tags (group_id, tag, tag_type) VALUES (?, ?, 'series')",
            (group_id, tag),
        )
    for tag in meta.character_tags:
        conn.execute(
            "INSERT INTO tags (group_id, tag, tag_type) VALUES (?, ?, 'character')",
            (group_id, tag),
        )
