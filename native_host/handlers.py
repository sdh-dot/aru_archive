"""
Native Host 액션 핸들러.
MainApp 실행 여부 확인 후 HTTP IPC 전달 또는 CoreWorker spawn.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def handle_save(message: dict, config: dict) -> dict:
    """
    save_artwork / save_ugoira 처리.
    MainApp 실행 중 → HTTP IPC 전달.
    MainApp 없음   → CoreWorker 서브프로세스 spawn.
    """
    from app.http_server import read_ipc_token

    data_dir = config.get("data_dir", "D:/AruArchive")
    token = read_ipc_token(data_dir)

    if token:
        return _forward_to_mainapp(message, config, token)
    return _spawn_core_worker(message, config)


def handle_no_metadata(message: dict, config: dict) -> dict:
    """
    save_no_metadata 처리: 파일 다운로드 후 no_metadata_queue에 기록.
    MVP-A 골격.
    """
    # TODO (Sprint 3): 실제 다운로드 + 큐 기록 구현
    return {"success": True, "data": {"queued": True}}


def _forward_to_mainapp(message: dict, config: dict, token: str) -> dict:
    """MainApp HTTP IPC로 저장 작업 전달 (X-Aru-Token 헤더)."""
    try:
        port = config.get("http_server", {}).get("port", 18456)
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/jobs",
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Aru-Token": token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"success": False, "error": str(e)}


def _spawn_core_worker(message: dict, config: dict) -> dict:
    """MainApp 없을 때 CoreWorker 서브프로세스 직접 실행."""
    try:
        payload = {**message, "config": config}
        proc = subprocess.run(
            [sys.executable, "-m", "core.worker", "--json-stdin"],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            timeout=120,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        if proc.returncode != 0:
            return {
                "success": False,
                "error": proc.stderr.decode("utf-8", errors="replace"),
            }
        return json.loads(proc.stdout)
    except Exception as e:
        return {"success": False, "error": str(e)}
