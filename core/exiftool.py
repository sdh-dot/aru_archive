"""
ExifTool 경로 검증, 버전 확인, XMP CLI 인자 빌더.

shell=True 사용 금지. 모든 subprocess 호출은 인자 리스트로 전달한다.
"""
from __future__ import annotations

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
