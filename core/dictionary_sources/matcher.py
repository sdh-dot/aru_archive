"""
Pixiv tag_observations ↔ Danbooru 후보 매칭.

매칭 결과는 external_dictionary_entries 또는 tag_candidates staging용으로만 사용된다.
자동 확정 금지.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def match_pixiv_tags_to_danbooru_candidates(
    pixiv_tags: list[str],
    danbooru_candidates: list[dict[str, Any]],
    *,
    known_series: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Pixiv raw tag 목록과 Danbooru 후보를 매칭하여 alias 후보를 생성한다.

    매칭 전략:
      1. exact: danbooru_tag와 pixiv_tag가 완전 일치
      2. normalized: normalize_tag_key 적용 후 비교
      3. co-occurrence: known_series가 있으면 series와 함께 등장한 태그에 가중치

    반환:
      [{"pixiv_tag": str, "danbooru_candidate": dict, "match_type": str,
        "evidence": dict}, ...]

    자동 확정 없음 — 결과를 external_dictionary_entries로만 저장.
    """
    from core.tag_normalize import normalize_tag_key

    known_series_set = set(known_series or [])
    norm_pixiv: dict[str, str] = {
        normalize_tag_key(t): t for t in pixiv_tags if t
    }
    results: list[dict[str, Any]] = []

    for candidate in danbooru_candidates:
        db_tag = candidate.get("danbooru_tag", "")
        db_canonical = candidate.get("canonical", "")
        db_tag_norm = normalize_tag_key(db_tag)
        db_canonical_norm = normalize_tag_key(db_canonical)

        for pixiv_tag in pixiv_tags:
            pt_norm = normalize_tag_key(pixiv_tag)
            match_type: str | None = None

            # 1. exact: danbooru_tag == pixiv_tag
            if pixiv_tag == db_tag:
                match_type = "exact"
            # 2. normalized: same normalized key
            elif pt_norm and (pt_norm == db_tag_norm or pt_norm == db_canonical_norm):
                match_type = "normalized"

            if match_type is None:
                continue

            co_occurred = bool(known_series_set)
            evidence = {
                "match_type":       match_type,
                "pixiv_tag":        pixiv_tag,
                "danbooru_tag":     db_tag,
                "co_occurred_with": sorted(known_series_set),
            }

            results.append({
                "pixiv_tag":          pixiv_tag,
                "danbooru_candidate": candidate,
                "match_type":         match_type,
                "co_occurred":        co_occurred,
                "evidence":           evidence,
            })

    return results


def build_external_entries_from_matches(
    matches: list[dict[str, Any]],
    *,
    source: str = "danbooru",
) -> list[dict[str, Any]]:
    """
    match 결과를 external_dictionary_entries 삽입용 dict 목록으로 변환한다.

    각 매칭마다 2종류의 entry를 생성한다:
      1. alias entry: Pixiv raw tag → canonical alias
      2. localization entry: ja display_name 후보 (Pixiv raw tag 기반)
    """
    from datetime import datetime, timezone
    from core.external_dictionary import calculate_external_dictionary_confidence

    now = datetime.now(timezone.utc).isoformat()
    entries: list[dict[str, Any]] = []

    for m in matches:
        cand = m["danbooru_candidate"]
        pixiv_tag = m["pixiv_tag"]
        evidence = m.get("evidence", {})
        co_occurred = m.get("co_occurred", False)

        canonical = cand.get("canonical", "")
        tag_type = cand.get("tag_type", "general")
        parent_series = cand.get("parent_series", "")
        danbooru_tag = cand.get("danbooru_tag", "")

        is_short = len(pixiv_tag) <= 3
        confidence = calculate_external_dictionary_confidence(
            danbooru_category_match=tag_type in ("character", "series"),
            parent_series_matched=bool(parent_series),
            pixiv_observation_matched=True,
            alias_relation_found=m["match_type"] == "exact",
            implication_found=False,
            localization_found=False,
            short_alias_penalty=is_short,
            multi_series_penalty=False,
            general_blacklist_penalty=False,
        )

        # 1. alias entry (Pixiv raw tag → canonical)
        entries.append({
            "source":             source,
            "danbooru_tag":       danbooru_tag,
            "danbooru_category":  cand.get("danbooru_category", ""),
            "canonical":          canonical,
            "tag_type":           tag_type,
            "parent_series":      parent_series,
            "alias":              pixiv_tag,
            "locale":             None,
            "display_name":       None,
            "confidence_score":   confidence,
            "evidence_json":      json.dumps(evidence, ensure_ascii=False),
            "imported_at":        now,
        })

        # 2. ja localization entry (Pixiv raw tag → ja display_name)
        entries.append({
            "source":             source,
            "danbooru_tag":       danbooru_tag,
            "danbooru_category":  cand.get("danbooru_category", ""),
            "canonical":          canonical,
            "tag_type":           tag_type,
            "parent_series":      parent_series,
            "alias":              None,
            "locale":             "ja",
            "display_name":       pixiv_tag,
            "confidence_score":   confidence * 0.9,
            "evidence_json":      json.dumps({**evidence, "entry_kind": "localization"}, ensure_ascii=False),
            "imported_at":        now,
        })

    return entries
