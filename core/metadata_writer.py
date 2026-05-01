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


def write_aru_metadata(file_path: str, metadata: dict, file_format: str) -> None:
    """
    파일 형식에 따라 AruArchive JSON 메타데이터를 삽입한다.

    file_format: 'jpg'|'jpeg'|'png'|'webp'|'zip'|'gif'
    BMP는 직접 지원하지 않는다 — PNG managed 경로를 전달할 것.

    실패 시 예외 발생 → 호출자: metadata_write_failed 처리.
    """
    fmt = file_format.lower().lstrip(".")
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
        result = subprocess.run(args, capture_output=True, timeout=60)
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
        build_exiftool_xp_args,
        validate_exiftool_path,
    )

    if not validate_exiftool_path(exiftool_path):
        logger.warning("ExifTool 실행 불가: %s", exiftool_path)
        return False

    # 사용자-facing 요약 문자열 생성 — XPSubject / XPComment / ImageDescription 공용
    summary = _build_user_facing_summary(metadata)

    # XMP 인자 (ImageDescription 포함, -overwrite_original과 file_path 포함)
    xmp_args = build_exiftool_xmp_args(file_path, metadata, user_facing_summary=summary)

    if include_xp_fields:
        # XPSubject: artwork_title (탐색기 "주제" 열)
        xp_subject = (metadata.get("artwork_title") or "").strip()
        # XPComment: 사용자-facing 짧은 요약 (탐색기 "설명/주석" 열)
        xp_comment = summary

        # XP 인자에서 중복되는 -overwrite_original / file_path 제거 후 합침
        xp_args = build_exiftool_xp_args(
            file_path, metadata,
            xp_subject=xp_subject,
            xp_comment=xp_comment,
        )
        xp_tag_args = [
            a for a in xp_args
            if a not in ("-overwrite_original", file_path)
        ]
        # XMP 인자의 마지막 두 항목(-overwrite_original, file_path) 앞에 삽입
        xmp_args = xmp_args[:-2] + xp_tag_args + xmp_args[-2:]

    args = [exiftool_path] + xmp_args
    _t0 = time.perf_counter()
    _timeout = False
    _success = False
    try:
        result = subprocess.run(args, capture_output=True, timeout=60)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            stdout = result.stdout.decode("utf-8", errors="replace")
            raise XmpWriteError(
                f"ExifTool 실패 (returncode={result.returncode}): "
                f"{stderr.strip() or stdout.strip()}"
            )
        logger.info("XMP%s 기록 완료: %s",
                    "+XP" if include_xp_fields else "", file_path)
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
