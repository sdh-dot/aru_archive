"""
태그 후보 생성 모듈.

tag_observations 데이터를 분석하여 시리즈/캐릭터 후보를 tag_candidates에 저장한다.
자동 확정 금지 — 후보 생성만 수행. 최종 확정은 사용자 승인(tag_candidate_actions) 기반.

confidence_score 계산:
  base=0.20
  +0.30  기지 시리즈와 함께 등장
  +0.20  evidence_count >= 3
  +0.20  번역 태그 존재
  -0.30  여러 시리즈에 걸쳐 등장 (모호)
  -0.50  GENERAL_TAG_BLACKLIST에 포함
  → clamp [0.0, 1.0]
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 절대 캐릭터/시리즈 후보가 되어서는 안 되는 속성 태그
GENERAL_TAG_BLACKLIST: frozenset[str] = frozenset({
    "女の子", "少女", "水着", "制服", "黒スト", "白スト",
    "R-18", "10000users入り", "5000users入り", "users入り",
    "オリジナル", "イラスト", "落書き",
    "solo", "ソロ", "1girl", "1boy",
})


def calculate_candidate_confidence(
    *,
    has_translated_tag: bool,
    cooccurs_with_known_series: bool,
    evidence_count: int,
    appears_in_multiple_series: bool,
    is_blacklisted_general: bool,
) -> float:
    """신뢰도 점수 계산. 반환값 범위: 0.0 ~ 1.0."""
    score = 0.20
    if cooccurs_with_known_series:
        score += 0.30
    if evidence_count >= 3:
        score += 0.20
    if has_translated_tag:
        score += 0.20
    if appears_in_multiple_series:
        score -= 0.30
    if is_blacklisted_general:
        score -= 0.50
    return max(0.0, min(1.0, score))


def generate_tag_candidates_for_group(
    conn: sqlite3.Connection,
    group_id: str,
) -> list[dict]:
    """
    단일 그룹의 관측 태그에서 후보를 생성한다.
    이미 tag_aliases에 확정된 태그, built-in aliases에 있는 태그는 건너뛴다.
    """
    from core.tag_classifier import SERIES_ALIASES, CHARACTER_ALIASES

    rows = conn.execute(
        "SELECT raw_tag, translated_tag, co_tags_json, artwork_id "
        "FROM tag_observations WHERE group_id = ?",
        (group_id,),
    ).fetchall()
    if not rows:
        return []

    confirmed_aliases = _load_confirmed_aliases(conn)
    results: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        raw_tag = row["raw_tag"]
        if raw_tag in confirmed_aliases:
            continue
        if raw_tag in SERIES_ALIASES or raw_tag in CHARACTER_ALIASES:
            continue

        co_tags: list[str] = []
        try:
            co_tags = json.loads(row["co_tags_json"] or "[]")
        except Exception:
            pass

        series_cooccur_names = {
            SERIES_ALIASES[t] for t in co_tags if t in SERIES_ALIASES
        }
        cooccurs = bool(series_cooccur_names)
        is_blacklisted = raw_tag in GENERAL_TAG_BLACKLIST
        has_translated = bool(row["translated_tag"])

        evidence_count = conn.execute(
            "SELECT COUNT(*) FROM tag_observations WHERE raw_tag = ?", (raw_tag,)
        ).fetchone()[0]

        multiple_series = len(series_cooccur_names) > 1
        suggested_type = "character" if cooccurs and not is_blacklisted else "general"
        suggested_series = next(iter(series_cooccur_names), "") if suggested_type == "character" else ""

        score = calculate_candidate_confidence(
            has_translated_tag=has_translated,
            cooccurs_with_known_series=cooccurs,
            evidence_count=evidence_count,
            appears_in_multiple_series=multiple_series,
            is_blacklisted_general=is_blacklisted,
        )

        candidate = _upsert_candidate(
            conn,
            raw_tag=raw_tag,
            translated_tag=row["translated_tag"],
            suggested_type=suggested_type,
            suggested_series=suggested_series,
            confidence_score=score,
            evidence_count=evidence_count,
            source="group_analysis",
            now=now,
        )
        if candidate:
            results.append(candidate)

    conn.commit()
    return results


def generate_tag_candidates_from_observations(conn: sqlite3.Connection) -> list[dict]:
    """
    전체 tag_observations에서 후보를 생성한다 (전체 재생성 용도).
    """
    from core.tag_classifier import SERIES_ALIASES, CHARACTER_ALIASES

    confirmed_aliases = _load_confirmed_aliases(conn)
    all_raw_tags = conn.execute(
        "SELECT DISTINCT raw_tag FROM tag_observations"
    ).fetchall()

    results: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for (raw_tag,) in all_raw_tags:
        if raw_tag in confirmed_aliases:
            continue
        if raw_tag in SERIES_ALIASES or raw_tag in CHARACTER_ALIASES:
            continue

        obs_rows = conn.execute(
            "SELECT translated_tag, co_tags_json FROM tag_observations WHERE raw_tag = ?",
            (raw_tag,),
        ).fetchall()

        evidence_count = len(obs_rows)
        has_translated = any(r["translated_tag"] for r in obs_rows)
        translated_tag = next(
            (r["translated_tag"] for r in obs_rows if r["translated_tag"]), None
        )

        series_cooccur_names: set[str] = set()
        for obs in obs_rows:
            try:
                co_tags = json.loads(obs["co_tags_json"] or "[]")
            except Exception:
                co_tags = []
            for t in co_tags:
                if t in SERIES_ALIASES:
                    series_cooccur_names.add(SERIES_ALIASES[t])

        cooccurs = bool(series_cooccur_names)
        is_blacklisted = raw_tag in GENERAL_TAG_BLACKLIST
        multiple_series = len(series_cooccur_names) > 1
        suggested_type = "character" if cooccurs and not is_blacklisted else "general"
        suggested_series = next(iter(series_cooccur_names), "") if suggested_type == "character" else ""

        score = calculate_candidate_confidence(
            has_translated_tag=has_translated,
            cooccurs_with_known_series=cooccurs,
            evidence_count=evidence_count,
            appears_in_multiple_series=multiple_series,
            is_blacklisted_general=is_blacklisted,
        )

        candidate = _upsert_candidate(
            conn,
            raw_tag=raw_tag,
            translated_tag=translated_tag,
            suggested_type=suggested_type,
            suggested_series=suggested_series,
            confidence_score=score,
            evidence_count=evidence_count,
            source="full_analysis",
            now=now,
        )
        if candidate:
            results.append(candidate)

    conn.commit()
    return results


def generate_classification_failure_candidates(
    conn: sqlite3.Connection,
    group_id: str,
    classification_info: dict,
) -> list[dict]:
    """
    분류 실패 그룹(series_uncategorized / author_fallback)에 대한 후보를 생성한다.

    - series_detected_but_character_missing → suggested_type='character', score=0.35, series=series_context
    - series_and_character_missing          → suggested_type='general',   score=0.20

    source = "classification_failure". 자동 확정 금지.
    """
    reason = classification_info.get("classification_reason", "")
    candidate_source_tags = classification_info.get("candidate_source_tags", [])
    series_context = classification_info.get("series_context", "")

    if not candidate_source_tags:
        return []

    confirmed_aliases = _load_confirmed_aliases(conn)
    now = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []

    for raw_tag in candidate_source_tags:
        if raw_tag in confirmed_aliases:
            continue
        if reason == "series_detected_but_character_missing":
            score = 0.35
            suggested_type = "character"
            suggested_series = series_context
        else:
            score = 0.20
            suggested_type = "general"
            suggested_series = ""

        candidate = _upsert_candidate(
            conn,
            raw_tag=raw_tag,
            translated_tag=None,
            suggested_type=suggested_type,
            suggested_series=suggested_series,
            confidence_score=score,
            evidence_count=1,
            source="classification_failure",
            now=now,
        )
        if candidate:
            results.append(candidate)

    conn.commit()
    return results


def generate_ambiguous_alias_candidates(
    conn: sqlite3.Connection,
    group_id: str,
    ambiguous_tags: list[dict],
) -> list[dict]:
    """
    classify_pixiv_tags()의 ambiguous 목록에서 후보를 생성한다.

    ambiguous_tags: [{"raw_tag": ..., "candidates": [{"canonical": ..., "parent_series": ...}]}]
    각 후보 (canonical, parent_series) 쌍마다 tag_candidate 행을 생성한다.
    자동 확정 금지 — source='ambiguous_alias', status='pending'.
    """
    if not ambiguous_tags:
        return []

    now = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []

    for amb in ambiguous_tags:
        raw_tag    = amb.get("raw_tag", "")
        candidates = amb.get("candidates", [])
        if not raw_tag or not candidates:
            continue

        for cand in candidates:
            parent_series = cand.get("parent_series", "")
            candidate = _upsert_candidate(
                conn,
                raw_tag=raw_tag,
                translated_tag=None,
                suggested_type="character",
                suggested_series=parent_series,
                confidence_score=0.30,
                evidence_count=1,
                source="ambiguous_alias",
                now=now,
            )
            if candidate:
                results.append(candidate)

    if results:
        conn.commit()
    return results


def generate_alias_candidates_from_failed_tags(
    conn: sqlite3.Connection,
) -> dict:
    """
    분류에 실패한 artwork_groups의 tags_json에서 괄호 변형 패턴을 분석하여
    alias 후보를 생성한다.

    대상: character_tags_json이 비어 있는 그룹 (Author Fallback / series_uncategorized)
    로직:
    - 각 raw tag에서 _parse_parenthetical(tag) → (base, inner) 추출
    - base가 아직 tag_aliases에 없으면 "variant_stripped_pattern" 후보로 등록
    - inner가 알려진 series alias면 suggested_series를 채움
    - confidence_score는 등장 횟수에 비례

    Returns:
        {"candidates_created": int, "candidates_updated": int, "bases_found": int}
    """
    from core.tag_classifier import _parse_parenthetical, SERIES_ALIASES, load_db_aliases

    now = datetime.now(timezone.utc).isoformat()

    # 분류 실패 그룹 로드 — character_tags_json이 비거나 NULL인 것
    rows = conn.execute(
        "SELECT group_id, tags_json FROM artwork_groups "
        "WHERE tags_json IS NOT NULL "
        "AND (character_tags_json IS NULL OR character_tags_json = '[]')"
    ).fetchall()

    confirmed_aliases = _load_confirmed_aliases(conn)

    # series alias 룩업 (시리즈 힌트 추출용)
    db_series, _ = load_db_aliases(conn)
    all_series_aliases: dict[str, str] = dict(SERIES_ALIASES)
    all_series_aliases.update(db_series)

    from core.tag_normalize import normalize_tag_key
    norm_series = {normalize_tag_key(k): v for k, v in all_series_aliases.items() if k}

    # base → {count, series_hint} 집계
    base_stats: dict[str, dict] = {}
    for row in rows:
        try:
            raw_tags: list[str] = json.loads(row["tags_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in raw_tags:
            base, inner = _parse_parenthetical(tag)
            if base == tag or not base:
                continue
            if base in confirmed_aliases:
                continue
            if base not in base_stats:
                base_stats[base] = {"count": 0, "series_hint": ""}
            base_stats[base]["count"] += 1
            # inner이 series alias면 힌트 저장
            if not base_stats[base]["series_hint"]:
                series = all_series_aliases.get(inner, "")
                if not series:
                    nk = normalize_tag_key(inner)
                    series = norm_series.get(nk, "")
                if series:
                    base_stats[base]["series_hint"] = series

    candidates_saved = 0
    for base, stats in base_stats.items():
        count = stats["count"]
        series_hint = stats["series_hint"]
        score = min(0.20 + 0.10 * count + (0.20 if series_hint else 0.0), 0.70)
        result = _upsert_candidate(
            conn,
            raw_tag=base,
            translated_tag=None,
            suggested_type="character",
            suggested_series=series_hint,
            confidence_score=score,
            evidence_count=count,
            source="variant_stripped_pattern",
            now=now,
        )
        if result:
            candidates_saved += 1

    if base_stats:
        conn.commit()

    return {
        "bases_found":      len(base_stats),
        "candidates_saved": candidates_saved,
    }


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _load_confirmed_aliases(conn: sqlite3.Connection) -> set[str]:
    try:
        rows = conn.execute("SELECT alias FROM tag_aliases").fetchall()
        return {row["alias"] for row in rows}
    except Exception:
        return set()


def _upsert_candidate(
    conn: sqlite3.Connection,
    *,
    raw_tag: str,
    translated_tag: str | None,
    suggested_type: str,
    suggested_series: str,
    confidence_score: float,
    evidence_count: int,
    source: str,
    now: str,
) -> dict | None:
    """
    tag_candidates를 INSERT 또는 UPDATE한다.
    status='pending'인 행만 갱신하고, 이미 처리된 행은 None 반환.
    """
    existing = conn.execute(
        "SELECT candidate_id, status FROM tag_candidates "
        "WHERE raw_tag = ? AND suggested_type = ? AND suggested_parent_series = ?",
        (raw_tag, suggested_type, suggested_series),
    ).fetchone()

    if existing:
        if existing["status"] != "pending":
            return None
        conn.execute(
            "UPDATE tag_candidates SET translated_tag=?, confidence_score=?, "
            "evidence_count=?, updated_at=? WHERE candidate_id=?",
            (translated_tag, confidence_score, evidence_count, now, existing["candidate_id"]),
        )
        candidate_id = existing["candidate_id"]
    else:
        candidate_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tag_candidates "
            "(candidate_id, raw_tag, translated_tag, suggested_type, "
            "suggested_parent_series, confidence_score, evidence_count, "
            "source, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                candidate_id, raw_tag, translated_tag, suggested_type,
                suggested_series, confidence_score, evidence_count,
                source, now, now,
            ),
        )

    return {
        "candidate_id":           candidate_id,
        "raw_tag":                raw_tag,
        "translated_tag":         translated_tag,
        "suggested_type":         suggested_type,
        "suggested_parent_series": suggested_series,
        "confidence_score":       confidence_score,
        "evidence_count":         evidence_count,
    }
