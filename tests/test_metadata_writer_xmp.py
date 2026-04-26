"""tests/test_metadata_writer_xmp.py — write_xmp_metadata_with_exiftool 단위 테스트."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from core.metadata_writer import XmpWriteError, write_xmp_metadata_with_exiftool


SAMPLE_META = {
    "artwork_title": "테스트 작품",
    "artist_name": "테스트 작가",
    "artwork_url": "https://www.pixiv.net/artworks/99999",
    "artwork_id": "99999",
    "source_site": "pixiv",
    "tags": ["오리지널", "풍경"],
    "series_tags": [],
    "character_tags": [],
}


# ---------------------------------------------------------------------------
# exiftool_path=None → False (no XMP, no ExifTool)
# ---------------------------------------------------------------------------

def test_none_exiftool_path_returns_false():
    result = write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, exiftool_path=None)
    assert result is False


def test_empty_exiftool_path_returns_false():
    result = write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, exiftool_path="")
    assert result is False


# ---------------------------------------------------------------------------
# validate_exiftool_path 실패 → False 반환 (예외 없음)
# ---------------------------------------------------------------------------

def test_invalid_exiftool_path_returns_false():
    with patch("core.exiftool.validate_exiftool_path", return_value=False):
        result = write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/bad/path")
    assert result is False


# ---------------------------------------------------------------------------
# subprocess 성공 → True
# ---------------------------------------------------------------------------

def test_subprocess_success_returns_true():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result),
    ):
        result = write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert result is True


def test_subprocess_called_with_list_not_shell():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    call_kwargs = mock_run.call_args
    assert call_kwargs is not None
    # 인자는 리스트여야 하며, shell=True가 아니어야 함
    args_list = call_kwargs[0][0]
    assert isinstance(args_list, list)
    assert call_kwargs[1].get("shell", False) is False


def test_file_path_with_spaces():
    mock_result = MagicMock()
    mock_result.returncode = 0
    file_path = "/tmp/my test file with spaces.jpg"
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = write_xmp_metadata_with_exiftool(file_path, SAMPLE_META, "/usr/bin/exiftool")
    assert result is True
    args_list = mock_run.call_args[0][0]
    assert args_list[-1] == file_path


# ---------------------------------------------------------------------------
# subprocess returncode != 0 → XmpWriteError
# ---------------------------------------------------------------------------

def test_nonzero_returncode_raises_xmp_write_error():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = b"ExifTool: some error"
    mock_result.stdout = b""
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result),
    ):
        with pytest.raises(XmpWriteError) as exc_info:
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert "returncode=1" in str(exc_info.value)


def test_error_message_includes_stderr():
    mock_result = MagicMock()
    mock_result.returncode = 2
    mock_result.stderr = b"Error: file not writable"
    mock_result.stdout = b""
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", return_value=mock_result),
    ):
        with pytest.raises(XmpWriteError) as exc_info:
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert "file not writable" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TimeoutExpired → XmpWriteError
# ---------------------------------------------------------------------------

def test_timeout_raises_xmp_write_error():
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch(
            "core.metadata_writer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=60),
        ),
    ):
        with pytest.raises(XmpWriteError) as exc_info:
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert "타임아웃" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 기타 예외 → XmpWriteError로 래핑
# ---------------------------------------------------------------------------

def test_os_error_wrapped_as_xmp_write_error():
    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch(
            "core.metadata_writer.subprocess.run",
            side_effect=OSError("permission denied"),
        ),
    ):
        with pytest.raises(XmpWriteError) as exc_info:
            write_xmp_metadata_with_exiftool("/tmp/test.jpg", SAMPLE_META, "/usr/bin/exiftool")
    assert "permission denied" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Subject 태그 포함 확인 (tags + series_tags + character_tags)
# ---------------------------------------------------------------------------

def test_xmp_subject_includes_all_tag_types():
    meta = {
        **SAMPLE_META,
        "tags": ["오리지널"],
        "series_tags": ["Blue Archive"],
        "character_tags": ["陸八魔アル"],
    }
    mock_result = MagicMock()
    mock_result.returncode = 0
    captured_args = []

    def capture_run(args, **kwargs):
        captured_args.extend(args)
        return mock_result

    with (
        patch("core.exiftool.validate_exiftool_path", return_value=True),
        patch("core.metadata_writer.subprocess.run", side_effect=capture_run),
    ):
        write_xmp_metadata_with_exiftool("/tmp/test.jpg", meta, "/usr/bin/exiftool")

    subjects = [a for a in captured_args if "XMP-dc:Subject" in a]
    subject_values = [a.split("=", 1)[1] for a in subjects]
    assert "오리지널" in subject_values
    assert "Blue Archive" in subject_values
    assert "陸八魔アル" in subject_values


# ---------------------------------------------------------------------------
# XmpWriteError는 Exception 서브클래스
# ---------------------------------------------------------------------------

def test_xmp_write_error_is_exception():
    exc = XmpWriteError("test")
    assert isinstance(exc, Exception)
    assert str(exc) == "test"
