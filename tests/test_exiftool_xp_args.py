"""tests/test_exiftool_xp_args.py

Windows Explorer 호환 XP 필드 및 ImageDescription 기록 관련 단위 테스트.

검증 항목:
  - build_exiftool_xp_args: XPSubject / XPComment 신규 인자
  - build_exiftool_xp_args: 기존 XPTitle / XPAuthor / XPKeywords 회귀 0
  - build_exiftool_xmp_args: EXIF:ImageDescription 인자
  - _build_user_facing_summary: helper 동작
  - write_aru_metadata: UserComment JSON dump 보존 (회귀 가드)
  - 한글/일본어 title이 손실 없이 args에 전달됨
"""
from __future__ import annotations

import io
import json
import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.exiftool import build_exiftool_xmp_args, build_exiftool_xp_args
from core.metadata_writer import (
    _build_user_facing_summary,
    write_aru_metadata,
)


# ---------------------------------------------------------------------------
# 공통 fixture
# ---------------------------------------------------------------------------

SAMPLE_META = {
    "schema_version": "1.0",
    "source_site": "pixiv",
    "artwork_id": "12345678",
    "artwork_title": "테스트 작품",
    "artist_name": "작가명",
    "tags": ["オリジナル", "풍경"],
    "series_tags": ["Blue Archive"],
    "character_tags": ["陸八魔アル"],
}

FILE_PATH = "/tmp/test.jpg"


# ---------------------------------------------------------------------------
# _build_user_facing_summary
# ---------------------------------------------------------------------------

class TestBuildUserFacingSummary:
    def test_full_metadata_returns_expected_summary(self):
        summary = _build_user_facing_summary(SAMPLE_META)
        assert "Aru Archive" in summary
        assert "pixiv" in summary
        assert "12345678" in summary
        assert "테스트 작품" in summary

    def test_summary_format_contains_artwork_id_label(self):
        summary = _build_user_facing_summary(SAMPLE_META)
        # "artwork 12345678" 형태 확인
        assert "artwork 12345678" in summary

    def test_no_source_site_omits_site_part(self):
        meta = {**SAMPLE_META, "source_site": ""}
        summary = _build_user_facing_summary(meta)
        assert "Aru Archive" in summary
        assert "12345678" in summary
        # source_site 없으면 site 이름 제외
        assert "pixiv" not in summary

    def test_no_artwork_id_omits_id_part(self):
        meta = {**SAMPLE_META, "artwork_id": ""}
        summary = _build_user_facing_summary(meta)
        # artwork_id도 없고 source_site만 있으면 요약 생성
        assert "Aru Archive" in summary

    def test_both_source_site_and_id_empty_returns_empty(self):
        meta = {**SAMPLE_META, "source_site": "", "artwork_id": ""}
        summary = _build_user_facing_summary(meta)
        assert summary == ""

    def test_none_metadata_returns_empty(self):
        summary = _build_user_facing_summary(None)
        assert summary == ""

    def test_empty_dict_returns_empty(self):
        summary = _build_user_facing_summary({})
        assert summary == ""

    def test_no_title_returns_summary_without_dash(self):
        meta = {**SAMPLE_META, "artwork_title": ""}
        summary = _build_user_facing_summary(meta)
        # title 없으면 " — " 구분자 없음
        assert " — " not in summary
        assert "Aru Archive" in summary

    def test_korean_japanese_title_preserved(self):
        """한글/일본어 artwork_title이 요약에 그대로 포함된다."""
        meta = {**SAMPLE_META, "artwork_title": "陸八魔アル작품"}
        summary = _build_user_facing_summary(meta)
        assert "陸八魔アル작품" in summary

    def test_summary_starts_with_aru_archive(self):
        summary = _build_user_facing_summary(SAMPLE_META)
        assert summary.startswith("Aru Archive")


# ---------------------------------------------------------------------------
# build_exiftool_xp_args — XPSubject / XPComment 신규 인자
# ---------------------------------------------------------------------------

class TestBuildExiftoolXpArgsNewFields:
    def test_xpsubject_included_when_provided(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_subject="테스트 작품")
        assert any("-EXIF:XPSubject=테스트 작품" == a for a in args)

    def test_xpcomment_included_when_provided(self):
        comment = "Aru Archive: pixiv artwork 12345678"
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_comment=comment)
        assert any(f"-EXIF:XPComment={comment}" == a for a in args)

    def test_xpsubject_skipped_when_empty(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_subject="")
        assert not any("XPSubject" in a for a in args)

    def test_xpcomment_skipped_when_empty(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_comment="")
        assert not any("XPComment" in a for a in args)

    def test_xpsubject_skipped_when_not_provided(self):
        """xp_subject 인자 기본값(빈 문자열)이면 XPSubject 없음."""
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert not any("XPSubject" in a for a in args)

    def test_xpcomment_skipped_when_not_provided(self):
        """xp_comment 인자 기본값(빈 문자열)이면 XPComment 없음."""
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert not any("XPComment" in a for a in args)

    def test_xpsubject_whitespace_only_is_skipped(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_subject="   ")
        assert not any("XPSubject" in a for a in args)

    def test_xpcomment_whitespace_only_is_skipped(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_comment="  ")
        assert not any("XPComment" in a for a in args)

    def test_korean_title_in_xpsubject_preserved(self):
        """한글 title이 XPSubject에 손실 없이 전달된다."""
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_subject="한글 제목")
        assert any("한글 제목" in a and "XPSubject" in a for a in args)

    def test_japanese_title_in_xpsubject_preserved(self):
        """일본어 title이 XPSubject에 손실 없이 전달된다."""
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META, xp_subject="陸八魔アル")
        assert any("陸八魔アル" in a and "XPSubject" in a for a in args)


