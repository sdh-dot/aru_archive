"""User Custom Alias 사전 진입 경로.

사용자가 명시적으로 추가한 alias를 tag_aliases.source='user_confirmed'로
저장한다. DB schema는 변경하지 않으며, 기존 enum의 예약된 값을
실제 진입 경로로 사용한다.

자동 승격 / 자동 추가 금지 — 모든 add 호출은 사용자 명시 의도를
가정한다 (UI 또는 외부 호출자가 사용자 동의를 확인할 책임).

tag_aliases 테이블 PRIMARY KEY: (alias, tag_type, parent_series)
  - 같은 (alias, tag_type, parent_series) 조합에 여러 source가 공존 불가.
  - user_confirmed add는 parent_series='' 기본값으로 삽입/갱신한다.
  - remove는 source='user_confirmed' 행만 soft-delete(enabled=0)한다.
    pack/built_in/import/candidate_accepted 등 다른 source는 절대 건드리지 않는다.
  - list는 enabled=1 AND source='user_confirmed' 행만 반환한다.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional


_VALID_TAG_TYPES = frozenset({"general", "character", "series"})
_USER_SOURCE = "user_confirmed"


def add_user_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    tag_type: str,
    *,
    parent_series: str = "",
    media_type: Optional[str] = None,
) -> dict:
    """User Custom alias를 tag_aliases에 source='user_confirmed'로 등록.

    중복 시 idempotent — 같은 (alias, tag_type, parent_series)이
    이미 user_confirmed로 있으면 canonical/media_type/updated_at 갱신
    (사용자의 재확인 의도를 반영).

    다른 source(pack/built_in/import/candidate_accepted 등)의 행은
    PRIMARY KEY가 충돌하지 않는 한 건드리지 않는다.
    PRIMARY KEY 충돌(같은 alias+tag_type+parent_series에 다른 source 존재) 시
    INSERT OR REPLACE가 그 행을 교체한다. 이 경우 기존 source와 관계없이
    user_confirmed 의도가 우선한다.

    Args:
        conn:          sqlite3.Connection (row_factory 유무 무관)
        alias:         등록할 별칭 (비어있으면 ValueError)
        canonical:     정규 태그명 (비어있으면 ValueError)
        tag_type:      'general' | 'character' | 'series'
        parent_series: character 타입 시 소속 시리즈 canonical명 (기본 '')
        media_type:    game | anime | manga | novel | original | unknown (선택)

    Returns:
        {"action": "inserted" | "updated", "rowid": int}

    Raises:
        ValueError: alias / canonical 이 빈 문자열이거나
                    tag_type 이 valid 집합에 없음.
        sqlite3.Error: DB 오류 (호출자에게 전달).
    """
    if not isinstance(alias, str) or not alias.strip():
        raise ValueError("alias must be a non-empty string")
    if not isinstance(canonical, str) or not canonical.strip():
        raise ValueError("canonical must be a non-empty string")
    if not isinstance(tag_type, str) or tag_type not in _VALID_TAG_TYPES:
        raise ValueError(
            f"tag_type must be one of {sorted(_VALID_TAG_TYPES)}, got {tag_type!r}"
        )

    alias_norm = alias.strip()
    canonical_norm = canonical.strip()
    parent_series_norm = (parent_series or "").strip()

    now = datetime.now(timezone.utc).isoformat()

    # 기존 user_confirmed 행이 있는지 확인 (action 결과 판별용)
    existing = conn.execute(
        "SELECT rowid FROM tag_aliases "
        "WHERE alias = ? AND tag_type = ? AND parent_series = ? "
        "AND source = ?",
        (alias_norm, tag_type, parent_series_norm, _USER_SOURCE),
    ).fetchone()

    if existing is not None:
        conn.execute(
            "UPDATE tag_aliases "
            "SET canonical = ?, media_type = ?, enabled = 1, updated_at = ? "
            "WHERE alias = ? AND tag_type = ? AND parent_series = ? AND source = ?",
            (
                canonical_norm,
                media_type,
                now,
                alias_norm,
                tag_type,
                parent_series_norm,
                _USER_SOURCE,
            ),
        )
        rowid_row = conn.execute(
            "SELECT rowid FROM tag_aliases "
            "WHERE alias = ? AND tag_type = ? AND parent_series = ? AND source = ?",
            (alias_norm, tag_type, parent_series_norm, _USER_SOURCE),
        ).fetchone()
        rowid = rowid_row[0] if rowid_row else -1
        action = "updated"
    else:
        # INSERT OR REPLACE: PK 충돌(다른 source) 시 교체, 미충돌 시 신규 삽입
        conn.execute(
            "INSERT OR REPLACE INTO tag_aliases "
            "(alias, canonical, tag_type, parent_series, media_type, source, "
            " enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                alias_norm,
                canonical_norm,
                tag_type,
                parent_series_norm,
                media_type,
                _USER_SOURCE,
                now,
                now,
            ),
        )
        rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        action = "inserted"

    return {"action": action, "rowid": rowid}


def remove_user_alias(
    conn: sqlite3.Connection,
    alias: str,
    tag_type: Optional[str] = None,
    *,
    parent_series: Optional[str] = None,
) -> int:
    """User Custom alias를 soft-delete(enabled=0).

    source='user_confirmed' 행만 비활성화한다.
    pack/built_in/import/candidate_accepted 등 다른 source는 절대 건드리지 않는다.

    Args:
        conn:          sqlite3.Connection
        alias:         제거할 별칭
        tag_type:      None이면 모든 tag_type에 적용, 지정하면 해당 type만
        parent_series: None이면 parent_series 조건 없음, 지정하면 해당 값만

    Returns:
        soft-delete된 행 수 (0이면 해당 user_confirmed alias 없음).

    Raises:
        ValueError: alias가 빈 문자열.
        sqlite3.Error: DB 오류 (호출자에게 전달).
    """
    if not isinstance(alias, str) or not alias.strip():
        raise ValueError("alias must be a non-empty string")

    alias_norm = alias.strip()
    now = datetime.now(timezone.utc).isoformat()

    # WHERE 절 동적 구성
    conditions = ["alias = ?", "source = ?"]
    params: list = [alias_norm, _USER_SOURCE]

    if tag_type is not None:
        if tag_type not in _VALID_TAG_TYPES:
            raise ValueError(
                f"tag_type must be one of {sorted(_VALID_TAG_TYPES)}, got {tag_type!r}"
            )
        conditions.append("tag_type = ?")
        params.append(tag_type)

    if parent_series is not None:
        conditions.append("parent_series = ?")
        params.append(parent_series.strip())

    where = " AND ".join(conditions)
    # SQL param order: updated_at=? first, then WHERE clause params
    conn.execute(
        f"UPDATE tag_aliases SET enabled = 0, updated_at = ? WHERE {where}",
        (now, *params),
    )
    changed = conn.execute("SELECT changes()").fetchone()[0]
    return changed


def list_user_aliases(
    conn: sqlite3.Connection,
    *,
    tag_type: Optional[str] = None,
    include_disabled: bool = False,
) -> list[dict]:
    """user_confirmed source인 alias 목록 반환.

    기본적으로 enabled=0(soft-deleted) 항목은 제외한다.

    Args:
        conn:             sqlite3.Connection
        tag_type:         None이면 전체, 지정하면 해당 type만 필터링
        include_disabled: True이면 soft-deleted 포함 (감사 목적)

    Returns:
        [
            {
                "alias":         str,
                "canonical":     str,
                "tag_type":      str,
                "parent_series": str,
                "media_type":    Optional[str],
                "source":        str,           # always 'user_confirmed'
                "enabled":       int,           # 1 or 0
                "created_at":    str,
                "updated_at":    Optional[str],
            },
            ...
        ]
        결과는 tag_type ASC, alias ASC 순으로 정렬된다.

    Raises:
        ValueError: tag_type이 유효하지 않음 (None은 허용).
        sqlite3.Error: DB 오류 (호출자에게 전달).
    """
    if tag_type is not None and tag_type not in _VALID_TAG_TYPES:
        raise ValueError(
            f"tag_type must be one of {sorted(_VALID_TAG_TYPES)}, got {tag_type!r}"
        )

    conditions = ["source = ?"]
    params: list = [_USER_SOURCE]

    if not include_disabled:
        conditions.append("enabled = 1")

    if tag_type is not None:
        conditions.append("tag_type = ?")
        params.append(tag_type)

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT alias, canonical, tag_type, parent_series, media_type, "
        f"       source, enabled, created_at, updated_at "
        f"FROM tag_aliases "
        f"WHERE {where} "
        f"ORDER BY tag_type ASC, alias ASC",
        params,
    ).fetchall()

    result: list[dict] = []
    for row in rows:
        # sqlite3.Row 또는 tuple 모두 지원
        if hasattr(row, "keys"):
            result.append(dict(row))
        else:
            result.append(
                {
                    "alias":         row[0],
                    "canonical":     row[1],
                    "tag_type":      row[2],
                    "parent_series": row[3],
                    "media_type":    row[4],
                    "source":        row[5],
                    "enabled":       row[6],
                    "created_at":    row[7],
                    "updated_at":    row[8],
                }
            )
    return result
