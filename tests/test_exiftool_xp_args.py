"""Tests for ExifTool XP/XMP argument builders."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from core.exiftool import build_exiftool_xmp_args, build_exiftool_xp_args
from core.metadata_writer import _build_user_facing_summary, write_aru_metadata


SAMPLE_META = {
    "schema_version": "1.0",
    "source_site": "pixiv",
    "artwork_id": "12345678",
    "artwork_title": "테스트 작품",
    "artist_name": "작가명",
    "tags": ["오리지널", "배경"],
    "series_tags": ["Blue Archive"],
    "character_tags": ["Arona"],
}

FILE_PATH = "/tmp/test.jpg"


class TestBuildUserFacingSummary:
    def test_summary_contains_basic_identity(self):
        summary = _build_user_facing_summary(SAMPLE_META)
        assert "Aru Archive" in summary
        assert "pixiv" in summary
        assert "12345678" in summary

    def test_empty_source_and_id_returns_empty(self):
        meta = {**SAMPLE_META, "source_site": "", "artwork_id": ""}
        assert _build_user_facing_summary(meta) == ""


class TestBuildExiftoolXpArgs:
    def test_xpsubject_included_when_provided(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_subject="테스트 작품")
        assert "-EXIF:XPSubject=테스트 작품" in args

    def test_xpcomment_included_when_provided(self):
        comment = "Aru Archive: pixiv artwork 12345678"
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_comment=comment)
        assert f"-EXIF:XPComment={comment}" in args

    def test_xpkeywords_use_only_tags(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert "-EXIF:XPKeywords=오리지널;배경" in args
        assert not any("Blue Archive" in a and "XPKeywords" in a for a in args)
        assert not any("Arona" in a and "XPKeywords" in a for a in args)


class TestBuildExiftoolXmpArgs:
    def test_image_description_included_when_summary_provided(self):
        summary = "Aru Archive: pixiv artwork 12345678 — 테스트 작품"
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META, user_facing_summary=summary)
        assert any("EXIF:ImageDescription" in a and summary in a for a in args)

    def test_non_ascii_xmp_text_fields_are_cleared(self):
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META)
        assert "-XMP-dc:Title=" in args
        assert "-XMP-dc:Creator=" in args
        assert "-XMP-dc:Subject=" in args

    def test_ascii_xmp_text_fields_are_preserved(self):
        meta = {
            **SAMPLE_META,
            "artwork_title": "Hasumi",
            "artist_name": "rikiddo",
            "tags": ["fanart", "swimsuit"],
            "series_tags": ["Blue Archive"],
            "character_tags": [],
        }
        args = build_exiftool_xmp_args(FILE_PATH, meta)
        assert "-XMP-dc:Title=Hasumi" in args
        assert "-XMP-dc:Creator=rikiddo" in args
        assert "-XMP-dc:Subject=fanart" in args


class TestUserCommentJsonPreserved:
    def _make_jpeg(self, path: Path) -> Path:
        from PIL import Image

        img = Image.new("RGB", (1, 1), color=(128, 64, 32))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        path.write_bytes(buf.getvalue())
        return path

    def test_user_comment_contains_json_dump(self, tmp_path: Path):
        pytest.importorskip("piexif")
        import piexif

        jpg = self._make_jpeg(tmp_path / "meta.jpg")
        write_aru_metadata(str(jpg), SAMPLE_META, "jpg")

        exif = piexif.load(str(jpg))
        uc = exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b"")
        assert uc.startswith(b"UNICODE\x00")
        parsed = json.loads(uc[8:].decode("utf-16-le"))
        assert parsed["artwork_id"] == "12345678"
