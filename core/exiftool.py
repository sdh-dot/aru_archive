"""
ExifTool 경로 검증, 버전 확인, XMP/XP CLI 인자 빌더, 진단 읽기.

shell=True 사용 금지. 모든 subprocess 호출은 인자 리스트로 전달한다.

Windows Explorer 호환 필드:
  XPTitle    (0x9C9B) — 탐색기 "제목" 열
  XPAuthor   (0x9C9D) — 탐색기 "만든 이" 열
  XPKeywords (0x9C9E) — 탐색기 "태그" 열
  모두 UTF-16LE null-terminated 로 저장.

주의: piexif는 이 태그들을 인식하지 못하므로, piexif로 EXIF를 재기록하면
기존 XP 필드가 소실된다. ExifTool을 사용해야 안전하다.
"""
from __future__ import annotations

import json as _json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def validate_exiftool_path(exiftool_path: Optional[str]) -> bool:
    """exiftool_path가 실행 가능한지 확인한다."""
    if not exiftool_path:
        return False
    try:
        result = subprocess.run(
            [exiftool_path, "-ver"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired, PermissionError):
        return False


def get_exiftool_version(exiftool_path: str) -> Optional[str]:
    """exiftool_path의 버전 문자열을 반환한다. 실패 시 None."""
    try:
        result = subprocess.run(
            [exiftool_path, "-ver"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception as exc:
        logger.debug("ExifTool 버전 확인 실패: %s", exc)
        return None


def build_exiftool_xmp_args(
    file_path: str,
    metadata: dict,
) -> list[str]:
    """
    ExifTool XMP 기록용 CLI 인자 리스트를 생성한다.

    반환값은 [exiftool_path] + 이 리스트를 concatenate해서 subprocess.run()에 전달한다.
    shell=True 없이 직접 사용 가능하다.

    매핑:
      XMP-dc:Title       ← artwork_title
      XMP-dc:Creator     ← artist_name
      XMP-dc:Subject     ← tags + series_tags + character_tags (multi-value)
      XMP-dc:Source      ← artwork_url
      XMP-dc:Description ← description / custom_notes
      XMP-dc:Identifier  ← artwork_id
      XMP:MetadataDate   ← 현재 UTC
      XMP:Rating         ← rating (있으면)
      XMP:Label          ← source_site 또는 "Aru Archive"
    """
    args: list[str] = []

    title = (metadata.get("artwork_title") or "").strip()
    if title:
        args.append(f"-XMP-dc:Title={title}")

    artist = (metadata.get("artist_name") or "").strip()
    if artist:
        args.append(f"-XMP-dc:Creator={artist}")

    # Subject: tags + series_tags + character_tags 합집합
    subjects: list[str] = []
    for key in ("tags", "series_tags", "character_tags"):
        val = metadata.get(key)
        if isinstance(val, list):
            subjects.extend(v for v in val if v and str(v).strip())
    for subj in subjects:
        args.append(f"-XMP-dc:Subject={subj}")

    artwork_url = (metadata.get("artwork_url") or "").strip()
    if artwork_url:
        args.append(f"-XMP-dc:Source={artwork_url}")

    description = (
        metadata.get("description") or metadata.get("custom_notes") or ""
    ).strip()
    if description:
        args.append(f"-XMP-dc:Description={description}")

    artwork_id = (metadata.get("artwork_id") or "").strip()
    if artwork_id:
        args.append(f"-XMP-dc:Identifier={artwork_id}")

    now = datetime.now(timezone.utc).strftime("%Y:%m:%d %H:%M:%S+00:00")
    args.append(f"-XMP:MetadataDate={now}")

    rating = metadata.get("rating")
    if rating is not None:
        try:
            args.append(f"-XMP:Rating={int(rating)}")
        except (TypeError, ValueError):
            pass

    source_site = (metadata.get("source_site") or "").strip()
    label = source_site if source_site else "Aru Archive"
    args.append(f"-XMP:Label={label}")

    args.append("-overwrite_original")
    args.append(file_path)

    return args


def build_exiftool_xp_args(
    file_path: str,
    metadata: dict,
) -> list[str]:
    """
    Windows Explorer 호환 EXIF XP 필드 기록용 ExifTool CLI 인자.

    XPTitle (0x9C9B), XPAuthor (0x9C9D), XPKeywords (0x9C9E)를
    UTF-16LE로 기록한다. ExifTool이 입력값을 UTF-8로 해석하도록
    -charset exif=utf8 을 지정한다.

    반환값: [exiftool_path] + 이 리스트 형태로 subprocess.run()에 전달.
    """
    args: list[str] = ["-charset", "exif=utf8"]

    title = (metadata.get("artwork_title") or "").strip()
    if title:
        args.append(f"-EXIF:XPTitle={title}")

    artist = (metadata.get("artist_name") or "").strip()
    if artist:
        args.append(f"-EXIF:XPAuthor={artist}")

    subjects: list[str] = []
    for key in ("tags", "series_tags", "character_tags"):
        val = metadata.get(key)
        if isinstance(val, list):
            subjects.extend(v for v in val if v and str(v).strip())
    for subj in subjects:
        args.append(f"-EXIF:XPKeywords={subj}")

    args.append("-overwrite_original")
    args.append(file_path)
    return args


# ---------------------------------------------------------------------------
# 진단: 현재 파일의 EXIF/XMP 메타데이터 상태 읽기
# ---------------------------------------------------------------------------

# Windows XP EXIF 태그 번호 (0th IFD)
_XP_TITLE    = 0x9C9B  # XPTitle
_XP_AUTHOR   = 0x9C9D  # XPAuthor
_XP_KEYWORDS = 0x9C9E  # XPKeywords


def read_exif_diagnostics(
    file_path: str,
    exiftool_path: Optional[str] = None,
) -> dict:
    """
    파일의 EXIF/XMP 메타데이터 현재 상태를 진단한다.

    반환:
    {
        "file_path":                str,
        "exif_xptitle":             str | None,   # 탐색기 제목
        "exif_xpkeywords":          list[str] | None,  # 탐색기 태그
        "exif_xpauthor":            str | None,   # 탐색기 만든 이
        "exif_user_comment_prefix": str | None,   # UserComment 인코딩 접두사
        "has_aru_metadata":         bool,
        "xmp_dc_title":             str | None,
        "xmp_dc_subject":           list[str] | None,
        "xmp_dc_creator":           str | None,
        "warnings":                 list[str],
    }

    exiftool_path 제공 시 XMP-dc 필드도 읽는다.
    ExifTool 없이도 EXIF XP 필드는 piexif로 읽는다.
    """
    result: dict = {
        "file_path":                file_path,
        "exif_xptitle":             None,
        "exif_xpkeywords":          None,
        "exif_xpauthor":            None,
        "exif_user_comment_prefix": None,
        "has_aru_metadata":         False,
        "xmp_dc_title":             None,
        "xmp_dc_subject":           None,
        "xmp_dc_creator":           None,
        "warnings":                 [],
    }

    _read_exif_via_piexif(file_path, result)

    if exiftool_path and validate_exiftool_path(exiftool_path):
        _read_xmp_via_exiftool(file_path, exiftool_path, result)

    return result


def _decode_xp_bytes(raw, warnings: list[str], field: str) -> Optional[str]:
    """UTF-16LE null-terminated XP 필드 → str. 실패 시 None.

    piexif는 알 수 없는 0th IFD 태그를 tuple[int]로 반환할 수 있다.
    bytes와 tuple 모두 처리한다.
    """
    if not raw:
        return None
    if isinstance(raw, tuple):
        raw = bytes(raw)
    try:
        return raw.decode("utf-16-le").rstrip("\x00")
    except Exception as exc:
        warnings.append(f"{field} 디코딩 실패 ({raw[:16].hex()}): {exc}")
        return None


def _read_exif_via_piexif(file_path: str, result: dict) -> None:
    """piexif로 EXIF UserComment와 XP 필드를 읽는다."""
    try:
        import piexif
    except ImportError:
        result["warnings"].append("piexif 미설치 — EXIF 직접 읽기 불가")
        return

    try:
        exif = piexif.load(file_path)
    except Exception:
        # EXIF 세그먼트가 없거나 손상 → 빈 dict로 계속 (XP 필드 없음 경고 발생)
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    # UserComment (Exif IFD)
    uc = exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b"")
    if uc:
        if uc.startswith(b"UNICODE\x00"):
            result["exif_user_comment_prefix"] = "UNICODE\\0 (AruArchive JSON)"
            result["has_aru_metadata"] = True
        elif uc.startswith(b"ASCII\x00\x00\x00"):
            result["exif_user_comment_prefix"] = "ASCII"
        else:
            result["exif_user_comment_prefix"] = f"raw:{uc[:8].hex()}"

    zeroth = exif.get("0th", {})
    warns  = result["warnings"]

    result["exif_xptitle"]  = _decode_xp_bytes(zeroth.get(_XP_TITLE,    b""), warns, "XPTitle")
    result["exif_xpauthor"] = _decode_xp_bytes(zeroth.get(_XP_AUTHOR,   b""), warns, "XPAuthor")

    kw_raw = zeroth.get(_XP_KEYWORDS, b"")
    if kw_raw:
        kw_str = _decode_xp_bytes(kw_raw, warns, "XPKeywords")
        if kw_str is not None:
            result["exif_xpkeywords"] = [k for k in kw_str.split(";") if k]

    if not result["exif_xptitle"] and not result["exif_xpkeywords"]:
        result["warnings"].append(
            "XPTitle / XPKeywords 없음 — "
            "Windows 탐색기에서 제목·태그가 표시되지 않습니다."
        )


def _read_xmp_via_exiftool(file_path: str, exiftool_path: str, result: dict) -> None:
    """ExifTool로 XMP-dc 필드를 읽어 result에 채운다."""
    try:
        proc = subprocess.run(
            [
                exiftool_path, "-j",
                "-charset", "exif=utf8",
                "-XMP-dc:Title", "-XMP-dc:Subject", "-XMP-dc:Creator",
                file_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            result["warnings"].append(
                f"ExifTool XMP 읽기 실패 (rc={proc.returncode})"
            )
            return
        data = _json.loads(proc.stdout.decode("utf-8", errors="replace"))
        if not data:
            return
        d = data[0]
        result["xmp_dc_title"]   = d.get("Title")
        result["xmp_dc_creator"] = d.get("Creator")
        subj = d.get("Subject")
        if isinstance(subj, str):
            result["xmp_dc_subject"] = [subj]
        elif isinstance(subj, list):
            result["xmp_dc_subject"] = subj
    except Exception as exc:
        result["warnings"].append(f"ExifTool XMP 읽기 오류: {exc}")
