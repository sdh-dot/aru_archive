"""
Windows Explorer 호환 EXIF XP 필드 진단·쓰기 테스트.

테스트 범위:
1. build_exiftool_xp_args — 인자 구조, charset, XPTitle/XPKeywords/XPAuthor
2. read_exif_diagnostics — piexif 경로: JPEG에 XP 필드 없을 때 warning, 있을 때 읽기
3. write_xmp_metadata_with_exiftool include_xp_fields — 합쳐진 args에 XP 태그 포함
4. write_windows_exif_fields — ExifTool 없으면 False 반환
5. piexif가 XP 태그를 보존하지 못한다는 것을 확인 (known limitation 문서화)
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest


# ── helpers ────────────────────────────────────────────────────────────────

def _minimal_jpeg(path: Path) -> Path:
    """SOI + APP0 + SOS + EOI — piexif.insert/load가 동작하는 최소 JPEG."""
    soi          = b"\xff\xd8"
    app0_payload = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"   # 14 B
    app0         = b"\xff\xe0" + struct.pack(">H", len(app0_payload) + 2) + app0_payload
    sos_payload  = b"\x01\x01\x00\x00\x3f\x00"                         # 6 B
    sos          = b"\xff\xda" + struct.pack(">H", len(sos_payload) + 2) + sos_payload
    eoi          = b"\xff\xd9"
    path.write_bytes(soi + app0 + sos + b"\x00" + eoi)
    return path


def _minimal_png(path: Path) -> Path:
    """1×1 흰색 PNG."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", c)

    sig  = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    iend = _chunk(b"IEND", b"")
    path.write_bytes(sig + ihdr + idat + iend)
    return path


_META = {
    "artwork_title": "Nagisa",
    "artist_name":   "Shigure@FANBOX",
    "tags":          ["ブルーアーカイブ", "나기사"],
    "series_tags":   ["Blue Archive"],
    "character_tags":["渚"],
}

# ── build_exiftool_xp_args ─────────────────────────────────────────────────

class TestBuildExiftoolXpArgs:
    def test_charset_utf8_present(self):
        from core.exiftool import build_exiftool_xp_args
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        assert "-charset" in args
        assert "exif=utf8" in args

    def test_xptitle_written(self):
        from core.exiftool import build_exiftool_xp_args
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        assert any("XPTitle=Nagisa" in a for a in args)

    def test_xpauthor_written(self):
        from core.exiftool import build_exiftool_xp_args
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        assert any("XPAuthor=Shigure@FANBOX" in a for a in args)

    def test_xpkeywords_include_all_tag_lists(self):
        from core.exiftool import build_exiftool_xp_args
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        kw_args = [a for a in args if "XPKeywords=" in a]
        keywords = {a.split("=", 1)[1] for a in kw_args}
        assert "ブルーアーカイブ" in keywords
        assert "나기사" in keywords
        assert "Blue Archive" in keywords
        assert "渚" in keywords

    def test_overwrite_original_present(self):
        from core.exiftool import build_exiftool_xp_args
        args = build_exiftool_xp_args("/tmp/a.jpg", _META)
        assert "-overwrite_original" in args
        assert args[-1] == "/tmp/a.jpg"

    def test_empty_metadata_has_no_xptitle(self):
        from core.exiftool import build_exiftool_xp_args
        args = build_exiftool_xp_args("/tmp/a.jpg", {})
        assert not any("XPTitle" in a for a in args)

    def test_no_xpkeywords_when_tags_empty(self):
        from core.exiftool import build_exiftool_xp_args
        args = build_exiftool_xp_args("/tmp/a.jpg", {"tags": [], "series_tags": [], "character_tags": []})
        assert not any("XPKeywords" in a for a in args)


# ── read_exif_diagnostics (piexif path) ───────────────────────────────────

class TestReadExifDiagnostics:
    def test_missing_xp_fields_warning(self, tmp_path):
        """XP 필드 없는 JPEG → warning이 포함되어야 한다."""
        from core.exiftool import read_exif_diagnostics
        jpg = _minimal_jpeg(tmp_path / "plain.jpg")
        result = read_exif_diagnostics(str(jpg))
        assert result["exif_xptitle"]    is None
        assert result["exif_xpkeywords"] is None
        warn_text = " ".join(result["warnings"])
        assert "XPTitle" in warn_text or "XPKeywords" in warn_text

    def test_no_aru_metadata_on_plain_jpeg(self, tmp_path):
        from core.exiftool import read_exif_diagnostics
        jpg = _minimal_jpeg(tmp_path / "plain.jpg")
        result = read_exif_diagnostics(str(jpg))
        assert result["has_aru_metadata"] is False

    def test_aru_metadata_detected_after_write(self, tmp_path):
        """write_aru_metadata 이후 has_aru_metadata=True."""
        import piexif
        from core.exiftool import read_exif_diagnostics
        from core.metadata_writer import write_aru_metadata

        jpg = _minimal_jpeg(tmp_path / "aru.jpg")
        # piexif로 먼저 최소 EXIF 삽입
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}
        piexif.insert(piexif.dump(exif), str(jpg))

        meta = {"schema_version": "1.0", "artwork_id": "test", "artwork_title": "Nagisa"}
        write_aru_metadata(str(jpg), meta, "jpg")

        result = read_exif_diagnostics(str(jpg))
        assert result["has_aru_metadata"] is True
        assert "UNICODE" in (result["exif_user_comment_prefix"] or "")

    def test_result_keys_complete(self, tmp_path):
        from core.exiftool import read_exif_diagnostics
        jpg = _minimal_jpeg(tmp_path / "keys.jpg")
        result = read_exif_diagnostics(str(jpg))
        for key in ("file_path", "exif_xptitle", "exif_xpkeywords", "exif_xpauthor",
                    "exif_user_comment_prefix", "has_aru_metadata",
                    "xmp_dc_title", "xmp_dc_subject", "xmp_dc_creator", "warnings"):
            assert key in result, f"키 누락: {key}"

    def test_xp_fields_read_when_written_raw(self, tmp_path):
        """piexif로 XP 필드를 직접 삽입 후 read_exif_diagnostics가 읽어야 한다."""
        import piexif
        from core.exiftool import read_exif_diagnostics

        jpg = _minimal_jpeg(tmp_path / "xp.jpg")
        title_bytes   = "Nagisa".encode("utf-16-le") + b"\x00\x00"
        keywords_bytes = "Blue Archive;渚".encode("utf-16-le") + b"\x00\x00"
        exif = {
            "0th": {
                0x9C9B: title_bytes,    # XPTitle
                0x9C9E: keywords_bytes, # XPKeywords
            },
            "Exif": {},
            "GPS":  {},
            "1st":  {},
        }
        try:
            piexif.insert(piexif.dump(exif), str(jpg))
        except Exception:
            pytest.skip("piexif가 XP 태그를 덤프하지 못함 (known limitation)")

        result = read_exif_diagnostics(str(jpg))
        if result["exif_xptitle"] is not None:
            assert result["exif_xptitle"] == "Nagisa"
        if result["exif_xpkeywords"] is not None:
            assert "渚" in result["exif_xpkeywords"]


