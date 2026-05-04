"""
Config 로드/저장/갱신.

config.json은 사용자별 로컬 파일이므로 Git에는 올리지 않는다.
GitHub에는 config.example.json과 이 모듈의 _DEFAULTS가 설정 계약을 설명한다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_APP_DATA_SUBDIRS = [".thumbcache", ".runtime", "logs"]

# PR #122: app_data_dir 내부 표준 하위 폴더. ensure_app_data_dirs 가 보장한다.
# managed/ 는 앱이 관리하는 파일들의 보관 위치 — output_dir 와는 다른 개념.
APP_DATA_STANDARD_SUBDIRS: tuple[str, ...] = (".runtime", "logs", "thumbcache", "managed")

# PR #122: 관리 폴더 (app_data_dir) 의 기본 위치. 사용자가 일반 설정에서 임의로
# 바꿀 수 있는 폴더가 아니다 — 앱 내부 데이터 (DB, 로그, 썸네일 캐시, 런타임
# 파일) 보관용. config 에서 override 는 가능하지만 wizard UI 는 읽기 전용으로
# 표시한다.
def default_app_data_dir() -> Path:
    """Path.home() / 'AruArchive' 를 안전하게 반환한다."""
    return Path.home() / "AruArchive"


_DEFAULTS: dict[str, Any] = {
    "schema_version": "1.0",
    "data_dir": "",
    "inbox_dir": "",
    "classified_dir": "",
    "managed_dir": "",
    # PR #122: 사용자 폴더 설정 명확화 — input_dir / output_dir 는 inbox_dir /
    # classified_dir 의 PR #122 신규 alias. 기존 inbox_dir / classified_dir 는
    # 여전히 정식 키로 유지되며, 두 alias 는 서로 동기화된다.
    "input_dir":   "",
    "output_dir":  "",
    "app_data_dir": "",
    # PR #122: 전역 UI 언어. 분류 폴더명 언어 (folder_name_language) 와 별도.
    # legacy ui_language 는 호환성 유지용. 새 코드는 app_language 를 사용한다.
    "app_language":         "ko",
    "folder_name_language": "ko",
    "classify_mode": "save_only",
    "undo_retention_days": 7,
    "exiftool_path": None,
    "preferred_browser": None,
    "http_port": 18456,
    "thumbnail_size": "256x256",
    "ui_language": "ko",
    "db": {"path": ""},
    "duplicates": {
        # 중복 검사 기본 범위 — Classified 복사본 제외 (원본과의 중복 오탐 방지)
        "default_scope":             "inbox_managed",
        "max_exact_files_per_run":   1000,
        "max_visual_files_per_run":  300,
        "visual_hash_batch_size":    50,
        "show_progress_every":       25,
        # True로 변경하면 전체 Archive 검사 허용 (경고 표시 후 실행)
        "allow_all_archive_scan":    False,
        # 시각적 중복 검사 실행 전 확인 다이얼로그 표시 여부
        "confirm_visual_scan":       True,
    },
    "developer": {
        # 개발자 전용 기능. 기본값은 모두 False — 일반 사용자에게 노출되지 않음.
        "enabled":                                False,
        "export_classification_failures":         False,
        "classification_failure_export_dir":      ".runtime/debug/classification_failures",
        "classification_failure_export_json":     True,
        "classification_failure_export_text":     True,
        "include_absolute_paths_in_debug_reports": False,
    },
    "classification": {
        # 분류 기준 선택 UI에서 저장되는 사용자 선택 값.
        # series_only | series_character | tag (tag는 미구현)
        "classification_level":           "series_character",
        # primary_strategy는 현재 문서화용 값이다. 실제 분기 플래그는 아래 bool 옵션들이다.
        "primary_strategy":               "series_character",
        # 기본 분류는 series/character를 우선하고, 정보가 부족할 때 author로 폴백한다.
        "enable_series_character":        True,
        "enable_series_uncategorized":    True,
        "enable_character_without_series": True,
        "fallback_by_author":             True,
        # 보조 경로. True로 켜면 위 기본 경로와 별개로 추가 복사 목적지를 만든다.
        "enable_by_author":               False,
        "enable_by_tag":                  False,
        "on_conflict":                    "rename",
        # 다국어 폴더명 설정
        "folder_locale":                  "ko",
        "fallback_locale":                "canonical",
        "enable_localized_folder_names":  True,
        "preserve_original_tag_names":    True,
        # 일괄 분류 설정
        "batch_default_scope":            "current_filter",
        "batch_existing_copy_policy":     "keep_existing",
    },
    "ui": {
        "startup_notice_seen_version": "",
    },
}


def _default_config() -> dict:
    cfg = dict(_DEFAULTS)
    cfg["db"]             = dict(_DEFAULTS["db"])              # type: ignore[arg-type]
    cfg["duplicates"]     = dict(_DEFAULTS["duplicates"])      # type: ignore[arg-type]
    cfg["classification"] = dict(_DEFAULTS["classification"])  # type: ignore[arg-type]
    cfg["developer"]      = dict(_DEFAULTS["developer"])       # type: ignore[arg-type]
    cfg["ui"]             = dict(_DEFAULTS["ui"])              # type: ignore[arg-type]
    return cfg


def derive_workspace_dirs(inbox_dir: str | Path) -> dict[str, str]:
    """Build sibling workspace folders from the chosen inbox folder."""
    inbox_path = Path(inbox_dir).expanduser().resolve(strict=False)
    parent = inbox_path.parent
    return {
        "inbox_dir": str(inbox_path),
        "classified_dir": str((parent / "Classified").resolve(strict=False)),
        "managed_dir": str((parent / "Managed").resolve(strict=False)),
    }


def _has_missing_windows_drive(path: Path) -> bool:
    drive = path.drive
    if not drive:
        return False
    return not Path(f"{drive}\\").exists()


def resolve_data_dir(raw_path: str | None) -> Path:
    """Resolve the archive root and fall back when a configured drive no longer exists."""
    fallback = Path.home() / "AruArchive"
    raw = (raw_path or "").strip()
    if not raw:
        return fallback.resolve(strict=False)

    candidate = Path(raw).expanduser()
    if _has_missing_windows_drive(candidate):
        log.warning("Configured data_dir drive is unavailable, falling back to %s", fallback)
        return fallback.resolve(strict=False)
    return candidate.resolve(strict=False)


def _normalize_path_value(raw_path: str | None, old_root: Path, new_root: Path, default_rel: Path) -> str:
    raw = (raw_path or "").strip()
    if not raw:
        return str((new_root / default_rel).resolve(strict=False))
    if "{data_dir}" in raw:
        return raw.replace("{data_dir}", str(new_root))

    candidate = Path(raw).expanduser()
    if _has_missing_windows_drive(candidate):
        try:
            rel = candidate.relative_to(old_root)
        except ValueError:
            rel = default_rel
        return str((new_root / rel).resolve(strict=False))
    return str(candidate.resolve(strict=False))


def normalize_archive_config(cfg: dict) -> dict:
    """Normalize archive-related paths for the current machine at runtime."""
    old_root_raw = cfg.get("data_dir", "")
    old_root = Path(old_root_raw).expanduser() if old_root_raw else (Path.home() / "AruArchive")
    new_root = resolve_data_dir(old_root_raw)

    cfg["data_dir"] = str(new_root)
    inbox_dir = (cfg.get("inbox_dir", "") or "").strip()
    classified_dir = (cfg.get("classified_dir", "") or "").strip()
    managed_dir = (cfg.get("managed_dir", "") or "").strip()

    cfg["inbox_dir"] = _normalize_path_value(inbox_dir, old_root, new_root, Path("Inbox")) if inbox_dir else ""
    cfg["classified_dir"] = (
        _normalize_path_value(classified_dir, old_root, new_root, Path("Classified"))
        if classified_dir else ""
    )
    cfg["managed_dir"] = (
        _normalize_path_value(managed_dir, old_root, new_root, Path("Managed"))
        if managed_dir else ""
    )

    db_cfg = cfg.setdefault("db", {})
    db_cfg["path"] = _normalize_path_value(db_cfg.get("path", ""), old_root, new_root, Path(".runtime") / "aru.db")
    return cfg


def load_config(path: str | Path = "config.json") -> dict:
    """JSON 파일을 읽어 config dict 반환. 없으면 기본값으로 생성."""
    p = Path(path)
    if not p.exists():
        cfg = _default_config()
        save_config(cfg, p)
        return cfg
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    cfg = _default_config()
    cfg.update(data)
    return cfg


def save_config(cfg: dict, path: str | Path = "config.json") -> None:
    """config dict를 JSON 파일에 저장한다."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    log.info("Config saved: %s", p)


