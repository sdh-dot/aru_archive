"""Config 로드/저장/갱신 — Aru Archive."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ARCHIVE_SUBDIRS = ["Inbox", "Classified", "Managed", ".thumbcache", ".runtime"]

_DEFAULTS: dict[str, Any] = {
    "schema_version": "1.0",
    "data_dir": "",
    "inbox_dir": "",
    "classified_dir": "",
    "classify_mode": "save_only",
    "undo_retention_days": 7,
    "exiftool_path": None,
    "preferred_browser": None,
    "http_port": 18456,
    "thumbnail_size": "256x256",
    "ui_language": "ko",
    "db": {"path": ""},
    "classification": {
        "enable_by_author":    True,
        "enable_by_series":    True,
        "enable_by_character": True,
        "enable_by_tag":       False,
        "on_conflict":         "rename",
    },
}


def _default_config() -> dict:
    cfg = dict(_DEFAULTS)
    cfg["db"]             = dict(_DEFAULTS["db"])              # type: ignore[arg-type]
    cfg["classification"] = dict(_DEFAULTS["classification"])  # type: ignore[arg-type]
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


def update_archive_root(cfg: dict, root_path: str) -> dict:
    """Archive Root에 따라 파생 경로를 갱신하고 반환한다."""
    root = Path(root_path)
    cfg["data_dir"] = str(root)
    cfg["inbox_dir"] = str(root / "Inbox")
    cfg["classified_dir"] = str(root / "Classified")
    db_cfg = cfg.setdefault("db", {})
    if not db_cfg.get("path"):
        db_cfg["path"] = str(root / ".runtime" / "aru.db")
    return cfg


def ensure_archive_directories(cfg: dict) -> list[str]:
    """Archive Root 아래 필수 폴더를 생성한다. 생성된 경로 목록 반환."""
    root = cfg.get("data_dir", "")
    if not root:
        return []
    root_path = Path(root)
    created: list[str] = []
    for sub in _ARCHIVE_SUBDIRS:
        p = root_path / sub
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p))
            log.info("Created directory: %s", p)
    return created
