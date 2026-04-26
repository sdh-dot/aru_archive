"""
태그 팩 로드·검증·DB seed 기능.

tag pack JSON 형식:
{
  "pack_id": "...",
  "name": "...",
  "version": "...",
  "source": "built_in",
  "series": [...],
  "characters": [...]
}

DB 저장 정책:
  series alias   → tag_aliases (tag_type='series',    parent_series='')
  character alias→ tag_aliases (tag_type='character', parent_series=parent_series)
  localization   → tag_localizations (INSERT OR IGNORE)
  source = 'built_in_pack:{pack_id}'
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


def load_tag_pack(path: Union[str, Path]) -> dict:
    """JSON tag pack 파일을 로드한다."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_tag_pack(pack: dict) -> None:
    """기본 구조 검증. 실패 시 ValueError."""
    for key in ("pack_id", "name", "version"):
        if key not in pack:
            raise ValueError(f"tag pack에 필수 키 없음: {key}")
    if not isinstance(pack.get("series", []), list):
        raise ValueError("'series'는 list여야 합니다")
    if not isinstance(pack.get("characters", []), list):
        raise ValueError("'characters'는 list여야 합니다")


def seed_tag_pack(conn: sqlite3.Connection, pack: dict) -> dict:
    """
    pack의 series/characters aliases를 tag_aliases에 INSERT OR IGNORE.
    localizations를 tag_localizations에 INSERT OR IGNORE.

    alias가 이미 다른 canonical에 등록되어 있으면 충돌로 기록하고 건너뛴다.

    반환:
        {
            "series_aliases":    N,
            "character_aliases": N,
            "localizations":     N,
            "conflicts": [{"alias": ..., "existing_canonical": ..., "pack_canonical": ...}],
        }
    """
    validate_tag_pack(pack)
    pack_id = pack["pack_id"]
    source = f"built_in_pack:{pack_id}"
    now = datetime.now(timezone.utc).isoformat()

    series_count = 0
    char_count = 0
    loc_count = 0
    conflicts: list[dict] = []

    for series in pack.get("series", []):
        canonical = series["canonical"]
        media_type = series.get("media_type", "")

        for alias in series.get("aliases", []):
            try:
                existing = conn.execute(
                    "SELECT canonical FROM tag_aliases "
                    "WHERE alias=? AND tag_type='series' AND enabled=1",
                    (alias,),
                ).fetchone()
                if existing and existing["canonical"] != canonical:
                    conflicts.append({
                        "alias":              alias,
                        "existing_canonical": existing["canonical"],
                        "pack_canonical":     canonical,
                    })
                    logger.debug(
                        "series alias 충돌 (건너뜀): %s → %s (기존 %s)",
                        alias, canonical, existing["canonical"],
                    )
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO tag_aliases
                       (alias, canonical, tag_type, parent_series, media_type,
                        source, enabled, created_at)
                       VALUES (?, ?, 'series', '', ?, ?, 1, ?)""",
                    (alias, canonical, media_type, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    series_count += 1
            except Exception as exc:
                logger.debug("series alias 삽입 실패 (%s): %s", alias, exc)

        for locale, display_name in series.get("localizations", {}).items():
            try:
                lid = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO tag_localizations
                       (localization_id, canonical, tag_type, parent_series,
                        locale, display_name, source, enabled, created_at)
                       VALUES (?, ?, 'series', '', ?, ?, ?, 1, ?)""",
                    (lid, canonical, locale, display_name, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    loc_count += 1
            except Exception as exc:
                logger.debug("series localization 삽입 실패 (%s/%s): %s", canonical, locale, exc)

    for character in pack.get("characters", []):
        canonical = character["canonical"]
        parent_series = character.get("parent_series", "")

        for alias in character.get("aliases", []):
            try:
                existing = conn.execute(
                    "SELECT canonical FROM tag_aliases "
                    "WHERE alias=? AND tag_type='character' AND enabled=1",
                    (alias,),
                ).fetchone()
                if existing and existing["canonical"] != canonical:
                    conflicts.append({
                        "alias":              alias,
                        "existing_canonical": existing["canonical"],
                        "pack_canonical":     canonical,
                    })
                    logger.debug(
                        "character alias 충돌 (건너뜀): %s → %s (기존 %s)",
                        alias, canonical, existing["canonical"],
                    )
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO tag_aliases
                       (alias, canonical, tag_type, parent_series,
                        source, enabled, created_at)
                       VALUES (?, ?, 'character', ?, ?, 1, ?)""",
                    (alias, canonical, parent_series, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    char_count += 1
            except Exception as exc:
                logger.debug("character alias 삽입 실패 (%s): %s", alias, exc)

        for locale, display_name in character.get("localizations", {}).items():
            try:
                lid = str(uuid.uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO tag_localizations
                       (localization_id, canonical, tag_type, parent_series,
                        locale, display_name, source, enabled, created_at)
                       VALUES (?, ?, 'character', ?, ?, ?, ?, 1, ?)""",
                    (lid, canonical, parent_series, locale, display_name, source, now),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    loc_count += 1
            except Exception as exc:
                logger.debug("character localization 삽입 실패 (%s/%s): %s", canonical, locale, exc)

    conn.commit()
    if conflicts:
        logger.warning(
            "tag pack '%s' alias 충돌 %d건 (건너뜀): %s",
            pack_id, len(conflicts),
            [c["alias"] for c in conflicts],
        )
    return {
        "series_aliases":    series_count,
        "character_aliases": char_count,
        "localizations":     loc_count,
        "conflicts":         conflicts,
    }


def seed_builtin_tag_packs(conn: sqlite3.Connection) -> dict:
    """
    resources/tag_packs/ 내 모든 내장 tag pack을 seed한다.
    중복 삽입은 INSERT OR IGNORE로 방지한다.

    반환: {"series_aliases": N, "character_aliases": N, "localizations": N}
    """
    packs_dir = Path(__file__).parent.parent / "resources" / "tag_packs"
    if not packs_dir.exists():
        logger.debug("tag_packs 디렉터리 없음: %s", packs_dir)
        return {"series_aliases": 0, "character_aliases": 0, "localizations": 0}

    total: dict[str, int] = {"series_aliases": 0, "character_aliases": 0, "localizations": 0}
    for pack_file in sorted(packs_dir.glob("*.json")):
        try:
            pack = load_tag_pack(pack_file)
            result = seed_tag_pack(conn, pack)
            for key in total:
                total[key] += result.get(key, 0)
            if any(result.values()):
                logger.info("tag pack seed 완료: %s → %s", pack_file.name, result)
        except Exception as exc:
            logger.warning("tag pack 로드 실패 (%s): %s", pack_file.name, exc)
    return total
