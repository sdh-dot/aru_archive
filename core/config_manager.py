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

_DEFAULTS: dict[str, Any] = {
    "schema_version": "1.0",
    "data_dir": "",
    "inbox_dir": "",
    "classified_dir": "",
    "managed_dir": "",
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
