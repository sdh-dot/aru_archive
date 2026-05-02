"""Read-only character/series inference helpers.

raw tags 안에서 character / series 후보를 찾아 사용자 검토용 inference 결과를
반환한다. 분류 결과 / preview UI / DB 를 절대 변경하지 않는다.

이 모듈의 책임:
- 입력 raw_tags 각각에 ``core.tag_text_normalizer.build_tag_variants`` 로
  variant 를 만든다.
- 각 variant 를 ``tag_aliases.alias`` 와 ``tag_localizations.display_name``
  두 테이블에 대조해 매칭 row 를 모은다.
- match_kind (variant 종류) + source 우선순위 + mojibake 휴리스틱을 합쳐
  ``CharacterSeriesInference.confidence`` (high / medium / low) 와 reason 을
  산정한다.
- 같은 canonical 에 대해 서로 다른 ``parent_series`` 가 매칭되면 ambiguous 로
  표시한다 (호출자가 자동 확정을 막을 수 있도록).

이 모듈이 절대 하지 않는 것:
- 분류 결과 / artwork_groups.status / classify_rules 변경
- preview / classification_overrides 갱신
- DB write (모든 SQL 은 SELECT 전용)
- 자동 series 확정 (호출자가 confidence + ambiguous 플래그를 보고 결정)

Source 우선순위 (높음 → 낮음):
    user_confirmed, user_import, user                       → 0
    built_in, built_in_pack:*                               → 1
    candidate_accepted, pixiv_translation                   → 2
    imported_localized_pack, candidate                      → 3
    NULL / unknown                                          → 4

Confidence 산정 (낮은 source rank + 강한 match_kind 가 high):
    high   — exact 또는 normalized variant + source rank ≤ 1
    medium — compact 또는 trailing_long_vowel_removed variant
             또는 normalized + source rank == 2/3
    low    — all_long_vowels_removed variant 또는 source rank == 4
             또는 mojibake 의심
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional, Sequence

from core.tag_text_normalizer import (
    TagTextVariant,
    build_tag_variants,
    looks_mojibake,
)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CharacterSeriesInference:
    """단일 매칭 후보 — 호출자가 사용자에게 보여주거나 ranking 한다."""
    raw_tag: str                  # 입력 원문 태그
    matched_text: str             # 매칭에 사용된 variant 값 (alias / display_name)
    canonical: str                # tag_aliases.canonical 또는 tag_localizations.canonical
    tag_type: str                 # 'series' | 'character' | 'general'
    parent_series: Optional[str]  # character 의 소속 series. 없거나 빈 문자열이면 None
    source: Optional[str]         # tag_aliases.source 또는 tag_localizations.source
    locale: Optional[str]         # tag_localizations.locale (alias 매칭이면 None)
    match_kind: str               # alias_exact | alias_normalized | loc_exact 등 — 디버그/로깅용
    confidence: str               # high | medium | low
    reason: str                   # 사람이 읽을 수 있는 한 줄 설명


# ---------------------------------------------------------------------------
# 내부: source 우선순위
# ---------------------------------------------------------------------------

_SOURCE_RANK = {
    "user_confirmed":           0,
    "user_import":              0,
    "user":                     0,
    "built_in":                 1,
    "candidate_accepted":       2,
    "pixiv_translation":        2,
    "imported_localized_pack":  3,
    "candidate":                3,
}

_UNKNOWN_RANK = 4


def _source_rank(source: Optional[str]) -> int:
    """built_in_pack:* 도 rank 1 로 묶어 반환."""
    if not source:
        return _UNKNOWN_RANK
    if source.startswith("built_in_pack:"):
        return 1
    return _SOURCE_RANK.get(source, _UNKNOWN_RANK)


# ---------------------------------------------------------------------------
# 내부: match_kind → 강도 분류
# ---------------------------------------------------------------------------

# variant confidence_hint 별 강도. 높을수록 강함.
_HINT_STRENGTH = {
    "exact":                        3,
    "normalized":                   3,
    "compact":                      2,
    "trailing_long_vowel_removed":  2,
    "all_long_vowels_removed":      1,
}


def _make_match_kind(prefix: str, hint: str) -> str:
    return f"{prefix}_{hint}"


# ---------------------------------------------------------------------------
# 내부: confidence 산정
# ---------------------------------------------------------------------------

def _resolve_confidence(
    *,
    hint_strength: int,
    source_rank: int,
    mojibake: bool,
) -> str:
    """match_kind 강도, source rank, mojibake 의심을 합쳐 high / medium / low 반환."""
    if mojibake:
        return "low"
    if source_rank >= _UNKNOWN_RANK:
        return "low"
    if hint_strength >= 3 and source_rank <= 1:
        return "high"
    if hint_strength == 1:
        return "low"
    if hint_strength >= 3 and source_rank <= 3:
        return "medium"
    if hint_strength == 2:
        return "medium"
    return "low"


def _format_reason(
    *,
    raw_tag: str,
    matched_text: str,
    match_kind: str,
    source: Optional[str],
    locale: Optional[str],
) -> str:
    parts = [f"raw={raw_tag!r}"]
    if matched_text != raw_tag:
        parts.append(f"matched={matched_text!r}")
    parts.append(f"via={match_kind}")
    if source:
        parts.append(f"source={source}")
    if locale:
        parts.append(f"locale={locale}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# 내부: DB 조회
# ---------------------------------------------------------------------------

_ALIAS_QUERY = (
    "SELECT alias, canonical, tag_type, parent_series, source "
    "FROM tag_aliases "
    "WHERE alias = ? AND enabled = 1"
)

_LOC_QUERY = (
    "SELECT display_name, canonical, tag_type, parent_series, locale, source "
    "FROM tag_localizations "
    "WHERE display_name = ? AND enabled = 1"
)


def _query_alias_rows(
    conn: sqlite3.Connection,
    value: str,
) -> list[sqlite3.Row]:
    return conn.execute(_ALIAS_QUERY, (value,)).fetchall()


def _query_localization_rows(
    conn: sqlite3.Connection,
    value: str,
) -> list[sqlite3.Row]:
    return conn.execute(_LOC_QUERY, (value,)).fetchall()


# ---------------------------------------------------------------------------
# 내부: row → CharacterSeriesInference
# ---------------------------------------------------------------------------

def _normalize_parent_series(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _alias_row_to_inference(
    *,
    raw_tag: str,
    variant: TagTextVariant,
    row: sqlite3.Row,
) -> CharacterSeriesInference:
    canonical = str(row["canonical"]).strip()
    matched_text = str(row["alias"])
    source = row["source"] if "source" in row.keys() else None
    parent_series = _normalize_parent_series(row["parent_series"])
    tag_type = str(row["tag_type"])
    match_kind = _make_match_kind("alias", variant.confidence_hint)
    mojibake = looks_mojibake(canonical) or looks_mojibake(matched_text)
    confidence = _resolve_confidence(
        hint_strength=_HINT_STRENGTH.get(variant.confidence_hint, 1),
        source_rank=_source_rank(source),
        mojibake=mojibake,
    )
    return CharacterSeriesInference(
        raw_tag=raw_tag,
        matched_text=matched_text,
        canonical=canonical,
        tag_type=tag_type,
        parent_series=parent_series,
        source=source,
        locale=None,
        match_kind=match_kind,
        confidence=confidence,
        reason=_format_reason(
            raw_tag=raw_tag,
            matched_text=matched_text,
            match_kind=match_kind,
            source=source,
            locale=None,
        ),
    )


def _loc_row_to_inference(
    *,
    raw_tag: str,
    variant: TagTextVariant,
    row: sqlite3.Row,
) -> CharacterSeriesInference:
    canonical = str(row["canonical"]).strip()
    matched_text = str(row["display_name"])
    source = row["source"] if "source" in row.keys() else None
    locale = row["locale"] if "locale" in row.keys() else None
    parent_series = _normalize_parent_series(row["parent_series"])
    tag_type = str(row["tag_type"])
    match_kind = _make_match_kind("loc", variant.confidence_hint)
    mojibake = looks_mojibake(canonical) or looks_mojibake(matched_text)
    confidence = _resolve_confidence(
        hint_strength=_HINT_STRENGTH.get(variant.confidence_hint, 1),
        source_rank=_source_rank(source),
        mojibake=mojibake,
    )
    return CharacterSeriesInference(
        raw_tag=raw_tag,
        matched_text=matched_text,
        canonical=canonical,
        tag_type=tag_type,
        parent_series=parent_series,
        source=source,
        locale=locale,
        match_kind=match_kind,
        confidence=confidence,
        reason=_format_reason(
            raw_tag=raw_tag,
            matched_text=matched_text,
            match_kind=match_kind,
            source=source,
            locale=locale,
        ),
    )


# ---------------------------------------------------------------------------
# 내부: dedupe / sort
# ---------------------------------------------------------------------------

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def _dedupe_key(inf: CharacterSeriesInference) -> tuple:
    """같은 (raw, canonical, tag_type, parent_series, match_kind) 는 1번만."""
    return (
        inf.raw_tag,
        inf.canonical,
        inf.tag_type,
        inf.parent_series or "",
        inf.match_kind,
    )


def _sort_key(inf: CharacterSeriesInference) -> tuple:
    """confidence 우선, source rank 다음, raw_tag / canonical 알파벳 순."""
    return (
        _CONFIDENCE_RANK.get(inf.confidence, 3),
        _source_rank(inf.source),
        inf.raw_tag,
        inf.canonical,
        inf.match_kind,
    )


# ---------------------------------------------------------------------------
# 내부: 한 raw tag 처리
# ---------------------------------------------------------------------------

def _gather_for_raw_tag(
    conn: sqlite3.Connection,
    raw_tag: str,
) -> list[CharacterSeriesInference]:
    if not raw_tag or not raw_tag.strip():
        return []

    out: list[CharacterSeriesInference] = []
    for variant in build_tag_variants(raw_tag):
        for row in _query_alias_rows(conn, variant.value):
            out.append(_alias_row_to_inference(raw_tag=raw_tag, variant=variant, row=row))
        for row in _query_localization_rows(conn, variant.value):
            out.append(_loc_row_to_inference(raw_tag=raw_tag, variant=variant, row=row))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_character_series_candidates(
    conn: sqlite3.Connection,
    raw_tags: Sequence[str],
) -> tuple[CharacterSeriesInference, ...]:
    """raw_tags 에서 character / series 후보를 read-only 로 추출한다.

    Parameters
    ----------
    conn:
        SQLite connection. **read-only 로만 사용** — 어떤 INSERT/UPDATE/DELETE 도
        실행하지 않는다. row_factory 가 ``sqlite3.Row`` 가 아닐 수도 있으므로
        호출 동안 일시 설정 후 원복한다.
    raw_tags:
        Pixiv 또는 외부 source 의 원본 태그 목록. 빈 문자열 / None 은 자동 skip.

    Returns
    -------
    tuple of ``CharacterSeriesInference``, confidence 순으로 정렬된 후보들.
    중복은 제거된다 (같은 raw / canonical / tag_type / parent_series / match_kind).

    이 함수는 절대 분류 결과를 변경하지 않는다. 호출자는 결과를 보고:
    - high confidence 에 한해 자동 적용을 고려할 수 있고
    - 같은 canonical 에 다른 parent_series 가 있으면 ambiguous 로 사용자에게
      확인 요청해야 한다 (``has_ambiguous_parent_series`` helper 참고).
    """
    if not raw_tags:
        return ()

    original_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        raw_results: list[CharacterSeriesInference] = []
        for raw_tag in raw_tags:
            if not isinstance(raw_tag, str):
                continue
            raw_results.extend(_gather_for_raw_tag(conn, raw_tag))
    finally:
        conn.row_factory = original_factory

    # 중복 제거 — 같은 dedupe_key 는 confidence 가 더 강한 것을 우선 보존.
    seen: dict[tuple, CharacterSeriesInference] = {}
    for inf in raw_results:
        key = _dedupe_key(inf)
        existing = seen.get(key)
        if existing is None:
            seen[key] = inf
            continue
        if _CONFIDENCE_RANK.get(inf.confidence, 3) < _CONFIDENCE_RANK.get(existing.confidence, 3):
            seen[key] = inf

    return tuple(sorted(seen.values(), key=_sort_key))


def has_ambiguous_parent_series(
    candidates: Sequence[CharacterSeriesInference],
) -> bool:
    """같은 character canonical 에 서로 다른 parent_series 가 매칭됐는지 확인.

    호출자가 자동 series 확정을 막을 때 사용한다. 같은 (canonical, tag_type) 조합에
    None / 빈 값 외의 parent_series 가 2개 이상이면 True.
    """
    by_key: dict[tuple, set[str]] = {}
    for c in candidates:
        if c.tag_type != "character":
            continue
        if not c.parent_series:
            continue
        key = (c.canonical, c.tag_type)
        by_key.setdefault(key, set()).add(c.parent_series)
    return any(len(parents) > 1 for parents in by_key.values())
