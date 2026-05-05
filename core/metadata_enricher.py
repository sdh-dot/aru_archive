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
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from core.adapters.pixiv import (
    PixivAdapter,
    PixivFetchError,
    PixivNetworkError,
    PixivNotFoundError,
    PixivParseError,
    PixivRestrictedError,
)
from core.pixiv_filename import parse_pixiv_filename
from core.metadata_writer import XmpWriteError, write_aru_metadata, write_xmp_metadata_with_exiftool

logger = logging.getLogger(__name__)


_TRUTHY_ENV = {"1", "true", "yes", "on"}

# Statuses that indicate a file was previously registered (has existing metadata).
# When these are the previous status, XMP write uses clear-first to overwrite stale fields.
_EXISTING_REGISTRATION_STATUSES: frozenset[str] = frozenset({
    "full", "json_only", "xmp_write_failed", "metadata_write_failed",
    "out_of_sync", "source_unavailable", "needs_reindex",
    "file_write_failed", "db_update_failed",
})


def _get_previous_status(conn: sqlite3.Connection, group_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    return row["metadata_sync_status"] if row else None


def _is_timing_enabled(config: Optional[dict] = None) -> bool:
    """ARU_ENRICH_TIMING / ARU_ARCHIVE_DEV_MODE / config.developer.enrich_timing 중 하나라도 truthy면 True."""
    if os.environ.get("ARU_ENRICH_TIMING", "").strip().lower() in _TRUTHY_ENV:
        return True
    if os.environ.get("ARU_ARCHIVE_DEV_MODE", "").strip().lower() in _TRUTHY_ENV:
        return True
    if config:
        dev = config.get("developer", {}) or {}
        if dev.get("enabled") and dev.get("enrich_timing"):
            return True
    return False


def fetch_and_store_pixiv_metadata(
    conn: sqlite3.Connection,
    file_id: str,
    adapter=None,
) -> dict:
    """Phase 1: Pixiv API 조회 + DB 저장. 파일 write 없음.

    Returns:
        {
            "status":      "ok" | "error",
            "phase":       "fetch_store",
            "group_id":    str | None,
            "file_id":     str,
            "sync_status": str | None,   # "json_only" on ok
            "message":     str,
            "error":       None | str,   # "not_found" | "no_artwork_id" | "restricted" |
                                         #  "not_found_at_source" | "network_error" | "parse_error"
        }
    """
    if adapter is None:
        adapter = PixivAdapter()

    # 1. DB 조회 (JOIN으로 artwork_id도 함께)
    row = conn.execute(
        "SELECT af.file_path, af.file_format, af.group_id, af.page_index, "
        "ag.artwork_id, ag.metadata_sync_status "
        "FROM artwork_files af "
        "JOIN artwork_groups ag ON af.group_id = ag.group_id "
        "WHERE af.file_id = ?",
        (file_id,),
    ).fetchone()

    if row is None:
        return {
            "status": "error", "phase": "fetch_store",
            "group_id": None, "file_id": file_id,
            "sync_status": None, "message": f"file_id 없음: {file_id}",
            "error": "not_found",
        }

    group_id        = row["group_id"]
    file_path       = row["file_path"]
    page_index      = row["page_index"] or 0
    previous_status = row["metadata_sync_status"]
    file_basename   = Path(file_path).name

    # 2. artwork_id 확보 (DB 우선 → 파일명 파싱 fallback)
    artwork_id = row["artwork_id"] or ""
    if not artwork_id:
        parsed = parse_pixiv_filename(file_path)
        if parsed is None:
            return {
                "status": "error", "phase": "fetch_store",
                "group_id": group_id, "file_id": file_id,
                "sync_status": previous_status,
                "message": f"파일명에서 artwork_id 추출 불가: {file_basename}",
                "error": "no_artwork_id",
            }
        artwork_id = parsed.artwork_id

    # 3. Pixiv API fetch
    try:
        raw = adapter.fetch_metadata(artwork_id)
    except PixivRestrictedError as exc:
        if previous_status != "full":
            _set_sync_status(conn, group_id, "metadata_write_failed")
        sync_s = None if previous_status == "full" else "metadata_write_failed"
        return {
            "status": "error", "phase": "fetch_store",
            "group_id": group_id, "file_id": file_id,
            "sync_status": sync_s, "message": str(exc), "error": "restricted",
        }
    except PixivNotFoundError as exc:
        if previous_status != "full":
            _set_sync_status(conn, group_id, "source_unavailable")
        sync_s = None if previous_status == "full" else "source_unavailable"
        return {
            "status": "error", "phase": "fetch_store",
            "group_id": group_id, "file_id": file_id,
            "sync_status": sync_s, "message": str(exc), "error": "not_found_at_source",
        }
    except PixivNetworkError as exc:
        return {
            "status": "error", "phase": "fetch_store",
            "group_id": group_id, "file_id": file_id,
            "sync_status": previous_status, "message": str(exc), "error": "network_error",
        }
    except (PixivParseError, PixivFetchError) as exc:
        return {
            "status": "error", "phase": "fetch_store",
            "group_id": group_id, "file_id": file_id,
            "sync_status": previous_status, "message": str(exc), "error": "parse_error",
        }

    # 4. AruMetadata 변환
    try:
        meta = adapter.to_aru_metadata(
            raw, page_index=page_index, original_filename=file_basename, conn=conn,
        )
    except Exception as exc:
        logger.error("AruMetadata 변환 실패: %s", exc)
        return {
            "status": "error", "phase": "fetch_store",
            "group_id": group_id, "file_id": file_id,
            "sync_status": previous_status,
            "message": f"메타데이터 변환 오류: {exc}",
            "error": "parse_error",
        }

    # 5. DB 저장 — sync_status = "json_only" (파일 write 없음)
    now = datetime.now(timezone.utc).isoformat()
    _update_group_from_meta(conn, group_id, meta, "json_only", now)
    conn.commit()
    logger.info("Phase 1 완료 (DB 저장): %s → json_only", file_basename)

    # 6. 태그 관측 기록 (raw가 있는 Phase 1에서만 수행)
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
        "status": "ok", "phase": "fetch_store",
        "group_id": group_id, "file_id": file_id,
        "sync_status": "json_only",
        "message": f"Pixiv 조회·DB 저장 완료: {meta.artwork_title or artwork_id}",
        "error": None,
    }


