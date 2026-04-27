#!/usr/bin/env python3
"""
Tag Pack Alias Enrichment Tool.

입력: docs/tag_pack_export_localized_ko_ja.json
출력: docs/tag_pack_export_localized_ko_ja_enriched.json
보고서: docs/tag_pack_export_localized_ko_ja_enriched_report.json

정책:
- localizations 값을 aliases에 보강 (matching용)
- Blue Archive 확인된 캐릭터의 canonical/aliases/localizations 보강
- variant tag를 base character에 병합
- 모호한 short alias 탐지
- group/general 후보는 character alias로 자동 확정하지 않음 (report-only)
- Danbooru/Safebooru 계열 후보 조회 (--danbooru 플래그 사용 시, 선택적)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ===========================================================================
# Built-in enrichment data
# 출처: Blue Archive 공식 게임 데이터
# HIGH = 공식 풀네임 확실히 확인됨 / MEDIUM = 중간 신뢰도 (review 유지)
# ===========================================================================

_HIGH_CONFIDENCE_ENRICHMENT: dict[str, dict] = {
    "Toki": {
        "new_canonical": "飛鳥馬トキ",
        "add_aliases": ["Asuma Toki", "トキ", "飛鳥馬トキ", "토키", "아스마 토키"],
        "new_localizations": {"en": "Asuma Toki", "ja": "飛鳥馬トキ", "ko": "아스마 토키"},
        "clear_review": ["needs_localization_check", "needs_canonical_check"],
        "evidence": "Millennium Science School; official JP full name 飛鳥馬トキ",
    },
    "Tsubasa": {
        "new_canonical": "小鳥遊ツバサ",
        "add_aliases": ["Takanashi Tsubasa", "ツバサ", "小鳥遊ツバサ", "타카나시 츠바사"],
        "new_localizations": {"en": "Takanashi Tsubasa", "ja": "小鳥遊ツバサ", "ko": "타카나시 츠바사"},
        "clear_review": ["needs_localization_check", "needs_canonical_check"],
        "evidence": "Millennium; same 小鳥遊 (Takanashi) family as Hoshino",
    },
}

_MEDIUM_CONFIDENCE_ENRICHMENT: dict[str, dict] = {
    "Hibiki": {
        "new_canonical": "日下部ヒビキ",
        "add_aliases": ["Kusakabe Hibiki", "ヒビキ", "日下部ヒビキ", "쿠사카베 히비키"],
        "new_localizations": {"en": "Kusakabe Hibiki", "ja": "日下部ヒビキ", "ko": "쿠사카베 히비키"},
        "evidence": "Abydos High School student council treasurer; medium confidence",
    },
    "Serika": {
        "new_canonical": "赤城セリカ",
        "add_aliases": ["Akagi Serika", "セリカ", "赤城セリカ", "아카기 세리카"],
        "new_localizations": {"en": "Akagi Serika", "ja": "赤城セリカ", "ko": "아카기 세리카"},
        "evidence": "Abydos High School; medium confidence",
    },
}

# variant entries → base canonical 병합 매핑
# new_base_canonical: 보강 적용 후 최종 canonical명
_VARIANT_MERGES: dict[str, dict] = {
    "Toki (school Uniform)": {
        "new_base_canonical": "飛鳥馬トキ",
        "variant": "school_uniform",
        # 확인되지 않은 variant alias는 report suggestions으로만 남김
        "unconfirmed_alias_suggestions": [
            "toki_(new_year)_(blue_archive)",
            "Toki (new year)",
            "トキ(正月)",
            "飛鳥馬トキ(正月)",
        ],
    },
}

# group/general 후보 canonical — character alias로 자동 확정하지 않음
_GROUP_GENERAL_CANONICALS: frozenset[str] = frozenset({
    "Gourmet Research Society",
    "Problem Solver 68",
    "Rabbit Platoon",
    "Veritas",
    "Occult Studies Club",
    "Justice Task Force Member",
    "タイツ",
    "メガネ",
    "白タイツ",
})


def _dedup_ordered(items: list[str]) -> list[str]:
    """중복 제거, 순서 보존, 빈 값 제거."""
    seen: set[str] = set()
    result: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            result.append(x)
    return result


def _build_enrichment_map() -> dict[str, dict]:
    """HIGH + MEDIUM 맵을 confidence 필드 포함해 반환."""
    result: dict[str, dict] = {}
    for canonical, info in _HIGH_CONFIDENCE_ENRICHMENT.items():
        result[canonical] = {**info, "confidence": "high"}
    for canonical, info in _MEDIUM_CONFIDENCE_ENRICHMENT.items():
        result[canonical] = {**info, "confidence": "medium"}
    return result


def enrich_single_entry(
    entry: dict,
    enrichment_map: dict[str, dict],
    report: dict,
) -> dict:
    """
    단일 character entry를 보강한다.

    순서:
    1. 기존 localizations 값을 aliases에 추가
    2. canonical 자체를 aliases에 추가
    3. built-in enrichment 적용 (canonical 변경 / 추가 aliases / 추가 localizations)
    4. 새 localizations 값도 aliases에 추가
    5. aliases dedup
    """
    canonical: str = entry.get("canonical", "")
    aliases: list[str] = list(entry.get("aliases", []))
    localizations: dict[str, str] = dict(entry.get("localizations", {}))
    parent_series: str = entry.get("parent_series", "")
    review: dict = dict(entry.get("_review", {}))

    canonical_before = canonical
    aliases_before: set[str] = set(aliases)
    newly_added: list[str] = []

    # 1. 기존 localizations → aliases
    for _locale, display_name in localizations.items():
        if display_name and display_name not in aliases:
            aliases.append(display_name)
            newly_added.append(display_name)

    # 2. canonical → aliases
    if canonical and canonical not in aliases:
        aliases.append(canonical)

    # 3. built-in enrichment
    enrichment = enrichment_map.get(canonical_before)
    if enrichment:
        new_canonical: str = enrichment.get("new_canonical", "")
        add_aliases: list[str] = enrichment.get("add_aliases", [])
        new_locs: dict[str, str] = enrichment.get("new_localizations", {})
        clear_review: list[str] = enrichment.get("clear_review", [])
        confidence: str = enrichment.get("confidence", "high")
        evidence: str = enrichment.get("evidence", "")

        # canonical 변경
        if new_canonical and new_canonical != canonical_before:
            canonical = new_canonical
            # 기존 canonical을 aliases에 보존
            if canonical_before and canonical_before not in aliases:
                aliases.append(canonical_before)
            report["canonical_changes"].append({
                "from": canonical_before,
                "to": new_canonical,
                "parent_series": parent_series,
                "confidence": confidence,
                "evidence": evidence,
            })

        # 추가 aliases 적용
        for alias in add_aliases:
            if alias and alias not in aliases:
                aliases.append(alias)
                newly_added.append(alias)

        # localizations 보강 (enrichment 데이터가 더 정확하므로 override)
        for locale, display_name in new_locs.items():
            if display_name:
                localizations[locale] = display_name

        # 4. 새 localizations 값도 aliases에
        for _locale, display_name in new_locs.items():
            if display_name and display_name not in aliases:
                aliases.append(display_name)
                newly_added.append(display_name)

        # _review 플래그 처리
        for flag in clear_review:
            review.pop(flag, None)

        if confidence == "medium":
            # medium confidence: _review 유지하되 reason 갱신
            review["needs_canonical_check"] = True
            review["reason"] = f"canonical changed with medium confidence — {evidence}"

    # 5. aliases 최종 정리
    aliases = _dedup_ordered(aliases)

    # report에 새 aliases 기록 (aliases_before 기준으로 진짜 새로 추가된 것만)
    for alias in newly_added:
        if alias not in aliases_before:
            report["aliases_added"].append({
                "canonical": canonical,
                "alias": alias,
                "source": "enrichment" if enrichment else "localizations",
                "parent_series": parent_series,
            })

    result: dict = {
        "aliases": aliases,
        "canonical": canonical,
        "localizations": localizations,
        "parent_series": parent_series,
    }
    if review:
        result["_review"] = review
    return result


def process_variant_merges(
    characters: list[dict],
    report: dict,
) -> list[dict]:
    """
    variant entries를 base character에 병합한다.
    enrichment 적용 후의 최종 canonical 기준으로 lookup.
    """
    canonical_to_idx: dict[str, int] = {
        e["canonical"]: i for i, e in enumerate(characters)
    }
    to_remove: set[int] = set()

    for variant_canonical, merge_info in _VARIANT_MERGES.items():
        new_base = merge_info["new_base_canonical"]
        variant_type = merge_info["variant"]
        suggestions = merge_info.get("unconfirmed_alias_suggestions", [])

        variant_idx = canonical_to_idx.get(variant_canonical)
        base_idx = canonical_to_idx.get(new_base)

        if variant_idx is None:
            logger.debug("Variant not found (already merged?): %s", variant_canonical)
            continue
        if base_idx is None:
            logger.warning("Base canonical not found for merge: %s → %s", variant_canonical, new_base)
            continue

        variant_entry = characters[variant_idx]
        base_entry = characters[base_idx]

        # variant aliases를 base에 흡수
        base_aliases: list[str] = list(base_entry["aliases"])
        absorbed: list[str] = []
        for alias in list(variant_entry.get("aliases", [])) + [variant_canonical]:
            if alias and alias not in base_aliases:
                base_aliases.append(alias)
                absorbed.append(alias)
        base_entry["aliases"] = _dedup_ordered(base_aliases)

        # merged_variants 기록
        base_review = base_entry.setdefault("_review", {})
        base_review.setdefault("merged_variants", []).append({
            "source_canonical": variant_canonical,
            "variant": variant_type,
            "reason": "costume/variant tag merged into base character",
            "absorbed_aliases": absorbed,
        })

        # 미확인 variant suggestions → warnings로만
        for suggestion in suggestions:
            report["warnings"].append({
                "type": "unconfirmed_variant_alias_suggestion",
                "canonical": new_base,
                "suggestion": suggestion,
                "reason": "not auto-confirmed; requires manual verification",
            })

        report["merges"].append({
            "from": variant_canonical,
            "into": new_base,
            "variant": variant_type,
            "absorbed_aliases": absorbed,
        })

        to_remove.add(variant_idx)

    return [e for i, e in enumerate(characters) if i not in to_remove]


def detect_ambiguous_aliases(characters: list[dict]) -> list[dict]:
    """
    같은 alias가 여러 canonical에 걸치는 경우를 탐지한다.
    group/general은 제외 (이미 별도 review 처리).
    """
    alias_map: dict[str, list[dict]] = {}
    for entry in characters:
        if entry.get("canonical", "") in _GROUP_GENERAL_CANONICALS:
            continue
        if entry.get("_review", {}).get("possibly_general_or_group_tag"):
            continue
        canonical = entry.get("canonical", "")
        parent_series = entry.get("parent_series", "")
        for alias in entry.get("aliases", []):
            if not alias:
                continue
            alias_map.setdefault(alias, []).append({
                "canonical": canonical,
                "parent_series": parent_series,
            })

    ambiguous: list[dict] = []
    seen: set[str] = set()
    for alias, entries in alias_map.items():
        if alias in seen:
            continue
        canonical_set = {e["canonical"] for e in entries}
        if len(canonical_set) > 1:
            seen.add(alias)
            series_set = {e["parent_series"] for e in entries}
            ambiguous.append({
                "type": "ambiguous_short_alias",
                "alias": alias,
                "candidates": [
                    {"canonical": e["canonical"], "parent_series": e["parent_series"]}
                    for e in entries
                ],
                "multi_series": len(series_set) > 1,
            })

    return ambiguous


def collect_observed_raw_tags(conn, parent_series: str | None = None) -> dict:
    """
    DB에 저장된 tag_observations에서 raw tag를 수집한다.
    같은 작품에서 co-occurring tag를 기반으로 alias 후보를 제안한다.

    반환: {raw_tag: {"count": N, "co_tags": [...]}}
    """
    result: dict = {}
    try:
        if parent_series:
            rows = conn.execute(
                "SELECT raw_tag, co_tags_json, COUNT(*) as cnt "
                "FROM tag_observations GROUP BY raw_tag"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT raw_tag, co_tags_json, COUNT(*) as cnt "
                "FROM tag_observations GROUP BY raw_tag"
            ).fetchall()

        for row in rows:
            raw_tag = row[0]
            co_json = row[1]
            cnt = row[2]
            co_tags: list[str] = []
            try:
                if co_json:
                    co_tags = json.loads(co_json)
            except Exception:
                pass
            result[raw_tag] = {"count": cnt, "co_tags": co_tags}
    except Exception as exc:
        logger.debug("collect_observed_raw_tags failed: %s", exc)
    return result


def _lookup_danbooru_tag(tag_name: str) -> dict | None:
    """Danbooru API에서 tag 정보를 조회한다. 실패 시 None 반환."""
    try:
        import httpx
        headers = {"User-Agent": "AruArchive/0.4.0 tag-enrichment-tool"}
        resp = httpx.get(
            "https://danbooru.donmai.us/tags.json",
            params={"search[name]": tag_name, "limit": "1"},
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, list) or not data:
            return None
        for tag in data:
            if isinstance(tag, dict) and tag.get("name") == tag_name:
                return tag
        return data[0] if data else None
    except Exception as exc:
        logger.debug("Danbooru lookup failed for %s: %s", tag_name, exc)
        return None


def _find_danbooru_alias(aliases: list[str]) -> str | None:
    """aliases에서 Danbooru 형식 태그 추출. 패턴: name_(series)"""
    import re
    pattern = re.compile(r'^[a-z][a-z0-9_]*_\([a-z_]+\)$')
    for alias in aliases:
        normalized = alias.lower().replace(" ", "_")
        if pattern.match(normalized) and alias == alias.lower():
            return alias
    return None


def enrich_from_danbooru(
    characters: list[dict],
    report: dict,
    max_requests: int = 20,
    delay: float = 1.0,
) -> None:
    """Danbooru에서 character tag 정보를 조회하여 external_evidence에 기록한다."""
    request_count = 0

    for entry in characters:
        if request_count >= max_requests:
            break
        canonical = entry.get("canonical", "")
        if canonical in _GROUP_GENERAL_CANONICALS:
            continue
        if entry.get("_review", {}).get("possibly_general_or_group_tag"):
            continue

        danbooru_tag = _find_danbooru_alias(entry.get("aliases", []))
        if not danbooru_tag:
            continue

        time.sleep(delay)
        request_count += 1
        tag_info = _lookup_danbooru_tag(danbooru_tag)
        if not tag_info:
            continue

        category = tag_info.get("category")
        if category != 4:  # 4 = character
            report["warnings"].append({
                "type": "danbooru_tag_not_character_category",
                "canonical": canonical,
                "danbooru_tag": danbooru_tag,
                "danbooru_category": category,
            })
            continue

        report["external_evidence"].append({
            "type": "external_alias_added",
            "canonical": canonical,
            "alias": danbooru_tag,
            "source": "danbooru",
            "evidence": {
                "tag_category": "character",
                "post_count": tag_info.get("post_count", 0),
                "matched_series": entry.get("parent_series", ""),
            },
        })


def enrich_pack(
    pack: dict,
    use_danbooru: bool = False,
    max_danbooru_requests: int = 20,
) -> tuple[dict, dict]:
    """
    Tag pack을 보강하고 (enriched_pack, report)를 반환한다.
    use_danbooru=False이면 네트워크 접근 없이 built-in 데이터만 사용.
    """
    report: dict = {
        "summary": {
            "aliases_added": 0,
            "canonical_changed": 0,
            "entities_merged": 0,
            "localizations_added": 0,
            "review_items_remaining": 0,
            "external_aliases_added": 0,
            "ambiguous_short_aliases": 0,
            "group_general_candidates": 0,
        },
        "canonical_changes": [],
        "merges": [],
        "aliases_added": [],
        "external_evidence": [],
        "ambiguous_aliases": [],
        "review_items_remaining": [],
        "warnings": [],
    }

    enrichment_map = _build_enrichment_map()

    # 1. 각 entry 보강
    characters: list[dict] = []
    for entry in pack.get("characters", []):
        enriched = enrich_single_entry(entry, enrichment_map, report)
        characters.append(enriched)

    # 2. variant 병합
    characters = process_variant_merges(characters, report)

    # 3. Danbooru enrichment (선택적)
    if use_danbooru:
        enrich_from_danbooru(characters, report, max_requests=max_danbooru_requests)

    # 4. ambiguous alias 탐지
    report["ambiguous_aliases"] = detect_ambiguous_aliases(characters)

    # 5. review items 수집
    group_general_count = 0
    for entry in characters:
        review = entry.get("_review", {})
        canonical = entry.get("canonical", "")
        parent_series = entry.get("parent_series", "")

        if review.get("possibly_general_or_group_tag"):
            group_general_count += 1
            report["review_items_remaining"].append({
                "canonical": canonical,
                "parent_series": parent_series,
                "reason": "group_or_general_candidate",
                "suggested_tag_type": review.get("suggested_tag_type"),
            })
        elif review.get("needs_localization_check") or review.get("needs_canonical_check"):
            report["review_items_remaining"].append({
                "canonical": canonical,
                "parent_series": parent_series,
                "reason": "needs_further_verification",
                "flags": {
                    k: v for k, v in review.items()
                    if k in ("needs_localization_check", "needs_canonical_check", "reason")
                },
            })

    # 6. summary 계산
    s = report["summary"]
    s["aliases_added"] = len(report["aliases_added"])
    s["canonical_changed"] = len(report["canonical_changes"])
    s["entities_merged"] = len(report["merges"])
    s["localizations_added"] = sum(
        1 for a in report["aliases_added"] if a.get("source") == "localizations"
    )
    s["review_items_remaining"] = len(report["review_items_remaining"])
    s["external_aliases_added"] = len(report["external_evidence"])
    s["ambiguous_short_aliases"] = len(report["ambiguous_aliases"])
    s["group_general_candidates"] = group_general_count

    # enriched pack 구성
    enriched_pack: dict = {
        "pack_id": pack.get("pack_id", "tag_pack_export_enriched"),
        "name": pack.get("name", "Tag Pack Export (Enriched)"),
        "version": pack.get("version", "1.0.0"),
        "source": "enriched",
        "series": list(pack.get("series", [])),
        "characters": characters,
        "exported_at": pack.get("exported_at", ""),
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }

    return enriched_pack, report


def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Tag Pack Alias Enrichment Tool")
    parser.add_argument(
        "--input", "-i",
        default="docs/tag_pack_export_localized_ko_ja.json",
    )
    parser.add_argument(
        "--output", "-o",
        default="docs/tag_pack_export_localized_ko_ja_enriched.json",
    )
    parser.add_argument(
        "--report", "-r",
        default="docs/tag_pack_export_localized_ko_ja_enriched_report.json",
    )
    parser.add_argument(
        "--danbooru", "-d",
        action="store_true",
        help="Danbooru API 조회 활성화 (rate-limited)",
    )
    parser.add_argument(
        "--max-danbooru", type=int, default=20,
        help="Danbooru 최대 요청 수 (기본 20)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 입력 파일 없음: {input_path}")
        return 1

    print(f"[INFO] 입력: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        pack = json.load(f)
    print(f"[INFO]   characters: {len(pack.get('characters', []))}, series: {len(pack.get('series', []))}")

    enriched_pack, report = enrich_pack(
        pack,
        use_danbooru=args.danbooru,
        max_danbooru_requests=args.max_danbooru,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched_pack, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 출력: {output_path}")

    report_path = Path(args.report)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 보고서: {report_path}")

    s = report["summary"]
    print("\n=== Enrichment Summary ===")
    print(f"  aliases_added:           {s['aliases_added']}")
    print(f"  canonical_changed:       {s['canonical_changed']}")
    print(f"  entities_merged:         {s['entities_merged']}")
    print(f"  localizations_added:     {s['localizations_added']}")
    print(f"  review_items_remaining:  {s['review_items_remaining']}")
    print(f"  ambiguous_short_aliases: {s['ambiguous_short_aliases']}")
    print(f"  group_general_candidates:{s['group_general_candidates']}")

    def _safe(s: str) -> str:
        return s.encode("ascii", errors="replace").decode()

    if report["canonical_changes"]:
        print("\n=== Canonical Changes ===")
        for cc in report["canonical_changes"]:
            print(f"  [{cc['confidence']}] {_safe(cc['from'])} -> {_safe(cc['to'])}")

    if report["merges"]:
        print("\n=== Variant Merges ===")
        for m in report["merges"]:
            absorbed = [_safe(a) for a in m["absorbed_aliases"]]
            print(f"  {_safe(m['from'])} -> {_safe(m['into'])} (absorbed: {absorbed})")

    if report["ambiguous_aliases"]:
        print("\n=== Ambiguous Short Aliases ===")
        for a in report["ambiguous_aliases"]:
            cands = ", ".join(
                f"{c['canonical']}({c['parent_series']})".encode("ascii", errors="replace").decode()
                for c in a["candidates"]
            )
            alias_safe = a["alias"].encode("ascii", errors="replace").decode()
            print(f"  '{alias_safe}' -> [{cands}]")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
