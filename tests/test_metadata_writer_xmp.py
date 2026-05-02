"""Tests for ExifTool-backed XMP writing."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.exiftool import build_exiftool_xmp_args
from core.metadata_writer import XmpWriteError, write_xmp_metadata_with_exiftool


SAMPLE_META = {
    "artwork_title": "테스트 작품",
    "artist_name": "테스트 작가",
    "artwork_url": "https://www.pixiv.net/artworks/99999",
    "artwork_id": "99999",
    "source_site": "pixiv",
    "tags": ["오리지널", "배경"],
    "series_tags": [],
    "character_tags": [],
}


def test_none_exiftool_path_returns_false():
    assert write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, exiftool_path=None) is False


def test_empty_exiftool_path_returns_false():
    assert write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, exiftool_path="") is False


def test_invalid_exiftool_path_returns_false():
    with patch("core.exiftool.validate_exiftool_path", return_value=False):
        assert write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/bad/path") is False


def test_subprocess_success_returns_true():
    mock_result = MagicMock(returncode=0)
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result),
    ):
        assert write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool") is True


def test_subprocess_called_with_list_not_shell():
    mock_result = MagicMock(returncode=0)
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    args_list = mock_run.call_args[0][0]
    assert isinstance(args_list, list)
    assert mock_run.call_args[1].get("shell", False) is False


def test_file_path_with_spaces():
    mock_result = MagicMock(returncode=0)
    file_path = "/tmp/my test file with spaces.jpg"
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        assert write_xmp_metadata_with_exiftool(file_path, SAMPLE_META, "/usr/bin/exiftool") is True
    assert mock_run.call_args[0][0][-1] == file_path


def test_misnamed_webp_disables_xp_and_image_description(tmp_path: Path):
    file_path = tmp_path / "mismatch.jpg"
    file_path.write_bytes(
        b"RIFF" + (14).to_bytes(4, "little") + b"WEBP" + b"VP8 " + b"\x00\x00\x00\x00"
    )
    mock_result = MagicMock(returncode=0)
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = write_xmp_metadata_with_exiftool(str(file_path), SAMPLE_META, "/usr/bin/exiftool")
    assert result is False
    mock_run.assert_not_called()


def test_existing_file_success_path_writes_no_xp_args_in_exiftool_call(tmp_path: Path):
    file_path = tmp_path / "real.jpg"
    file_path.write_bytes(b"\xff\xd8\xff\xd9")
    mock_result = MagicMock(returncode=0)
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result) as mock_run,
        patch("core.metadata_writer._write_windows_exif_fields_best_effort") as mock_xp,
    ):
        assert write_xmp_metadata_with_exiftool(str(file_path), SAMPLE_META, "/usr/bin/exiftool") is True
    args_list = mock_run.call_args[0][0]
    assert not any("XPTitle" in a for a in args_list)
    assert not any("XPKeywords" in a for a in args_list)
    mock_xp.assert_called_once()


def test_nonzero_returncode_raises_xmp_write_error():
    mock_result = MagicMock(returncode=1, stderr=b"ExifTool: some error", stdout=b"")
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result),
    ):
        with pytest.raises(XmpWriteError) as exc_info:
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert "returncode=1" in str(exc_info.value)


def test_error_message_includes_stderr():
    mock_result = MagicMock(returncode=2, stderr=b"Error: file not writable", stdout=b"")
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result),
    ):
        with pytest.raises(XmpWriteError) as exc_info:
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert "file not writable" in str(exc_info.value)


def test_timeout_raises_xmp_write_error():
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch(
            "core.metadata_writer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=60),
        ),
    ):
        with pytest.raises(XmpWriteError):
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")


def test_os_error_wrapped_as_xmp_write_error():
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", side_effect=OSError("permission denied")),
    ):
        with pytest.raises(XmpWriteError) as exc_info:
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert "permission denied" in str(exc_info.value)


def test_non_ascii_xmp_title_creator_and_subject_are_cleared():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert "-XMP-dc:Title=" in args
    assert "-XMP-dc:Creator=" in args
    assert "-XMP-dc:Subject=" in args
    assert not any(a.startswith("-XMP-dc:Title=") and a != "-XMP-dc:Title=" for a in args)
    assert not any(a.startswith("-XMP-dc:Creator=") and a != "-XMP-dc:Creator=" for a in args)


def test_ascii_xmp_text_fields_are_kept():
    meta = {
        **SAMPLE_META,
        "artwork_title": "Hasumi",
        "artist_name": "rikiddo",
        "tags": ["Blue Archive", "Swimsuit"],
        "series_tags": ["Trinity"],
        "character_tags": [],
    }
    args = build_exiftool_xmp_args("/tmp/test.jpg", meta)
    assert "-XMP-dc:Title=Hasumi" in args
    assert "-XMP-dc:Creator=rikiddo" in args
    assert "-XMP-dc:Subject=Blue Archive" in args
    assert "-XMP-dc:Subject=Swimsuit" in args
    assert "-XMP-dc:Subject=Trinity" in args


def test_xmp_write_error_is_exception():
    exc = XmpWriteError("test")
    assert isinstance(exc, Exception)
    assert str(exc) == "test"
