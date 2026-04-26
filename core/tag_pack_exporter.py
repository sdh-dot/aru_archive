"""
Tag pack 내보내기 서비스.

export_public_tag_pack():    tag_aliases + tag_localizations → 공개용 pack (개인 데이터 제외)
export_dictionary_backup():  tag_aliases + tag_localizations + external_dictionary_entries 전체
save_to_file():              UTF-8 pretty JSON으로 파일에 저장
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def export_public_tag_pack(
    conn: sqlite3.Connection,
    pack_id: str,
    pack_name: str,
    version: str = "1.0.0",
) -> dict:
    """
    tag_aliases + tag_localizations를 공개용 tag pack 형식으로 내보낸다.

    개인 데이터(작품 ID, 파일 경로, evidence_json)는 포함하지 않는다.

    반환:
        tag pack dict — 그대로 seed_tag_pack()에 전달 가능한 형식
    """
    pack: dict = {
        "pack_id":     pack_id,
        "name":        pack_name,
        "version":     version,
        "source":      "user_export",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "series":      [],
        "characters":  [],
    }

    # ── series ──
    series_canonicals = conn.execute(
        "SELECT DISTINCT canonical FROM tag_aliases "
        "WHERE tag_type='series' AND enabled=1 ORDER BY canonical"
    ).fetchall()

    for sr in series_canonicals:
        canonical = sr["canonical"]

        aliases = [r["alias"] for r in conn.execute(
            "SELECT alias FROM tag_aliases "
            "WHERE canonical=? AND tag_type='series' AND enabled=1 "
            "ORDER BY alias",
            (canonical,),
        ).fetchall()]

        locs = {r["locale"]: r["display_name"] for r in conn.execute(
            "SELECT locale, display_name FROM tag_localizations "
            "WHERE canonical=? AND tag_type='series' AND enabled=1 "
            "ORDER BY locale",
            (canonical,),
        ).fetchall()}

        pack["series"].append({
            "canonical":     canonical,
            "aliases":       aliases,
            "localizations": locs,
        })

    # ── characters ──
    char_canonicals = conn.execute(
        "SELECT DISTINCT canonical, parent_series FROM tag_aliases "
        "WHERE tag_type='character' AND enabled=1 "
        "ORDER BY canonical",
    ).fetchall()

    for cr in char_canonicals:
        canonical     = cr["canonical"]
        parent_series = cr["parent_series"] or ""

        aliases = [r["alias"] for r in conn.execute(
            "SELECT alias FROM tag_aliases "
            "WHERE canonical=? AND tag_type='character' AND parent_series=? AND enabled=1 "
            "ORDER BY alias",
            (canonical, parent_series),
        ).fetchall()]

        locs = {r["locale"]: r["display_name"] for r in conn.execute(
            "SELECT locale, display_name FROM tag_localizations "
            "WHERE canonical=? AND tag_type='character' AND parent_series=? AND enabled=1 "
            "ORDER BY locale",
            (canonical, parent_series),
        ).fetchall()}

        pack["characters"].append({
            "canonical":     canonical,
            "parent_series": parent_series,
            "aliases":       aliases,
            "localizations": locs,
        })

    return pack


def export_dictionary_backup(conn: sqlite3.Connection) -> dict:
    """
    tag_aliases + tag_localizations + external_dictionary_entries 전체를 내보낸다.

    evidence_json 등 개인 데이터 포함. 복원 용도.
    """
    aliases = [dict(r) for r in conn.execute(
        "SELECT * FROM tag_aliases ORDER BY tag_type, canonical, alias"
    ).fetchall()]

    localizations = [dict(r) for r in conn.execute(
        "SELECT * FROM tag_localizations ORDER BY canonical, tag_type, locale"
    ).fetchall()]

    external_entries = [dict(r) for r in conn.execute(
        "SELECT * FROM external_dictionary_entries ORDER BY source, canonical"
    ).fetchall()]

    return {
        "backup_type":                 "dictionary_backup",
        "exported_at":                 datetime.now(timezone.utc).isoformat(),
        "tag_aliases":                 aliases,
        "tag_localizations":           localizations,
        "external_dictionary_entries": external_entries,
    }


def save_to_file(data: dict, path: str | Path) -> None:
    """UTF-8 pretty JSON (ensure_ascii=False, indent=2, sort_keys=True) 으로 저장한다."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
