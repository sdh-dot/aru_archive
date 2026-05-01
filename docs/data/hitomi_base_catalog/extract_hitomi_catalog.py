"""
extract_hitomi_catalog.py
=========================
Read-only extraction tool: Hitomi local tags.txt → docs sample JSON files.

Usage:
    python docs/data/hitomi_base_catalog/extract_hitomi_catalog.py \
        --tags "D:/Personal/hitomi_downloader_GUI/hitomi_data/tags.txt" \
        --out docs/data/hitomi_base_catalog \
        --limit 100

CLI arguments:
    --tags PATH            Path to hitomi_data/tags.txt (required)
    --out DIR              Output directory (required)
    --limit N              Sample size per category, default 100

Output files:
    catalog_summary.json   Category counts + sample metadata
    schema.json            JSON schema for sample items
    series.sample.json     Top N series by count
    character.sample.json  Top N characters by count
    female.sample.json     Top N female tags (adult/explicit filtered)
    male.sample.json       Top N male tags (adult/explicit filtered)

NOTE: This script is READ-ONLY with respect to source data.
      The original tags.txt is never modified.
      Do NOT commit the full tags.txt or any gallery pack files.
      female/male samples are filtered through ADULT_DENYLIST — review
      output files after extraction to catch any borderline items.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Adult / explicit content denylist
# ---------------------------------------------------------------------------
# Any female/male tag whose canonical slug contains one of these substrings
# (case-insensitive, partial match) is excluded from the sample.
# This is a conservative heuristic — review output files after extraction.
ADULT_DENYLIST: frozenset[str] = frozenset({
    # Sexual acts — oral / penetrative
    "anal", "oral", "fellatio", "cunnilingus", "intercourse", "penetration",
    "nakadashi", "creampie", "pregnant", "impregnation", "ejaculation",
    "masturbation", "handjob", "footjob", "paizuri", "titjob",
    "doggy", "missionary", "cowgirl", "sixty-nine",
    "blowjob", "deepthroat", "rimjob", "fingering", "frottage",
    "pegging", "prostate massage", "urethra insertion",
    "leg lock", "stomach deformation", "squirting",
    "mesuiki", "multiple orgasms", "orgasm denial",
    "mmm threesome",
    # Sexual actions / states
    "sex", "fuck", "rape", "noncon", "non-con", "consensual",
    "ahegao", "mind break", "mindbreak", "defloration", "deflower",
    "lactation", "lactating", "urination", "piss", "pissing",
    "scat", "shit", "feces", "urine", "vomit",
    "gangbang", "harem", "netorare", "ntr", "swinging", "cuckold",
    "cheating", "prostitution", "virginity",
    "voyeurism", "voyeur",
    # Genitalia / explicit body parts
    "penis", "cock", "dick", "vagina", "pussy", "vulva", "labia", "clitoris",
    "testicle", "ballbusting", "anus", "anal beads",
    "nipple", "areola", "areolae",
    "phimosis", "smegma", "big balls",
    "crotch tattoo", "body writing",
    "naked", "nude", "exhibitionism", "topless", "bottomless",
    "lewd", "ecchi explicit",
    "hairy",  # 성인물 맥락 (음모)
    # Body fetish / transformation
    "breast expansion", "inflation", "breast feeding",
    "enema", "gaping",
    # Fetish / BDSM / restraint
    "bondage", "bdsm", "femdom", "maledom", "mistress", "slave",
    "bukk", "facial", "watersports", "golden shower",
    "tentacle", "vore", "guro", "gore", "snuff",
    "shibari", "gag", "leash", "collar",  # 성적 결박/BDSM 도구
    "strap-on", "onahole", "chastity belt",  # 성인 용품
    "humiliation", "blackmail", "drugs",  # 성적 착취/강압
    "spanking", "cbt", "smalldom",
    "foot licking", "armpit licking",
    # Incest / family sexual context
    "incest", "imouto sex", "sister sex", "mother son", "father daughter",
    "kodomo doushi",  # 아동 간 성행위 — 법적 위험
    # Minor-related — MUST exclude (legal risk)
    "loli", "shota", "lolicon", "shotacon", "underage",
    # Gender variant — conservative exclusion
    "futanari", "futa", "shemale",
    # Non-consent / violence
    "molestation", "molester", "drugged", "kidnapping",
    "torture", "mutilation", "abuse",
    # Bestiality
    "bestiality", "human on furry",
    "dog",  # male 카테고리에서 수간 맥락
    "horse",  # male 카테고리에서 수간 맥락
    # Miscellaneous adult-context
    "x-ray",  # 성관계 체내 투시 묘사
    "filming",  # 성행위 촬영
    "corruption",  # 성적 타락
    "exposed clothing",  # 성적 노출 의상
    # Sexual acts — additional (missed in first pass)
    "cumflation",  # 정액 + 팽창 (성행위 결과)
    "gokkun",  # 정액 음용
    "milking",  # 성적 착유
    "facesitting",  # 성적 행위
    "sumata",  # 외부 성기 마찰
    "tribadism",  # 여성 간 성기 마찰
    "fisting",  # 성적 삽입
    "prolapse",  # 성적 신체 변형
    "condom",  # 성행위 용품
    "blindfold",  # BDSM 구속 도구
    # Fetish / non-consent (missed)
    "ryona",  # 여성 폭행 묘사 페티시
    "chikan",  # 성추행 (groping)
    "asphyxiation",  # 성적 질식
    "petplay",  # 성인 역할극
    "tail plug",  # 성인 삽입 용품
    "pasties",  # 유두 가리개
    "oyakodon",  # 모녀/부자 성행위 (incest 맥락)
    # Male-specific missed
    "necrophilia", "necro",  # 시체 성행위
    "josou seme",  # 여장 성행위
    "age regression",  # 연령 퇴행 (미성년 묘사 위험)
    "solo action",  # 자위 행위
    "layer cake",  # 성행위 체위/용어
    "mesuiki",  # 전립선 오르가즘 (이미 있지만 재확인)
    # Additional missed (third pass)
    "large insertion",  # 성적 삽입 페티시
    "public use",  # 성적 공용
    "nose hook",  # BDSM 구속 도구
    "chloroform",  # 비동의 약물 사용
    "shimaidon",  # 자매 성행위 (incest)
    "machine",  # 성적 기계 삽입
    "ball sucking",  # 구강 성행위
    "stuck in wall",  # 성적 상황
    "smell",  # 성인물 맥락 (냄새 페티시)
    "drunk",  # 비동의/판단력 저하 맥락
    "crying",  # 성적 강제 맥락에서 주로 사용
    "unbirth",  # 성인 페티시 (역출산)
    "diaper",  # ABDL 페티시 (성인 아동 회귀)
    "eggs",  # 성적 체내 산란 페티시
    "miniguy",  # 소형화 성인 페티시
    "shrinking",  # 소형화 성인 페티시
    # Fifth pass additions
    "netorase",  # NTR 변형 (성적 공유/타협)
    "possession",  # 성적 빙의 맥락
    "farting", "fart",  # 성인 페티시
    "coprophagia", "copro",  # 분변 관련 성인 행위
    "lipstick mark",  # 구강 성행위 흔적
    "cousin",  # 근친 관계 맥락
    "aunt",  # 근친 관계 맥락
    "shimapan",  # 성인 doujin 문맥에서 성적 의미
    "amputee",  # 성인 페티시 (절단 맥락)
    "blood",  # 폭력/성행위 중 출혈 묘사 맥락
    "blackmail",  # 이미 있지만 partial 매칭 확인
    # Sixth pass additions
    "clit",  # 성기 관련 (clit stimulation, big clit 등)
    "all the way through",  # 성적 관통 페티시
    "tickling",  # 성적 간지럼 페티시
    "giantess",  # 성인 크기 차이 페티시
    "body modification",  # 성기/신체 개조 성인 맥락
    # Seventh pass additions
    "parasite",  # 성인 기생충 페티시
    "forced exposure",  # 강제 노출 (비동의)
    "stirrup legwear",  # 성인 의상 맥락
    # Eighth pass additions
    "randoseru",  # 초등학생 책가방 — 미성년 암시 (법적 위험)
    "electric shock",  # BDSM 고문 도구
    "insect",  # 성인 곤충 페티시
})


# ---------------------------------------------------------------------------
# Categories produced by this script
# ---------------------------------------------------------------------------
ACTIVE_CATEGORIES: list[str] = ["series", "character", "female", "male"]
FILTERED_CATEGORIES: frozenset[str] = frozenset({"female", "male"})

CATEGORY_SAMPLE_FILE: dict[str, str] = {
    "series": "series.sample.json",
    "character": "character.sample.json",
    "female": "female.sample.json",
    "male": "male.sample.json",
}

SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Hitomi base catalog sample item",
    "description": (
        "One item extracted from hitomi_data/tags.txt. "
        "Represents a canonical slug as used by Hitomi.la."
    ),
    "type": "object",
    "properties": {
        "canonical": {
            "type": ["string", "null"],
            "description": "Canonical slug/name as stored in Hitomi catalog",
        },
        "count": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of galleries tagged with this entry",
        },
        "source_category": {
            "type": "string",
            "enum": ["series", "character", "female", "male"],
            "description": "Source category in tags.txt",
        },
        "source": {
            "type": "string",
            "const": "hitomi_tags_txt",
            "description": "Identifier for the data origin",
        },
        "filtered_subset": {
            "type": "string",
            "description": (
                "Present on female/male samples only. "
                "Value 'non_adult_descriptive' indicates this sample was filtered "
                "through ADULT_DENYLIST to exclude adult/explicit content tags."
            ),
        },
    },
    "required": ["canonical", "count", "source_category", "source"],
}


def load_tags(tags_path: str) -> dict:
    """Load and return the tags.txt JSON. Raises on parse error."""
    with open(tags_path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_adult(slug: str) -> bool:
    """Return True if slug matches any denylist keyword (partial, case-insensitive)."""
    lower = slug.lower()
    return any(kw in lower for kw in ADULT_DENYLIST)


def to_sample_items(
    items: list,
    category: str,
    limit: int | None = None,
    apply_filter: bool = False,
) -> tuple[list[dict], int]:
    """
    Convert raw items to sample schema, sorted by count descending.

    Returns (sample_items, filtered_out_count).
    filtered_out_count is non-zero only when apply_filter=True.
    """
    filtered_out = 0
    converted = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = item.get("s") or ""
        if apply_filter and is_adult(slug):
            filtered_out += 1
            continue
        entry: dict = {
            "canonical": slug if slug else None,
            "count": item.get("t", 0),
            "source_category": category,
            "source": "hitomi_tags_txt",
        }
        if apply_filter:
            entry["filtered_subset"] = "non_adult_descriptive"
        converted.append(entry)

    converted.sort(key=lambda x: x["count"], reverse=True)
    if limit is not None:
        converted = converted[:limit]
    return converted, filtered_out


def write_json(path: str, data, indent: int = 2) -> int:
    """Write JSON and return file size in bytes."""
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.getsize(path)


def build_summary(
    tags_path: str,
    data: dict,
    filter_stats: dict[str, dict],
    limit: int,
    generated_at: str,
) -> dict:
    source_size = os.path.getsize(tags_path)

    categories: dict = {}
    for cat in ACTIVE_CATEGORIES:
        items = data.get(cat, [])
        total = len(items)
        sample_size = min(limit, total)
        entry: dict = {
            "count": total,
            "sample_file": CATEGORY_SAMPLE_FILE.get(cat),
            "sample_size": sample_size,
        }
        if cat in FILTERED_CATEGORIES and cat in filter_stats:
            fs = filter_stats[cat]
            entry["filtered_count"] = fs["after_filter"]
            entry["filter_strategy"] = "denylist removes adult/explicit content tags"
        categories[cat] = entry

    return {
        "source": "hitomi_downloader_GUI hitomi_data/tags.txt",
        "source_path_user": tags_path.replace("\\", "/"),
        "source_size_bytes": source_size,
        "generated_at": generated_at,
        "categories": categories,
        "item_schema": {
            "s": "canonical slug/name",
            "t": "gallery count",
        },
        "scope": (
            "Aru Archive internal design reference — "
            "series/character/non-adult body descriptors only"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Hitomi tags.txt catalog into docs sample JSON files."
    )
    parser.add_argument("--tags", required=True, help="Path to hitomi_data/tags.txt")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument(
        "--limit", type=int, default=100, help="Sample size per category (default 100)"
    )
    args = parser.parse_args()

    tags_path = args.tags
    out_dir = args.out
    limit = args.limit

    # Validate source
    if not os.path.isfile(tags_path):
        print(f"ERROR: tags.txt not found: {tags_path}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)

    print(f"Loading: {tags_path}")
    data = load_tags(tags_path)
    print(f"Top-level keys: {list(data.keys())}")
    print()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Write schema
    schema_path = os.path.join(out_dir, "schema.json")
    sz = write_json(schema_path, SCHEMA)
    print(f"  schema.json  -- {sz:,} bytes")

    filter_stats: dict[str, dict] = {}

    # Process active categories only
    for cat in ACTIVE_CATEGORIES:
        if cat not in data:
            print(f"  SKIP {cat}: not found in tags.txt")
            continue

        items = data[cat]
        total = len(items)
        apply_filter = cat in FILTERED_CATEGORIES

        sample_items, filtered_out = to_sample_items(
            items, cat, limit=limit, apply_filter=apply_filter
        )
        actual = len(sample_items)

        if apply_filter:
            after_filter = total - filtered_out
            filter_stats[cat] = {
                "total": total,
                "filtered_out": filtered_out,
                "after_filter": after_filter,
                "sample_size": actual,
            }
            print(
                f"  {cat}: {total:,} total → {filtered_out:,} excluded by denylist "
                f"→ {after_filter:,} pass → sample {actual:,}"
            )
        else:
            print(f"  {cat}: {total:,} total → sample {actual:,}")

        fname = CATEGORY_SAMPLE_FILE[cat]
        out_path = os.path.join(out_dir, fname)
        file_sz = write_json(out_path, sample_items)
        print(f"  --> {fname}  {file_sz:,} bytes ({file_sz/1024:.1f} KB)")

    print()

    # Write summary
    summary = build_summary(tags_path, data, filter_stats, limit, generated_at)
    summary_path = os.path.join(out_dir, "catalog_summary.json")
    sz = write_json(summary_path, summary)
    print(f"  catalog_summary.json  -- {sz:,} bytes")

    print()
    print("Done. Output:", out_dir)
    print()
    print("IMPORTANT: Review female.sample.json and male.sample.json manually.")
    print("If any borderline item is found, add the keyword to ADULT_DENYLIST and re-run.")
    print("NOTE: Do NOT commit the original tags.txt or gallery pack files.")


if __name__ == "__main__":
    main()
