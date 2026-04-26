"""
AruArchive 메타데이터 읽기.
파일 형식별로 AruArchive JSON을 추출하여 dict로 반환한다.
파싱 실패 또는 메타데이터 없음 시 None 반환.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Optional

ARU_KEYWORD = "AruArchive"


def read_aru_metadata(file_path: str, file_format: str) -> Optional[dict]:
    """
    파일 형식에 따라 AruArchive JSON 메타데이터를 읽어 반환한다.
    파싱 실패 또는 메타데이터 없으면 None 반환.

    BMP는 PNG managed에서 읽어야 한다 (호출자 책임).
    """
    fmt = file_format.lower().lstrip(".")
    try:
        if fmt in ("jpg", "jpeg"):
            return _read_exif_user_comment(file_path)
        elif fmt == "png":
            return _read_png_itxt(file_path)
        elif fmt == "webp":
            return _read_exif_user_comment(file_path)
        elif fmt in ("zip", "gif"):
            return _read_sidecar(file_path)
        else:
            return None
    except Exception:
        return None


def _read_exif_user_comment(file_path: str) -> Optional[dict]:
    """JPEG / WebP EXIF UserComment에서 AruArchive JSON 읽기."""
    try:
        import piexif
    except ImportError:
        return None

    try:
        exif_dict = piexif.load(file_path)
        uc = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment)
        if uc and uc.startswith(b"UNICODE\x00"):
            return json.loads(uc[8:].decode("utf-16-le"))
    except Exception:
        pass
    return None


def _read_png_itxt(file_path: str) -> Optional[dict]:
    """PNG iTXt chunk (keyword=AruArchive)에서 JSON 읽기."""
    PNG_SIG = b"\x89PNG\r\n\x1a\n"

    with open(file_path, "rb") as f:
        data = f.read()

    if not data.startswith(PNG_SIG):
        return None

    chunks = _parse_png_chunks(data[8:])
    keyword_prefix = ARU_KEYWORD.encode("utf-8") + b"\x00"

    for ctype, cdata in chunks:
        if ctype != b"iTXt" or not cdata.startswith(keyword_prefix):
            continue
        rest = cdata[len(keyword_prefix):]
        # skip compression_flag(1) + compression_method(1)
        rest = rest[2:]
        # skip language \0
        lang_end = rest.find(b"\x00")
        if lang_end < 0:
            continue
        rest = rest[lang_end + 1 :]
        # skip translated keyword \0
        trans_end = rest.find(b"\x00")
        if trans_end < 0:
            continue
        text_bytes = rest[trans_end + 1 :]
        try:
            return json.loads(text_bytes.decode("utf-8"))
        except Exception:
            continue
    return None


def _parse_png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    chunks: list[tuple[bytes, bytes]] = []
    offset = 0
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        ctype = data[offset + 4 : offset + 8]
        cdata = data[offset + 8 : offset + 8 + length]
        chunks.append((ctype, cdata))
        offset += 12 + length
    return chunks


def _read_sidecar(file_path: str) -> Optional[dict]:
    """
    {file_path}.aru.json sidecar에서 JSON 읽기.
    ZIP(ugoira) 및 static GIF에서 사용.
    """
    sidecar_path = Path(str(file_path) + ".aru.json")
    if not sidecar_path.exists():
        return None
    try:
        return json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return None
