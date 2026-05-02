"""Windows Explorer-facing EXIF XP field tests."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from core.exiftool import build_exiftool_xp_args, read_exif_diagnostics
from core.metadata_writer import write_aru_metadata, write_windows_exif_fields


_META = {
    "artwork_title": "Nagisa",
    "artist_name": "Shigure@FANBOX",
    "tags": ["mizugi", "beach"],
    "series_tags": ["Blue Archive"],
    "character_tags": ["Nagisa"],
}


def _minimal_jpeg(path: Path) -> Path:
    from PIL import Image

    img = Image.new("RGB", (1, 1), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())
    return path


class TestBuildExiftoolXpArgs:
    def test_charset_utf8_present(self):
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        assert "-charset" in args
        assert "exif=utf8" in args

    def test_xptitle_written(self):
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        assert any("XPTitle=Nagisa" in a for a in args)

    def test_xpauthor_written(self):
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        assert any("XPAuthor=Shigure@FANBOX" in a for a in args)

    def test_xpkeywords_uses_only_tags_as_single_semicolon_string(self):
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        kw_args = [a for a in args if a.startswith("-EXIF:XPKeywords=")]
        assert kw_args == ["-EXIF:XPKeywords=mizugi;beach"]

    def test_no_xpkeywords_when_tags_empty(self):
        args = build_exiftool_xp_args(
            "/tmp/a.jpg",
            {"tags": [], "series_tags": ["Blue Archive"], "character_tags": ["Nagisa"]},
        )
        assert not any("XPKeywords" in a for a in args)


class TestReadExifDiagnostics:
    def test_missing_xp_fields_warning(self, tmp_path: Path):
        jpg = _minimal_jpeg(tmp_path / "plain.jpg")
        result = read_exif_diagnostics(str(jpg))
        assert result["exif_xptitle"] is None
        assert result["exif_xpkeywords"] is None
        warn_text = " ".join(result["warnings"])
        assert "XPTitle" in warn_text or "XPKeywords" in warn_text

    def test_aru_metadata_detected_after_write(self, tmp_path: Path):
        pytest.importorskip("piexif")
        jpg = _minimal_jpeg(tmp_path / "aru.jpg")
        meta = {"schema_version": "1.0", "artwork_id": "test", "artwork_title": "Nagisa"}
        write_aru_metadata(str(jpg), meta, "jpg")
        result = read_exif_diagnostics(str(jpg))
        assert result["has_aru_metadata"] is True
        assert "UNICODE" in (result["exif_user_comment_prefix"] or "")


class TestWriteWindowsExifFields:
    def test_returns_false_when_no_exiftool(self, tmp_path: Path):
        jpg = _minimal_jpeg(tmp_path / "noxmp.jpg")
        assert write_windows_exif_fields(str(jpg), _META, exiftool_path=None) is False

    def test_returns_false_when_invalid_exiftool_path(self, tmp_path: Path):
        jpg = _minimal_jpeg(tmp_path / "noxmp2.jpg")
        assert (
            write_windows_exif_fields(str(jpg), _META, exiftool_path="/nonexistent/exiftool")
            is False
        )
