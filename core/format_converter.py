"""
파일 형식 변환기.
BMP → PNG managed, animated GIF → WebP managed 변환.

v2.4 정책:
- BMP: original 보존 + PNG managed 생성 (WebP가 아님)
- animated GIF: original 보존 + WebP managed 생성
- ugoira ZIP → WebP managed: ugoira_converter.py 담당
- WebP managed는 ugoira / animated GIF 전용

실패 시 예외를 삼키지 않고 호출자에게 전달한다.
호출자는 실패를 다음과 같이 처리한다:
  BMP 변환 실패  → metadata_sync_status='convert_failed', fail_reason='bmp_convert_failed'
  GIF 변환 실패  → metadata_sync_status='convert_failed', fail_reason='managed_file_create_failed'
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def convert_bmp_to_png(bmp_path: str, dest_dir: str) -> str:
    """
    BMP original을 PNG managed로 무손실 변환한다.
    출력 파일명: {stem}_managed.png

    BMP 처리 정책 (v2.4):
    - BMP original 보존 (Inbox에 그대로 유지)
    - PNG managed 생성 (이 함수)
    - PNG managed에 AruArchive JSON 기록 (metadata_writer 담당)
    - ExifTool 사용 가능 시 PNG managed에 XMP 기록
    - 분류/썸네일/검색 대상은 PNG managed 우선

    실패 시 PIL.UnidentifiedImageError 또는 OSError 등을 호출자에게 전달.
    호출자: convert_failed + bmp_convert_failed 처리.
    """
    src = Path(bmp_path)
    dst_dir = Path(dest_dir)
    png_path = dst_dir / f"{src.stem}_managed.png"

    with Image.open(bmp_path) as img:
        out = img if img.mode in ("RGB", "RGBA", "L") else img.convert("RGB")
        out.save(str(png_path), format="PNG", optimize=True)
    return str(png_path)


def is_animated_gif(gif_path: str) -> bool:
    """
    GIF 파일이 animated인지 판별한다.
    is_animated 속성과 n_frames > 1 두 조건을 모두 확인한다.
    """
    with Image.open(gif_path) as img:
        return getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1


def convert_gif_to_webp(gif_path: str, dest_dir: str) -> str:
    """
    animated GIF original을 animated WebP managed로 변환한다.
    출력 파일명: {stem}_managed.webp

    실패 시 예외를 호출자에게 전달.
    호출자: convert_failed + managed_file_create_failed 처리.
    """
    src = Path(gif_path)
    dst_dir = Path(dest_dir)
    webp_path = dst_dir / f"{src.stem}_managed.webp"

    with Image.open(gif_path) as img:
        frames: list[Image.Image] = []
        durations: list[int] = []
        for i in range(img.n_frames):
            img.seek(i)
            frames.append(img.copy().convert("RGBA"))
            durations.append(img.info.get("duration", 100))

    frames[0].save(
        str(webp_path),
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
    )
    return str(webp_path)


def get_file_format(file_path: str) -> str:
    """파일 확장자에서 소문자 형식 문자열 반환 (점 제외)."""
    suffix = Path(file_path).suffix.lower().lstrip(".")
    if suffix == "jpeg":
        return "jpg"
    return suffix


def needs_managed_conversion(file_format: str) -> tuple[bool, str]:
    """
    managed 변환이 필요한 형식인지 판별한다.
    반환: (변환 필요 여부, 변환 후 형식)

    BMP → PNG managed
    animated GIF → WebP managed (is_animated_gif()로 추가 판별 필요)
    그 외 → 변환 불필요
    """
    fmt = file_format.lower()
    if fmt == "bmp":
        return True, "png"
    if fmt == "gif":
        return True, "webp"  # animated인지는 호출자가 is_animated_gif()로 확인
    return False, fmt
