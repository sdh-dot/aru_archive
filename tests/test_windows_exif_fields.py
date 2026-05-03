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


# ---------------------------------------------------------------------------
# clear-first 재등록 회귀 — Explorer XP 필드만 대상, UserComment 보존
# ---------------------------------------------------------------------------

_EXPLORER_XP_TAG_IDS_EXPECTED = (
    0x9C9B,  # XPTitle
    0x9C9F,  # XPSubject
    0x9C9D,  # XPAuthor
    0x9C9E,  # XPKeywords
    0x9C9C,  # XPComment
)


def _set_xp_field(file_path: Path, tag_id: int, value: bytes) -> None:
    """tests-only helper — IFD0 의 임의 태그를 직접 set."""
    import piexif
    exif_dict = piexif.load(str(file_path))
    exif_dict.setdefault("0th", {})[tag_id] = value
    piexif.insert(piexif.dump(exif_dict), str(file_path))


def _xp_value_as_bytes(value) -> bytes:
    """piexif 가 set/load 사이에서 bytes 또는 tuple-of-ints 로 표현하는 차이를 흡수."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, tuple):
        return bytes(value)
    return b""


def _read_xp_fields(file_path: Path) -> dict[int, bytes]:
    import piexif
    exif_dict = piexif.load(str(file_path))
    zeroth = exif_dict.get("0th", {})
    return {
        tid: _xp_value_as_bytes(zeroth[tid])
        for tid in _EXPLORER_XP_TAG_IDS_EXPECTED if tid in zeroth
    }


def _read_user_comment(file_path: Path) -> bytes | None:
    import piexif
    exif_dict = piexif.load(str(file_path))
    return exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment)


class TestExplorerXpClearFirstScope:
    """clear-first 가 Explorer XP 5종에만 적용되고 UserComment 는 보존된다."""

    def test_clear_target_id_set_excludes_user_comment(self):
        from core.metadata_writer import _EXPLORER_XP_TAG_IDS
        # UserComment (Exif IFD 0x9286) 는 명시적으로 제외되어야 한다.
        assert 0x9286 not in _EXPLORER_XP_TAG_IDS
        # 정확히 5종 — Title/Subject/Author/Keywords/Comment.
        assert set(_EXPLORER_XP_TAG_IDS) == set(_EXPLORER_XP_TAG_IDS_EXPECTED)

    def test_clear_first_replaces_existing_xp_fields(self, tmp_path):
        pytest.importorskip("piexif")
        from core.metadata_writer import _write_windows_exif_fields_direct

        jpg = _minimal_jpeg(tmp_path / "with_old_xp.jpg")
        # 기존 (옛) XP 값 5종 모두 의도적으로 set.
        for tid in _EXPLORER_XP_TAG_IDS_EXPECTED:
            _set_xp_field(jpg, tid, "OLD".encode("utf-16-le") + b"\x00\x00")
        before = _read_xp_fields(jpg)
        assert len(before) == 5

        _write_windows_exif_fields_direct(
            str(jpg), _META, clear_before_write=True,
        )
        after = _read_xp_fields(jpg)
        # 새 값으로 대체되었으며 옛 'OLD' 토큰은 사라져야 한다.
        for tid, val in after.items():
            assert b"OLD" not in val, (
                f"tag {hex(tid)} still contains old bytes after clear-first"
            )

    def test_clear_first_does_not_touch_user_comment(self, tmp_path):
        pytest.importorskip("piexif")
        from core.metadata_writer import (
            _write_exif_user_comment, _write_windows_exif_fields_direct,
        )

        jpg = _minimal_jpeg(tmp_path / "uc_preserve.jpg")
        aru_meta = {
            "schema_version": "1.0",
            "source_site": "pixiv",
            "artwork_id": "12345",
            "tags": ["alpha", "beta"],
            "series_tags": ["Blue Archive"],
            "character_tags": ["伊落マリー"],
        }
        _write_exif_user_comment(str(jpg), aru_meta)
        uc_before = _read_user_comment(jpg)
        assert uc_before is not None and b"UNICODE" in uc_before[:8]

        _write_windows_exif_fields_direct(
            str(jpg), _META, clear_before_write=True,
        )
        uc_after = _read_user_comment(jpg)
        assert uc_after == uc_before, (
            "UserComment (Aru JSON) was modified by Explorer XP clear-first write"
        )

    def test_clear_first_keywords_replace_not_append(self, tmp_path):
        """기존 XPKeywords 가 새 keyword list 와 합쳐지지 않고 완전 대체."""
        pytest.importorskip("piexif")
        from core.metadata_writer import _write_windows_exif_fields_direct

        jpg = _minimal_jpeg(tmp_path / "kw_replace.jpg")
        # 옛 XPKeywords 값을 직접 주입.
        old_kw = "trickcal;legacy_tag".encode("utf-16-le") + b"\x00\x00"
        _set_xp_field(jpg, 0x9C9E, old_kw)

        _write_windows_exif_fields_direct(
            str(jpg), _META, clear_before_write=True,
        )
        new_kw_bytes = _read_xp_fields(jpg).get(0x9C9E, b"")
        # bytes -> str (utf-16-le, null terminator 제거)
        new_kw = new_kw_bytes.decode("utf-16-le").rstrip("\x00")
        assert new_kw == "mizugi;beach", (
            f"keywords were appended/merged instead of replaced: {new_kw!r}"
        )
        assert "trickcal" not in new_kw
        assert "legacy_tag" not in new_kw

    def test_default_path_unchanged_when_clear_before_write_false(self, tmp_path, monkeypatch):
        """clear_before_write=False 기본 경로는 ExifTool 우선 → fallback 흐름 유지."""
        from core.metadata_writer import _write_windows_exif_fields_best_effort

        called: dict = {"primary": 0, "direct": 0}

        def _fake_primary(file_path, metadata, exiftool_path=None):
            called["primary"] += 1
            return True

        def _fake_direct(file_path, metadata, *, clear_before_write=False):
            called["direct"] += 1
            assert clear_before_write is False, (
                "default path should not request clear-first"
            )

        monkeypatch.setattr(
            "core.metadata_writer.write_windows_exif_fields", _fake_primary
        )
        monkeypatch.setattr(
            "core.metadata_writer._write_windows_exif_fields_direct", _fake_direct
        )

        jpg = _minimal_jpeg(tmp_path / "default.jpg")
        result = _write_windows_exif_fields_best_effort(
            str(jpg), _META, exiftool_path="/fake/exiftool",
        )
        assert result == "primary"
        assert called["primary"] == 1
        assert called["direct"] == 0

    def test_clear_first_skips_exiftool_path(self, tmp_path, monkeypatch):
        """clear_before_write=True 면 ExifTool 경로를 건너뛰고 direct write 만 사용."""
        from core.metadata_writer import _write_windows_exif_fields_best_effort

        called: dict = {"primary": 0, "direct": 0, "direct_clear_first": 0}

        def _fake_primary(file_path, metadata, exiftool_path=None):
            called["primary"] += 1
            return True

        def _fake_direct(file_path, metadata, *, clear_before_write=False):
            called["direct"] += 1
            if clear_before_write:
                called["direct_clear_first"] += 1

        monkeypatch.setattr(
            "core.metadata_writer.write_windows_exif_fields", _fake_primary
        )
        monkeypatch.setattr(
            "core.metadata_writer._write_windows_exif_fields_direct", _fake_direct
        )

        jpg = _minimal_jpeg(tmp_path / "clearfirst.jpg")
        result = _write_windows_exif_fields_best_effort(
            str(jpg), _META, exiftool_path="/fake/exiftool",
            clear_before_write=True,
        )
        assert result == "clear_first"
        assert called["primary"] == 0
        assert called["direct_clear_first"] == 1


class TestWriteXmpMetadataClearFirstPlumbing:
    """write_xmp_metadata_with_exiftool 의 clear_windows_xp_fields_before_write
    인자가 _write_windows_exif_fields_best_effort 까지 그대로 전달된다."""

    def test_signature_accepts_kwarg(self):
        import inspect
        from core.metadata_writer import write_xmp_metadata_with_exiftool
        sig = inspect.signature(write_xmp_metadata_with_exiftool)
        assert "clear_windows_xp_fields_before_write" in sig.parameters
        # 기본값은 False — 신규 등록 경로 blast radius 차단.
        assert sig.parameters["clear_windows_xp_fields_before_write"].default is False

    def test_xmp_retry_call_site_passes_clear_first_true(self):
        import inspect
        import core.xmp_retry as mod
        src = inspect.getsource(mod)
        assert "clear_windows_xp_fields_before_write=True" in src, (
            "xmp_retry should request clear-first XP rewrite"
        )

    def test_explorer_meta_repair_call_site_passes_clear_first_true(self):
        import inspect
        import core.explorer_meta_repair as mod
        src = inspect.getsource(mod)
        assert "clear_windows_xp_fields_before_write=True" in src, (
            "explorer_meta_repair should request clear-first XP rewrite"
        )

    def test_metadata_enricher_does_not_request_clear_first(self):
        """신규 enrichment 경로는 default(False) 그대로 — blast radius 보호."""
        import inspect
        import core.metadata_enricher as mod
        src = inspect.getsource(mod)
        assert "clear_windows_xp_fields_before_write=True" not in src, (
            "신규 enrichment 가 clear-first 를 요청하면 안 됨 — "
            "재등록 경로(xmp_retry/explorer_meta_repair) 만 사용"
        )

    def test_worker_does_not_request_clear_first(self):
        import inspect
        import core.worker as mod
        src = inspect.getsource(mod)
        assert "clear_windows_xp_fields_before_write=True" not in src, (
            "신규 다운로드 worker 가 clear-first 를 요청하면 안 됨"
        )
