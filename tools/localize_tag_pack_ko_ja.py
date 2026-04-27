from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "docs" / "tag_pack_export.json"
OUTPUT_PATH = ROOT / "docs" / "tag_pack_export_localized_ko_ja.json"


Localization = dict[str, str]


# Conservative hand-curated additions. Existing localizations are never replaced.
BLUE_ARCHIVE_LOCALIZATIONS: dict[tuple[str, str], Localization] = {
    ("Blue Archive", "Akari"): {"ja": "鰐渕アカリ", "ko": "와니부치 아카리"},
    ("Blue Archive", "Akira"): {"ja": "清澄アキラ", "ko": "키요스미 아키라"},
    ("Blue Archive", "Arona"): {"ja": "アロナ", "ko": "아로나"},
    ("Blue Archive", "Aru"): {"ja": "陸八魔アル", "ko": "리쿠하치마 아루"},
    ("Blue Archive", "Asuna"): {"ja": "一之瀬アスナ", "ko": "이치노세 아스나"},
    ("Blue Archive", "Ayane"): {"ja": "奥空アヤネ", "ko": "오쿠소라 아야네"},
    ("Blue Archive", "Azusa"): {"ja": "白洲アズサ", "ko": "시라스 아즈사"},
    ("Blue Archive", "Black Suit"): {"ja": "黒服", "ko": "검은 양복"},
    ("Blue Archive", "Chihiro"): {"ja": "各務チヒロ", "ko": "카가미 치히로"},
    ("Blue Archive", "Chinatsu"): {"ja": "火宮チナツ", "ko": "히노미야 치나츠"},
    ("Blue Archive", "Hanae"): {"ja": "朝顔ハナエ", "ko": "아사가오 하나에"},
    ("Blue Archive", "Hare"): {"ja": "小鈎ハレ", "ko": "오마가리 하레"},
    ("Blue Archive", "Haruka"): {"ja": "伊草ハルカ", "ko": "이구사 하루카"},
    ("Blue Archive", "Haruna"): {"ja": "黒舘ハルナ", "ko": "쿠로다테 하루나"},
    ("Blue Archive", "Himari"): {"ja": "明星ヒマリ", "ko": "아케보시 히마리"},
    ("Blue Archive", "Hina"): {"ja": "空崎ヒナ", "ko": "소라사키 히나"},
    ("Blue Archive", "Hinata"): {"ja": "若葉ヒナタ", "ko": "와카바 히나타"},
    ("Blue Archive", "Hoshino"): {"ja": "小鳥遊ホシノ", "ko": "타카나시 호시노"},
    ("Blue Archive", "Ibuki"): {"ja": "丹花イブキ", "ko": "탄가 이부키"},
    ("Blue Archive", "Izumi"): {"ja": "獅子堂イズミ", "ko": "시시도우 이즈미"},
    ("Blue Archive", "Izuna"): {"ja": "久田イズナ", "ko": "쿠다 이즈나"},
    ("Blue Archive", "Junko"): {"ja": "赤司ジュンコ", "ko": "아카시 준코"},
    ("Blue Archive", "Kaya"): {"ja": "不知火カヤ", "ko": "시라누이 카야"},
    ("Blue Archive", "Kayoko"): {"ja": "鬼方カヨコ", "ko": "오니카타 카요코"},
    ("Blue Archive", "Kazusa"): {"ja": "杏山カズサ", "ko": "쿄야마 카즈사"},
    ("Blue Archive", "Kikyou"): {"ja": "桐生キキョウ", "ko": "키류 키쿄"},
    ("Blue Archive", "Kirino"): {"ja": "中務キリノ", "ko": "나카츠카사 키리노"},
    ("Blue Archive", "Kokona"): {"ja": "春原ココナ", "ko": "스노하라 코코나"},
    ("Blue Archive", "Kotama"): {"ja": "音瀬コタマ", "ko": "오토세 코타마"},
    ("Blue Archive", "Maki"): {"ja": "小塗マキ", "ko": "코누리 마키"},
    ("Blue Archive", "Makoto"): {"ja": "羽沼マコト", "ko": "하누마 마코토"},
    ("Blue Archive", "Mari"): {"ja": "伊落マリー", "ko": "이오치 마리"},
    ("Blue Archive", "Midori"): {"ja": "才羽ミドリ", "ko": "사이바 미도리"},
    ("Blue Archive", "Mika"): {"ja": "聖園ミカ", "ko": "미소노 미카"},
    ("Blue Archive", "Mine"): {"ja": "蒼森ミネ", "ko": "아오모리 미네"},
    ("Blue Archive", "Miyako"): {"ja": "月雪ミヤコ", "ko": "츠키유키 미야코"},
    ("Blue Archive", "Miyu"): {"ja": "霞沢ミユ", "ko": "카스미자와 미유"},
    ("Blue Archive", "Moe"): {"ja": "風倉モエ", "ko": "카자쿠라 모에"},
    ("Blue Archive", "Momoi"): {"ja": "才羽モモイ", "ko": "사이바 모모이"},
    ("Blue Archive", "Mutsuki"): {"ja": "浅黄ムツキ", "ko": "아사기 무츠키"},
    ("Blue Archive", "Nagusa"): {"ja": "御稜ナグサ", "ko": "미사사기 나구사"},
    ("Blue Archive", "Noa"): {"ja": "生塩ノア", "ko": "우시오 노아"},
    ("Blue Archive", "Plana"): {"ja": "プラナ", "ko": "프라나"},
    ("Blue Archive", "Reisa"): {"ja": "宇沢レイサ", "ko": "우자와 레이사"},
    ("Blue Archive", "Renge"): {"ja": "不破レンゲ", "ko": "후와 렌게"},
    ("Blue Archive", "Saori"): {"ja": "錠前サオリ", "ko": "조마에 사오리"},
    ("Blue Archive", "Saki"): {"ja": "空井サキ", "ko": "소라이 사키"},
    ("Blue Archive", "Sena"): {"ja": "氷室セナ", "ko": "히무로 세나"},
    ("Blue Archive", "Sensei"): {"ja": "先生", "ko": "선생"},
    ("Blue Archive", "Shiroko"): {"ja": "砂狼シロコ", "ko": "스나오오카미 시로코"},
    ("Blue Archive", "Suzumi"): {"ja": "守月スズミ", "ko": "모리츠키 스즈미"},
    ("Blue Archive", "Ui"): {"ja": "古関ウイ", "ko": "코제키 우이"},
    ("Blue Archive", "Yukari"): {"ja": "勘解由小路ユカリ", "ko": "카데노코지 유카리"},
    ("Blue Archive", "Yuuka"): {"ja": "早瀬ユウカ", "ko": "하야세 유우카"},
    ("Blue Archive", "各務チヒロ"): {"ja": "各務チヒロ", "ko": "카가미 치히로"},
    ("Blue Archive", "明星ヒマリ"): {"ja": "明星ヒマリ", "ko": "아케보시 히마리"},
}


