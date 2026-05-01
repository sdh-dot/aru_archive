"""Icon asset existence and integrity checks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------

class TestIconFilesExist:
    def test_source_icon(self):
        assert (ROOT / "assets" / "icon" / "source" / "icon_1.png").is_file()

    def test_master_png(self):
        assert (ROOT / "assets" / "icon" / "aru_archive_icon_master.png").is_file()

    def test_ico(self):
        assert (ROOT / "assets" / "icon" / "aru_archive_icon.ico").is_file()

    def test_docs_icon(self):
        assert (ROOT / "docs" / "icon.png").is_file()

    @pytest.mark.parametrize("size", [1024, 512, 256, 128, 64, 48, 32, 16])
    def test_png_size_set(self, size: int):
        assert (ROOT / "assets" / "icon" / f"aru_archive_icon_{size}.png").is_file()

    @pytest.mark.parametrize("size", [16, 32, 48, 128])
    def test_extension_icons(self, size: int):
        assert (ROOT / "extension" / "icons" / f"icon{size}.png").is_file()


# ---------------------------------------------------------------------------
# Alpha channel
# ---------------------------------------------------------------------------

class TestIconAlpha:
    def test_master_has_alpha(self):
        pytest.importorskip("PIL")
        from PIL import Image
        img = Image.open(ROOT / "assets" / "icon" / "aru_archive_icon_master.png")
        assert "A" in img.mode, "master PNG must have an alpha channel"

    def test_master_has_transparent_background(self):
        pytest.importorskip("PIL")
        from PIL import Image
        img = Image.open(ROOT / "assets" / "icon" / "aru_archive_icon_master.png")
        assert "A" in img.mode
        alpha = img.getchannel("A")
        w, h = img.size
        # All four corners must be fully transparent
        for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
            assert alpha.getpixel((x, y)) == 0, f"Corner ({x},{y}) is not transparent"

    def test_master_has_opaque_pixels(self):
        pytest.importorskip("PIL")
        from PIL import Image
        img = Image.open(ROOT / "assets" / "icon" / "aru_archive_icon_master.png")
        assert "A" in img.mode
        alpha = img.getchannel("A")
        pixels = list(alpha.getdata())
        opaque = sum(1 for p in pixels if p == 255)
        assert opaque > 0, "master PNG has no fully opaque pixels (character missing?)"


# ---------------------------------------------------------------------------
# Extension manifest icon paths
# ---------------------------------------------------------------------------

class TestExtensionManifestIcons:
    def _manifest(self) -> dict:
        manifest_path = ROOT / "extension" / "manifest.json"
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_manifest_icons_section_exists(self):
        manifest = self._manifest()
        assert "icons" in manifest

    @pytest.mark.parametrize("size", ["16", "32", "48", "128"])
    def test_manifest_icon_file_exists(self, size: str):
        manifest = self._manifest()
        icons = manifest.get("icons", {})
        assert size in icons, f"icon size {size} missing from manifest icons"
        rel_path = icons[size]
        assert (ROOT / "extension" / rel_path).is_file(), \
            f"manifest references non-existent file: extension/{rel_path}"

    @pytest.mark.parametrize("size", ["16", "32", "48", "128"])
    def test_manifest_action_icon_file_exists(self, size: str):
        manifest = self._manifest()
        default_icon = manifest.get("action", {}).get("default_icon", {})
        assert size in default_icon, f"action.default_icon missing size {size}"
        rel_path = default_icon[size]
        assert (ROOT / "extension" / rel_path).is_file(), \
            f"action.default_icon references non-existent file: extension/{rel_path}"


# ---------------------------------------------------------------------------
# PyInstaller spec icon path
# ---------------------------------------------------------------------------

class TestSpecIconPath:
    def test_spec_ico_exists(self):
        spec_path = ROOT / "build" / "aru_archive.spec"
        spec_text = spec_path.read_text(encoding="utf-8")
        # spec uses Path operators: ROOT / "assets" / "icon" / "aru_archive_icon.ico"
        assert "aru_archive_icon.ico" in spec_text, \
            "PyInstaller spec does not reference aru_archive_icon.ico"
        assert "assets" in spec_text and "icon" in spec_text, \
            "PyInstaller spec icon path does not use assets/icon directory"
        assert (ROOT / "assets" / "icon" / "aru_archive_icon.ico").is_file(), \
            "assets/icon/aru_archive_icon.ico does not exist"


# ---------------------------------------------------------------------------
# app/resources icon_path
# ---------------------------------------------------------------------------

class TestAppResourcesIconPath:
    def test_icon_path_points_to_existing_file(self):
        from app.resources import icon_path
        path = Path(icon_path())
        assert path.is_file(), f"icon_path() returned non-existent path: {path}"

    def test_icon_path_is_ico(self):
        from app.resources import icon_path
        assert icon_path().endswith(".ico")
