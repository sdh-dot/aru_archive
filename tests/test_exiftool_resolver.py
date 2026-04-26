"""
core/exiftool_resolver.py 테스트.

resolve_exiftool_path, find_bundled_exiftool, get_app_base_path 동작 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from core.exiftool_resolver import (
    find_bundled_exiftool,
    get_app_base_path,
    resolve_exiftool_path,
)


# ---------------------------------------------------------------------------
# get_app_base_path
# ---------------------------------------------------------------------------

class TestGetAppBasePath:
    def test_returns_path_object(self):
        base = get_app_base_path()
        assert isinstance(base, Path)

    def test_dev_env_is_project_root(self):
        base = get_app_base_path()
        # 개발 환경: exiftool_resolver.py가 core/ 아래 → 부모의 부모 = 프로젝트 루트
        assert (base / "core" / "exiftool_resolver.py").exists()

    def test_frozen_onefile_uses_meipass(self, tmp_path):
        fake_meipass = str(tmp_path / "meipass")
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", fake_meipass, create=True):
            base = get_app_base_path()
        assert base == Path(fake_meipass)

    def test_frozen_onedir_uses_exe_parent(self, tmp_path):
        fake_exe = tmp_path / "AruArchive" / "aru_archive.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.touch()
        with patch.object(sys, "frozen", True, create=True), \
             patch("sys.executable", str(fake_exe)), \
             patch("sys._MEIPASS", None, create=True):
            base = get_app_base_path()
        # _MEIPASS가 None이면 exe 부모를 사용
        assert base == fake_exe.parent


# ---------------------------------------------------------------------------
# find_bundled_exiftool
# ---------------------------------------------------------------------------

class TestFindBundledExiftool:
    def test_finds_exiftool_exe(self, tmp_path):
        et_dir = tmp_path / "tools" / "exiftool"
        et_dir.mkdir(parents=True)
        et_exe = et_dir / "exiftool.exe"
        et_exe.touch()

        with patch("core.exiftool_resolver.get_app_base_path", return_value=tmp_path):
            result = find_bundled_exiftool()

        assert result == str(et_exe)

    def test_finds_exiftool_k_exe_as_fallback(self, tmp_path):
        et_dir = tmp_path / "tools" / "exiftool"
        et_dir.mkdir(parents=True)
        et_k = et_dir / "exiftool(-k).exe"
        et_k.write_bytes(b"fake exe")

        with patch("core.exiftool_resolver.get_app_base_path", return_value=tmp_path):
            result = find_bundled_exiftool()

        assert result == str(et_dir / "exiftool.exe")
        assert (et_dir / "exiftool.exe").read_bytes() == b"fake exe"

    def test_prefers_exiftool_exe_over_k_variant(self, tmp_path):
        et_dir = tmp_path / "tools" / "exiftool"
        et_dir.mkdir(parents=True)
        et_exe = et_dir / "exiftool.exe"
        et_k   = et_dir / "exiftool(-k).exe"
        et_exe.touch()
        et_k.touch()

        with patch("core.exiftool_resolver.get_app_base_path", return_value=tmp_path):
            result = find_bundled_exiftool()

        assert result == str(et_exe)

    def test_returns_none_when_not_found(self, tmp_path):
        with patch("core.exiftool_resolver.get_app_base_path", return_value=tmp_path):
            result = find_bundled_exiftool()

        assert result is None

    def test_no_tools_dir(self, tmp_path):
        with patch("core.exiftool_resolver.get_app_base_path", return_value=tmp_path):
            result = find_bundled_exiftool()
        assert result is None


# ---------------------------------------------------------------------------
# resolve_exiftool_path
# ---------------------------------------------------------------------------

class TestResolveExiftoolPath:
    def test_config_path_takes_priority(self, tmp_path):
        et = tmp_path / "my_exiftool.exe"
        et.touch()
        config = {"exiftool_path": str(et)}

        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=None), \
             patch("shutil.which", return_value=None):
            result = resolve_exiftool_path(config)

        assert result == str(et)

    def test_config_path_missing_falls_back_to_bundled(self, tmp_path):
        bundled = tmp_path / "tools" / "exiftool" / "exiftool.exe"
        config = {"exiftool_path": "/nonexistent/exiftool.exe"}

        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=str(bundled)):
            result = resolve_exiftool_path(config)

        assert result == str(bundled)

    def test_null_config_path_uses_bundled(self, tmp_path):
        bundled = tmp_path / "exiftool.exe"
        bundled.touch()
        config = {"exiftool_path": None}

        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=str(bundled)):
            result = resolve_exiftool_path(config)

        assert result == str(bundled)

    def test_auto_config_path_uses_bundled(self, tmp_path):
        bundled = tmp_path / "exiftool.exe"
        bundled.touch()
        config = {"exiftool_path": "auto"}

        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=str(bundled)):
            result = resolve_exiftool_path(config)

        assert result == str(bundled)

    def test_empty_config_path_uses_bundled(self):
        config = {"exiftool_path": ""}
        fake_bundled = "/fake/exiftool.exe"

        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=fake_bundled):
            result = resolve_exiftool_path(config)

        assert result == fake_bundled

    def test_none_config_uses_bundled(self):
        fake_bundled = "/fake/exiftool.exe"
        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=fake_bundled):
            result = resolve_exiftool_path(None)
        assert result == fake_bundled

    def test_path_fallback_when_no_bundled(self):
        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=None), \
             patch("shutil.which", return_value="/usr/bin/exiftool"):
            result = resolve_exiftool_path(None)
        assert result == "/usr/bin/exiftool"

    def test_returns_none_when_nothing_found(self):
        with patch("core.exiftool_resolver.find_bundled_exiftool", return_value=None), \
             patch("shutil.which", return_value=None):
            result = resolve_exiftool_path(None)
        assert result is None

    def test_frozen_onefile_meipass_bundled(self, tmp_path):
        fake_meipass = tmp_path / "meipass"
        et_dir = fake_meipass / "tools" / "exiftool"
        et_dir.mkdir(parents=True)
        et_exe = et_dir / "exiftool.exe"
        et_exe.touch()

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", str(fake_meipass), create=True):
            result = resolve_exiftool_path(None)

        assert result == str(et_exe)
