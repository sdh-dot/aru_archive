"""
Explorer-facing metadata repair helpers.

This feature force-rewrites Windows Explorer-visible metadata for selected
groups, even when the current metadata_sync_status is already ``full``.
It reuses the same target-file selection policy as XMP retry, but the user
intent is different: clean up mixed legacy XP/XMP fields so Explorer stops
showing stale or mojibake values.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Optional, Sequence

from core.xmp_retry import _read_metadata_for_xmp, _set_sync_status, select_xmp_target_file

logger = logging.getLogger(__name__)


def repair_explorer_meta_for_group(
    conn: sqlite3.Connection,
    group_id: str,
    exiftool_path: Optional[str],
) -> dict:
    """
    Force-rewrite Explorer-facing metadata for a single group.

    Returns:
        {
          "status": "success" | "no_target" | "no_exiftool" | "failed" | "skipped",
          "message": str,
        }
    """
    if not exiftool_path:
        return {
            "status": "no_exiftool",
            "message": "ExifTool path is not configured",
        }

    target = select_xmp_target_file(conn, group_id)
    if target is None:
        return {
            "status": "no_target",
            "message": f"No writable metadata target file for group: {group_id}",
        }

    metadata = _read_metadata_for_xmp(conn, group_id)
    file_path = target["file_path"]

    from core.metadata_writer import (
        XmpWriteError,
        detect_header_extension_mismatch,
        write_xmp_metadata_with_exiftool,
    )

    mismatch = detect_header_extension_mismatch(file_path)
    if mismatch is not None:
        path_fmt, actual_fmt = mismatch
        logger.warning(
            "Explorer metadata repair skipped due to header/extension mismatch "
            "(group=%s): %s ext=%s actual=%s",
            group_id,
            file_path,
            path_fmt,
            actual_fmt,
        )
        return {
            "status": "skipped",
            "message": (
                f"header/extension mismatch: ext={path_fmt} actual={actual_fmt} "
                f"({file_path})"
            ),
        }

    try:
        ok = write_xmp_metadata_with_exiftool(file_path, metadata, exiftool_path)
    except XmpWriteError as exc:
        _set_sync_status(conn, group_id, "xmp_write_failed")
        logger.warning("Explorer metadata repair failed (group=%s): %s", group_id, exc)
        return {"status": "failed", "message": str(exc)}

    if ok:
        _set_sync_status(conn, group_id, "full")
        return {
            "status": "success",
            "message": f"Explorer metadata repaired: {file_path}",
        }

    return {
        "status": "no_exiftool",
        "message": "ExifTool execution unavailable",
    }


def repair_explorer_meta_for_groups(
    conn: sqlite3.Connection,
    group_ids: Sequence[str],
    exiftool_path: Optional[str],
    progress_fn: Optional[Callable[[int, int, str, str], None]] = None,
) -> dict:
    """
    Force-rewrite Explorer-facing metadata for selected groups.
    """
    ids = list(dict.fromkeys(group_ids))
    total = len(ids)
    success = 0
    failed = 0
    skipped = 0
    errors: list[str] = []

    for index, gid in enumerate(ids, start=1):
        if progress_fn:
            progress_fn(index - 1, total, gid, "running")
        result = repair_explorer_meta_for_group(conn, gid, exiftool_path)
        status = result["status"]
        if status == "success":
            success += 1
        elif status in ("no_target", "no_exiftool", "skipped"):
            skipped += 1
        else:
            failed += 1
            errors.append(f"{gid[:8]}: {result.get('message', '')}")
        if progress_fn:
            progress_fn(index, total, gid, status)

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "group_ids": ids,
    }
