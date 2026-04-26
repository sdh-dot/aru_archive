"""tests/test_exiftool.py — core.exiftool 단위 테스트."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from core.exiftool import (
    build_exiftool_xmp_args,
    get_exiftool_version,
    validate_exiftool_path,
)


# ---------------------------------------------------------------------------
# validate_exiftool_path
# ---------------------------------------------------------------------------

def test_validate_none_returns_false():
    assert validate_exiftool_path(None) is False


def test_validate_empty_string_returns_false():
    assert validate_exiftool_path("") is False


def test_validate_nonexistent_path_returns_false():
    assert validate_exiftool_path("/nonexistent/exiftool_xyz_9999") is False


def test_validate_success_via_mock():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = validate_exiftool_path("/usr/bin/exiftool")
    assert result is True
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "/usr/bin/exiftool"
    assert "-ver" in call_args


def test_validate_nonzero_returncode_returns_false():
    mock_result = MagicMock()
    mock_result.returncode = 1
    with patch("subprocess.run", return_value=mock_result):
        result = validate_exiftool_path("/usr/bin/exiftool")
    assert result is False


def test_validate_file_not_found_returns_false():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = validate_exiftool_path("/no/such/exiftool")
    assert result is False


def test_validate_timeout_returns_false():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=10)):
        result = validate_exiftool_path("/slow/exiftool")
    assert result is False


# ---------------------------------------------------------------------------
# get_exiftool_version
# ---------------------------------------------------------------------------

def test_get_version_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "12.76\n"
    with patch("subprocess.run", return_value=mock_result):
        ver = get_exiftool_version("/usr/bin/exiftool")
    assert ver == "12.76"


def test_get_version_nonzero_returns_none():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    with patch("subprocess.run", return_value=mock_result):
        ver = get_exiftool_version("/usr/bin/exiftool")
    assert ver is None


def test_get_version_exception_returns_none():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        ver = get_exiftool_version("/no/such/exiftool")
    assert ver is None


# ---------------------------------------------------------------------------
# build_exiftool_xmp_args — shell=True 사용 금지 확인
# ---------------------------------------------------------------------------

SAMPLE_META = {
    "artwork_title":  "테스트 작품",
    "artist_name":    "테스트 작가",
    "artwork_url":    "https://www.pixiv.net/artworks/12345",
    "artwork_id":     "12345",
    "source_site":    "pixiv",
    "tags":           ["오리지널", "풍경"],
    "series_tags":    ["Blue Archive"],
    "character_tags": ["陸八魔アル"],
}


def test_build_args_returns_list():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert isinstance(args, list)
    assert all(isinstance(a, str) for a in args)


def test_build_args_no_shell_true():
    """인자 리스트에 shell=True 트리거 문자열이 없어야 한다."""
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    for a in args:
        assert "&&" not in a
        assert ";" not in a
        assert "|" not in a or a.startswith("-XMP")  # XMP 값에는 | 있을 수 있으나 최소화


def test_build_args_contains_title():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert any("XMP-dc:Title" in a and "테스트 작품" in a for a in args)


def test_build_args_contains_creator():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert any("XMP-dc:Creator" in a and "테스트 작가" in a for a in args)


def test_build_args_contains_subject_tags():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    subjects = [a for a in args if "XMP-dc:Subject" in a]
    subject_values = [a.split("=", 1)[1] for a in subjects]
    assert "오리지널" in subject_values
    assert "풍경" in subject_values
    assert "Blue Archive" in subject_values
    assert "陸八魔アル" in subject_values


def test_build_args_contains_source():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert any("XMP-dc:Source" in a for a in args)


def test_build_args_contains_identifier():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert any("XMP-dc:Identifier" in a and "12345" in a for a in args)


def test_build_args_overwrite_original():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert "-overwrite_original" in args


def test_build_args_file_path_last():
    file_path = "/tmp/my test file with spaces.jpg"
    args = build_exiftool_xmp_args(file_path, SAMPLE_META)
    assert args[-1] == file_path


def test_build_args_empty_metadata():
    args = build_exiftool_xmp_args("/tmp/test.jpg", {})
    assert isinstance(args, list)
    assert "-overwrite_original" in args
    assert args[-1] == "/tmp/test.jpg"


def test_build_args_rating():
    meta = {**SAMPLE_META, "rating": 4}
    args = build_exiftool_xmp_args("/tmp/test.jpg", meta)
    assert any("XMP:Rating=4" in a for a in args)


def test_build_args_label_source_site():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert any("XMP:Label=pixiv" in a for a in args)


def test_build_args_label_default():
    meta = {**SAMPLE_META, "source_site": ""}
    args = build_exiftool_xmp_args("/tmp/test.jpg", meta)
    assert any("XMP:Label=Aru Archive" in a for a in args)


def test_build_args_metadata_date_present():
    args = build_exiftool_xmp_args("/tmp/test.jpg", SAMPLE_META)
    assert any("XMP:MetadataDate" in a for a in args)