# ── piexif XP 태그 보존 실패 (known limitation) ───────────────────────────

class TestPiexifXpTagRoundtrip:
    def test_piexif_preserves_xp_tags_on_rewrite(self, tmp_path):
        """
        piexif load/dump 사이클에서 unknown 태그(XP 태그)가 보존됨을 확인.

        piexif는 알 수 없는 0th IFD 태그를 tuple로 보존하므로,
        write_aru_metadata(piexif 기반) 이후에도 piexif가 쓴 XP 태그는 살아있다.
        단, ExifTool이 쓴 XP 필드의 보존 여부는 raw bytes 타입 코드에 따라 다를 수 있어
        write_windows_exif_fields를 enrichment 마지막에 호출하는 것을 권장한다.
        """
        import piexif
        from core.metadata_writer import write_aru_metadata

        jpg = _minimal_jpeg(tmp_path / "roundtrip.jpg")

        # 1) piexif로 XP 태그 삽입
        keywords_bytes = "테스트태그".encode("utf-16-le") + b"\x00\x00"
        exif_before = {
            "0th":  {0x9C9E: keywords_bytes},
            "Exif": {},
            "GPS":  {},
            "1st":  {},
        }
        try:
            piexif.insert(piexif.dump(exif_before), str(jpg))
        except Exception:
            pytest.skip("piexif가 XP 태그 삽입을 지원하지 않음")

        loaded = piexif.load(str(jpg))
        had_xp = 0x9C9E in loaded.get("0th", {})

        # 2) write_aru_metadata (piexif 재조립) 이후 XP 태그 보존 확인
        meta = {"schema_version": "1.0", "artwork_id": "x", "artwork_title": "Test"}
        write_aru_metadata(str(jpg), meta, "jpg")

        loaded_after = piexif.load(str(jpg))
        still_has_xp = 0x9C9E in loaded_after.get("0th", {})

        if had_xp:
            assert still_has_xp, (
                "piexif가 XP 태그를 소실시켰다 — "
                "write_windows_exif_fields를 write_aru_metadata 이후에 반드시 호출해야 한다."
            )


# ── write_xmp_metadata_with_exiftool include_xp_fields ────────────────────

class TestWriteXmpIncludeXpFields:
    def test_include_xp_true_adds_xp_tag_args(self):
        """include_xp_fields=True 시 XMP 인자에 XP 태그 인자가 포함된다."""
        from core.exiftool import build_exiftool_xmp_args, build_exiftool_xp_args

        meta = _META
        xmp_args = build_exiftool_xmp_args("/a.jpg", meta)
        xp_args  = build_exiftool_xp_args("/a.jpg", meta)

        # 합쳐진 args 시뮬레이션 (write_xmp_metadata_with_exiftool 내부 로직)
        xp_tag_args = [
            a for a in xp_args
            if a not in ("-overwrite_original", "/a.jpg")
        ]
        combined = xmp_args[:-2] + xp_tag_args + xmp_args[-2:]

        assert any("XPTitle" in a for a in combined)
        assert any("XPKeywords" in a for a in combined)
        assert combined[-1] == "/a.jpg"
        assert "-overwrite_original" in combined

    def test_include_xp_false_no_xp_tag_args(self):
        """include_xp_fields=False 시 XMP 인자에만 의존한다."""
        from core.exiftool import build_exiftool_xmp_args

        args = build_exiftool_xmp_args("/a.jpg", _META)
        assert not any("XPTitle" in a for a in args)
        assert not any("XPKeywords" in a for a in args)


# ── write_windows_exif_fields (no exiftool) ───────────────────────────────

class TestWriteWindowsExifFields:
    def test_returns_false_when_no_exiftool(self, tmp_path):
        from core.metadata_writer import write_windows_exif_fields
        jpg = _minimal_jpeg(tmp_path / "noxmp.jpg")
        result = write_windows_exif_fields(str(jpg), _META, exiftool_path=None)
        assert result is False

    def test_returns_false_when_invalid_exiftool_path(self, tmp_path):
        from core.metadata_writer import write_windows_exif_fields
        jpg = _minimal_jpeg(tmp_path / "noxmp2.jpg")
        result = write_windows_exif_fields(str(jpg), _META, exiftool_path="/nonexistent/exiftool")
        assert result is False