VARIANT_LOCALIZATIONS: dict[tuple[str, str], tuple[str, Localization]] = {
    ("Blue Archive", "Hina (dress)"): (
        "Hina",
        {"ja": "空崎ヒナ（ドレス）", "ko": "소라사키 히나(드레스)"},
    ),
    ("Blue Archive", "Hina (pajamas)"): (
        "Hina",
        {"ja": "空崎ヒナ（パジャマ）", "ko": "소라사키 히나(잠옷)"},
    ),
    ("Blue Archive", "Hina (swimsuit)"): (
        "Hina",
        {"ja": "空崎ヒナ（水着）", "ko": "소라사키 히나(수영복)"},
    ),
    ("Blue Archive", "Mari (idol)"): (
        "Mari",
        {"ja": "伊落マリー（アイドル）", "ko": "이오치 마리(아이돌)"},
    ),
    ("Blue Archive", "Midori (maid)"): (
        "Midori",
        {"ja": "才羽ミドリ（メイド）", "ko": "사이바 미도리(메이드)"},
    ),
    ("Blue Archive", "Momoi (maid)"): (
        "Momoi",
        {"ja": "才羽モモイ（メイド）", "ko": "사이바 모모이(메이드)"},
    ),
    ("Blue Archive", "Chihiro (pajamas)"): (
        "Chihiro",
        {"ja": "各務チヒロ（パジャマ）", "ko": "카가미 치히로(잠옷)"},
    ),
    ("Blue Archive", "伊落マリー(体操服)"): (
        "伊落マリー",
        {"ja": "伊落マリー（体操服）", "ko": "이오치 마리(체육복)"},
    ),
    ("Blue Archive", "愛清フウカ(正月)"): (
        "愛清フウカ",
        {"ja": "愛清フウカ（正月）", "ko": "아이키요 후우카(새해)"},
    ),
    ("Blue Archive", "フウカ(正月)"): (
        "愛清フウカ",
        {"ja": "愛清フウカ（正月）", "ko": "아이키요 후우카(새해)"},
    ),
}


VARIANT_REVIEW_ONLY: dict[tuple[str, str], str] = {
    ("Blue Archive", "Kei (new Body)"): "Kei",
}


MERGE_CANDIDATES: dict[tuple[str, str], str] = {
    ("Blue Archive", "Aru"): "陸八魔アル",
    ("Blue Archive", "Azusa"): "白洲アズサ",
    ("Blue Archive", "Chihiro"): "各務チヒロ",
    ("Blue Archive", "Himari"): "明星ヒマリ",
    ("Blue Archive", "Hoshino"): "小鳥遊ホシノ",
    ("Blue Archive", "Mari"): "伊落マリー",
}