def write_stored_metadata_to_file(
    conn: sqlite3.Connection,
    file_id: str,
    exiftool_path: Optional[str] = None,
    *,
    _override_previous_sync_status: Optional[str] = None,
) -> dict:
    """Phase 2: DB에 저장된 metadata를 파일(UserComment JSON/XMP/XP)에 기록한다.
    Pixiv API 조회 없음.

    Args:
        _override_previous_sync_status: clear-first 판단에 사용할 "이전 상태"를 명시적으로
            전달한다. Phase 1이 DB를 먼저 갱신한 후 Phase 2를 호출하는 wrapper에서, Phase 1
            실행 전에 읽은 원래 sync_status를 전달해 XP clear-first 판단이 올바르게 동작하도록
            한다. None이면 DB에서 읽은 현재 값을 사용한다.

    Returns:
        {
            "status":      "ok" | "error" | "skipped",
            "phase":       "metadata_write",
            "group_id":    str | None,
            "file_id":     str,
            "sync_status": str | None,   # "full" | "json_only" | "xmp_write_failed" on ok
            "message":     str,
            "error":       None | str,
        }
    """
    from core.models import AruMetadata

    # 1. DB 조회 — 파일 + 그룹 메타데이터 전체
    row = conn.execute(
        """SELECT af.file_path, af.file_format, af.group_id, af.page_index,
                  ag.artwork_id, ag.artwork_url, ag.artwork_title, ag.total_pages,
                  ag.artist_id, ag.artist_name, ag.artist_url,
                  ag.tags_json, ag.series_tags_json, ag.character_tags_json,
                  ag.metadata_sync_status, ag.downloaded_at
           FROM artwork_files af
           JOIN artwork_groups ag ON af.group_id = ag.group_id
           WHERE af.file_id = ?""",
        (file_id,),
    ).fetchone()

    if row is None:
        return {
            "status": "error", "phase": "metadata_write",
            "group_id": None, "file_id": file_id,
            "sync_status": None, "message": f"file_id 없음: {file_id}",
            "error": "not_found",
        }

    group_id        = row["group_id"]
    file_path       = row["file_path"]
    file_format     = row["file_format"]
    page_index      = row["page_index"] or 0
    previous_status = row["metadata_sync_status"]
    file_basename   = Path(file_path).name

    # _override_previous_sync_status: wrapper가 Phase 1 실행 전에 읽은 원래 상태를 전달.
    # clear-first 판단은 "Phase 1 실행 전" 상태를 기준으로 해야 한다.
    if _override_previous_sync_status is not None:
        previous_status = _override_previous_sync_status

    # 2. DB metadata 검증 (artwork_id가 있어야 write 가능)
    if not row["artwork_id"]:
        return {
            "status": "skipped", "phase": "metadata_write",
            "group_id": group_id, "file_id": file_id,
            "sync_status": previous_status,
            "message": "DB에 artwork_id 없음 — Phase 1 먼저 실행 필요",
            "error": "metadata_missing",
        }

    # 3. 파일 존재 확인
    if not Path(file_path).exists():
        _set_file_missing(conn, file_id)
        conn.commit()
        return {
            "status": "error", "phase": "metadata_write",
            "group_id": group_id, "file_id": file_id,
            "sync_status": previous_status,
            "message": f"파일 없음: {file_basename}",
            "error": "missing_file",
        }

    # 4. DB → AruMetadata 재구성 (Pixiv API 호출 없음)
    meta = AruMetadata(
        source_site="pixiv",
        artwork_id=row["artwork_id"] or "",
        artwork_url=row["artwork_url"] or "",
        artwork_title=row["artwork_title"] or "",
        page_index=page_index,
        total_pages=row["total_pages"] or 1,
        original_filename=file_basename,
        artist_id=row["artist_id"] or "",
        artist_name=row["artist_name"] or "",
        artist_url=row["artist_url"] or "",
        tags=json.loads(row["tags_json"] or "[]"),
        character_tags=json.loads(row["character_tags_json"] or "[]"),
        series_tags=json.loads(row["series_tags_json"] or "[]"),
        downloaded_at=row["downloaded_at"] or "",
    )

    # 5. clear-first 정책 — 기존 등록 상태에서 재기록 시 stale XP 필드 제거
    _clear_first = previous_status in _EXISTING_REGISTRATION_STATUSES

    # 6. UserComment JSON / iTXt write
    try:
        write_aru_metadata(file_path, meta.to_dict(), file_format)
        sync_status: Optional[str] = "json_only"
        logger.info("JSON 메타데이터 기록 완료: %s", file_basename)
    except Exception as exc:
        logger.error("메타데이터 쓰기 실패: %s → %s", file_basename, exc)
        _set_sync_status(conn, group_id, "metadata_write_failed")
        _set_file_embedded(conn, file_id, 0)
        return {
            "status": "error", "phase": "metadata_write",
            "group_id": group_id, "file_id": file_id,
            "sync_status": "metadata_write_failed",
            "message": f"파일 메타데이터 쓰기 실패: {exc}",
            "error": "embed_failed",
        }

    # 7. XMP/XP 기록 시도 (ExifTool 설정 시)
    if exiftool_path and sync_status == "json_only":
        try:
            ok = write_xmp_metadata_with_exiftool(
                file_path, meta.to_dict(), exiftool_path,
                clear_windows_xp_fields_before_write=_clear_first,
            )
            if ok:
                sync_status = "full"
        except XmpWriteError as exc:
            logger.warning("XMP 기록 실패: %s → %s", file_basename, exc)
            sync_status = "xmp_write_failed"

    logger.info("Phase 2 완료 (파일 기록): %s → %s", file_basename, sync_status)

    # 8. DB 갱신 — 단일 트랜잭션
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE artwork_groups SET metadata_sync_status = ?, updated_at = ? WHERE group_id = ?",
        (sync_status, now, group_id),
    )
    conn.execute(
        "UPDATE artwork_files SET metadata_embedded = 1 WHERE file_id = ?",
        (file_id,),
    )
    conn.commit()

    return {
        "status": "ok", "phase": "metadata_write",
        "group_id": group_id, "file_id": file_id,
        "sync_status": sync_status,
        "message": (
            f"메타데이터 기록 완료: {meta.artwork_title or row['artwork_id']}"
            f" / {meta.artist_name or meta.artist_id}"
            f" (sync={sync_status})"
        ),
        "error": None,
    }


