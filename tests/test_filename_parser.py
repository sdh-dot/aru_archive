"""
core.filename_parser 테스트.

지원 패턴:
  141100516_p0_master1200.jpg → artwork_id=141100516, page_index=0
  141100516_p1.png            → artwork_id=141100516, page_index=1
  141100516_p0.jpg            → artwork_id=141100516, page_index=0
  141100516_ugoira.zip        → artwork_id=141100516, page_index=0
  invalid_name.jpg            → None
"""
from __future__ import annotations

import pytest

from core.filename_parser import parse_pixiv_filename, PixivFilenameResult, PIXIV_BASE_URL


# ---------------------------------------------------------------------------
# 정상 케이스
# ---------------------------------------------------------------------------

def test_p0_with_quality():
    r = parse_pixiv_filename("141100516_p0_master1200.jpg")
    assert r is not None
    assert r.artwork_id == "141100516"
    assert r.page_index == 0
    assert r.artwork_url == f"{PIXIV_BASE_URL}141100516"


def test_p0_simple():
    r = parse_pixiv_filename("141100516_p0.jpg")
    assert r is not None
    assert r.artwork_id == "141100516"
    assert r.page_index == 0


def test_p1():
    r = parse_pixiv_filename("141100516_p1.png")
    assert r is not None
    assert r.artwork_id == "141100516"
    assert r.page_index == 1


def test_ugoira():
    r = parse_pixiv_filename("141100516_ugoira.zip")
    assert r is not None
    assert r.artwork_id == "141100516"
    assert r.page_index == 0


def test_ugoira_with_suffix():
    r = parse_pixiv_filename("141100516_ugoira_1920.zip")
    assert r is not None
    assert r.artwork_id == "141100516"
    assert r.page_index == 0


def test_full_path():
    """경로 포함 전달 시 basename만 사용한다."""
    r = parse_pixiv_filename("/some/path/to/141100516_p0.jpg")
    assert r is not None
    assert r.artwork_id == "141100516"


def test_windows_path():
    r = parse_pixiv_filename(r"C:\Users\user\Inbox\141100516_p2_master1200.png")
    assert r is not None
    assert r.artwork_id == "141100516"
    assert r.page_index == 2


def test_short_but_valid_id():
    """5자리 artwork_id (역사적으로 존재)."""
    r = parse_pixiv_filename("12345_p0.jpg")
    assert r is not None
    assert r.artwork_id == "12345"


def test_page_index_multidigit():
    r = parse_pixiv_filename("141100516_p12.jpg")
    assert r is not None
    assert r.page_index == 12


def test_returns_frozen_dataclass():
    r = parse_pixiv_filename("141100516_p0.jpg")
    assert isinstance(r, PixivFilenameResult)


# ---------------------------------------------------------------------------
# 실패 케이스 (None 반환)
# ---------------------------------------------------------------------------

def test_plain_name():
    assert parse_pixiv_filename("photo.jpg") is None


def test_no_separator():
    """_p 구분자 없이 숫자만 있는 경우."""
    assert parse_pixiv_filename("141100516.jpg") is None


def test_too_short_id():
    """4자리 이하 ID는 거부."""
    assert parse_pixiv_filename("1234_p0.jpg") is None


def test_non_numeric_id():
    assert parse_pixiv_filename("abc12345_p0.jpg") is None


def test_underscore_prefix():
    assert parse_pixiv_filename("_141100516_p0.jpg") is None


def test_empty_string():
    assert parse_pixiv_filename("") is None


def test_only_extension():
    assert parse_pixiv_filename(".jpg") is None


def test_no_extension():
    """확장자 없는 파일명은 거부."""
    assert parse_pixiv_filename("141100516_p0") is None


def test_artwork_url_format():
    r = parse_pixiv_filename("99999999_p0.jpg")
    assert r.artwork_url == "https://www.pixiv.net/artworks/99999999"
