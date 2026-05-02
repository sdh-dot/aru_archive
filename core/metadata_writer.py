"""
AruArchive 메타데이터 쓰기.

형식별 저장 방식 (v2.4):
- JPEG/WebP : EXIF UserComment (0x9286, prefix=UNICODE\\0, UTF-16LE JSON)
- PNG       : iTXt chunk (keyword=AruArchive)
- ZIP       : ZIP comment(식별자) + .aru.json sidecar
- GIF static: .aru.json sidecar (파일 우선 원칙의 예외)
- BMP       : PNG managed에 쓰는 것이 원칙
              호출자가 PNG managed file_path를 전달해야 함

XMP 기록: ExifTool subprocess 사용 (write_xmp_metadata_with_exiftool)
  - exiftool_path=None → False (json_only 유지)
  - ExifTool 실패 → XmpWriteError (xmp_write_failed 처리)
  - ExifTool 성공 → True (full 승격)

실패 시 예외를 삼키지 않고 호출자에게 전달한다.
호출자는 실패를 metadata_write_failed로 처리한다.
"""
from __future__ import annotations

import json
import logging
import os
import struct
import subprocess
import time
import zlib
from pathlib import Path
from typing import Optional

from core.subprocess_util import no_window_kwargs

logger = logging.getLogger(__name__)


class XmpWriteError(Exception):
    """XMP 기록 실패 예외 — no_metadata_queue에 넣지 않음."""

ARU_KEYWORD = "AruArchive"


_TRUTHY_ENV = {"1", "true", "yes", "on"}


def _is_exiftool_timing_enabled() -> bool:
    """ARU_ENRICH_TIMING 또는 ARU_ARCHIVE_DEV_MODE 환경변수가 truthy면 True. config는 미참조."""
    if os.environ.get("ARU_ENRICH_TIMING", "").strip().lower() in _TRUTHY_ENV:
        return True
    if os.environ.get("ARU_ARCHIVE_DEV_MODE", "").strip().lower() in _TRUTHY_ENV:
        return True
    return False


def _log_exiftool_call(
    file_path: str,
    elapsed: float,
    args_count: int,
    timeout: bool,
    success: bool,
) -> None:
    """exiftool subprocess 1회 호출 timing을 logger.info에 기록한다 (timing 활성 시)."""
    if not _is_exiftool_timing_enabled():
        return
    logger.info(
        "exiftool_call file=%s elapsed=%.3fs args=%d timeout=%s success=%s",
        Path(file_path).name, elapsed, args_count,
        "true" if timeout else "false",
        "true" if success else "false",
    )


def _normalize_format_name(file_format: str) -> str:
    fmt = (file_format or "").lower().lstrip(".")
    return "jpg" if fmt == "jpeg" else fmt