GROUP_TAGS = {
    ("Blue Archive", "Gourmet Research Society"): "group",
    ("Blue Archive", "Problem Solver 68"): "group",
    ("Blue Archive", "Rabbit Platoon"): "group",
    ("Blue Archive", "Veritas"): "group",
    ("Blue Archive", "Occult Studies Club"): "group",
    ("Blue Archive", "Justice Task Force Member"): "group",
}


GENERAL_TAGS = {
    ("Blue Archive", "タイツ"): "general",
    ("Blue Archive", "メガネ"): "general",
    ("Blue Archive", "白タイツ"): "general",
}


NIKKE_KO_TRANSLITERATIONS: dict[tuple[str, str], str] = {
    ("Nikke", "Belorta"): "벨로타",
    ("Nikke", "Liliweiss"): "릴리바이스",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(data: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def ensure_review(entry: dict[str, Any]) -> dict[str, Any]:
    review = entry.get("_review")
    if not isinstance(review, dict):
        review = {}
        entry["_review"] = review
    return review


def add_missing_localizations(entry: dict[str, Any], values: Localization) -> dict[str, int]:
    locs = entry.setdefault("localizations", {})
    added = {"ko": 0, "ja": 0}
    for locale in ("ko", "ja"):
        if locale in values and locale not in locs:
            locs[locale] = values[locale]
            added[locale] += 1
    return added


def mark_merge_candidate(entry: dict[str, Any], candidate: str, reason: str) -> None:
    review = ensure_review(entry)
    review.setdefault("merge_candidate", candidate)
    review.setdefault("preferred_canonical", candidate)
    review.setdefault("preferred_canonical_rule", "ja_full_name > ko_full_name > en")
    review.setdefault("reason", reason)
    review["match_method"] = review.get("match_method", "known_alias_or_normalized_like")
    review["needs_merge_review"] = True


def mark_localization_check(entry: dict[str, Any], reason: str) -> None:
    review = ensure_review(entry)
    review["needs_localization_check"] = True
    review.setdefault("reason", reason)


def mark_group_or_general(entry: dict[str, Any], suggested_type: str) -> None:
    review = ensure_review(entry)
    review["possibly_general_or_group_tag"] = True
    review["suggested_tag_type"] = suggested_type
    if suggested_type == "group":
        review.setdefault(
            "reason",
            "appears to be a group/faction tag rather than an individual character",
        )
    else:
        review.setdefault(
            "reason",
            "appears to be a general attribute tag rather than a character",
        )


def mark_variant(entry: dict[str, Any], base_candidate: str) -> None:
    review = ensure_review(entry)
    review["variant_tag"] = True
    review["base_character_candidate"] = base_candidate
    review.setdefault(
        "reason",
        "costume/variant tag; should usually be merged into base character for folder classification",
    )


def is_japanese_full_name(value: str) -> bool:
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in value)
    has_kana = any("\u30a0" <= ch <= "\u30ff" for ch in value)
    return has_cjk and has_kana


def validate_invariants(before: dict[str, Any], after: dict[str, Any]) -> None:
    if len(before.get("characters", [])) != len(after.get("characters", [])):
        raise AssertionError("characters count changed")
    if len(before.get("series", [])) != len(after.get("series", [])):
        raise AssertionError("series count changed")

    for section in ("characters", "series"):
        before_items = before.get(section, [])
        after_items = after.get(section, [])
        for index, (old, new) in enumerate(zip(before_items, after_items)):
            for field in ("canonical", "parent_series"):
                if old.get(field) != new.get(field):
                    raise AssertionError(f"{section}[{index}].{field} changed")
            old_aliases = old.get("aliases", [])
            new_aliases = new.get("aliases", [])
            if len(new_aliases) < len(old_aliases):
                raise AssertionError(f"{section}[{index}] aliases were removed")
            if old_aliases != new_aliases[: len(old_aliases)]:
                raise AssertionError(f"{section}[{index}] aliases order/content changed")
            old_locs = old.get("localizations", {})
            new_locs = new.get("localizations", {})
            for locale in ("en", "ko", "ja"):
                if locale in old_locs and new_locs.get(locale) != old_locs[locale]:
                    raise AssertionError(f"{section}[{index}] {locale} localization overwritten")


def summarize(data: dict[str, Any], original: dict[str, Any], added: dict[str, int]) -> dict[str, int]:
    characters = data.get("characters", [])
    original_existing = 0
    review_count = 0
    group_general = 0
    variants = 0
    merge_candidates = 0
    ambiguous = 0
    for before, after in zip(original.get("characters", []), characters):
        original_existing += sum(1 for locale in ("ko", "ja") if locale in before.get("localizations", {}))
        review = after.get("_review", {})
        if review:
            review_count += 1
        if review.get("possibly_general_or_group_tag"):
            group_general += 1
        if review.get("variant_tag"):
            variants += 1
        if review.get("needs_merge_review") or review.get("merge_candidate"):
            merge_candidates += 1
        if review.get("ambiguous_candidates"):
            ambiguous += 1
    return {
        "ko_added": added["ko"],
        "ja_added": added["ja"],
        "existing_ko_ja_preserved": original_existing,
        "review_marked": review_count,
        "group_general_suspected": group_general,
        "variant_marked": variants,
        "merge_candidate_marked": merge_candidates,
        "ambiguous_candidate_marked": ambiguous,
    }


def localize(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    out = copy.deepcopy(data)
    added = {"ko": 0, "ja": 0}

    alias_to_full_name_by_series: dict[str, dict[str, set[str]]] = {}
    for entry in out.get("characters", []):
        canonical = entry.get("canonical", "")
        if is_japanese_full_name(canonical):
            series = entry.get("parent_series", "")
            lookup = alias_to_full_name_by_series.setdefault(series, {})
            for alias in entry.get("aliases", []):
                lookup.setdefault(alias.lower(), set()).add(canonical)

    for entry in out.get("characters", []):
        series = entry.get("parent_series", "")
        canonical = entry.get("canonical", "")
        key = (series, canonical)

        if key in BLUE_ARCHIVE_LOCALIZATIONS:
            counts = add_missing_localizations(entry, BLUE_ARCHIVE_LOCALIZATIONS[key])
            added["ko"] += counts["ko"]
            added["ja"] += counts["ja"]

        if key in VARIANT_LOCALIZATIONS:
            base_candidate, values = VARIANT_LOCALIZATIONS[key]
            mark_variant(entry, base_candidate)
            counts = add_missing_localizations(entry, values)
            added["ko"] += counts["ko"]
            added["ja"] += counts["ja"]

        if key in VARIANT_REVIEW_ONLY:
            mark_variant(entry, VARIANT_REVIEW_ONLY[key])
            mark_localization_check(entry, "ko/ja variant official name not verified")

        if key in MERGE_CANDIDATES:
            mark_merge_candidate(
                entry,
                MERGE_CANDIDATES[key],
                "appears to be duplicate canonical for the same Blue Archive character",
            )

        if key in GROUP_TAGS:
            mark_group_or_general(entry, GROUP_TAGS[key])

        if key in GENERAL_TAGS:
            mark_group_or_general(entry, GENERAL_TAGS[key])

        if series in {"Trickcal", "Nikke"}:
            if series == "Nikke" and key in NIKKE_KO_TRANSLITERATIONS:
                counts = add_missing_localizations(entry, {"ko": NIKKE_KO_TRANSLITERATIONS[key]})
                added["ko"] += counts["ko"]
                mark_localization_check(entry, "ko localization is transliteration candidate")
            else:
                mark_localization_check(entry, "ko/ja official name not verified")

        if series == "Horuhara":
            mark_localization_check(entry, "fan-work or crossover tag; ko/ja official name not verified")

        if series == "Blue Archive" and "localizations" not in entry:
            mark_localization_check(entry, "ko/ja official name not verified")

        if series == "Blue Archive" and not entry.get("localizations", {}).get("ko") and not entry.get("localizations", {}).get("ja"):
            if key not in GENERAL_TAGS and key not in GROUP_TAGS and key not in VARIANT_REVIEW_ONLY:
                mark_localization_check(entry, "ko/ja official name not verified")

        # Short-name aliases that point at an existing Japanese full-name canonical remain review-only.
        matching_full_names = sorted(
            name
            for name in alias_to_full_name_by_series.get(series, {}).get(canonical.lower(), set())
            if name != canonical
        )
        if len(matching_full_names) == 1 and "merge_candidate" not in entry.get("_review", {}):
            mark_merge_candidate(
                entry,
                matching_full_names[0],
                "short-name canonical appears to match a full Japanese canonical in the same parent_series",
            )
        elif len(matching_full_names) > 1:
            review = ensure_review(entry)
            review["needs_merge_review"] = True
            review["ambiguous_candidates"] = [
                {"canonical": name, "parent_series": series} for name in sorted(matching_full_names)
            ]
            review.setdefault(
                "reason",
                "short-name alias is ambiguous across multiple candidates",
            )

    return out, added


def main() -> None:
    original = load_json(INPUT_PATH)
    localized, added = localize(original)
    validate_invariants(original, localized)
    dump_json(localized, OUTPUT_PATH)

    reloaded = load_json(OUTPUT_PATH)
    validate_invariants(original, reloaded)
    summary = summarize(reloaded, original, added)
    print("Tag pack ko/ja localization completed")
    print(f"output: {OUTPUT_PATH.relative_to(ROOT)}")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