def update_workspace_from_inbox(cfg: dict, inbox_path: str) -> dict:
    """Use the selected folder as inbox and derive sibling workspace directories."""
    workspace = derive_workspace_dirs(inbox_path)
    cfg.update(workspace)
    return cfg


def update_archive_root(cfg: dict, root_path: str) -> dict:
    """Backward-compatible helper for legacy callers."""
    root = Path(root_path)
    cfg["data_dir"] = str(root)
    cfg["inbox_dir"] = str(root / "Inbox")
    cfg["classified_dir"] = str(root / "Classified")
    cfg["managed_dir"] = str(root / "Managed")
    db_cfg = cfg.setdefault("db", {})
    if not db_cfg.get("path"):
        db_cfg["path"] = str(root / ".runtime" / "aru.db")
    return cfg


def ensure_app_directories(cfg: dict) -> list[str]:
    """Create internal application data folders under data_dir."""
    data_dir = cfg.get("data_dir", "")
    if not data_dir:
        return []
    root_path = Path(data_dir)
    created: list[str] = []
    for sub in _APP_DATA_SUBDIRS:
        p = root_path / sub
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p))
            log.info("Created directory: %s", p)
    return created


def resolve_app_data_dir(cfg: dict | None = None) -> Path:
    """관리 폴더 (app_data_dir) 의 실제 경로를 반환한다 (PR #122).

    우선순위:
    1. ``cfg["app_data_dir"]`` 명시 값 (빈 문자열 제외)
    2. 기본값 ``Path.home() / "AruArchive"``

    cfg 가 None 이거나 키가 없으면 기본값 그대로 반환. 경로는
    ``resolve(strict=False)`` 로 정규화되며, 존재 여부 검사는 caller 책임.
    """
    raw = ((cfg or {}).get("app_data_dir") or "").strip() if cfg else ""
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    return default_app_data_dir().resolve(strict=False)


