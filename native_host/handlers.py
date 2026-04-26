"""
Native Host 액션 핸들러 (프로토콜 v2).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def handle_save_pixiv_artwork(payload: dict, config: dict) -> dict:
    """
    save_pixiv_artwork 처리.
    DB에 연결하여 CoreWorker save_pixiv_artwork를 직접 호출한다.
    """
    artwork_id   = payload.get("artwork_id", "")
    page_url     = payload.get("page_url", "")
    cookies      = payload.get("cookies") or {}
    preload_data = payload.get("preload_data")

    if not artwork_id:
        return {"success": False, "error": "artwork_id가 없습니다."}

    db_path = config.get("db", {}).get("path", "aru_archive.db")
    try:
        from db.database import initialize_database
        from core.locks import LockAcquisitionError
        from core.worker import save_pixiv_artwork

        conn = initialize_database(db_path)
        try:
            result = save_pixiv_artwork(
                conn,
                config,
                artwork_id,
                page_url     = page_url,
                cookies      = cookies,
                preload_data = preload_data,
            )
            return {"success": True, "data": result}
        except LockAcquisitionError as exc:
            return {"success": False, "error": f"이미 처리 중입니다: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            conn.close()
    except Exception as exc:
        return {"success": False, "error": str(exc)}
