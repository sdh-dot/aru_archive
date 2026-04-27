"""core/config_manager 단위 테스트."""
from __future__ import annotations

import json
from pathlib import Path

from core.config_manager import (
    derive_workspace_dirs,
    ensure_app_directories,
    ensure_archive_directories,
    ensure_workspace_directories,
    load_config,
    normalize_archive_config,
    resolve_data_dir,
    save_config,
    update_workspace_from_inbox,
)


def test_load_creates_default_if_missing(tmp_path):
    """config 파일이 없으면 기본 config를 생성한다."""
    p = tmp_path / "config.json"
    cfg = load_config(p)
    assert p.exists()
    assert cfg["schema_version"] == "1.0"
    assert "data_dir" in cfg


def test_save_and_reload(tmp_path):
    """저장 후 다시 load_config() 하면 경로가 유지된다."""
    p = tmp_path / "config.json"
    cfg = load_config(p)
    cfg["data_dir"] = str(tmp_path / "root")
    save_config(cfg, p)
    reloaded = load_config(p)
    assert reloaded["data_dir"] == str(tmp_path / "root")


def test_update_workspace_from_inbox_sets_sibling_paths(tmp_path):
    """선택 폴더를 inbox로 유지하고 같은 레벨에 Classified/Managed를 만든다."""
    cfg: dict = {}
    inbox = str(tmp_path / "PixivInbox")
    update_workspace_from_inbox(cfg, inbox)
    assert cfg["inbox_dir"] == inbox
    assert cfg["classified_dir"] == str(tmp_path / "Classified")
    assert cfg["managed_dir"] == str(tmp_path / "Managed")


def test_derive_workspace_dirs_returns_siblings(tmp_path):
    inbox = tmp_path / "ToSort"
    paths = derive_workspace_dirs(inbox)
    assert paths["inbox_dir"] == str(inbox.resolve(strict=False))
    assert paths["classified_dir"] == str((tmp_path / "Classified").resolve(strict=False))
    assert paths["managed_dir"] == str((tmp_path / "Managed").resolve(strict=False))


def test_ensure_app_directories_creates_internal_subdirs(tmp_path):
    root = tmp_path / "AppData"
    cfg = {"data_dir": str(root)}
    created = ensure_app_directories(cfg)
    for sub in [".thumbcache", ".runtime", "logs"]:
        assert (root / sub).exists(), f"{sub} not created"
    assert len(created) == 3


def test_ensure_workspace_directories_creates_workspace_dirs(tmp_path):
    cfg = {
        "inbox_dir": str(tmp_path / "InboxSelected"),
        "classified_dir": str(tmp_path / "Classified"),
        "managed_dir": str(tmp_path / "Managed"),
    }
    created = ensure_workspace_directories(cfg)
    assert Path(cfg["inbox_dir"]).exists()
    assert Path(cfg["classified_dir"]).exists()
    assert Path(cfg["managed_dir"]).exists()
    assert len(created) == 3


def test_ensure_archive_directories_idempotent(tmp_path):
    """호환 래퍼를 두 번 호출해도 추가 생성이 없다."""
    root = tmp_path / "AppData"
    cfg = {
        "data_dir": str(root),
        "inbox_dir": str(tmp_path / "InboxSelected"),
        "classified_dir": str(tmp_path / "Classified"),
        "managed_dir": str(tmp_path / "Managed"),
    }
    ensure_archive_directories(cfg)
    created2 = ensure_archive_directories(cfg)
    assert created2 == []


def test_ensure_app_directories_empty_data_dir():
    """data_dir가 비어 있으면 빈 리스트를 반환한다."""
    assert ensure_app_directories({"data_dir": ""}) == []


def test_load_config_preserves_extra_fields(tmp_path):
    """기존 config에 있는 추가 필드가 load 후에도 유지된다."""
    p = tmp_path / "config.json"
    data = {"schema_version": "1.0", "data_dir": "/foo", "extra_key": "extra_value"}
    p.write_text(json.dumps(data), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["extra_key"] == "extra_value"
    assert cfg["data_dir"] == "/foo"


def test_resolve_data_dir_falls_back_when_drive_is_missing(monkeypatch, tmp_path):
    fallback = tmp_path / "home"
    monkeypatch.setattr("core.config_manager.Path.home", lambda: fallback)
    monkeypatch.setattr("core.config_manager._has_missing_windows_drive", lambda path: True)

    resolved = resolve_data_dir(r"F:\Aru_Archive")

    assert resolved == (fallback / "AruArchive").resolve(strict=False)


def test_normalize_archive_config_rebases_paths_when_root_drive_is_missing(monkeypatch, tmp_path):
    fallback = tmp_path / "home"
    monkeypatch.setattr("core.config_manager.Path.home", lambda: fallback)
    monkeypatch.setattr(
        "core.config_manager._has_missing_windows_drive",
        lambda path: str(path).startswith("F:\\"),
    )

    cfg = {
        "data_dir": r"F:\Aru_Archive",
        "inbox_dir": r"F:\Aru_Archive\Inbox",
        "classified_dir": r"F:\Aru_Archive\Classified",
        "managed_dir": r"F:\Aru_Archive\Managed",
        "db": {"path": r"F:\Aru_Archive\.runtime\aru.db"},
    }

    normalize_archive_config(cfg)

    new_root = (fallback / "AruArchive").resolve(strict=False)
    assert cfg["data_dir"] == str(new_root)
    assert cfg["inbox_dir"] == str((new_root / "Inbox").resolve(strict=False))
    assert cfg["classified_dir"] == str((new_root / "Classified").resolve(strict=False))
    assert cfg["managed_dir"] == str((new_root / "Managed").resolve(strict=False))
    assert cfg["db"]["path"] == str((new_root / ".runtime" / "aru.db").resolve(strict=False))