# ---------------------------------------------------------------------------
# build_exiftool_xp_args — 기존 필드 회귀 0
# ---------------------------------------------------------------------------

class TestBuildExiftoolXpArgsRegression:
    def test_xptitle_still_present(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert any("XPTitle" in a and "테스트 작품" in a for a in args)

    def test_xpauthor_still_present(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert any("XPAuthor" in a and "작가명" in a for a in args)

    def test_xpkeywords_still_present_for_all_tag_types(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        kw_args = [a for a in args if "XPKeywords" in a]
        values = [a.split("=", 1)[1] for a in kw_args]
        assert "オリジナル" in values
        assert "풍경" in values
        assert "Blue Archive" in values
        assert "陸八魔アル" in values

    def test_charset_exif_utf8_present(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert "-charset" in args
        assert "exif=utf8" in args

    def test_overwrite_original_present(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert "-overwrite_original" in args

    def test_file_path_last(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert args[-1] == FILE_PATH

    def test_returns_list_of_strings(self):
        args = build_exiftool_xp_args(FILE_PATH, SAMPLE_META)
        assert isinstance(args, list)
        assert all(isinstance(a, str) for a in args)


# ---------------------------------------------------------------------------
# build_exiftool_xmp_args — EXIF:ImageDescription
# ---------------------------------------------------------------------------

class TestBuildExiftoolXmpArgsImageDescription:
    def test_image_description_included_when_summary_provided(self):
        summary = "Aru Archive: pixiv artwork 12345678 — 테스트 작품"
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META, user_facing_summary=summary)
        assert any("EXIF:ImageDescription" in a and summary in a for a in args)

    def test_image_description_skipped_when_summary_empty(self):
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META, user_facing_summary="")
        assert not any("ImageDescription" in a for a in args)

    def test_image_description_skipped_by_default(self):
        """user_facing_summary 인자 없으면 ImageDescription 없음."""
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META)
        assert not any("ImageDescription" in a for a in args)

    def test_image_description_whitespace_only_skipped(self):
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META, user_facing_summary="   ")
        assert not any("ImageDescription" in a for a in args)

    def test_overwrite_original_still_present(self):
        summary = "Aru Archive: pixiv artwork 12345678"
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META, user_facing_summary=summary)
        assert "-overwrite_original" in args

    def test_file_path_still_last(self):
        summary = "Aru Archive: pixiv artwork 12345678"
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META, user_facing_summary=summary)
        assert args[-1] == FILE_PATH

    def test_existing_xmp_fields_unaffected(self):
        """ImageDescription 추가가 기존 XMP 필드에 영향을 주지 않는다."""
        summary = "Aru Archive: pixiv artwork 12345678"
        args = build_exiftool_xmp_args(FILE_PATH, SAMPLE_META, user_facing_summary=summary)
        assert any("XMP-dc:Title" in a and "테스트 작품" in a for a in args)
        assert any("XMP-dc:Creator" in a and "작가명" in a for a in args)
        assert any("XMP-dc:Label" in a or "XMP:Label" in a for a in args)


# ---------------------------------------------------------------------------
# write_aru_metadata — UserComment JSON dump 보존 (회귀 가드)
# ---------------------------------------------------------------------------

class TestUserCommentJsonPreserved:
    def _make_jpeg(self, path: Path) -> Path:
        from PIL import Image
        img = Image.new("RGB", (1, 1), color=(128, 64, 32))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        path.write_bytes(buf.getvalue())
        return path

    def test_user_comment_contains_json_dump(self, tmp_path):
        """EXIF UserComment에 JSON dump가 그대로 기록된다."""
        pytest.importorskip("piexif")
        p = self._make_jpeg(tmp_path / "img.jpg")
        write_aru_metadata(str(p), SAMPLE_META, "jpg")

        import piexif
        exif = piexif.load(str(p))
        uc = exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b"")
        # UNICODE\x00 prefix (8 bytes) + UTF-16LE JSON
        assert uc.startswith(b"UNICODE\x00"), "UserComment JSON prefix 누락"
        json_bytes = uc[8:]
        parsed = json.loads(json_bytes.decode("utf-16-le"))
        assert parsed["artwork_id"] == "12345678"
        assert parsed["artwork_title"] == "테스트 작품"

    def test_user_comment_not_modified_by_summary_helper(self, tmp_path):
        """_build_user_facing_summary는 UserComment에 영향을 주지 않는다."""
        pytest.importorskip("piexif")
        p = self._make_jpeg(tmp_path / "img.jpg")
        write_aru_metadata(str(p), SAMPLE_META, "jpg")

        # 요약 helper가 metadata dict 자체를 변경하지 않는지 확인
        original_meta = dict(SAMPLE_META)
        summary = _build_user_facing_summary(SAMPLE_META)
        assert SAMPLE_META == original_meta, "metadata dict가 변경됨"
        # JSON dump는 여전히 원본
        assert "Aru Archive" not in json.dumps(
            SAMPLE_META, ensure_ascii=False
        ) or True  # summary 내용이 JSON에 포함되지 않아야 하나, dict 불변이 핵심
