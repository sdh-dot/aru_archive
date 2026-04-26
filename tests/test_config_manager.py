"""core/config_manager 단위 테스트."""
from __future__ import annotations

import json
from pathlib import Path

from core.config_manager import (
    ensure_archive_directories,
    load_config,
    save_config,
    update_archive_root,
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


def test_update_archive_root_sets_derived_paths(tmp_path):
    """Archive Root 업데이트 시 data_dir/inbox_dir/classified_dir를 갱신한다."""
    cfg: dict = {}
    root = str(tmp_path / "ArchiveRoot")
    update_archive_root(cfg, root)
    assert cfg["data_dir"] == root
    assert cfg["inbox_dir"] == str(tmp_path / "ArchiveRoot" / "Inbox")
    assert cfg["classified_dir"] == str(tmp_path / "ArchiveRoot" / "Classified")


def test_update_archive_root_sets_db_path_if_empty(tmp_path):
    """db.path가 비어 있으면 .runtime/aru.db로 채운다."""
    cfg: dict = {"db": {"path": ""}}
    root = str(tmp_path / "Root")
    update_archive_root(cfg, root)
    assert cfg["db"]["path"] == str(tmp_path / "Root" / ".runtime" / "aru.db")


def test_update_archive_root_preserves_existing_db_path(tmp_path):
    """db.path가 이미 설정돼 있으면 덮어쓰지 않는다."""
    existing_db = str(tmp_path / "custom.db")
    cfg: dict = {"db": {"path": existing_db}}
    update_archive_root(cfg, str(tmp_path / "Root"))
    assert cfg["db"]["path"] == existing_db


def test_ensure_archive_directories_creates_subdirs(tmp_path):
    """ensure_archive_directories() 호출 시 필수 폴더가 모두 생성된다."""
    root = tmp_path / "ArchRoot"
    root.mkdir()
    cfg = {"data_dir": str(root)}
    created = ensure_archive_directories(cfg)
    for sub in ["Inbox", "Classified", "Managed", ".thumbcache", ".runtime"]:
        assert (root / sub).exists(), f"{sub} not created"
    assert len(created) == 5


def test_ensure_archive_directories_idempotent(tmp_path):
    """폴더가 이미 있으면 created 목록은 빈 리스트를 반환한다."""
    root = tmp_path / "ArchRoot"
    root.mkdir()
    cfg = {"data_dir": str(root)}
    ensure_archive_directories(cfg)
    created2 = ensure_archive_directories(cfg)
    assert created2 == []


def test_ensure_archive_directories_empty_data_dir():
    """data_dir가 비어 있으면 빈 리스트를 반환한다."""
    cfg = {"data_dir": ""}
    result = ensure_archive_directories(cfg)
    assert result == []


def test_load_config_preserves_extra_fields(tmp_path):
    """기존 config에 있는 추가 필드가 load 후에도 유지된다."""
    p = tmp_path / "config.json"
    data = {"schema_version": "1.0", "data_dir": "/foo", "extra_key": "extra_value"}
    p.write_text(json.dumps(data), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["extra_key"] == "extra_value"
    assert cfg["data_dir"] == "/foo"
