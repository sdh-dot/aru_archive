"""
core/exiftool_resolver.validate_exiftool_bundle 테스트.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.exiftool_resolver import validate_exiftool_bundle


def _make_bundle(base: Path, *, with_exe: bool = True, exe_name: str = "exiftool.exe",
                 with_files: bool = True) -> Path:
    et_dir = base / "tools" / "exiftool"
    et_dir.mkdir(parents=True, exist_ok=True)
    if with_exe:
        (et_dir / exe_name).touch()
    if with_files:
        (et_dir / "exiftool_files").mkdir(exist_ok=True)
    return et_dir


class TestValidateExiftoolBundle:
    def test_ok_when_everything_present(self, tmp_path):
        _make_bundle(tmp_path)
        with patch("core.exiftool.get_exiftool_version", return_value="12.50"):
            result = validate_exiftool_bundle(tmp_path)

        assert result["ok"] is True
        assert result["exiftool_path"] is not None
        assert result["has_exiftool_files"] is True
        assert result["version"] == "12.50"
        assert result["warnings"] == []

    def test_missing_exe_sets_ok_false(self, tmp_path):
        _make_bundle(tmp_path, with_exe=False)
        result = validate_exiftool_bundle(tmp_path)

        assert result["ok"] is False
        assert result["exiftool_path"] is None
        assert any("exiftool.exe" in w for w in result["warnings"])

    def test_missing_exiftool_files_sets_ok_false(self, tmp_path):
        _make_bundle(tmp_path, with_files=False)
        with patch("core.exiftool.get_exiftool_version", return_value="12.50"):
            result = validate_exiftool_bundle(tmp_path)

        assert result["ok"] is False
        assert result["has_exiftool_files"] is False
        assert any("exiftool_files" in w for w in result["warnings"])

    def test_k_variant_found_with_warning(self, tmp_path):
        _make_bundle(tmp_path, exe_name="exiftool(-k).exe")
        with patch("core.exiftool.get_exiftool_version", return_value="12.50"):
            result = validate_exiftool_bundle(tmp_path)

        assert result["exiftool_path"] is not None
        assert result["exiftool_path"].endswith("exiftool.exe")
        assert result["warnings"] == []

    def test_version_check_failure_adds_warning(self, tmp_path):
        _make_bundle(tmp_path)
        with patch("core.exiftool.get_exiftool_version", return_value=None):
            result = validate_exiftool_bundle(tmp_path)

        assert result["version"] is None
        assert any("버전 확인" in w for w in result["warnings"])

    def test_uses_get_app_base_path_when_base_dir_none(self, tmp_path):
        _make_bundle(tmp_path)
        with patch("core.exiftool_resolver.get_app_base_path", return_value=tmp_path), \
             patch("core.exiftool.get_exiftool_version", return_value="12.60"):
            result = validate_exiftool_bundle(None)

        assert result["ok"] is True

    def test_completely_empty_dir(self, tmp_path):
        result = validate_exiftool_bundle(tmp_path)
        assert result["ok"] is False
        assert result["exiftool_path"] is None
        assert result["has_exiftool_files"] is False
        assert len(result["warnings"]) >= 1

    def test_result_keys_always_present(self, tmp_path):
        result = validate_exiftool_bundle(tmp_path)
        for key in ("ok", "exiftool_path", "has_exiftool_files", "version", "warnings"):
            assert key in result
