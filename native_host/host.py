"""
Native Messaging Host.
Chrome / Naver Whale 브라우저 확장과 stdin/stdout으로 JSON 메시지를 주고받는다.
메시지 형식: [4 bytes little-endian length][JSON UTF-8 bytes]

프로토콜 v2:
  요청: {"action": "...", "request_id": "...", "payload": {...}}
  응답: {"success": bool, "request_id": "...", "data": {...}}
       {"success": false, "request_id": "...", "error": "..."}

액션:
  ping               → {"status": "ok"}
  save_pixiv_artwork → {"job_id": "...", "saved": N, "total": N, "failed": N}
  get_config_summary → {"data_dir": "...", "inbox_dir": "...", "db_path": "..."}
  open_main_app      → {"launched": true}
  get_job_status     → {"status": "...", "progress": {...}, "pages": [...]}

등록:
  Chrome: HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\net.aru_archive.host
  Whale:  HKCU\\Software\\Naver\\Whale\\NativeMessagingHosts\\net.aru_archive.host

stdout 규칙: Native Messaging 응답 JSON만 출력. 로그는 stderr + 파일에만 기록.
"""
from __future__ import annotations

import json
import logging
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_log = logging.getLogger("aru_archive.host")

_LOG_DIR = Path(os.environ.get("APPDATA", "~")).expanduser() / "AruArchive" / "NativeHost"


def _setup_logging() -> None:
    """파일 + stderr 핸들러 설정. stdout에는 절대 출력하지 않는다."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / "native_host.log"
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)

        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)

        _log.propagate = False
        _log.setLevel(logging.DEBUG)
        _log.addHandler(fh)
        _log.addHandler(sh)
    except Exception:
        pass  # 로깅 설정 실패 시 무음 계속


def read_raw() -> bytes | None:
    """stdin에서 4바이트 길이 + raw bytes 읽기. EOF면 None."""
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) < 4:
        return None
    length = struct.unpack("<I", raw_length)[0]
    return sys.stdin.buffer.read(length)


def read_message() -> dict | None:
    """read_raw()로 읽은 bytes를 JSON 디코딩하여 반환한다. EOF면 None."""
    raw = read_raw()
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def send_message(data: dict) -> None:
    """stdout에 4바이트 길이 + JSON 쓰기. stdout에는 이것만 출력한다."""
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _reply(
    request_id: str,
    success: bool,
    data: dict | None = None,
    error: str | None = None,
) -> dict:
    resp: dict = {"success": success, "request_id": request_id}
    if success and data is not None:
        resp["data"] = data
    if not success and error is not None:
        resp["error"] = error
    return resp


def load_config() -> dict:
    """config.json 로드. 없으면 기본값 반환."""
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    example_path = config_path.parent / "config.example.json"
    if example_path.exists():
        return json.loads(example_path.read_text(encoding="utf-8"))
    return {
        "data_dir":  "D:/AruArchive",
        "inbox_dir": "D:/AruArchive/Inbox",
        "db":        {"path": "D:/AruArchive/.runtime/aru.db"},
    }


def _handle_get_job_status(conn, job_id: str) -> dict:
    """save_jobs + job_pages(+artwork_files JOIN) 조회. 결과 dict를 반환한다."""
    row = conn.execute(
        "SELECT status, saved_pages, total_pages, failed_pages, error_message"
        " FROM save_jobs WHERE job_id=?",
        (job_id,),
    ).fetchone()
    if not row:
        return {"_error": "job_not_found"}

    page_rows = conn.execute(
        "SELECT jp.page_index, jp.status, af.file_path, jp.error_message"
        " FROM job_pages jp"
        " LEFT JOIN artwork_files af ON jp.file_id = af.file_id"
        " WHERE jp.job_id=? ORDER BY jp.page_index",
        (job_id,),
    ).fetchall()

    pages = []
    for p in page_rows:
        entry: dict = {
            "page_index": p["page_index"],
            "status":     p["status"],
        }
        if p["file_path"]:
            entry["file_path"] = p["file_path"]
        if p["error_message"]:
            entry["error_message"] = p["error_message"]
        pages.append(entry)

    return {
        "status": row["status"],
        "progress": {
            "total_pages":  row["total_pages"]  or 0,
            "saved_pages":  row["saved_pages"]  or 0,
            "failed_pages": row["failed_pages"] or 0,
        },
        "error_message": row["error_message"],
        "pages": pages,
    }


def main() -> None:
    """Native Host 메인 루프."""
    _setup_logging()
    _log.info("Native Host 시작")
    config = load_config()

    while True:
        raw = read_raw()
        if raw is None:
            _log.info("Native Host 종료 (EOF)")
            break

        # JSON decode — 실패 시 protocol_error 응답 후 계속
        try:
            message = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            _log.warning("malformed JSON: %s", exc)
            send_message(_reply("", False, error="protocol_error: malformed JSON"))
            continue

        action     = message.get("action", "")
        request_id = str(message.get("request_id", ""))
        payload    = message.get("payload") or {}

        _log.info("action=%s request_id=%s", action, request_id)

        try:
            if action == "ping":
                send_message(_reply(request_id, True, {"status": "ok"}))

            elif action == "save_pixiv_artwork":
                from native_host.handlers import handle_save_pixiv_artwork
                result = handle_save_pixiv_artwork(payload, config)
                if result.get("success"):
                    send_message(_reply(request_id, True, result.get("data", {})))
                else:
                    send_message(_reply(request_id, False, error=result.get("error", "unknown_error")))

            elif action == "get_config_summary":
                send_message(_reply(request_id, True, {
                    "data_dir":  config.get("data_dir", ""),
                    "inbox_dir": config.get("inbox_dir", ""),
                    "db_path":   config.get("db", {}).get("path", ""),
                }))

            elif action == "open_main_app":
                import subprocess
                root = Path(__file__).resolve().parent.parent
                subprocess.Popen(
                    [sys.executable, str(root / "main.py")],
                    cwd=str(root),
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
                send_message(_reply(request_id, True, {"launched": True}))

            elif action == "get_job_status":
                job_id = payload.get("job_id", "")
                if not job_id:
                    _log.warning("get_job_status: job_id 누락")
                    send_message(_reply(request_id, False, error="missing job_id"))
                else:
                    from db.database import initialize_database
                    db_path = config.get("db", {}).get("path", "aru_archive.db")
                    conn = initialize_database(db_path)
                    try:
                        result = _handle_get_job_status(conn, job_id)
                        if "_error" in result:
                            send_message(_reply(request_id, False, error=result["_error"]))
                        else:
                            send_message(_reply(request_id, True, result))
                    finally:
                        conn.close()

            else:
                _log.warning("unknown_action: %s", action)
                send_message(_reply(request_id, False, error=f"unknown_action: {action}"))

        except Exception as exc:
            _log.exception("action=%s 처리 중 예외: %s", action, exc)
            send_message(_reply(request_id, False, error=str(exc)))


if __name__ == "__main__":
    main()
