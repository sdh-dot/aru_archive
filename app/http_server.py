"""
MainApp HTTP IPC 서버.
NativeHost와 localhost:18456에서 통신.
X-Aru-Token 헤더로 인증 (세션별 UUID).

토큰 생명주기:
  시작 시: secrets.token_hex(32) 생성 → {data_dir}/.runtime/ipc_token 파일 저장
  종료 시: ipc_token 파일 삭제
  재시작 시: ipc_token 파일 덮어쓰기 (항상 재생성)
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional

DEFAULT_PORT = 18456
RUNTIME_DIR = ".runtime"
IPC_TOKEN_FILENAME = "ipc_token"
logger = logging.getLogger(__name__)


class _IpcHandler(BaseHTTPRequestHandler):
    """IPC 요청 핸들러. server 인스턴스의 속성으로 토큰과 콜백을 참조한다."""

    def log_message(self, fmt, *args):
        pass  # stdout 로그 억제

    def _check_token(self) -> bool:
        token = self.headers.get("X-Aru-Token", "")
        return secrets.compare_digest(token, self.server.aru_token)  # type: ignore[attr-defined]

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._check_token():
            self._send_json(401, {"error": "Unauthorized"})
            return

        if self.path == "/api/ping":
            self._send_json(200, {"status": "ok"})

        elif self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            cb = self.server.on_get_job  # type: ignore[attr-defined]
            if cb:
                self._send_json(200, cb(job_id))
            else:
                self._send_json(404, {"error": "not found"})

        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._check_token():
            self._send_json(401, {"error": "Unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/jobs":
            cb = self.server.on_add_job  # type: ignore[attr-defined]
            if cb:
                self._send_json(200, cb(body))
            else:
                self._send_json(503, {"error": "no handler"})

        elif self.path == "/api/notify":
            cb = self.server.on_notify  # type: ignore[attr-defined]
            if cb:
                cb(body)
            self._send_json(200, {"status": "ok"})

        else:
            self._send_json(404, {"error": "not found"})


class AppHttpServer(threading.Thread):
    """
    MainApp IPC HTTP 서버 (daemon thread).
    MainApp 시작 시 start(), 종료 시 stop() 호출.
    """

    def __init__(
        self,
        data_dir: str,
        port: int = DEFAULT_PORT,
        on_add_job: Optional[Callable[[dict], dict]] = None,
        on_get_job: Optional[Callable[[str], dict]] = None,
        on_notify: Optional[Callable[[dict], None]] = None,
    ):
        super().__init__(daemon=True, name="AruIpcServer")
        self.data_dir = data_dir
        self.port = port
        self.token = secrets.token_hex(32)
        self.token_file = Path(data_dir) / RUNTIME_DIR / IPC_TOKEN_FILENAME
        self.on_add_job = on_add_job
        self.on_get_job = on_get_job
        self.on_notify = on_notify
        self._server: Optional[HTTPServer] = None

    def run(self) -> None:
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(self.token, encoding="utf-8")
            try:
                self.token_file.chmod(0o600)
            except Exception:
                pass  # Windows chmod 제한 무시
        except OSError as exc:
            logger.warning("IPC 토큰 파일 생성 실패, IPC 서버를 비활성화합니다: %s", exc)
            return

        try:
            server = HTTPServer(("127.0.0.1", self.port), _IpcHandler)
        except OSError as exc:
            logger.warning("IPC 서버 포트 바인딩 실패, IPC 서버를 비활성화합니다: %s", exc)
            self.token_file.unlink(missing_ok=True)
            return
        server.aru_token = self.token  # type: ignore[attr-defined]
        server.on_add_job = self.on_add_job  # type: ignore[attr-defined]
        server.on_get_job = self.on_get_job  # type: ignore[attr-defined]
        server.on_notify = self.on_notify  # type: ignore[attr-defined]
        self._server = server
        try:
            server.serve_forever()
        finally:
            self.token_file.unlink(missing_ok=True)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


def read_ipc_token(data_dir: str) -> Optional[str]:
    """
    NativeHost에서 MainApp IPC 토큰을 읽는다.
    파일이 없으면 None 반환 → MainApp 미실행으로 판단 → CoreWorker spawn.
    """
    token_file = Path(data_dir) / RUNTIME_DIR / IPC_TOKEN_FILENAME
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    return None