def _sniff_file_format(file_path: str) -> Optional[str]:
    """Best-effort signature sniffing for metadata write routing."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
    except OSError:
        return None

    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"BM"):
        return "bmp"
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return None


def _resolve_effective_metadata_format(file_path: str, file_format: str) -> str:
    """Prefer file signature over the caller-provided format when they disagree."""
    requested = _normalize_format_name(file_format)
    actual = _sniff_file_format(file_path)
    if actual and actual != requested:
        logger.warning(
            "metadata format mismatch detected: path=%s requested=%s actual=%s",
            file_path, requested, actual,
        )
        return actual
    return requested


def detect_header_extension_mismatch(file_path: str) -> tuple[str, str] | None:
    """Return (path_format, actual_format) when extension and file signature differ."""
    actual_fmt = _sniff_file_format(file_path)
    path_fmt = _normalize_format_name(Path(file_path).suffix)
    if actual_fmt and path_fmt and actual_fmt != path_fmt:
        return path_fmt, actual_fmt
    return None


def _encode_xp_field(value: str) -> bytes:
    """Encode a Windows XP EXIF field as UTF-16LE with a null terminator."""
    return value.encode("utf-16-le") + b"\x00\x00"


def _ascii_image_description(metadata: dict) -> str:
    """Build an ASCII-safe EXIF ImageDescription to avoid JSON dump in Explorer."""
    source_site = (metadata.get("source_site") or "").strip()
    artwork_id = (metadata.get("artwork_id") or "").strip()
    if source_site and artwork_id:
        return f"Aru Archive: {source_site} artwork {artwork_id}"
    if artwork_id:
        return f"Aru Archive artwork {artwork_id}"
    if source_site:
        return f"Aru Archive: {source_site}"
    return "Aru Archive"


def _is_ascii_only(value: str) -> bool:
    try:
        value.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _write_windows_exif_fields_direct(file_path: str, metadata: dict) -> None:
    """Write Explorer-facing XP fields directly to EXIF using UTF-16LE bytes."""
    try:
        import piexif
    except ImportError as exc:
        raise XmpWriteError("piexif package is required for Windows EXIF XP fields") from exc

    try:
        exif_dict = piexif.load(file_path)
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    zeroth = exif_dict.setdefault("0th", {})

    title = (metadata.get("artwork_title") or "").strip()
    artist = (metadata.get("artist_name") or "").strip()
    summary = _build_user_facing_summary(metadata).strip()

    tag_values = metadata.get("tags")
    keywords: list[str] = []
    if isinstance(tag_values, list):
        keywords.extend(str(v).strip() for v in tag_values if str(v).strip())
    keywords_text = ";".join(dict.fromkeys(keywords))

    updates = {
        0x9C9B: title,         # XPTitle
        0x9C9F: title,         # XPSubject
        0x9C9D: artist,        # XPAuthor
        0x9C9E: keywords_text, # XPKeywords
        0x9C9C: summary,       # XPComment
    }
    for tag_id, text in updates.items():
        if text:
            zeroth[tag_id] = _encode_xp_field(text)
        else:
            zeroth.pop(tag_id, None)

    # ASCII-only fallback so Explorer prefers a short description over JSON dump.
    zeroth[piexif.ImageIFD.ImageDescription] = _ascii_image_description(metadata)

    try:
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, file_path)
    except Exception as exc:
        raise XmpWriteError(f"Windows EXIF XP field write failed: {exc}") from exc


def _write_windows_exif_fields_best_effort(
    file_path: str,
    metadata: dict,
    exiftool_path: Optional[str],
) -> None:
    """
    Prefer ExifTool for Explorer-facing XP fields and fall back to direct write.

    Explorer compatibility is better when XP fields are written by ExifTool.
    The direct piexif path is kept as a fallback for environments where
    ExifTool is unavailable after XMP was already written.
    """
    if exiftool_path:
        try:
            if write_windows_exif_fields(file_path, metadata, exiftool_path=exiftool_path):
                return
        except XmpWriteError as exc:
            logger.warning("ExifTool XP field write failed, falling back to direct EXIF write: %s", exc)
    _write_windows_exif_fields_direct(file_path, metadata)


def write_aru_metadata(file_path: str, metadata: dict, file_format: str) -> None:
    """
    파일 형식에 따라 AruArchive JSON 메타데이터를 삽입한다.

    file_format: 'jpg'|'jpeg'|'png'|'webp'|'zip'|'gif'
    BMP는 직접 지원하지 않는다 — PNG managed 경로를 전달할 것.

    실패 시 예외 발생 → 호출자: metadata_write_failed 처리.
    """
    fmt = _resolve_effective_metadata_format(file_path, file_format)
    if fmt in ("jpg", "jpeg"):
        _write_exif_user_comment(file_path, metadata)
    elif fmt == "png":
        _write_png_itxt(file_path, metadata)
    elif fmt == "webp":
        _write_exif_user_comment(file_path, metadata)
    elif fmt == "zip":
        _write_zip_metadata(file_path, metadata)
    elif fmt == "gif":
        _write_sidecar(file_path, metadata)
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {file_format}")


def _write_exif_user_comment(file_path: str, metadata: dict) -> None:
    """
    JPEG / WebP EXIF UserComment (0x9286)에 AruArchive JSON 기록.
    prefix: UNICODE\\x00 (8 bytes) + UTF-16LE JSON.
    """
    try:
        import piexif
    except ImportError:
        raise RuntimeError("piexif 패키지가 필요합니다: pip install piexif")

    json_bytes = json.dumps(metadata, ensure_ascii=False).encode("utf-16-le")
    user_comment = b"UNICODE\x00" + json_bytes

    try:
        exif_dict = piexif.load(file_path)
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    exif_dict.setdefault("Exif", {})[piexif.ExifIFD.UserComment] = user_comment
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, file_path)


def _write_png_itxt(file_path: str, metadata: dict) -> None:
    """PNG iTXt chunk (keyword=AruArchive)에 JSON 기록."""
    json_text = json.dumps(metadata, ensure_ascii=False)
    _insert_png_itxt_chunk(file_path, ARU_KEYWORD, json_text)


def _insert_png_itxt_chunk(file_path: str, keyword: str, text: str) -> None:
    """
    PNG 파일에 iTXt chunk를 삽입/교체한다.
    기존 AruArchive iTXt chunk가 있으면 먼저 제거한다.
    """
    PNG_SIG = b"\x89PNG\r\n\x1a\n"

    with open(file_path, "rb") as f:
        data = f.read()

    if not data.startswith(PNG_SIG):
        raise ValueError(f"유효한 PNG 파일이 아닙니다: {file_path}")

    chunks = _parse_png_chunks(data[8:])

    # 기존 AruArchive iTXt 청크 제거
    keyword_prefix = keyword.encode("utf-8") + b"\x00"
    chunks = [
        (ct, cd) for ct, cd in chunks
        if not (ct == b"iTXt" and cd.startswith(keyword_prefix))
    ]

    # 새 iTXt 청크: keyword \0 compression_flag(0) compression_method(0) language \0 translated_kw \0 text
    itxt_data = keyword.encode("utf-8") + b"\x00\x00\x00\x00\x00" + text.encode("utf-8")

    # IEND 앞에 삽입
    iend_idx = next((i for i, (ct, _) in enumerate(chunks) if ct == b"IEND"), len(chunks))
    chunks.insert(iend_idx, (b"iTXt", itxt_data))

    # 재조합
    result = PNG_SIG
    for ctype, cdata in chunks:
        crc = zlib.crc32(ctype + cdata) & 0xFFFFFFFF
        result += struct.pack(">I", len(cdata)) + ctype + cdata + struct.pack(">I", crc)

    with open(file_path, "wb") as f:
        f.write(result)


def _parse_png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """PNG 청크 파싱 → (type, data) 튜플 리스트."""
    chunks: list[tuple[bytes, bytes]] = []
    offset = 0
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        ctype = data[offset + 4 : offset + 8]
        cdata = data[offset + 8 : offset + 8 + length]
        chunks.append((ctype, cdata))
        offset += 12 + length
    return chunks


def _write_zip_metadata(file_path: str, metadata: dict) -> None:
    """
    ZIP (ugoira) 파일에 comment(식별자)를 삽입하고,
    .aru.json sidecar 파일을 생성한다.
    """
    import zipfile

    artwork_id = metadata.get("artwork_id", "")
    page_index = metadata.get("page_index", 0)
    comment = f"aru:v1:{artwork_id}:{page_index}".encode("utf-8")

    with zipfile.ZipFile(file_path, "a") as zf:
        zf.comment = comment

    _write_sidecar(file_path, metadata)


def _write_sidecar(file_path: str, metadata: dict) -> None:
    """
    {file_path}.aru.json sidecar 파일에 JSON 기록.
    static GIF와 ugoira ZIP에서 사용.
    """
    sidecar_path = Path(str(file_path) + ".aru.json")
    json_text = json.dumps(metadata, ensure_ascii=False, indent=2)
    sidecar_path.write_text(json_text, encoding="utf-8")


def _build_user_facing_summary(metadata: dict) -> str:
    """
    Windows Explorer에 표시할 사용자-facing 짧은 설명 문자열을 생성한다.

    형식: "Aru Archive: <source_site> artwork <artwork_id>"
    artwork_title이 있으면 부가 정보로 title도 포함한다.
    예: "Aru Archive: pixiv artwork 12345678 — 테스트 작품"

    metadata가 None이거나 필요한 키가 없으면 빈 문자열을 반환한다.
    반환값은 ExifTool XP 필드(XPComment, XPSubject)와
    EXIF:ImageDescription에 사용한다.

    주의: UserComment에 기록되는 JSON dump와 무관하다.
    UserComment는 Aru Archive 내부 schema 전용이며 변경하지 않는다.
    """
    if not metadata:
        return ""
    source_site = (metadata.get("source_site") or "").strip()
    artwork_id = (metadata.get("artwork_id") or "").strip()
    artwork_title = (metadata.get("artwork_title") or "").strip()

    if not source_site and not artwork_id:
        return ""

    parts = ["Aru Archive"]
    if source_site:
        parts.append(source_site)
    if artwork_id:
        parts.append(f"artwork {artwork_id}")
    summary = " ".join(parts)
    if artwork_title:
        summary = f"{summary} — {artwork_title}"
    return summary


def write_windows_exif_fields(
    file_path: str,
    metadata: dict,
    exiftool_path: Optional[str] = None,
) -> bool:
    """
    Windows Explorer 호환 EXIF XP 필드를 ExifTool로 기록한다.

    XPTitle / XPSubject / XPAuthor / XPKeywords / XPComment를
    UTF-16LE로 기록한다. ExifTool 없으면 False 반환.

    권장 호출 순서: write_aru_metadata → write_xmp_metadata_with_exiftool
    (include_xp_fields=True, 기본값). ExifTool이 XMP와 XP 필드를 한 번에 기록.
    이 함수는 XP 필드만 독립적으로 재기록할 때 사용한다.

    반환값:
      True  : 기록 성공
      False : ExifTool 없음
    예외:
      XmpWriteError : ExifTool 실행 실패
    """
    if not exiftool_path:
        return False

    from core.exiftool import build_exiftool_xp_args, validate_exiftool_path

    if not validate_exiftool_path(exiftool_path):
        logger.warning("ExifTool 실행 불가 (XP 필드 기록 건너뜀): %s", exiftool_path)
        return False

    summary = _build_user_facing_summary(metadata)
    xp_subject = (metadata.get("artwork_title") or "").strip()
    args = [exiftool_path] + build_exiftool_xp_args(
        file_path, metadata,
        xp_subject=xp_subject,
        xp_comment=summary,
    )
    _t0 = time.perf_counter()
    _timeout = False
    _success = False
    try:
        result = subprocess.run(args, capture_output=True, timeout=60, **no_window_kwargs())
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            stdout = result.stdout.decode("utf-8", errors="replace")
            raise XmpWriteError(
                f"XP 필드 기록 실패 (rc={result.returncode}): "
                f"{stderr.strip() or stdout.strip()}"
            )
        logger.info("Windows EXIF XP 필드 기록 완료: %s", file_path)
        _success = True
        return True
    except subprocess.TimeoutExpired:
        _timeout = True
        raise XmpWriteError(f"ExifTool 타임아웃 (XP 필드): {file_path}")
    except XmpWriteError:
        raise
    except Exception as exc:
        raise XmpWriteError(f"ExifTool 실행 오류 (XP 필드): {exc}") from exc
    finally:
        _log_exiftool_call(
            file_path, time.perf_counter() - _t0, len(args),
            timeout=_timeout, success=_success,
        )


def write_xmp_metadata_with_exiftool(
    file_path: str,
    metadata: dict,
    exiftool_path: Optional[str] = None,
    include_xp_fields: bool = True,
) -> bool:
    """
    ExifTool을 사용하여 XMP 표준 필드를 기록한다.

    include_xp_fields=True (기본값)이면 XMP-dc 필드와 함께
    Windows Explorer 호환 EXIF XP 필드를 한 번의 ExifTool 호출로 기록한다.
      - XPTitle / XPAuthor / XPKeywords (기존)
      - XPSubject / XPComment (신규 — 사용자-facing 요약 기록)
      - EXIF:ImageDescription (신규 — description column JSON dump 방지)

    반환값:
      True   : XMP 기록 성공 → metadata_sync_status = 'full'
      False  : ExifTool 없음 또는 실행 불가 → json_only 유지

    예외:
      XmpWriteError : ExifTool 실행 실패 → metadata_sync_status = 'xmp_write_failed'

    exiftool_path=None이면 항상 False 반환.
    shell=True 사용 금지 — subprocess.run([...]) 인자 리스트 사용.
    """
    if not exiftool_path:
        return False

    from core.exiftool import (
        build_exiftool_xmp_args,
        validate_exiftool_path,
    )

    if not validate_exiftool_path(exiftool_path):
        logger.warning("ExifTool 실행 불가: %s", exiftool_path)
        return False

    mismatch = detect_header_extension_mismatch(file_path)
    effective_include_xp = include_xp_fields
    include_exif_description = True

    if mismatch is not None:
        path_fmt, actual_fmt = mismatch
        logger.warning(
            "XMP target header/extension mismatch: path=%s ext=%s actual=%s",
            file_path, path_fmt, actual_fmt,
        )
        return False

    # 사용자-facing 요약 문자열 생성 — XPSubject / XPComment / ImageDescription 공용
    summary = _build_user_facing_summary(metadata)

    # XMP 인자 (ImageDescription 포함, -overwrite_original과 file_path 포함)
    xmp_args = build_exiftool_xmp_args(
        file_path,
        metadata,
        user_facing_summary=summary,
        include_exif_description=include_exif_description,
    )

    args = [exiftool_path] + xmp_args
    _t0 = time.perf_counter()
    _timeout = False
    _success = False
    try:
        result = subprocess.run(args, capture_output=True, timeout=60, **no_window_kwargs())
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            stdout = result.stdout.decode("utf-8", errors="replace")
            raise XmpWriteError(
                f"ExifTool 실패 (returncode={result.returncode}): "
                f"{stderr.strip() or stdout.strip()}"
            )
        if effective_include_xp and Path(file_path).exists():
            _write_windows_exif_fields_best_effort(
                file_path,
                metadata,
                exiftool_path,
            )
        logger.info("XMP%s 기록 완료: %s",
                    "+XP" if effective_include_xp else "", file_path)
        _success = True
        return True
    except subprocess.TimeoutExpired:
        _timeout = True
        raise XmpWriteError(f"ExifTool 타임아웃 (60s): {file_path}")
    except XmpWriteError:
        raise
    except Exception as exc:
        raise XmpWriteError(f"ExifTool 실행 오류: {exc}") from exc
    finally:
        _log_exiftool_call(
            file_path, time.perf_counter() - _t0, len(args),
            timeout=_timeout, success=_success,
        )
