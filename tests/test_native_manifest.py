"""
native_host manifest 구조 검증 및 gen_manifest.py 단위 테스트.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_PROJECT = Path(__file__).resolve().parent.parent


def _load_gen_manifest():
    """build/gen_manifest.py를 동적으로 임포트한다."""
    spec = importlib.util.spec_from_file_location(
        "gen_manifest", _PROJECT / "build" / "gen_manifest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 정적 manifest 파일 구조 검증
# ---------------------------------------------------------------------------

class TestStaticManifests:
    """native_host/manifest_*.json 의 필수 필드를 확인한다."""

    @pytest.fixture(params=["manifest_chrome.json", "manifest_whale.json"])
    def manifest(self, request):
        path = _PROJECT / "native_host" / request.param
        return json.loads(path.read_text(encoding="utf-8")), request.param

    def test_name(self, manifest):
        data, _ = manifest
        assert data["name"] == "net.aru_archive.host"

    def test_type_stdio(self, manifest):
        data, _ = manifest
        assert data["type"] == "stdio"

    def test_allowed_origins_present(self, manifest):
        data, _ = manifest
        assert len(data["allowed_origins"]) >= 1

    def test_chrome_origin_scheme(self):
        data = json.loads(
            (_PROJECT / "native_host" / "manifest_chrome.json").read_text(encoding="utf-8")
        )
        assert data["allowed_origins"][0].startswith("chrome-extension://")

    def test_whale_origin_scheme(self):
        data = json.loads(
            (_PROJECT / "native_host" / "manifest_whale.json").read_text(encoding="utf-8")
        )
        assert data["allowed_origins"][0].startswith("naver-extension://")


# ---------------------------------------------------------------------------
# gen_manifest.py 단위 테스트
# ---------------------------------------------------------------------------

class TestGenManifest:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = _load_gen_manifest()

    def test_chrome_origin(self, tmp_path):
        host = str(tmp_path / "host.bat")
        m = self.mod.make_manifest(host, "chrome", "abcdef1234567890abcdef1234567890")
        assert m["allowed_origins"] == ["chrome-extension://abcdef1234567890abcdef1234567890/"]

    def test_whale_origin(self, tmp_path):
        host = str(tmp_path / "host.bat")
        m = self.mod.make_manifest(host, "whale", "xyz9876")
        assert m["allowed_origins"] == ["naver-extension://xyz9876/"]

    def test_path_is_set(self, tmp_path):
        host = str(tmp_path / "host.bat")
        m = self.mod.make_manifest(host, "chrome", "abc")
        assert m["path"] == host

    def test_required_fields(self, tmp_path):
        host = str(tmp_path / "host.bat")
        m = self.mod.make_manifest(host, "chrome", "abc")
        assert m["name"]  == "net.aru_archive.host"
        assert m["type"]  == "stdio"

    def test_unknown_browser_raises(self, tmp_path):
        host = str(tmp_path / "host.bat")
        with pytest.raises(ValueError, match="지원하지 않는"):
            self.mod.make_manifest(host, "firefox", "abc")

    def test_output_file_written(self, tmp_path):
        host    = str(tmp_path / "host.bat")
        outfile = tmp_path / "manifest.json"
        import sys
        saved_argv = sys.argv[:]
        try:
            sys.argv = [
                "gen_manifest.py",
                host,
                "chrome",
                "testid123",
                str(outfile),
            ]
            ret = self.mod.main()
        finally:
            sys.argv = saved_argv

        assert ret == 0
        assert outfile.exists()
        data = json.loads(outfile.read_text(encoding="utf-8"))
        assert data["allowed_origins"] == ["chrome-extension://testid123/"]
        assert data["path"] == host
