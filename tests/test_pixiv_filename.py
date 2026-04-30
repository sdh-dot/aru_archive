"""
Pixiv 파일명 파서 테스트.

core.pixiv_filename.parse_pixiv_filename() 의 모든 변형을 검증한다.
"""
from __future__ import annotations

import pytest

from core.pixiv_filename import PixivFilenameInfo, parse_pixiv_filename


# ---------------------------------------------------------------------------
# 1. 정상 파싱
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "filename, artwork_id, page_index",
    [
        ("106586263_p0_master1200.jpg",   "106586263", 0),
        ("106586263_p0.jpg",              "106586263", 0),
        ("106586263_p0_master1200 (1).jpg", "106586263", 0),
        ("106586263_p0 (2).webp",         "106586263", 0),
        ("106586263_P0_master1200.jpg",   "106586263", 0),
        ("106586263-p1-master1200.png",   "106586263", 1),
        ("pixiv_106586263_p2.jpg",        "106586263", 2),
        # 추가 변형
        ("141100516_p0_master1200.jpg",   "141100516", 0),
        ("141100516_p1.png",              "141100516", 1),
        ("141100516_ugoira.zip",          "141100516", 0),
        ("99999_p0.jpg",                  "99999",     0),   # 최소 5자리
        ("999999999999_p10.jpg",          "999999999999", 10),  # 최대 12자리
        ("106586263_p0 (10).jpg",         "106586263", 0),   # 두 자리 dup suffix
        ("106586263-p0.jpg",              "106586263", 0),   # - 구분자
        ("pixiv_106586263_p0_master1200.jpg", "106586263", 0),  # pixiv_ + suffix
    ],
)
def test_parse_pixiv_filename_variants(filename: str, artwork_id: str, page_index: int) -> None:
    result = parse_pixiv_filename(filename)
    assert result is not None, f"파싱 실패: {filename!r}"
    assert isinstance(result, PixivFilenameInfo)
    assert result.artwork_id == artwork_id, f"{filename!r}: artwork_id"
    assert result.page_index == page_index, f"{filename!r}: page_index"
    assert result.source == "filename"
    assert result.normalized_stem == f"{artwork_id}_p{page_index}"


# ---------------------------------------------------------------------------
# 2. 파싱 실패 케이스
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "filename",
    [
        "not_pixiv.jpg",
        "master1200.jpg",
        "106586263.jpg",          # p 없음
        "p0_master1200.jpg",      # artwork_id 없음
        "1234_p0.jpg",            # artwork_id 너무 짧음 (4자리)
        "1234567890123_p0.jpg",   # artwork_id 너무 길음 (13자리)
        "image.png",
        "screenshot.png",
    ],
)
def test_parse_pixiv_filename_invalid(filename: str) -> None:
    result = parse_pixiv_filename(filename)
    assert result is None, f"None이어야 하는데 파싱됨: {filename!r} → {result}"


# ---------------------------------------------------------------------------
# 3. confidence 값
# ---------------------------------------------------------------------------

def test_confidence_high_for_standard_format() -> None:
    result = parse_pixiv_filename("106586263_p0_master1200.jpg")
    assert result is not None
    assert result.confidence == "high"


def test_confidence_medium_for_pixiv_prefix() -> None:
    result = parse_pixiv_filename("pixiv_106586263_p2.jpg")
    assert result is not None
    assert result.confidence == "medium"


# ---------------------------------------------------------------------------
# 4. 전체 경로 전달 시 basename만 사용
# ---------------------------------------------------------------------------

def test_full_path_uses_basename() -> None:
    result = parse_pixiv_filename("/some/deep/path/106586263_p0_master1200.jpg")
    assert result is not None
    assert result.artwork_id == "106586263"


def test_windows_path_uses_basename() -> None:
    from pathlib import Path
    result = parse_pixiv_filename(Path("C:\\Users\\user\\Downloads\\106586263_p0.jpg"))
    assert result is not None
    assert result.artwork_id == "106586263"


# ---------------------------------------------------------------------------
# 5. normalized_stem
# ---------------------------------------------------------------------------

def test_normalized_stem_strips_suffix() -> None:
    result = parse_pixiv_filename("106586263_p3_master1200.jpg")
    assert result is not None
    assert result.normalized_stem == "106586263_p3"


# ---------------------------------------------------------------------------
# 6. filename_parser 하위 호환 레이어
# ---------------------------------------------------------------------------

def test_filename_parser_compat_layer() -> None:
    """filename_parser.parse_pixiv_filename()도 동일 artwork_id를 반환해야 한다."""
    from core.filename_parser import parse_pixiv_filename as legacy_parse

    result = legacy_parse("106586263_p0_master1200.jpg")
    assert result is not None
    assert result.artwork_id == "106586263"
    assert result.page_index == 0
    assert "106586263" in result.artwork_url


def test_filename_parser_compat_new_patterns() -> None:
    """하위 호환 레이어가 새 패턴(pixiv_ prefix, dash separator)도 처리한다."""
    from core.filename_parser import parse_pixiv_filename as legacy_parse

    assert legacy_parse("pixiv_106586263_p2.jpg") is not None
    assert legacy_parse("106586263-p1-master1200.png") is not None
    assert legacy_parse("106586263_p0 (1).jpg") is not None
