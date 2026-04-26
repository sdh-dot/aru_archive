#!/usr/bin/env python
"""
ExifTool 번들 구성 검증 스크립트.

실행:
    python build/check_exiftool_bundle.py

검증 항목:
  - tools/exiftool/exiftool.exe (또는 exiftool(-k).exe) 존재
  - tools/exiftool/exiftool_files/ 폴더 존재
  - ExifTool 버전 확인
  - PyInstaller spec에 tools/exiftool 포함 여부
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure UTF-8 output on Windows CP949 consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 프로젝트 루트 = 이 스크립트의 상위 디렉터리
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _warn(msg: str) -> None:
    print(f"  \033[33m⚠\033[0m {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def check_exiftool_bundle() -> bool:
    from core.exiftool_resolver import validate_exiftool_bundle
    print("\n[1] ExifTool bundle validation")
    result = validate_exiftool_bundle(PROJECT_ROOT)

    if result["exiftool_path"]:
        _ok(f"실행 파일: {result['exiftool_path']}")
    else:
        _fail("tools/exiftool/exiftool.exe 를 찾을 수 없습니다.")
        _warn("  →  tools/exiftool/ 에 exiftool.exe 를 배치하세요.")
        _warn("  →  공식 배포판의 exiftool(-k).exe 를 exiftool.exe 로 이름을 바꿔도 됩니다.")

    if result["has_exiftool_files"]:
        _ok("exiftool_files/ 폴더 존재")
    else:
        _warn("tools/exiftool/exiftool_files/ 폴더가 없습니다 (일부 기능 불가).")

    if result["version"]:
        _ok(f"ExifTool 버전: {result['version']}")
    else:
        _warn("ExifTool 버전 확인 불가.")

    for w in result["warnings"]:
        _warn(w)

    return result["ok"]


def check_spec_includes_exiftool() -> bool:
    print("\n[2] PyInstaller spec 검증")
    spec_path = PROJECT_ROOT / "build" / "aru_archive.spec"
    if not spec_path.exists():
        _warn(f"spec 파일 없음: {spec_path}")
        return False
    content = spec_path.read_text(encoding="utf-8")
    if "tools/exiftool" in content or "tools\\exiftool" in content:
        _ok(f"spec 파일에 tools/exiftool 포함 확인: {spec_path.name}")
        return True
    else:
        _fail("spec 파일에 tools/exiftool 항목이 없습니다.")
        return False


def check_resolver_auto() -> None:
    print("\n[3] resolve_exiftool_path 자동 탐색 결과")
    from core.exiftool_resolver import resolve_exiftool_path
    path = resolve_exiftool_path(config=None)
    if path:
        _ok(f"자동 탐색 성공: {path}")
    else:
        _warn("자동 탐색 결과 없음 — ExifTool 설치 필요 또는 PATH 미등록")


def main() -> int:
    print("=" * 60)
    print("  Aru Archive - ExifTool Bundle Check")
    print("=" * 60)

    bundle_ok   = check_exiftool_bundle()
    spec_ok     = check_spec_includes_exiftool()
    check_resolver_auto()

    print()
    if bundle_ok and spec_ok:
        print("\033[32m✓ 모든 검증 통과\033[0m")
        return 0
    else:
        print("\033[33m⚠ 일부 항목에 경고 또는 오류가 있습니다. 위 메시지를 확인하세요.\033[0m")
        return 1


if __name__ == "__main__":
    sys.exit(main())
