"""
PyInstaller spec 파일에 tools/exiftool가 포함되어 있는지 검증.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parent.parent / "build" / "aru_archive.spec"


class TestPyinstallerSpecExiftool:
    def test_spec_file_exists(self):
        assert SPEC_PATH.exists(), f"spec 파일 없음: {SPEC_PATH}"

    def test_spec_includes_tools_exiftool(self):
        content = SPEC_PATH.read_text(encoding="utf-8")
        assert "tools/exiftool" in content or "tools\\exiftool" in content, (
            "spec 파일에 tools/exiftool 항목이 없습니다."
        )

    def test_spec_has_datas_section(self):
        content = SPEC_PATH.read_text(encoding="utf-8")
        assert "datas=[" in content or "datas =" in content

    def test_spec_exiftool_is_in_datas_not_binaries(self):
        content = SPEC_PATH.read_text(encoding="utf-8")
        # datas 섹션에 exiftool 포함 여부 (binaries 섹션 아님)
        datas_start = content.find("datas=[")
        if datas_start == -1:
            pytest.skip("datas 섹션 파싱 불가")
        datas_end = content.find("],", datas_start)
        datas_section = content[datas_start:datas_end]
        assert "tools/exiftool" in datas_section or "tools\\exiftool" in datas_section