def enrich_file_from_pixiv(
    conn: sqlite3.Connection,
    file_id: str,
    adapter=None,
    exiftool_path: Optional[str] = None,
) -> dict:
    """공개 호환 wrapper: Phase 1 + Phase 2를 순서대로 실행한다.

    기존 caller API와 완전 호환.
    신규 코드는 fetch_and_store_pixiv_metadata / write_stored_metadata_to_file을 직접 호출 권장.

    Returns dict:
        status      : "success" | "not_found" | "no_artwork_id" | "network_error"
                      | "restricted" | "parse_error" | "embed_failed" | "missing_file"
                      | "not_found_at_source"
        sync_status : "json_only" | "full" | "xmp_write_failed" | "metadata_write_failed" | None
        message     : 사람이 읽을 수 있는 결과 설명
        timings     : dict (ARU_ENRICH_TIMING 활성 시에만)
    """
    _timing_on = _is_timing_enabled()
    _t0 = time.perf_counter() if _timing_on else 0.0

    # 기존 동작 호환: 파일명 파싱 pre-check + 원래 sync_status 선취.
    #
    # 두 가지 목적을 위해 Phase 1 실행 전에 DB를 한 번 읽는다:
    # 1) 파일명 파싱 실패 시 기존과 동일하게 no_artwork_id 반환 (Phase 1은 DB artwork_id 우선이므로)
    # 2) Phase 1이 DB를 json_only로 갱신하기 전의 원래 sync_status를 기억해,
    #    Phase 2의 clear-first 판단이 "Phase 1 실행 전" 상태를 기준으로 하도록 한다.
    _pre_row = conn.execute(
        "SELECT af.file_path, ag.metadata_sync_status "
        "FROM artwork_files af "
        "JOIN artwork_groups ag ON af.group_id = ag.group_id "
        "WHERE af.file_id = ?",
        (file_id,),
    ).fetchone()
    _original_sync_status: Optional[str] = None
    if _pre_row is not None:
        _original_sync_status = _pre_row["metadata_sync_status"]
        _parsed = parse_pixiv_filename(_pre_row["file_path"])
        if _parsed is None:
            result: dict = {
                "status":      "no_artwork_id",
                "sync_status": None,
                "message":     f"파일명에서 artwork_id 추출 불가: {Path(_pre_row['file_path']).name}",
            }
            if _timing_on:
                _t1_early = time.perf_counter()
                result["timings"] = {
                    "fetch_store":    _t1_early - _t0,
                    "metadata_write": 0.0,
                    "total":          _t1_early - _t0,
                }
            return result

    # Phase 1: Pixiv 조회 + DB 저장
    r1 = fetch_and_store_pixiv_metadata(conn, file_id, adapter=adapter)
    _t1 = time.perf_counter() if _timing_on else 0.0

    if r1["status"] != "ok":
        # Phase 1 실패 → 기존 호환 status 코드로 매핑
        # network_error는 기존 동작상 sync_status=None을 반환한다.
        _error_to_status: dict[str, str] = {
            "not_found":           "not_found",
            "no_artwork_id":       "no_artwork_id",
            "restricted":          "restricted",
            "not_found_at_source": "not_found_at_source",
            "network_error":       "network_error",
            "parse_error":         "parse_error",
        }
        old_status = _error_to_status.get(r1.get("error") or "", r1.get("error") or "error")
        # network_error / parse_error는 기존 동작상 sync_status=None
        _err = r1.get("error") or ""
        _sync = None if _err in ("network_error", "parse_error") else r1["sync_status"]
        result = {
            "status":      old_status,
            "sync_status": _sync,
            "message":     r1["message"],
        }
        if _timing_on:
            result["timings"] = {
                "fetch_store":    _t1 - _t0,
                "metadata_write": 0.0,
                "total":          _t1 - _t0,
            }
        return result

    # Phase 2: 파일 메타데이터 기록
    # _original_sync_status: Phase 1 실행 전 상태를 전달해 clear-first 판단을 올바르게 한다.
    r2 = write_stored_metadata_to_file(
        conn, file_id, exiftool_path=exiftool_path,
        _override_previous_sync_status=_original_sync_status,
    )
    _t2 = time.perf_counter() if _timing_on else 0.0

    if r2["status"] != "ok":
        _error_to_status2: dict[str, str] = {
            "embed_failed": "embed_failed",
            "missing_file": "missing_file",
            "not_found":    "not_found",
        }
        old_status2 = _error_to_status2.get(r2.get("error") or "", "embed_failed")
        result = {
            "status":      old_status2,
            "sync_status": r2["sync_status"],
            "message":     r2["message"],
        }
        if _timing_on:
            result["timings"] = {
                "fetch_store":    _t1 - _t0,
                "metadata_write": _t2 - _t1,
                "total":          _t2 - _t0,
            }
        return result

    result = {
        "status":      "success",
        "sync_status": r2["sync_status"],
        "message":     r2["message"],
    }
    if _timing_on:
        result["timings"] = {
            "fetch_store":    _t1 - _t0,
            "metadata_write": _t2 - _t1,
            "total":          _t2 - _t0,
        }
    return result


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
    """Update metadata_embedded flag and commit immediately.

    The explicit commit removes a latent dependency on caller-side trailing
    commits — the embed_failed code path needs metadata_embedded=0 to be
    persisted even if the connection is closed before the caller can commit.
    Repeating commits in the success path is a no-op (no-op on already-clean
    transactions in SQLite Python).
    """
    conn.execute(
        "UPDATE artwork_files SET metadata_embedded = ? WHERE file_id = ?",
        (embedded, file_id),
    )
    conn.commit()


