"""
Native Messaging Host.
Chrome / Naver Whale 브라우저 확장과 stdin/stdout으로 JSON 메시지를 주고받는다.
메시지 형식: [4 bytes little-endian length][JSON UTF-8 bytes]

등록:
  Chrome: HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\net.aru_archive.host
  Whale:  HKCU\\Software\\Naver\\Whale\\NativeMessagingHosts\\net.aru_archive.host
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def read_message() -> dict | None:
    """stdin에서 4바이트 길이 + JSON 읽기."""
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) < 4:
        return None
    length = struct.unpack("<I", raw_length)[0]
    raw_message = sys.stdin.buffer.read(length)
    return json.loads(raw_message.decode("utf-8"))


def send_message(data: dict) -> None:
    """stdout에 4바이트 길이 + JSON 쓰기."""
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def load_config() -> dict:
    """config.json 로드. 없으면 기본값 반환."""
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    # config.json 없으면 example 시도
    example_path = config_path.parent / "config.example.json"
    if example_path.exists():
        return json.loads(example_path.read_text(encoding="utf-8"))
    return {
        "data_dir": "D:/AruArchive",
        "http_server": {"port": 18456},
        "classify_mode": "save_only",
    }


def main() -> None:
    """Native Host 메인 루프."""
    config = load_config()

    while True:
        message = read_message()
        if message is None:
            break

        action = message.get("action", "")

        if action == "ping":
            send_message({"success": True, "data": {"status": "ok"}})

        elif action in ("save_artwork", "save_ugoira"):
            from native_host.handlers import handle_save
            result = handle_save(message, config)
            send_message(result)

        elif action == "get_job_status":
            job_id = message.get("job_id", "")
            # TODO (Sprint 3): DB에서 실제 상태 조회
            send_message({
                "success": True,
                "data": {"job_id": job_id, "status": "pending"},
            })

        elif action == "save_no_metadata":
            from native_host.handlers import handle_no_metadata
            result = handle_no_metadata(message, config)
            send_message(result)

        else:
            send_message({"success": False, "error": f"알 수 없는 액션: {action}"})


if __name__ == "__main__":
    main()
