"""
format_converter 단위 테스트.
BMP → PNG managed 변환, GIF animated 판별, animated GIF → WebP managed 변환.
"""
from pathlib import Path

import pytest
from PIL import Image

from core.format_converter import (
    convert_bmp_to_png,
    convert_gif_to_webp,
    is_animated_gif,
    needs_managed_conversion,
)


# ---------------------------------------------------------------------------
# 테스트용 이미지 생성 헬퍼
# ---------------------------------------------------------------------------

def _make_bmp(path: str, size=(10, 10), color=(200, 100, 50)):
    Image.new("RGB", size, color=color).save(path, format="BMP")


def _make_static_gif(path: str, size=(10, 10)):
    Image.new("P", size, color=0).save(path, format="GIF")


def _make_animated_gif(path: str, size=(10, 10), n_frames=3):
    frames = [
        Image.new("RGB", size, color=(i * 80, i * 40, i * 20))
        for i in range(n_frames)
    ]
    frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )


# ---------------------------------------------------------------------------
# BMP → PNG managed 변환
# ---------------------------------------------------------------------------

class TestConvertBmpToPng:
    def test_success(self, tmp_path):
        bmp = str(tmp_path / "test.bmp")
        _make_bmp(bmp)
        result = convert_bmp_to_png(bmp, str(tmp_path))
        assert Path(result).exists()

    def test_output_is_png(self, tmp_path):
        bmp = str(tmp_path / "test.bmp")
        _make_bmp(bmp)
        result = convert_bmp_to_png(bmp, str(tmp_path))
        img = Image.open(result)
        assert img.format == "PNG"

    def test_filename_convention(self, tmp_path):
        """출력 파일명은 {stem}_managed.png 여야 한다."""
        bmp = str(tmp_path / "artwork_001.bmp")
        _make_bmp(bmp)
        result = convert_bmp_to_png(bmp, str(tmp_path))
        assert Path(result).name == "artwork_001_managed.png"

    def test_different_stem(self, tmp_path):
        bmp = str(tmp_path / "141100516_p0.bmp")
        _make_bmp(bmp)
        result = convert_bmp_to_png(bmp, str(tmp_path))
        assert Path(result).name == "141100516_p0_managed.png"

    def test_raises_on_nonexistent_file(self, tmp_path):
        with pytest.raises(Exception):
            convert_bmp_to_png(str(tmp_path / "ghost.bmp"), str(tmp_path))

    def test_pixel_integrity(self, tmp_path):
        """변환 후 픽셀 값이 보존되어야 한다 (무손실)."""
        bmp = str(tmp_path / "color.bmp")
        color = (123, 45, 67)
        _make_bmp(bmp, size=(4, 4), color=color)
        result = convert_bmp_to_png(bmp, str(tmp_path))
        img = Image.open(result).convert("RGB")
        assert img.getpixel((0, 0)) == color


# ---------------------------------------------------------------------------
# GIF animated 판별
# ---------------------------------------------------------------------------

class TestIsAnimatedGif:
    def test_static_gif_is_false(self, tmp_path):
        gif = str(tmp_path / "static.gif")
        _make_static_gif(gif)
        assert is_animated_gif(gif) is False

    def test_animated_gif_is_true(self, tmp_path):
        gif = str(tmp_path / "animated.gif")
        _make_animated_gif(gif)
        assert is_animated_gif(gif) is True

    def test_two_frame_gif_is_animated(self, tmp_path):
        gif = str(tmp_path / "two_frames.gif")
        _make_animated_gif(gif, n_frames=2)
        assert is_animated_gif(gif) is True


# ---------------------------------------------------------------------------
# animated GIF → WebP managed 변환
# ---------------------------------------------------------------------------

class TestConvertGifToWebp:
    def test_success(self, tmp_path):
        gif = str(tmp_path / "anim.gif")
        _make_animated_gif(gif)
        result = convert_gif_to_webp(gif, str(tmp_path))
        assert Path(result).exists()

    def test_filename_convention(self, tmp_path):
        gif = str(tmp_path / "artwork_002.gif")
        _make_animated_gif(gif)
        result = convert_gif_to_webp(gif, str(tmp_path))
        assert Path(result).name == "artwork_002_managed.webp"

    def test_output_is_webp(self, tmp_path):
        gif = str(tmp_path / "anim.gif")
        _make_animated_gif(gif)
        result = convert_gif_to_webp(gif, str(tmp_path))
        img = Image.open(result)
        assert img.format == "WEBP"

    def test_raises_on_nonexistent_file(self, tmp_path):
        with pytest.raises(Exception):
            convert_gif_to_webp(str(tmp_path / "ghost.gif"), str(tmp_path))


# ---------------------------------------------------------------------------
# needs_managed_conversion 헬퍼
# ---------------------------------------------------------------------------

class TestNeedsManagedConversion:
    def test_bmp_needs_png(self):
        needs, fmt = needs_managed_conversion("bmp")
        assert needs is True
        assert fmt == "png"

    def test_gif_needs_webp(self):
        needs, fmt = needs_managed_conversion("gif")
        assert needs is True
        assert fmt == "webp"

    def test_jpg_no_conversion(self):
        needs, fmt = needs_managed_conversion("jpg")
        assert needs is False

    def test_png_no_conversion(self):
        needs, fmt = needs_managed_conversion("png")
        assert needs is False

    def test_webp_no_conversion(self):
        needs, fmt = needs_managed_conversion("webp")
        assert needs is False
