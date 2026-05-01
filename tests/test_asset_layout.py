"""Asset relocation 회귀 가드.

docs/ 하위 runtime asset이 assets/ 하위로 이동했는지, docs/ 문서 이미지는
그대로 유지되는지 검증.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestRuntimeAssetsRelocated:
    def test_splash_at_assets_splash(self):
        p = REPO_ROOT / "assets" / "splash" / "splash.png"
        assert p.exists(), f"assets/splash/splash.png 누락: {p}"

    def test_icon_source_1_at_assets_icon_source(self):
        p = REPO_ROOT / "assets" / "icon" / "source" / "icon_1.png"
        assert p.exists()

    def test_icon_source_02_at_assets_icon_source(self):
        p = REPO_ROOT / "assets" / "icon" / "source" / "icon_02.png"
        assert p.exists()


class TestRuntimeAssetsRemovedFromDocs:
    def test_splash_no_longer_in_docs(self):
        p = REPO_ROOT / "docs" / "splash.png"
        assert not p.exists(), "docs/splash.png은 assets/splash/로 이동했어야 함"

    def test_icon_1_no_longer_in_docs(self):
        p = REPO_ROOT / "docs" / "icon_1.png"
        assert not p.exists()

    def test_icon_02_no_longer_in_docs(self):
        p = REPO_ROOT / "docs" / "icon_02.png"
        assert not p.exists()


class TestDocsImagesPreserved:
    def test_icon_01_remains_in_docs(self):
        """README가 참조하는 docs/icon_01.png은 그대로 유지."""
        p = REPO_ROOT / "docs" / "icon_01.png"
        assert p.exists()

    def test_icon_png_remains_in_docs(self):
        """packaging.md 언급 docs/icon.png은 그대로 유지."""
        p = REPO_ROOT / "docs" / "icon.png"
        assert p.exists()


class TestExistingIconAssetsUnchanged:
    def test_aru_archive_icon_ico_present(self):
        p = REPO_ROOT / "assets" / "icon" / "aru_archive_icon.ico"
        assert p.exists()

    def test_aru_archive_icon_master_present(self):
        p = REPO_ROOT / "assets" / "icon" / "aru_archive_icon_master.png"
        assert p.exists()
