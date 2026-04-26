"""
CoreWorker: Pixiv 아트워크 다운로드 및 DB 기록 파이프라인.

NativeHost에서 직접 호출하거나 서브프로세스로 spawn된다.
  python -m core.worker --json-stdin

진입점:
  save_pixiv_artwork(conn, config, artwork_id, *, page_url, cookies, preload_data)
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def save_pixiv_artwork(
    conn,
    config: dict,
    artwork_id: str,
    *,
    page_url: str = "",
    cookies: dict | None = None,
    preload_data: dict | None = None,
) -> dict:
    """
    Pixiv 아트워크를 Inbox에 저장하고 DB에 기록한다.

    Returns:
        {job_id, saved, total, failed, results}
    Raises:
        LockAcquisitionError — 이미 동일 작업 진행 중
    """
    from core.constants import make_save_lock_key
    from core.locks import locked_operation

    logger.info("save_pixiv_artwork started: artwork_id=%s", artwork_id)
    lock_key = make_save_lock_key("pixiv", artwork_id)
    with locked_operation(conn, lock_key, "native_host", 120):
        return _run_pipeline(
            conn, config, artwork_id,
            page_url=page_url, cookies=cookies, preload_data=preload_data,
        )


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def _run_pipeline(
    conn,
    config: dict,
    artwork_id: str,
    *,
    page_url: str,
    cookies: dict | None,
    preload_data: dict | None,
) -> dict:
    from core.adapters.pixiv import PixivAdapter, PixivFetchError
    from core.metadata_writer import write_aru_metadata
    from core.models import AruMetadata
    from core.pixiv_downloader import download_pixiv_image

    adapter   = PixivAdapter()
    now       = datetime.now(timezone.utc).isoformat()
    job_id    = str(uuid.uuid4())
    inbox_dir = config.get("inbox_dir") or str(Path(config.get("data_dir", "")) / "Inbox")
    data_dir  = config.get("data_dir", "")

    # 1. Fetch metadata
    raw = None
    try:
        raw  = adapter.fetch_metadata(artwork_id)
        meta = adapter.to_aru_metadata(raw)
    except PixivFetchError as exc:
        logger.warning("Pixiv API fetch 실패, preload_data fallback 시도: %s", exc)
        if preload_data:
            meta = _meta_from_preload(artwork_id, preload_data, page_url)
        else:
            raise

    # 2. Fetch page image URLs
    try:
        pages_raw = _fetch_pages(artwork_id, cookies=cookies)
    except Exception as exc:
        logger.warning("페이지 URL 조회 실패: %s", exc)
        pages_raw = []

    targets     = adapter.build_download_targets(meta, pages_raw) if pages_raw else []
    total_pages = len(targets) or meta.total_pages

    # 3. Insert save_jobs (이후 예외 발생 시 반드시 failed로 갱신)
    conn.execute(
        """INSERT INTO save_jobs
            (job_id, source_site, artwork_id, status, total_pages,
             saved_pages, failed_pages, classify_mode, started_at)
           VALUES (?, 'pixiv', ?, 'running', ?, 0, 0, ?, ?)""",
        (job_id, artwork_id, total_pages,
         config.get("classify_mode", "save_only"), now),
    )
    conn.commit()
    job_inserted = True  # noqa: F841 — flag for the except block below

    try:
        # 4. Create/update artwork_group
        group_id = _upsert_artwork_group(conn, meta, total_pages, now)
        conn.execute("UPDATE save_jobs SET group_id=? WHERE job_id=?", (group_id, job_id))
        conn.commit()

        # 5. Download pages
        saved   = 0
        failed  = 0
        results = []

        for target in targets:
            pi       = target["page_index"]
            url      = target["url"]
            filename = target["filename"]
            ext      = Path(filename).suffix.lstrip(".")

            conn.execute(
                "INSERT INTO job_pages (job_id, page_index, url, filename, status)"
                " VALUES (?, ?, ?, ?, 'pending')",
                (job_id, pi, url, filename),
            )
            conn.commit()
            jp_row = conn.execute("SELECT last_insert_rowid()").fetchone()
            jp_id  = jp_row[0] if jp_row else None

            dest_path = Path(inbox_dir) / filename
            try:
                conn.execute("UPDATE job_pages SET status='downloading' WHERE id=?", (jp_id,))
                conn.commit()

                referer  = f"https://www.pixiv.net/artworks/{artwork_id}"
                bytes_dl = download_pixiv_image(url, dest_path, referer=referer, cookies=cookies)
                logger.info("download OK page %d: %s (%d bytes)", pi, filename, bytes_dl)

                page_meta = AruMetadata(
                    source_site       = "pixiv",
                    artwork_id        = artwork_id,
                    artwork_url       = meta.artwork_url,
                    artwork_title     = meta.artwork_title,
                    page_index        = pi,
                    total_pages       = total_pages,
                    original_filename = filename,
                    artist_id         = meta.artist_id,
                    artist_name       = meta.artist_name,
                    artist_url        = meta.artist_url,
                    tags              = meta.tags,
                    character_tags    = meta.character_tags,
                    series_tags       = meta.series_tags,
                    is_ugoira         = meta.is_ugoira,
                    downloaded_at     = now,
                    _provenance       = meta._provenance,
                )

                sync_status = "json_only"
                try:
                    write_aru_metadata(str(dest_path), page_meta.to_dict(), ext)
                except Exception as we:
                    logger.warning("메타데이터 임베딩 실패: %s", we)
                    sync_status = "metadata_write_failed"

                # XMP 기록 시도 (ExifTool이 탐색된 경우, 포맷 적합 시만)
                if sync_status == "json_only" and ext not in ("gif", "bmp", "zip"):
                    from core.exiftool_resolver import resolve_exiftool_path
                    exiftool_path = resolve_exiftool_path(config)
                    if exiftool_path:
                        from core.metadata_writer import (
                            XmpWriteError, write_xmp_metadata_with_exiftool,
                        )
                        try:
                            ok = write_xmp_metadata_with_exiftool(
                                str(dest_path), page_meta.to_dict(), exiftool_path
                            )
                            if ok:
                                sync_status = "full"
                        except XmpWriteError as xmp_exc:
                            logger.warning("XMP 기록 실패: %s → %s", dest_path.name, xmp_exc)
                            sync_status = "xmp_write_failed"

                file_id = _register_file(conn, group_id, pi, dest_path, ext, sync_status, now)

                conn.execute(
                    "UPDATE job_pages SET status='saved', file_id=?, download_bytes=?, saved_at=?"
                    " WHERE id=?",
                    (file_id, bytes_dl, datetime.now(timezone.utc).isoformat(), jp_id),
                )
                conn.commit()
                saved += 1
                results.append({"page_index": pi, "status": "saved", "filename": filename})

            except Exception as exc:
                logger.error("페이지 %d 다운로드 실패: %s", pi, exc)
                conn.execute(
                    "UPDATE job_pages SET status='failed', error_message=? WHERE id=?",
                    (str(exc), jp_id),
                )
                conn.commit()
                failed += 1
                results.append({"page_index": pi, "status": "failed", "error": str(exc)})

        # 6. Update artwork_group status
        ms = "json_only" if saved > 0 else "pending"
        conn.execute(
            "UPDATE artwork_groups SET metadata_sync_status=?, updated_at=? WHERE group_id=?",
            (ms, datetime.now(timezone.utc).isoformat(), group_id),
        )
        conn.commit()

        # 7. Sync tags
        if raw is not None:
            _sync_tags(conn, group_id, meta)

        # 8. Tag observations + candidates (best-effort)
        try:
            from core.tag_observer import record_tag_observations
            from core.tag_candidate_generator import generate_tag_candidates_for_group
            tags_raw_list = raw.get("tags", {}).get("tags", []) if raw else []
            translated_tags = {
                t.get("tag", ""): (t.get("translation") or {}).get("en", "")
                for t in tags_raw_list
                if t.get("tag") and (t.get("translation") or {}).get("en")
            }
            all_tags = meta.tags + meta.series_tags + meta.character_tags
            record_tag_observations(
                conn,
                source_site     = "pixiv",
                artwork_id      = artwork_id,
                group_id        = group_id,
                tags            = all_tags,
                translated_tags = translated_tags or None,
                artist_id       = meta.artist_id,
            )
            generate_tag_candidates_for_group(conn, group_id)
        except Exception as exc:
            logger.debug("태그 관측 실패 (무시): %s", exc)

        # 9. Thumbnail (best-effort)
        if saved > 0 and data_dir:
            try:
                _generate_cover_thumbnail(conn, group_id, data_dir)
            except Exception as exc:
                logger.warning("thumbnail 생성 실패 (무시): %s", exc)

        # 10. Finalize job
        if failed == 0 and saved > 0:
            final_status = "completed"
        elif saved > 0:
            final_status = "partial"
        else:
            final_status = "failed"

        conn.execute(
            "UPDATE save_jobs"
            " SET status=?, saved_pages=?, failed_pages=?, completed_at=?"
            " WHERE job_id=?",
            (final_status, saved, failed, datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
        logger.info(
            "save_pixiv_artwork %s: artwork_id=%s saved=%d failed=%d",
            final_status, artwork_id, saved, failed,
        )
        return {
            "job_id":  job_id,
            "saved":   saved,
            "total":   total_pages,
            "failed":  failed,
            "results": results,
        }

    except Exception:
        # 예기치 않은 예외: save_jobs를 반드시 failed로 마킹
        try:
            conn.execute(
                "UPDATE save_jobs SET status='failed', completed_at=? WHERE job_id=?",
                (datetime.now(timezone.utc).isoformat(), job_id),
            )
            conn.commit()
        except Exception as db_exc:
            logger.error("save_jobs 실패 상태 업데이트 오류: %s", db_exc)
        logger.exception("save_pixiv_artwork failed (unexpected): artwork_id=%s", artwork_id)
        raise


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _fetch_pages(artwork_id: str, *, cookies: dict | None) -> list[dict]:
    """Pixiv /ajax/illust/{id}/pages 에서 페이지 URL 목록을 가져온다."""
    import httpx

    url = f"https://www.pixiv.net/ajax/illust/{artwork_id}/pages?lang=ja"
    headers = {
        "Referer": f"https://www.pixiv.net/artworks/{artwork_id}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    with httpx.Client(cookies=cookies or {}, headers=headers, timeout=15.0) as client:
        resp = client.get(url)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"Pixiv pages API 오류: {data.get('message')}")
    return data.get("body", [])


def _meta_from_preload(artwork_id: str, preload_data: dict, page_url: str) -> "AruMetadata":
    """preload_data (pageProps)에서 AruMetadata를 빌드한다."""
    from core.adapters.pixiv import PixivAdapter
    adapter = PixivAdapter()
    raw = {"artwork_id": artwork_id, **preload_data}
    meta = adapter.parse_page_data(raw)
    if page_url:
        meta.artwork_url = page_url
    return meta


def _upsert_artwork_group(conn, meta, total_pages: int, now: str) -> str:
    """artwork_groups에 INSERT OR IGNORE. 이미 있으면 기존 group_id를 반환한다."""
    row = conn.execute(
        "SELECT group_id FROM artwork_groups WHERE artwork_id=? AND source_site='pixiv'",
        (meta.artwork_id,),
    ).fetchone()
    if row:
        return row["group_id"]

    group_id = str(uuid.uuid4())
    kind = "ugoira" if meta.is_ugoira else ("multi_page" if total_pages > 1 else "single_image")
    conn.execute(
        """INSERT INTO artwork_groups
            (group_id, source_site, artwork_id, artwork_url, artwork_title,
             artist_id, artist_name, artist_url, artwork_kind, total_pages,
             tags_json, character_tags_json, series_tags_json,
             downloaded_at, indexed_at, status, metadata_sync_status)
           VALUES (?, 'pixiv', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'inbox', 'pending')""",
        (
            group_id,
            meta.artwork_id,
            meta.artwork_url,
            meta.artwork_title,
            meta.artist_id,
            meta.artist_name,
            meta.artist_url,
            kind,
            total_pages,
            json.dumps(meta.tags, ensure_ascii=False),
            json.dumps(meta.character_tags, ensure_ascii=False),
            json.dumps(meta.series_tags, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()
    return group_id


def _register_file(
    conn,
    group_id: str,
    page_index: int,
    dest_path: Path,
    ext: str,
    sync_status: str,
    now: str,
) -> str:
    """artwork_files에 파일을 등록하고 file_id를 반환한다."""
    file_id   = str(uuid.uuid4())
    file_size = dest_path.stat().st_size if dest_path.exists() else 0
    file_hash = _sha256(dest_path) if dest_path.exists() else None
    conn.execute(
        """INSERT INTO artwork_files
            (file_id, group_id, page_index, file_role, file_path,
             file_format, file_hash, file_size, metadata_embedded,
             file_status, created_at)
           VALUES (?, ?, ?, 'original', ?, ?, ?, ?, 1, 'present', ?)""",
        (file_id, group_id, page_index, str(dest_path), ext, file_hash, file_size, now),
    )
    conn.commit()
    return file_id


def _sync_tags(conn, group_id: str, meta) -> None:
    """tags 테이블에 태그를 INSERT OR IGNORE."""
    pairs = (
        [(t, "general")   for t in meta.tags]
        + [(t, "character") for t in meta.character_tags]
        + [(t, "series")    for t in meta.series_tags]
    )
    for tag, tag_type in pairs:
        if tag:
            conn.execute(
                "INSERT OR IGNORE INTO tags (group_id, tag, tag_type) VALUES (?, ?, ?)",
                (group_id, tag, tag_type),
            )
    conn.commit()


def _generate_cover_thumbnail(conn, group_id: str, data_dir: str) -> None:
    """그룹의 첫 번째 original 파일로 썸네일을 생성한다."""
    from core.thumbnail_manager import generate_thumbnail

    row = conn.execute(
        "SELECT file_id, file_path, file_hash FROM artwork_files"
        " WHERE group_id=? AND file_role='original' AND file_status='present'"
        " ORDER BY page_index ASC LIMIT 1",
        (group_id,),
    ).fetchone()
    if not row:
        return
    generate_thumbnail(
        conn,
        file_path   = row["file_path"],
        data_dir    = data_dir,
        file_id     = row["file_id"],
        source_hash = row["file_hash"] or "",
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# --json-stdin 모드 (NativeHost subprocess spawn용)
# ---------------------------------------------------------------------------

def run_from_stdin() -> None:
    """stdin에서 JSON payload를 읽고 stdout에 결과를 출력."""
    raw     = sys.stdin.buffer.read()
    payload = json.loads(raw)
    config  = payload.get("config", {})
    db_path = config.get("db", {}).get("path", "aru_archive.db")

    from db.database import initialize_database
    conn = initialize_database(db_path)
    try:
        result = save_pixiv_artwork(
            conn,
            config,
            payload.get("artwork_id", ""),
            page_url     = payload.get("page_url", ""),
            cookies      = payload.get("cookies"),
            preload_data = payload.get("preload_data"),
        )
        sys.stdout.write(json.dumps({"success": True, "data": result}, ensure_ascii=False))
    except Exception as exc:
        sys.stdout.write(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
    finally:
        conn.close()
        sys.stdout.flush()


if __name__ == "__main__":
    if "--json-stdin" in sys.argv:
        run_from_stdin()