def ensure_app_data_dirs(app_data_dir: str | Path | None = None) -> list[str]:
    """관리 폴더 내부 표준 하위 디렉터리를 생성한다 (PR #122).

    생성 대상: ``.runtime`` / ``logs`` / ``thumbcache`` / ``managed``.
    이미 존재하면 건너뛴다. 생성 실패 시 OSError 메시지를 로그에 남기고
    예외를 caller 로 전파 — 조용히 무시하지 않는다.

    Args:
        app_data_dir: ``Path`` / 문자열 / None. None 이면
                      ``default_app_data_dir()`` (``Path.home() / 'AruArchive'``)
                      을 사용한다.

    Returns:
        실제로 새로 생성된 폴더의 절대 경로 문자열 list.

    Raises:
        OSError: ``app_data_dir`` 자체 또는 표준 하위 폴더 생성에 실패했을 때.
                 metadata pipeline 과 무관하므로 여기서 예외를 던져도 분류
                 status 의미는 영향 없음.
    """
    base: Path
    if app_data_dir is None:
        base = default_app_data_dir()
    else:
        base = Path(app_data_dir).expanduser()
    base = base.resolve(strict=False)
    base.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    for sub in APP_DATA_STANDARD_SUBDIRS:
        p = base / sub
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p))
            log.info("Created app_data_dir subfolder: %s", p)
    return created


def sync_io_dir_aliases(cfg: dict) -> dict:
    """input_dir / inbox_dir 와 output_dir / classified_dir 를 동기화한다 (PR #122).

    PR #122 는 사용자 친화적인 ``input_dir`` / ``output_dir`` 키를 도입했지만,
    기존 코드 / 테스트 / DB / 마이그레이션은 여전히 ``inbox_dir`` /
    ``classified_dir`` 를 읽는다. 두 키는 서로 alias 로 동작해야 한다.

    동기화 정책 (이번 호출 한 번만 적용 — 이후 변경은 wizard / 설정 UI 가 직접
    두 키 모두를 갱신해야 한다):
    - 양쪽 모두 비어 있으면 변경 없음.
    - 한쪽만 채워져 있으면 다른 쪽으로 복사.
    - 양쪽 다 채워져 있으면 ``inbox_dir`` / ``classified_dir`` 가 우선
      (기존 사용자 설정 보존).
    """
    inbox    = (cfg.get("inbox_dir") or "").strip()
    in_alias = (cfg.get("input_dir") or "").strip()
    if inbox and not in_alias:
        cfg["input_dir"] = inbox
    elif in_alias and not inbox:
        cfg["inbox_dir"] = in_alias

    classified = (cfg.get("classified_dir") or "").strip()
    out_alias  = (cfg.get("output_dir")     or "").strip()
    if classified and not out_alias:
        cfg["output_dir"] = classified
    elif out_alias and not classified:
        cfg["classified_dir"] = out_alias

    return cfg


def ensure_workspace_directories(cfg: dict) -> list[str]:
    """Create the user-facing workspace folders when configured."""
    created: list[str] = []
    for key in ("inbox_dir", "classified_dir", "managed_dir"):
        raw = cfg.get(key, "")
        if not raw:
            continue
        p = Path(raw)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p))
            log.info("Created directory: %s", p)
    return created


def ensure_archive_directories(cfg: dict) -> list[str]:
    """Compatibility wrapper that creates both app-data and workspace folders."""
    return ensure_app_directories(cfg) + ensure_workspace_directories(cfg)
