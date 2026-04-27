#!/usr/bin/env python3
"""
Failure Report Tag Pack Patch Tool.

분류 실패 리포트(TXT)에서 관찰된 raw tags를 기반으로 tag pack alias를 보강한다.

입력:
  --tag-pack         enriched tag pack JSON (기본: docs/tag_pack_export_localized_ko_ja_enriched.json)
  --failure-report   분류 실패 TXT 파일 (기본: 없음, 없으면 patch data만 적용)
  --output           출력 JSON (기본: docs/tag_pack_export_localized_ko_ja_failure_patch.json)
  --report           패치 보고서 JSON (기본: --output 경로에 _report.json 추가)

정책:
  - 26개 Blue Archive 캐릭터를 pack에 추가 (already-existing canonical은 skip)
  - 기존 aliases/localizations 덮어쓰지 않음 (INSERT OR IGNORE 방식)
  - 인기 suffix 태그(5000users入り 등)는 캐릭터 alias로 추가하지 않음
  - general/attribute 태그는 캐릭터 alias로 추가하지 않음
  - group 태그는 캐릭터 alias로 추가하지 않음
  - 괄호 variant 태그는 base character entry의 aliases에 병합
  - 시리즈 disambiguator(サツキ(ブルーアーカイブ))는 해당 canonical의 alias로 포함
  - title-only 후보는 report에만 기록, 자동 확정하지 않음
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ===========================================================================
# Constants — tags that must NOT become character aliases
# ===========================================================================

_GENERAL_TAGS: frozenset[str] = frozenset({
    "巨乳", "爆乳", "着衣巨乳", "ロリ巨乳", "女の子", "少女", "美少女", "おっぱい",
    "体操服", "体操着", "水着", "ビキニ", "バニーガール", "制服", "セーラー服",
    "チアリーダー", "チアガール", "ふともも", "魅惑のふともも", "魅惑の谷間",
    "黒スト", "黒タイツ", "白タイツ", "ニーソ", "ストッキング", "ハイヒール",
    "メガネ", "眼鏡", "ポニーテール", "ツインテール", "ショートヘア",
    "笑顔", "照れ", "泣き顔", "上目遣い",
    "足組み", "ぺたん座り", "しゃがみ", "お腹",
    "晄輪大祭", "エンジニア部", "補習授業部",
    "百合", "イラスト", "漫画", "SD", "コイカツ",
})

_GROUP_TAGS: frozenset[str] = frozenset({
    "便利屋68", "ティーパーティー", "ヘイロー",
    "正義実現委員会", "正義実現委員会のモブ",
    "トリニティ総合学園", "ミレニアムサイエンススクール",
    "生活安全局", "ヴァルキューレ警察学校",
    "連邦生徒会", "ゲヘナ学園", "エデン条約機構",
    "キラキラ部", "ブルアカモータリゼーション",
})

# Series disambiguator raw_tag → resolved canonical.
# These are added as aliases to the canonical entry, NOT as separate entries.
_SERIES_DISAMBIGUATORS: dict[str, str] = {
    "サツキ(ブルーアーカイブ)":  "京極サツキ",
    "キサキ(ブルーアーカイブ)":  "竜華キサキ",
    "キララ(ブルーアーカイブ)":  "夜桜キララ",
    "ノノミ(ブルーアーカイブ)":  "十六夜ノノミ",
}

# Parenthetical variant raw_tag → base canonical.
# The variant tag itself is added as an alias to the base entry, recorded in _review.merged_variants.
_VARIANT_MERGES_FROM_FAILURES: dict[str, dict] = {
    "猫塚ヒビキ(応援団)":    {"base_canonical": "猫塚ヒビキ",  "variant": "cheerleader"},
    "羽川ハスミ(体操服)":    {"base_canonical": "羽川ハスミ",  "variant": "gym_uniform"},
    "黒崎コユキ(バニーガール)": {"base_canonical": "黒崎コユキ", "variant": "bunny_girl"},
    "鷲見セリナ(クリスマス)": {"base_canonical": "鷲見セリナ",  "variant": "christmas"},
    "鷲見セリナ(ナース)":     {"base_canonical": "鷲見セリナ",  "variant": "nurse"},
    "河和シズコ(水着)":       {"base_canonical": "河和シズコ",  "variant": "swimsuit"},
    "春原シュン(幼女)":       {"base_canonical": "春原シュン",  "variant": "child_form"},
}

# v2: characters verified from training knowledge (no web crawl required)
_WEB_EVIDENCE_V2: list[dict] = [
    {"tag": "仲正イチカ", "verified_as": "Blue Archive character (Millennium Science School)",
     "source": "training_knowledge", "evidence_url": ""},
    {"tag": "浦和ハナコ", "verified_as": "Blue Archive character (Gehenna Academy)",
     "source": "training_knowledge", "evidence_url": ""},
    {"tag": "春原シュン", "verified_as": "Blue Archive character (Hyakkiyako Academy)",
     "source": "training_knowledge", "evidence_url": ""},
    {"tag": "伊落マリー", "verified_as": "Blue Archive character (Trinity General School)",
     "source": "training_knowledge", "evidence_url": ""},
]

# v2: ambiguous tags that need human review before adding as character aliases
_NEEDS_REVIEW_V2: list[dict] = [
    {"tag": "ムツキ",   "reason": "ambiguous — multiple series share this name; no Blue Archive context confirmed"},
    {"tag": "カヨアル", "reason": "likely a ship name (カヨ + アル) rather than a standalone character"},
    {"tag": "碧蓝档案", "reason": "Chinese name for Blue Archive series — add as series alias, not character alias"},
    {"tag": "ヘイロー(ブルーアーカイブ)",   "reason": "in-game halo item/mechanic tag, not a character"},
    {"tag": "ティーパーティー(ブルーアーカイブ)", "reason": "faction/group tag, not a character"},
    {"tag": "コハル(アニポケ)", "reason": "Pokémon anime character, not Blue Archive コハル"},
]

# ===========================================================================
# Patch character data — 26 Blue Archive characters confirmed missing from pack
# ===========================================================================

_PATCH_CHARACTERS: list[dict] = [
    {
        "canonical": "羽川ハスミ",
        "localizations": {"en": "Hanekawa Hasumi", "ja": "羽川ハスミ", "ko": "하네카와 하스미"},
        "aliases": [
            "Hasumi", "ハスミ", "Hanekawa Hasumi", "hanekawa_hasumi_(blue_archive)",
            "羽川ハスミ", "하스미", "하네카와 하스미",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "黒崎コユキ",
        "localizations": {"en": "Kurosaki Koyuki", "ja": "黒崎コユキ", "ko": "쿠로사키 코유키"},
        "aliases": [
            "Koyuki", "コユキ", "Kurosaki Koyuki", "kurosaki_koyuki_(blue_archive)",
            "黒崎コユキ", "코유키", "쿠로사키 코유키",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "合歓垣フブキ",
        "localizations": {"en": "Nekogaki Fubuki", "ja": "合歓垣フブキ", "ko": "네코가키 후부키"},
        "aliases": [
            "Fubuki", "フブキ", "Nekogaki Fubuki", "nekogaki_fubuki_(blue_archive)",
            "合歓垣フブキ", "후부키", "네코가키 후부키", "ネムガキ",
        ],
        "parent_series": "Blue Archive",
    },
    {
        # 日下部ヒビキ와 다른 캐릭터 — 단독 'ヒビキ' / 'Hibiki' alias 추가 불가
        "canonical": "猫塚ヒビキ",
        "localizations": {"en": "Nekozuka Hibiki", "ja": "猫塚ヒビキ", "ko": "네코즈카 히비키"},
        "aliases": [
            "Nekozuka Hibiki", "nekozuka_hibiki_(blue_archive)",
            "猫塚ヒビキ", "네코즈카 히비키",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "十六夜ノノミ",
        "localizations": {"en": "Izayoi Nonomi", "ja": "十六夜ノノミ", "ko": "이자요이 노노미"},
        "aliases": [
            "Nonomi", "ノノミ", "Izayoi Nonomi", "izayoi_nonomi_(blue_archive)",
            "十六夜ノノミ", "노노미", "이자요이 노노미",
            "ノノミ(ブルーアーカイブ)",  # series disambiguator
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "七神リン",
        "localizations": {"en": "Nanagami Rin", "ja": "七神リン", "ko": "나나카미 린"},
        "aliases": [
            "Rin", "リン", "Nanagami Rin", "nanagami_rin_(blue_archive)",
            "七神リン", "린", "나나카미 린",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "桐藤ナギサ",
        "localizations": {"en": "Kiritou Nagisa", "ja": "桐藤ナギサ", "ko": "키리토 나기사"},
        "aliases": [
            "Nagisa", "ナギサ", "Kiritou Nagisa", "kiritou_nagisa_(blue_archive)",
            "桐藤ナギサ", "나기사", "키리토 나기사",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "京極サツキ",
        "localizations": {"en": "Kyogoku Satsuki", "ja": "京極サツキ", "ko": "쿄고쿠 사츠키"},
        "aliases": [
            "Satsuki", "サツキ", "Kyogoku Satsuki", "kyogoku_satsuki_(blue_archive)",
            "京極サツキ", "사츠키", "쿄고쿠 사츠키",
            "サツキ(ブルーアーカイブ)",  # series disambiguator
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "夜桜キララ",
        "localizations": {"en": "Yozakura Kirara", "ja": "夜桜キララ", "ko": "요자쿠라 키라라"},
        "aliases": [
            "Kirara", "キララ", "Yozakura Kirara", "yozakura_kirara_(blue_archive)",
            "夜桜キララ", "키라라", "요자쿠라 키라라",
            "キララ(ブルーアーカイブ)",  # series disambiguator
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "竜華キサキ",
        "localizations": {"en": "Ryuka Kisaki", "ja": "竜華キサキ", "ko": "류카 키사키"},
        "aliases": [
            "Kisaki", "キサキ", "Ryuka Kisaki", "ryuka_kisaki_(blue_archive)",
            "竜華キサキ", "키사키", "류카 키사키",
            "キサキ(ブルーアーカイブ)",  # series disambiguator
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "下江コハル",
        "localizations": {"en": "Shimoe Koharu", "ja": "下江コハル", "ko": "시모에 코하루"},
        "aliases": [
            "Koharu", "コハル", "Shimoe Koharu", "shimoe_koharu_(blue_archive)",
            "下江コハル", "코하루", "시모에 코하루",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "鷲見セリナ",
        "localizations": {"en": "Washimi Serina", "ja": "鷲見セリナ", "ko": "와시미 세리나"},
        "aliases": [
            "Serina", "セリナ", "Washimi Serina", "washimi_serina_(blue_archive)",
            "鷲見セリナ", "세리나", "와시미 세리나",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "河和シズコ",
        "localizations": {"en": "Kawawa Shizuko", "ja": "河和シズコ", "ko": "카와와 시즈코"},
        "aliases": [
            "Shizuko", "シズコ", "Kawawa Shizuko", "kawawa_shizuko_(blue_archive)",
            "河和シズコ", "시즈코", "카와와 시즈코",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "天雨アコ",
        "localizations": {"en": "Amamiya Ako", "ja": "天雨アコ", "ko": "아마미야 아코"},
        "aliases": [
            "Ako", "アコ", "Amamiya Ako", "amamiya_ako_(blue_archive)",
            "天雨アコ", "아코", "아마미야 아코",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "歌住サクラコ",
        "localizations": {"en": "Utasumi Sakurako", "ja": "歌住サクラコ", "ko": "우타스미 사쿠라코"},
        "aliases": [
            "Sakurako", "サクラコ", "Utasumi Sakurako", "utasumi_sakurako_(blue_archive)",
            "歌住サクラコ", "사쿠라코", "우타스미 사쿠라코",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "花岡ユズ",
        "localizations": {"en": "Hanaoka Yuzu", "ja": "花岡ユズ", "ko": "하나오카 유즈"},
        "aliases": [
            "Yuzu", "ユズ", "Hanaoka Yuzu", "hanaoka_yuzu_(blue_archive)",
            "花岡ユズ", "유즈", "하나오카 유즈",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "春日ツバキ",
        "localizations": {"en": "Kasuga Tsubaki", "ja": "春日ツバキ", "ko": "카스가 츠바키"},
        "aliases": [
            "ツバキ", "Kasuga Tsubaki", "kasuga_tsubaki_(blue_archive)",
            "春日ツバキ", "츠바키", "카스가 츠바키",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "牛牧ジュリ",
        "localizations": {"en": "Ushimaki Juri", "ja": "牛牧ジュリ", "ko": "우시마키 주리"},
        "aliases": [
            "Juri", "ジュリ", "Ushimaki Juri", "ushimaki_juri_(blue_archive)",
            "牛牧ジュリ", "주리", "우시마키 주리",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "佐城トモエ",
        "localizations": {"en": "Sajo Tomoe", "ja": "佐城トモエ", "ko": "사죠 토모에"},
        "aliases": [
            "Tomoe", "トモエ", "Sajo Tomoe", "sajo_tomoe_(blue_archive)",
            "佐城トモエ", "토모에", "사죠 토모에",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "柚鳥ナツ",
        "localizations": {"en": "Yudori Natsu", "ja": "柚鳥ナツ", "ko": "유도리 나츠"},
        "aliases": [
            "Natsu", "ナツ", "Yudori Natsu", "yudori_natsu_(blue_archive)",
            "柚鳥ナツ", "나츠", "유도리 나츠",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "栗村アイリ",
        "localizations": {"en": "Kurimura Airi", "ja": "栗村アイリ", "ko": "쿠리무라 아이리"},
        "aliases": [
            "Airi", "アイリ", "Kurimura Airi", "kurimura_airi_(blue_archive)",
            "栗村アイリ", "아이리", "쿠리무라 아이리",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "阿慈谷ヒフミ",
        "localizations": {"en": "Azaiya Hifumi", "ja": "阿慈谷ヒフミ", "ko": "아자이야 히후미"},
        "aliases": [
            "Hifumi", "ヒフミ", "Azaiya Hifumi", "azaiya_hifumi_(blue_archive)",
            "阿慈谷ヒフミ", "히후미", "아자이야 히후미",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "剣先ツルギ",
        "localizations": {"en": "Kensaki Tsurugi", "ja": "剣先ツルギ", "ko": "켄사키 츠루기"},
        "aliases": [
            "Tsurugi", "ツルギ", "Kensaki Tsurugi", "kensaki_tsurugi_(blue_archive)",
            "剣先ツルギ", "츠루기", "켄사키 츠루기",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "静山マシロ",
        "localizations": {"en": "Shizuyama Mashiro", "ja": "静山マシロ", "ko": "시즈야마 마시로"},
        "aliases": [
            "Mashiro", "マシロ", "Shizuyama Mashiro", "shizuyama_mashiro_(blue_archive)",
            "静山マシロ", "마시로", "시즈야마 마시로",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "旗見エリカ",
        "localizations": {"en": "Hatami Erika", "ja": "旗見エリカ", "ko": "하타미 에리카"},
        "aliases": [
            "Erika", "エリカ", "Hatami Erika", "hatami_erika_(blue_archive)",
            "旗見エリカ", "에리카", "하타미 에리카",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "伊原木ヨシミ",
        "localizations": {"en": "Ibaraki Yoshimi", "ja": "伊原木ヨシミ", "ko": "이바라키 요시미"},
        "aliases": [
            "Yoshimi", "ヨシミ", "Ibaraki Yoshimi", "ibaraki_yoshimi_(blue_archive)",
            "伊原木ヨシミ", "요시미", "이바라키 요시미",
        ],
        "parent_series": "Blue Archive",
    },
    # --- v2 additions (from classification_failures_20260427T114343Z.txt) ---
    {
        "canonical": "仲正イチカ",
        "localizations": {"en": "Nakasei Ichika", "ja": "仲正イチカ", "ko": "나카세이 이치카"},
        "aliases": [
            "Ichika", "イチカ", "Nakasei Ichika", "nakasei_ichika_(blue_archive)",
            "仲正イチカ", "이치카", "나카세이 이치카",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "浦和ハナコ",
        "localizations": {"en": "Urawa Hanako", "ja": "浦和ハナコ", "ko": "우라와 하나코"},
        "aliases": [
            "Hanako", "ハナコ", "Urawa Hanako", "urawa_hanako_(blue_archive)",
            "浦和ハナコ", "하나코", "우라와 하나코",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "春原シュン",
        "localizations": {"en": "Haruhara Shun", "ja": "春原シュン", "ko": "하루하라 슌"},
        "aliases": [
            "Shun", "シュン", "Haruhara Shun", "haruhara_shun_(blue_archive)",
            "春原シュン", "슌", "하루하라 슌",
        ],
        "parent_series": "Blue Archive",
    },
    {
        "canonical": "伊落マリー",
        "localizations": {"en": "Iochi Marie", "ja": "伊落マリー", "ko": "이오치 마리"},
        "aliases": [
            "Marie", "マリー", "Iochi Marie", "iochi_marie_(blue_archive)",
            "伊落マリー", "마리", "이오치 마리",
        ],
        "parent_series": "Blue Archive",
    },
]


# ===========================================================================
# TXT Parser
# ===========================================================================

_POPULAR_RE = re.compile(r"^(.+?)[\s　]?\d+users入り$")


def parse_failure_txt(text: str) -> dict:
    """Parse a classification failure TXT report into structured data.

    Returns:
        {
            "summary": {"failed_groups": int, "unique_raw_tags": int, "generated_at": str},
            "frequent_tags": [{"tag": str, "count": int}, ...],
            "failed_files": [
                {
                    "file_name": str,
                    "rule_type": str,
                    "title": str,
                    "artist": str,
                    "raw_tags": [str, ...],
                    "debug_notes": [str, ...],
                },
                ...
            ],
        }
    """
    lines = text.splitlines()
    result: dict = {
        "summary": {},
        "frequent_tags": [],
        "failed_files": [],
    }

    section: str = ""
    current_file: dict | None = None
    current_list: str = ""

    for line in lines:
        s = line.strip()

        if s == "## Summary":
            section = "summary"
            current_list = ""
        elif s == "## Frequent Unknown Tags":
            section = "frequent"
            current_list = ""
        elif s == "## Failed Files":
            if current_file is not None:
                result["failed_files"].append(current_file)
                current_file = None
            section = "files"
            current_list = ""
        elif s.startswith("### ") and section == "files":
            if current_file is not None:
                result["failed_files"].append(current_file)
            current_file = {
                "file_name": s[4:].strip(),
                "rule_type": "",
                "title": "",
                "artist": "",
                "raw_tags": [],
                "debug_notes": [],
            }
            current_list = ""
        elif section == "summary":
            m = re.match(r"^-\s+(.+?):\s+(.+)$", s)
            if m:
                key = m.group(1).strip().replace(" ", "_")
                val = m.group(2).strip()
                result["summary"][key] = val
        elif section == "frequent":
            m = re.match(r"^\d+\.\s+(.+?)\s+—\s+(\d+)\s+files?$", s)
            if m:
                result["frequent_tags"].append({
                    "tag": m.group(1),
                    "count": int(m.group(2)),
                })
        elif section == "files" and current_file is not None:
            if s.startswith("rule_type:"):
                current_list = ""
                current_file["rule_type"] = s[len("rule_type:"):].strip()
            elif s.startswith("title:"):
                current_list = ""
                current_file["title"] = s[len("title:"):].strip()
            elif s.startswith("artist:"):
                current_list = ""
                current_file["artist"] = s[len("artist:"):].strip()
            elif s == "raw_tags:":
                current_list = "raw_tags"
            elif s == "debug_notes:":
                current_list = "debug_notes"
            elif s.startswith("- ") and current_list:
                current_file[current_list].append(s[2:])

    if current_file is not None:
        result["failed_files"].append(current_file)

    # Coerce numeric summary fields
    for key in ("failed_groups", "unique_raw_tags"):
        if key in result["summary"]:
            try:
                result["summary"][key] = int(result["summary"][key])
            except (ValueError, TypeError):
                pass

    return result


# ===========================================================================
# Patch logic
# ===========================================================================

def _dedup_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            result.append(x)
    return result


def _build_canonical_index(characters: list[dict]) -> dict[str, int]:
    return {entry["canonical"]: i for i, entry in enumerate(characters)}


def apply_failure_patch(pack: dict, config: dict) -> tuple[dict, dict]:
    """Apply patch data to a tag pack.

    config keys (all optional):
        characters_to_add   list[dict] | None — override _PATCH_CHARACTERS
        variant_merges      dict | None — override _VARIANT_MERGES_FROM_FAILURES
        series_disambiguators dict | None — override _SERIES_DISAMBIGUATORS
        skip_existing       bool (default True) — skip if canonical already in pack

    Returns (patched_pack, report).
    """
    characters_to_add: list[dict] = config.get("characters_to_add") or _PATCH_CHARACTERS
    variant_merges: dict[str, dict] = config.get("variant_merges") or _VARIANT_MERGES_FROM_FAILURES
    series_disambiguators: dict[str, str] = (
        config.get("series_disambiguators") or _SERIES_DISAMBIGUATORS
    )
    skip_existing: bool = config.get("skip_existing", True)

    report: dict = {
        "summary": {
            "characters_added": 0,
            "characters_skipped_existing": 0,
            "variant_aliases_merged": 0,
            "series_disambiguator_aliases_added": 0,
        },
        "added": [],
        "skipped": [],
        "variant_merges": [],
        "series_disambiguators": [],
        "warnings": [],
    }

    now = datetime.now(timezone.utc).isoformat()
    characters: list[dict] = list(pack.get("characters", []))
    canonical_index = _build_canonical_index(characters)

    # 1. Add new characters
    for char_data in characters_to_add:
        canonical: str = char_data["canonical"]

        if skip_existing and canonical in canonical_index:
            report["skipped"].append({
                "canonical": canonical,
                "reason": "already_exists",
            })
            report["summary"]["characters_skipped_existing"] += 1
            continue

        aliases: list[str] = _dedup_ordered(list(char_data.get("aliases", [])))
        # Ensure canonical is in aliases
        if canonical not in aliases:
            aliases.insert(0, canonical)

        entry: dict = {
            "aliases": aliases,
            "canonical": canonical,
            "localizations": dict(char_data.get("localizations", {})),
            "parent_series": char_data.get("parent_series", ""),
        }

        characters.append(entry)
        canonical_index[canonical] = len(characters) - 1

        report["added"].append({
            "canonical": canonical,
            "parent_series": entry["parent_series"],
            "aliases_count": len(aliases),
        })
        report["summary"]["characters_added"] += 1

    # 2. Merge variant aliases into base characters
    for variant_tag, merge_info in variant_merges.items():
        base_canonical: str = merge_info["base_canonical"]
        variant_type: str = merge_info.get("variant", "")

        idx = canonical_index.get(base_canonical)
        if idx is None:
            report["warnings"].append({
                "type": "variant_merge_base_not_found",
                "variant_tag": variant_tag,
                "base_canonical": base_canonical,
            })
            continue

        entry = characters[idx]
        base_aliases: list[str] = list(entry.get("aliases", []))
        if variant_tag not in base_aliases:
            base_aliases.append(variant_tag)
            entry["aliases"] = _dedup_ordered(base_aliases)

            review = entry.setdefault("_review", {})
            review.setdefault("merged_variants", []).append({
                "source_tag": variant_tag,
                "variant": variant_type,
                "reason": "costume/variant tag merged into base character from failure report",
            })

            report["variant_merges"].append({
                "variant_tag": variant_tag,
                "into": base_canonical,
                "variant": variant_type,
            })
            report["summary"]["variant_aliases_merged"] += 1

    # 3. Series disambiguators → already embedded in aliases for each character above.
    #    Record them in the report for traceability.
    for disambig_tag, target_canonical in series_disambiguators.items():
        idx = canonical_index.get(target_canonical)
        if idx is None:
            report["warnings"].append({
                "type": "series_disambiguator_target_not_found",
                "disambig_tag": disambig_tag,
                "target_canonical": target_canonical,
            })
            continue

        entry = characters[idx]
        if disambig_tag in entry.get("aliases", []):
            report["series_disambiguators"].append({
                "tag": disambig_tag,
                "resolved_to": target_canonical,
                "status": "present",
            })
            report["summary"]["series_disambiguator_aliases_added"] += 1

    patched_pack: dict = {
        "pack_id": pack.get("pack_id", "tag_pack_export"),
        "name": pack.get("name", "Tag Pack Export"),
        "version": pack.get("version", "1.0.0"),
        "source": "failure_patched",
        "series": list(pack.get("series", [])),
        "characters": characters,
        "exported_at": pack.get("exported_at", ""),
        "enriched_at": pack.get("enriched_at", ""),
        "patched_at": now,
    }

    return patched_pack, report


# ===========================================================================
# Failure report analysis (title-only candidates)
# ===========================================================================

def analyze_failure_report(parsed: dict) -> dict:
    """Identify title-only candidates and other observations from a parsed report.

    Title-only candidate: artwork whose title contains a known character name
    but has no raw_tags that match. These are report-only; never auto-confirmed.

    Returns {
        "title_only_candidates": [{"file_name", "title", "artist", "candidate_name"}, ...],
        "popularity_tags_observed": [str, ...],
        "group_tags_observed": [str, ...],
        "general_tags_observed": [str, ...],
    }
    """
    patch_canonicals: set[str] = {c["canonical"] for c in _PATCH_CHARACTERS}
    patch_short_aliases: set[str] = set()
    for c in _PATCH_CHARACTERS:
        for a in c.get("aliases", []):
            if len(a) <= 6 and re.search(r"[぀-ヿ一-鿿]", a):
                patch_short_aliases.add(a)

    title_only: list[dict] = []
    popularity_observed: list[str] = []
    group_observed: list[str] = []
    general_observed: list[str] = []

    popularity_re = re.compile(r"^.+?\d+users入り$")
    seen_pop: set[str] = set()
    seen_group: set[str] = set()
    seen_gen: set[str] = set()

    for item in parsed.get("failed_files", []):
        raw_tags: list[str] = item.get("raw_tags", [])
        title: str = item.get("title", "")

        # Classify raw tags
        for tag in raw_tags:
            if popularity_re.match(tag) and tag not in seen_pop:
                popularity_observed.append(tag)
                seen_pop.add(tag)
            elif tag in _GROUP_TAGS and tag not in seen_group:
                group_observed.append(tag)
                seen_group.add(tag)
            elif tag in _GENERAL_TAGS and tag not in seen_gen:
                general_observed.append(tag)
                seen_gen.add(tag)

        # Title-only detection: title mentions a known canonical/alias but raw_tags don't
        raw_tag_set = set(raw_tags)
        if not raw_tag_set.intersection(patch_canonicals | patch_short_aliases):
            for name in patch_canonicals | patch_short_aliases:
                if name and name in title:
                    title_only.append({
                        "file_name": item["file_name"],
                        "title": title,
                        "artist": item.get("artist", ""),
                        "candidate_name": name,
                    })
                    break

    return {
        "title_only_candidates": title_only,
        "popularity_tags_observed": popularity_observed,
        "group_tags_observed": group_observed,
        "general_tags_observed": general_observed,
    }


# ===========================================================================
# v2 report builder
# ===========================================================================

def build_v2_report(patch_report: dict, failure_analysis: dict) -> dict:
    """Transform internal patch_report into the v2 public report format."""
    added = patch_report.get("added", [])
    variant_merges = patch_report.get("variant_merges", [])
    gen_observed: list[str] = failure_analysis.get("general_tags_observed", [])
    group_observed: list[str] = failure_analysis.get("group_tags_observed", [])

    aliases_added: list[dict] = []
    for vm in variant_merges:
        aliases_added.append({
            "canonical": vm["into"],
            "alias_added": vm["variant_tag"],
            "reason": f"variant costume/form tag merged into base character ({vm['variant']})",
        })
    for sd in patch_report.get("series_disambiguators", []):
        if sd.get("status") == "present":
            aliases_added.append({
                "canonical": sd["resolved_to"],
                "alias_added": sd["tag"],
                "reason": "series disambiguator alias already present in character entry",
            })

    return {
        "summary": {
            "characters_added": patch_report["summary"]["characters_added"],
            "aliases_added": len(aliases_added),
            "canonical_changed": 0,
            "variants_merged": patch_report["summary"]["variant_aliases_merged"],
            "web_verified_items": len(_WEB_EVIDENCE_V2),
            "needs_review": len(_NEEDS_REVIEW_V2),
            "ignored_general_tags": len(gen_observed) + len(group_observed),
        },
        "characters_added": added,
        "aliases_added": aliases_added,
        "variants_merged": variant_merges,
        "web_evidence": _WEB_EVIDENCE_V2,
        "needs_review": _NEEDS_REVIEW_V2,
        "ignored_general_tags": gen_observed + group_observed,
        "title_only_candidates": failure_analysis.get("title_only_candidates", []),
        "warnings": patch_report.get("warnings", []),
    }


# ===========================================================================
# CLI
# ===========================================================================

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Failure Report Tag Pack Patch Tool")
    parser.add_argument(
        "--tag-pack", "-p",
        default="docs/tag_pack_export_localized_ko_ja_enriched.json",
        help="입력 tag pack JSON",
    )
    parser.add_argument(
        "--failure-report", "-f",
        default=None,
        help="분류 실패 TXT 파일 (없으면 patch data만 적용)",
    )
    parser.add_argument(
        "--output", "-o",
        default="docs/tag_pack_export_localized_ko_ja_failure_patch.json",
        help="출력 patched pack JSON",
    )
    parser.add_argument(
        "--report", "-r",
        default=None,
        help="패치 보고서 JSON (기본: --output 기반 _report.json)",
    )
    args = parser.parse_args()

    pack_path = Path(args.tag_pack)
    if not pack_path.exists():
        print(f"[ERROR] tag pack 파일 없음: {pack_path}", file=sys.stderr)
        return 1

    print(f"[INFO] 입력: {pack_path}")
    with open(pack_path, encoding="utf-8") as f:
        pack = json.load(f)
    print(f"[INFO]   characters: {len(pack.get('characters', []))}")

    # Parse failure report if provided
    failure_analysis: dict = {}
    if args.failure_report:
        report_path = Path(args.failure_report)
        if not report_path.exists():
            print(f"[ERROR] failure report 파일 없음: {report_path}", file=sys.stderr)
            return 1
        print(f"[INFO] failure report: {report_path}")
        with open(report_path, encoding="utf-8") as f:
            failure_text = f.read()
        parsed_failures = parse_failure_txt(failure_text)
        failure_analysis = analyze_failure_report(parsed_failures)
        summary = parsed_failures.get("summary", {})
        print(f"[INFO]   failed_groups: {summary.get('failed_groups', '?')}")
        print(f"[INFO]   unique_raw_tags: {summary.get('unique_raw_tags', '?')}")
        print(f"[INFO]   title_only_candidates: {len(failure_analysis['title_only_candidates'])}")

    # Apply patch
    patched_pack, patch_report = apply_failure_patch(pack, {})

    # Build v2 report with standardized fields
    v2_report = build_v2_report(patch_report, failure_analysis)

    s = v2_report["summary"]
    print("\n[INFO] Patch summary (v2):")
    print(f"  characters_added:      {s['characters_added']}")
    print(f"  aliases_added:         {s['aliases_added']}")
    print(f"  variants_merged:       {s['variants_merged']}")
    print(f"  web_verified_items:    {s['web_verified_items']}")
    print(f"  needs_review:          {s['needs_review']}")
    print(f"  ignored_general_tags:  {s['ignored_general_tags']}")
    print(f"  total characters out:  {len(patched_pack['characters'])}")

    # Write outputs
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(patched_pack, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] 출력: {output_path}")

    report_out = args.report or str(output_path).replace(".json", "_report.json")
    report_path_out = Path(report_out)
    with open(report_path_out, "w", encoding="utf-8") as f:
        json.dump(v2_report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 보고서: {report_path_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
