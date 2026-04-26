"""
Native Messaging Host manifest 생성기.

사용법:
  python gen_manifest.py <host_bat_path> <browser> <extension_id> <output_path>

인자:
  host_bat_path  -- host.bat 절대 경로
  browser        -- chrome | whale
  extension_id   -- 브라우저 확장 프로그램 ID
  output_path    -- 출력할 manifest.json 경로

예시:
  python gen_manifest.py "C:\\AruArchive\\NativeHost\\host.bat" chrome abc123def manifest_chrome.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def make_manifest(host_bat_path: str, browser: str, extension_id: str) -> dict:
    """Native Messaging Host manifest dict를 반환한다."""
    if browser == "chrome":
        origin = f"chrome-extension://{extension_id}/"
    elif browser == "whale":
        origin = f"naver-extension://{extension_id}/"
    else:
        raise ValueError(f"지원하지 않는 브라우저: {browser!r}. chrome 또는 whale을 사용하세요.")

    return {
        "name":            "net.aru_archive.host",
        "description":     "Aru Archive Native Messaging Host",
        "path":            host_bat_path,
        "type":            "stdio",
        "allowed_origins": [origin],
    }


def main() -> int:
    if len(sys.argv) != 5:
        print(
            f"사용법: {sys.argv[0]} <host_bat_path> <browser> <extension_id> <output_path>",
            file=sys.stderr,
        )
        return 1

    host_bat_path = sys.argv[1]
    browser       = sys.argv[2]
    extension_id  = sys.argv[3]
    output_path   = Path(sys.argv[4])

    try:
        manifest = make_manifest(host_bat_path, browser, extension_id)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OK] manifest 생성: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
