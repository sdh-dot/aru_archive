"""
태그 로컬라이즈 모듈.

역할:
  - canonical tag → locale별 display name (폴더명용) 변환
  - built-in localization seed (Blue Archive 등)
  - DB tag_localizations 테이블 CRUD 헬퍼

우선순위:
  1. locale == "canonical" → canonical 즉시 반환
  2. DB tag_localizations (enabled=1) 검색
  3. BUILTIN_LOCALIZATIONS 검색
  4. fallback_locale로 DB 재검색
  5. fallback_locale로 BUILTIN 재검색
  6. canonical 반환
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Built-in localizations
# ---------------------------------------------------------------------------

BUILTIN_LOCALIZATIONS: list[dict] = [
    # ── Series ──────────────────────────────────────────────────────
    {
        "canonical": "Blue Archive",
        "tag_type": "series",
        "parent_series": "",
        "locale": "ko",
        "display_name": "블루 아카이브",
    },
    {
        "canonical": "Blue Archive",
        "tag_type": "series",
        "parent_series": "",
        "locale": "ja",
        "display_name": "ブルーアーカイブ",
    },
    {
        "canonical": "Blue Archive",
        "tag_type": "series",
        "parent_series": "",
        "locale": "en",
        "display_name": "Blue Archive",
    },
    # ── Blue Archive Characters (ko) ────────────────────────────────
    {
        "canonical": "伊落マリー",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "이오치 마리",
    },
    {
        "canonical": "水羽ミモリ",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "미즈하 미모리",
    },
    {
        "canonical": "陸八魔アル",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "리쿠하치마 아루",
    },
    {
        "canonical": "砂狼シロコ",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "스나오카미 시로코",
    },
    {
        "canonical": "小鳥遊ホシノ",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "타카나시 호시노",
    },
    {
        "canonical": "飛鳥馬トキ",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "아스마 도키",
    },
    {
        "canonical": "天雨涙",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "아마우 루이",
    },
    {
        "canonical": "鬼方カリン",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "오니가타 카린",
    },
    {
        "canonical": "壱百満天原サロメ",
        "tag_type": "character",
        "parent_series": "Blue Archive",
        "locale": "ko",
        "display_name": "이치카 만텐바라 살로메",
    },
]


# ---------------------------------------------------------------------------
# 내부 lookup 헬퍼
# ---------------------------------------------------------------------------

def _builtin_lookup(
    canonical: str,
    tag_type: str,
    parent_series: str,
    locale: str,
) -> Optional[str]:
    """BUILTIN_LOCALIZATIONS에서 exact match 검색. 없으면 None."""
    ps = parent_series or ""
    for entry in BUILTIN_LOCALIZATIONS:
        if (
            entry["canonical"] == canonical
            and entry["tag_type"] == tag_type
            and (entry.get("parent_series") or "") == ps
            and entry["locale"] == locale
        ):
            return entry["display_name"]
    return None


def _db_lookup(
    conn: sqlite3.Connection,
    canonical: str,
    tag_type: str,
    parent_series: str,
    locale: str,
) -> Optional[str]:
    """DB tag_localizations에서 enabled=1 exact match 검색. 없으면 None."""
    ps = parent_series or ""
    row = conn.execute(
        """SELECT display_name FROM tag_localizations
           WHERE canonical = ? AND tag_type = ? AND parent_series = ?
             AND locale = ? AND enabled = 1
           LIMIT 1""",
        (canonical, tag_type, ps, locale),
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def resolve_display_name(
    conn: Optional[sqlite3.Connection],
    canonical: str,
    tag_type: str,
    *,
    parent_series: Optional[str] = None,
    locale: str = "canonical",
    fallback_locale: str = "canonical",
) -> str:
    """
    canonical tag → folder display name 변환.

    우선순위:
      1. locale == "canonical" → canonical 즉시 반환
      2. DB 검색 (enabled=1)
      3. BUILTIN_LOCALIZATIONS 검색
      4. fallback_locale DB 검색
      5. fallback_locale BUILTIN 검색
      6. canonical 반환
    """
    if locale == "canonical" or not canonical:
        return canonical

    ps = parent_series or ""

    # 2. DB
    if conn is not None:
        found = _db_lookup(conn, canonical, tag_type, ps, locale)
        if found is not None:
            return found

    # 3. built-in
    found = _builtin_lookup(canonical, tag_type, ps, locale)
    if found is not None:
        return found

    # 4-5. fallback
    if fallback_locale and fallback_locale != locale and fallback_locale != "canonical":
        if conn is not None:
            found = _db_lookup(conn, canonical, tag_type, ps, fallback_locale)
            if found is not None:
                return found
        found = _builtin_lookup(canonical, tag_type, ps, fallback_locale)
        if found is not None:
            return found

    return canonical


def resolve_display_name_with_info(
    conn: Optional[sqlite3.Connection],
    canonical: str,
    tag_type: str,
    *,
    parent_series: Optional[str] = None,
    locale: str = "canonical",
    fallback_locale: str = "canonical",
) -> tuple[str, bool]:
    """
    (display_name, used_fallback) 반환.

    used_fallback=True: 요청 locale에서 찾지 못해 canonical을 반환함.
    """
    if locale == "canonical" or not canonical:
        return canonical, False

    ps = parent_series or ""

    if conn is not None:
        found = _db_lookup(conn, canonical, tag_type, ps, locale)
        if found is not None:
            return found, False

    found = _builtin_lookup(canonical, tag_type, ps, locale)
    if found is not None:
        return found, False

    if fallback_locale and fallback_locale != locale and fallback_locale != "canonical":
        if conn is not None:
            found = _db_lookup(conn, canonical, tag_type, ps, fallback_locale)
            if found is not None:
                return found, False
        found = _builtin_lookup(canonical, tag_type, ps, fallback_locale)
        if found is not None:
            return found, False

    return canonical, True


def seed_builtin_localizations(conn: sqlite3.Connection) -> int:
    """
    BUILTIN_LOCALIZATIONS를 tag_localizations에 INSERT OR IGNORE.

    반환: 실제 삽입 건수.
    """
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for entry in BUILTIN_LOCALIZATIONS:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO tag_localizations
                   (localization_id, canonical, tag_type, parent_series,
                    locale, display_name, sort_name, source, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'built_in', 1, ?)""",
                (
                    str(uuid.uuid4()),
                    entry["canonical"],
                    entry["tag_type"],
                    entry.get("parent_series") or "",
                    entry["locale"],
                    entry["display_name"],
                    entry.get("sort_name"),
                    now,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception:
            pass
    conn.commit()
    return inserted


def list_localizations(
    conn: sqlite3.Connection,
    locale: Optional[str] = None,
) -> list[dict]:
    """등록된 localization 목록 반환."""
    if locale:
        rows = conn.execute(
            "SELECT * FROM tag_localizations WHERE locale = ? ORDER BY canonical",
            (locale,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tag_localizations ORDER BY canonical, locale"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_localization(
    conn: sqlite3.Connection,
    canonical: str,
    tag_type: str,
    locale: str,
    display_name: str,
    parent_series: Optional[str] = None,
    source: str = "user",
) -> None:
    """localization을 추가하거나 갱신한다."""
    ps = parent_series or ""
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        """SELECT localization_id FROM tag_localizations
           WHERE canonical = ? AND tag_type = ? AND parent_series = ? AND locale = ?""",
        (canonical, tag_type, ps, locale),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE tag_localizations
               SET display_name = ?, source = ?, enabled = 1, updated_at = ?
               WHERE localization_id = ?""",
            (display_name, source, now, existing[0]),
        )
    else:
        conn.execute(
            """INSERT INTO tag_localizations
               (localization_id, canonical, tag_type, parent_series, locale,
                display_name, source, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (str(uuid.uuid4()), canonical, tag_type, ps, locale, display_name, source, now),
        )
    conn.commit()
