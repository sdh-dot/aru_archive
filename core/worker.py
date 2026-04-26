"""
CoreWorker: 파일 다운로드, 메타데이터 임베딩, SQLite 업데이트.

NativeHost에서 직접 호출하거나 서브프로세스로 spawn된다.
  python -m core.worker --json-stdin

MVP-A: 기본 골격. 세부 파이프라인은 Sprint 2~3에서 완성.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def process_save_job(payload: dict, config: dict, db_path: str) -> dict:
    """
    save_artwork 또는 save_ugoira 작업을 처리한다.

    payload:
      action   : 'save_artwork' | 'save_ugoira'
      metadata : AruMetadata.to_dict()
      pages    : [{page_index, url, filename, width, height}]
      config   : config.json 내용 (선택)

    반환: {success: bool, data: {job_id, saved, results}}
    """
    from db.database import initialize_database
    from core.constants import make_save_lock_key
    from core.locks import locked_operation, LockAcquisitionError

    action = payload.get("action", "")
    metadata = payload.get("metadata", {})
    source_site = metadata.get("source_site", "pixiv")
    artwork_id = metadata.get("artwork_id", "")

    conn = initialize_database(db_path)
    job_id = str(uuid.uuid4())

    try:
        lock_key = make_save_lock_key(source_site, artwork_id)
        with locked_operation(conn, lock_key, "core_worker", 120):
            result = _run_save_pipeline(conn, job_id, payload, config)
        return {"success": True, "data": result}
    except LockAcquisitionError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _run_save_pipeline(conn, job_id: str, payload: dict, config: dict) -> dict:
    """
    실제 저장 파이프라인. Sprint 2~3에서 완성.
    현재: save_jobs INSERT 및 골격만 구현.
    """
    metadata = payload.get("metadata", {})
    pages = payload.get("pages", [])
    now = datetime.now(timezone.utc).isoformat()

    # save_jobs INSERT
    conn.execute(
        """
        INSERT INTO save_jobs
            (job_id, source_site, artwork_id, status, total_pages,
             saved_pages, failed_pages, classify_mode, started_at)
        VALUES (?, ?, ?, 'running', ?, 0, 0, ?, ?)
        """,
        (
            job_id,
            metadata.get("source_site", "pixiv"),
            metadata.get("artwork_id", ""),
            len(pages),
            config.get("classify_mode", "save_only"),
            now,
        ),
    )
    conn.commit()

    # TODO (Sprint 2): 실제 다운로드 + 임베딩 + 분류 파이프라인 구현
    conn.execute(
        "UPDATE save_jobs SET status='completed', completed_at=? WHERE job_id=?",
        (datetime.now(timezone.utc).isoformat(), job_id),
    )
    conn.commit()

    return {"job_id": job_id, "saved": 0, "results": []}


def run_from_stdin() -> None:
    """
    --json-stdin 모드: stdin에서 JSON payload를 읽고 stdout에 결과를 출력.
    NativeHost가 subprocess.run()으로 spawn할 때 사용.
    """
    raw = sys.stdin.buffer.read()
    payload = json.loads(raw)
    config = payload.get("config", {})
    db_path = config.get("db_path", "aru_archive.db")
    result = process_save_job(payload, config, db_path)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    if "--json-stdin" in sys.argv:
        run_from_stdin()