def _set_file_missing(conn: sqlite3.Connection, file_id: str) -> None:
    conn.execute(
        "UPDATE artwork_files SET file_status = 'missing' WHERE file_id = ?",
        (file_id,),
    )
    conn.commit()


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
            raw_tags_json        = ?,
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
            json.dumps(meta.raw_tags, ensure_ascii=False) if meta.raw_tags else None,
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


# ---------------------------------------------------------------------------
# 보강 큐 빌더
# ---------------------------------------------------------------------------

EnrichMode = Literal["missing_only", "all_pixiv"]

_VALID_MODES: frozenset[str] = frozenset({"missing_only", "all_pixiv"})


def build_enrichment_queue(
    conn: sqlite3.Connection,
    *,
    mode: EnrichMode = "missing_only",
) -> list[str]:
    """모드에 따라 enrichment 대상 file_id 리스트를 반환한다.

    공통 조건:
    - artwork_id가 NULL/"" 아님
    - file_role = 'original'
    - ORDER BY ag.indexed_at DESC

    missing_only:
        metadata_sync_status = 'metadata_missing'

    all_pixiv:
        metadata_sync_status IN (
            'metadata_missing', 'metadata_write_failed', 'xmp_write_failed'
        )

    두 모드 모두 'full' / 'json_only' / 'source_unavailable' / 'pending' 제외.

    'json_only' 가 all_pixiv 에서 제외되는 이유:
        json_only 는 이미 파일에 Aru JSON 이 임베딩된 정상 상태다.
        이 그룹을 다시 enrich 하면 Pixiv API 의 raw tags 를 현재 alias 로
        재분류한 결과로 series_tags_json / character_tags_json 을 덮어쓰게
        되는데, 사용자가 한국어 alias 위주로 설정한 경우 일본어 raw 와
        매칭 실패해 series/character 가 빈 list 로 사라질 수 있다.
        '전체 보강' 의도는 실패/누락 상태 회복이지 정상 상태 덮어쓰기가
        아니므로 json_only 는 보호한다.

    Raises:
        ValueError: invalid mode.
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"invalid enrichment mode: {mode!r}. "
            f"expected one of {sorted(_VALID_MODES)}"
        )

    if mode == "missing_only":
        status_filter = "ag.metadata_sync_status = 'metadata_missing'"
    else:  # all_pixiv
        status_filter = (
            "ag.metadata_sync_status IN ("
            "'metadata_missing', 'metadata_write_failed', 'xmp_write_failed'"
            ")"
        )

    sql = (
        "SELECT af.file_id, af.file_path FROM artwork_files af "
        "JOIN artwork_groups ag ON ag.group_id = af.group_id "
        f"WHERE {status_filter} "
        "AND (ag.artwork_id IS NOT NULL AND ag.artwork_id != '') "
        "AND af.file_role = 'original' "
        "AND af.file_status = 'present' "
        "ORDER BY ag.indexed_at DESC"
    )
    rows = conn.execute(sql).fetchall()
    return [r["file_id"] for r in rows if Path(r["file_path"]).exists()]
