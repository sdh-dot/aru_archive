"""Read-only multilingual tag autocomplete candidate provider.

수동 입력 자동완성에서 한국어 / 일본어 / 영어 입력 모두에 대해 후보를 제공한다.
``tag_aliases`` 와 ``tag_localizations`` 두 테이블을 통합 조회하고 source / locale /
match 강도 기반으로 confidence 점수를 산정해 정렬한다.

이 모듈의 책임:
- ``suggest_tag_completions(conn, query, *, tag_type=None, limit=20)`` 를 제공
- exact / prefix / contains / variant (NFKC, compact, 일본어 장음) 매칭을 지원
- 같은 canonical / tag_type / parent_series 후보를 dedupe (가장 강한 후보 보존)
- mojibake 의심 후보는 강하게 감점

이 모듈이 절대 하지 않는 것:
- DB write — SELECT 만 사용
- UI / Qt 의존
- ASCII hyphen ``-`` 와 일본어 장음부호 ``ー`` 동치 처리
- 분류 결과 / classification_overrides 변경

호출자 책임:
- 결과 후보를 사용자에게 그대로 표시하거나 (display_text), 선택 시 canonical /
  tag_type / parent_series 를 분류 파이프라인으로 전달
- locale / source 우선순위 정책을 더 세분화하고 싶으면 confidence 를 후처리

확신도 (``confidence``) 산정:
    base = match kind 강도 (exact 100 → contains 40)
        + source bonus (user_confirmed +15, built_in_pack:* +10, …)
        + locale bonus (입력 script 와 동일 locale +10, 보조 +3)
        - mojibake penalty (-50)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional, Sequence

from core.tag_text_normalizer import (
    build_tag_variants,
    detect_input_script,
    looks_mojibake,
    normalize_tag_text,
)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TagAutocompleteCandidate:
    """자동완성 후보 한 건. 호출자가 그대로 표시 / 선택값으로 사용한다."""
    display_text: str            # 사용자에게 표시할 1순위 텍스트
    insert_text: str             # LineEdit 에 삽입될 텍스트 (보통 display_text 와 동일)
    canonical: str               # 분류 파이프라인에 전달할 정규명
    tag_type: str                # 'series' | 'character' | 'general'
    parent_series: Optional[str] # character 의 소속 series (없으면 None)
    locale: str                  # 'ko' | 'ja' | 'en' | 'canonical' | 'alias'
    source: Optional[str]        # tag_aliases.source 또는 tag_localizations.source
    match_kind: str              # exact / prefix / contains / normalized / compact / long_vowel
    confidence: int              # 정수 점수 — 높을수록 우선 (정렬 키)
    secondary_text: str          # tooltip / 부가 표시용 (canonical · tag_type · parent_series · source)


# ---------------------------------------------------------------------------
# 점수 테이블
# ---------------------------------------------------------------------------

# match_kind → 기본 점수
_MATCH_KIND_SCORE = {
    "exact":      100,
    "prefix":      80,
    "normalized":  75,
    "compact":     65,
    "long_vowel":  55,
    "contains":    40,
}

# source → 가산점. 알 수 없는 source 는 0.
_SOURCE_BONUS = {
    "user_confirmed":          15,
    "user_import":             15,
    "user":                    15,
    "built_in":                 8,
    "external:safebooru":       5,
    "candidate_accepted":       3,
    "pixiv_translation":        3,
    "imported_localized_pack":  1,
    "candidate":                0,
}

# 입력 script 와 candidate locale 의 우선 매핑.
# (input_script, candidate_locale) → bonus
_LOCALE_BONUS_TABLE = {
    ("ko", "ko"):           10,
    ("ko", "ja"):            3,
    ("ko", "en"):            3,
    ("ko", "canonical"):     5,
    ("ko", "alias"):         5,
    ("ja", "ja"):           10,
    ("ja", "ko"):            3,
    ("ja", "en"):            3,
    ("ja", "canonical"):     5,
    ("ja", "alias"):         5,
    ("ascii", "canonical"): 10,
    ("ascii", "alias"):     10,
    ("ascii", "en"):        10,
    ("ascii", "ko"):         3,
    ("ascii", "ja"):         3,
    ("mixed", "canonical"):  5,
    ("mixed", "alias"):      5,
    ("mixed", "ko"):         5,
    ("mixed", "ja"):         5,
    ("mixed", "en"):         5,
    ("unknown", "canonical"): 3,
    ("unknown", "alias"):     3,
}

# mojibake 의심 후보 감점 — 정상 후보보다 항상 아래로 가도록 충분히 큰 값.
_MOJIBAKE_PENALTY = 50


def _source_bonus(source: Optional[str]) -> int:
    if not source:
        return 0
    if source.startswith("built_in_pack:"):
        return 10
    return _SOURCE_BONUS.get(source, 0)


def _locale_bonus(input_script: str, candidate_locale: str) -> int:
    return _LOCALE_BONUS_TABLE.get((input_script, candidate_locale), 0)


def _normalize_parent_series(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


# ---------------------------------------------------------------------------
# row → candidate
# ---------------------------------------------------------------------------

def _row_to_candidate(
    *,
    display_text: str,
    insert_text: str,
    canonical: str,
    tag_type: str,
    parent_series: Optional[str],
    locale: str,
    source: Optional[str],
    match_kind: str,
    input_script: str,
) -> TagAutocompleteCandidate:
    base = _MATCH_KIND_SCORE.get(match_kind, 0)
    bonus = _source_bonus(source) + _locale_bonus(input_script, locale)
    penalty = (
        _MOJIBAKE_PENALTY
        if (looks_mojibake(canonical) or looks_mojibake(display_text))
        else 0
    )
    confidence = base + bonus - penalty

    secondary_parts = [canonical, tag_type]
    if parent_series:
        secondary_parts.append(parent_series)
    if source:
        secondary_parts.append(source)
    secondary_text = " · ".join(secondary_parts)

    return TagAutocompleteCandidate(
        display_text=display_text,
        insert_text=insert_text,
        canonical=canonical,
        tag_type=tag_type,
        parent_series=parent_series,
        locale=locale,
        source=source,
        match_kind=match_kind,
        confidence=confidence,
        secondary_text=secondary_text,
    )


# ---------------------------------------------------------------------------
# DB 조회 — exact (variant) / prefix / contains
# ---------------------------------------------------------------------------

# Variant.confidence_hint → match_kind. exact 는 항상 가장 강함.
_VARIANT_HINT_TO_MATCH_KIND = {
    "exact":                        "exact",
    "normalized":                   "normalized",
    "compact":                      "compact",
    "trailing_long_vowel_removed":  "long_vowel",
    "all_long_vowels_removed":      "long_vowel",
}


def _query_alias_exact(conn: sqlite3.Connection, value: str):
    return conn.execute(
        "SELECT alias, canonical, tag_type, parent_series, source "
        "FROM tag_aliases WHERE alias = ? AND enabled = 1",
        (value,),
    ).fetchall()


def _query_loc_exact(conn: sqlite3.Connection, value: str):
    return conn.execute(
        "SELECT display_name, canonical, tag_type, parent_series, locale, source "
        "FROM tag_localizations WHERE display_name = ? AND enabled = 1",
        (value,),
    ).fetchall()


def _query_alias_prefix(conn: sqlite3.Connection, prefix: str):
    return conn.execute(
        "SELECT alias, canonical, tag_type, parent_series, source "
        "FROM tag_aliases "
        "WHERE alias LIKE ? || '%' AND enabled = 1 "
        "LIMIT 200",
        (prefix,),
    ).fetchall()


def _query_loc_prefix(conn: sqlite3.Connection, prefix: str):
    return conn.execute(
        "SELECT display_name, canonical, tag_type, parent_series, locale, source "
        "FROM tag_localizations "
        "WHERE display_name LIKE ? || '%' AND enabled = 1 "
        "LIMIT 200",
        (prefix,),
    ).fetchall()


def _query_alias_contains(conn: sqlite3.Connection, needle: str):
    return conn.execute(
        "SELECT alias, canonical, tag_type, parent_series, source "
        "FROM tag_aliases "
        "WHERE alias LIKE '%' || ? || '%' AND enabled = 1 "
        "LIMIT 200",
        (needle,),
    ).fetchall()


def _query_loc_contains(conn: sqlite3.Connection, needle: str):
    return conn.execute(
        "SELECT display_name, canonical, tag_type, parent_series, locale, source "
        "FROM tag_localizations "
        "WHERE display_name LIKE '%' || ? || '%' AND enabled = 1 "
        "LIMIT 200",
        (needle,),
    ).fetchall()


# ---------------------------------------------------------------------------
# row → TagAutocompleteCandidate adapters
# ---------------------------------------------------------------------------

def _alias_row(row, match_kind: str, input_script: str) -> TagAutocompleteCandidate:
    canonical = str(row["canonical"]).strip()
    alias = str(row["alias"])
    parent_series = _normalize_parent_series(row["parent_series"])
    return _row_to_candidate(
        display_text=alias,
        insert_text=alias,
        canonical=canonical,
        tag_type=str(row["tag_type"]),
        parent_series=parent_series,
        locale="alias",
        source=row["source"] if "source" in row.keys() else None,
        match_kind=match_kind,
        input_script=input_script,
    )


def _loc_row(row, match_kind: str, input_script: str) -> TagAutocompleteCandidate:
    canonical = str(row["canonical"]).strip()
    display = str(row["display_name"])
    parent_series = _normalize_parent_series(row["parent_series"])
    return _row_to_candidate(
        display_text=display,
        insert_text=display,
        canonical=canonical,
        tag_type=str(row["tag_type"]),
        parent_series=parent_series,
        locale=str(row["locale"]) if "locale" in row.keys() and row["locale"] else "canonical",
        source=row["source"] if "source" in row.keys() else None,
        match_kind=match_kind,
        input_script=input_script,
    )


# ---------------------------------------------------------------------------
# 후보 수집 + dedupe + 정렬
# ---------------------------------------------------------------------------

def _dedupe_key(c: TagAutocompleteCandidate) -> tuple:
    return (c.canonical, c.tag_type, c.parent_series or "")


def _sort_key(c: TagAutocompleteCandidate) -> tuple:
    # confidence DESC → display_text ASC → canonical ASC.
    return (-c.confidence, c.display_text, c.canonical)


def _gather_exact(
    conn: sqlite3.Connection,
    query: str,
    input_script: str,
) -> list[TagAutocompleteCandidate]:
    out: list[TagAutocompleteCandidate] = []
    for variant in build_tag_variants(query):
        match_kind = _VARIANT_HINT_TO_MATCH_KIND.get(variant.confidence_hint, "exact")
        for row in _query_alias_exact(conn, variant.value):
            out.append(_alias_row(row, match_kind, input_script))
        for row in _query_loc_exact(conn, variant.value):
            out.append(_loc_row(row, match_kind, input_script))
    return out


def _gather_prefix(
    conn: sqlite3.Connection,
    normalized_query: str,
    input_script: str,
) -> list[TagAutocompleteCandidate]:
    out: list[TagAutocompleteCandidate] = []
    for row in _query_alias_prefix(conn, normalized_query):
        out.append(_alias_row(row, "prefix", input_script))
    for row in _query_loc_prefix(conn, normalized_query):
        out.append(_loc_row(row, "prefix", input_script))
    return out


def _gather_contains(
    conn: sqlite3.Connection,
    normalized_query: str,
    input_script: str,
) -> list[TagAutocompleteCandidate]:
    out: list[TagAutocompleteCandidate] = []
    for row in _query_alias_contains(conn, normalized_query):
        out.append(_alias_row(row, "contains", input_script))
    for row in _query_loc_contains(conn, normalized_query):
        out.append(_loc_row(row, "contains", input_script))
    return out


def _dedupe_keep_highest(
    candidates: Sequence[TagAutocompleteCandidate],
) -> list[TagAutocompleteCandidate]:
    """같은 (canonical, tag_type, parent_series) 키는 confidence 가장 높은 1건만 유지."""
    by_key: dict = {}
    for c in candidates:
        key = _dedupe_key(c)
        existing = by_key.get(key)
        if existing is None or c.confidence > existing.confidence:
            by_key[key] = c
    return list(by_key.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_VALID_TAG_TYPES = frozenset({"series", "character", "general"})


def suggest_tag_completions(
    conn: sqlite3.Connection,
    query: str,
    *,
    tag_type: Optional[str] = None,
    limit: int = 20,
) -> tuple[TagAutocompleteCandidate, ...]:
    """``query`` 에 대한 자동완성 후보를 confidence 순으로 반환한다.

    Parameters
    ----------
    conn:
        SQLite connection. **read-only** — INSERT/UPDATE/DELETE 가 발생하지 않는다.
        ``row_factory`` 는 호출 동안 일시 변경 후 finally 에서 원복된다.
    query:
        사용자 입력 문자열. 빈 문자열 / None → 빈 tuple.
    tag_type:
        ``'series'`` / ``'character'`` / ``'general'`` 중 하나면 해당 tag_type
        후보만 반환. None 이면 전체.
    limit:
        결과 최대 개수. 1 미만이면 빈 tuple.

    Returns
    -------
    tuple of ``TagAutocompleteCandidate``, confidence 가 높은 순.
    같은 (canonical, tag_type, parent_series) 키는 dedupe 되어 한 번만 표시된다.
    """
    if not query or not query.strip():
        return ()
    if limit < 1:
        return ()
    if tag_type is not None and tag_type not in _VALID_TAG_TYPES:
        return ()

    normalized_query = normalize_tag_text(query)
    if not normalized_query:
        return ()

    input_script = detect_input_script(query)

    original_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        all_candidates: list[TagAutocompleteCandidate] = []
        all_candidates.extend(_gather_exact(conn, query, input_script))
        all_candidates.extend(_gather_prefix(conn, normalized_query, input_script))
        all_candidates.extend(_gather_contains(conn, normalized_query, input_script))
    finally:
        conn.row_factory = original_factory

    if tag_type is not None:
        all_candidates = [c for c in all_candidates if c.tag_type == tag_type]

    deduped = _dedupe_keep_highest(all_candidates)
    deduped.sort(key=_sort_key)
    return tuple(deduped[:limit])
