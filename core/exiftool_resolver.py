"""
ExifTool 경로 자동 탐색 및 번들 검증.

탐색 우선순위:
  1. config["exiftool_path"] — 사용자 지정 경로
  2. 개발 환경 / PyInstaller onedir: ./tools/exiftool/exiftool.exe
  3. PyInstaller onefile: sys._MEIPASS/tools/exiftool/exiftool.exe
  4. exiftool(-k).exe fallback (Windows 공식 배포판 기본 이름)
  5. 시스템 PATH에 등록된 exiftool
  6. 없으면 None

shell=True 사용 금지. subprocess 호출은 인자 리스트로만 전달한다.
"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_EXIFTOOL_SUBDIR = Path("tools") / "exiftool"
_EXIFTOOL_NAMES = ["exiftool.exe", "exiftool(-k).exe", "exiftool"]


def _ensure_cli_exiftool_alias(et_dir: Path) -> Optional[Path]:
    """
    Windows 공식 배포판의 exiftool(-k).exe만 있을 때 CLI용 exiftool.exe 별칭을 만든다.

    exiftool(-k).exe는 더블클릭 실행 후 창을 유지하기 위한 이름이다. 자동 XMP
    재처리에서는 표준 이름인 exiftool.exe가 더 안정적이므로, 개발/onedir처럼
    쓰기 가능한 번들에서는 복사본을 만들어 그 경로를 사용한다.
    """
    cli = et_dir / "exiftool.exe"
    if cli.exists():
        return cli

    k_variant = et_dir / "exiftool(-k).exe"
    if not k_variant.exists():
        return None

    try:
        shutil.copy2(k_variant, cli)
        logger.info("ExifTool CLI 별칭 생성: %s", cli)
        return cli
    except OSError as exc:
        logger.warning("ExifTool CLI 별칭 생성 실패: %s", exc)
        return k_variant


def get_app_base_path() -> Path:
    """
    개발 환경과 PyInstaller 환경 모두에서 앱 기준 경로를 반환한다.

    - PyInstaller onefile: sys._MEIPASS (임시 압축 해제 디렉터리)
    - PyInstaller onedir:  실행 파일이 있는 폴더
    - 개발 환경:           이 모듈의 상위 상위 디렉터리 (프로젝트 루트)
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def find_bundled_exiftool() -> Optional[str]:
    """
    개발 환경 / PyInstaller onedir / onefile 환경에서
    tools/exiftool/exiftool.exe (또는 exiftool(-k).exe)를 찾는다.

    반환: 실행 파일 절대 경로 문자열, 없으면 None.
    """
    base = get_app_base_path()
    et_dir = base / _EXIFTOOL_SUBDIR
    alias = _ensure_cli_exiftool_alias(et_dir)
    if alias:
        return str(alias)

    for name in _EXIFTOOL_NAMES:
        candidate = et_dir / name
        if candidate.exists():
            if name != "exiftool.exe":
                logger.debug(
                    "bundled ExifTool: %s (%s 로 이름을 변경하면 표준 동작)", candidate, "exiftool.exe"
                )
            return str(candidate)
    return None


def resolve_exiftool_path(config: Optional[dict] = None) -> Optional[str]:
    """
    config 지정 경로, bundled ExifTool, PATH 순서로 ExifTool 실행 파일을 찾는다.

    config["exiftool_path"]가 None, 빈 문자열, 또는 "auto"이면 자동 탐색한다.
    찾지 못하면 None을 반환한다.
    """
    if config:
        cfg_path = config.get("exiftool_path")
        if cfg_path and str(cfg_path).strip() not in ("", "null", "auto"):
            p = Path(str(cfg_path))
            if p.exists():
                return str(p)
            logger.warning("config.exiftool_path 경로가 존재하지 않음: %s — 자동 탐색으로 fallback", cfg_path)

    bundled = find_bundled_exiftool()
    if bundled:
        logger.debug("bundled ExifTool 사용: %s", bundled)
        return bundled

    which = shutil.which("exiftool")
    if which:
        logger.debug("PATH ExifTool 사용: %s", which)
        return which

    return None


def validate_exiftool_bundle(base_dir: Optional[str | Path] = None) -> dict:
    """
    bundled ExifTool 구성 상태를 점검한다.

    반환:
    {
        "ok":                bool,
        "exiftool_path":     str | None,
        "has_exiftool_files": bool,
        "version":           str | None,
        "warnings":          [str, ...]
    }
    """
    from core.exiftool import get_exiftool_version

    if base_dir is None:
        base_dir = get_app_base_path()
    base_dir = Path(base_dir)
    et_dir = base_dir / _EXIFTOOL_SUBDIR
    warnings: list[str] = []

    alias = _ensure_cli_exiftool_alias(et_dir)
    exiftool_path: Optional[str] = str(alias) if alias else None
    if exiftool_path and Path(exiftool_path).name != "exiftool.exe":
        warnings.append("exiftool.exe 별칭 생성 실패 — exiftool(-k).exe fallback 사용")

    if exiftool_path is None:
        warnings.append(f"exiftool.exe 가 {et_dir} 에 없습니다.")

    has_exiftool_files = (et_dir / "exiftool_files").exists()
    if not has_exiftool_files:
        warnings.append(f"exiftool_files/ 폴더가 {et_dir} 에 없습니다.")

    version: Optional[str] = None
    if exiftool_path:
        version = get_exiftool_version(exiftool_path)
        if version is None:
            warnings.append("ExifTool 버전 확인 실패 (실행 파일이 손상됐을 수 있습니다).")

    ok = exiftool_path is not None and has_exiftool_files
    return {
        "ok":                ok,
        "exiftool_path":     exiftool_path,
        "has_exiftool_files": has_exiftool_files,
        "version":           version,
        "warnings":          warnings,
    }
