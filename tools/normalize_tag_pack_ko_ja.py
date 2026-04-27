from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "docs" / "tag_pack_export.json"
OUTPUT_PATH = ROOT / "docs" / "tag_pack_export_localized_ko_ja.json"
REPORT_PATH = ROOT / "docs" / "tag_pack_export_localized_ko_ja_report.json"


Localization = dict[str, str]
EntityKey = tuple[str, str]


# Conservative official-name map. Blue Archive uses the Japanese original full name as canonical.
BLUE_ARCHIVE_NAMES: dict[str, dict[str, str]] = {
    "Akari": {"canonical": "鰐渕アカリ", "ko": "와니부치 아카리", "ja": "鰐渕アカリ"},
    "Akira": {"canonical": "清澄アキラ", "ko": "키요스미 아키라", "ja": "清澄アキラ"},
    "Arona": {"canonical": "アロナ", "ko": "아로나", "ja": "アロナ"},
    "Aru": {"canonical": "陸八魔アル", "ko": "리쿠하치마 아루", "ja": "陸八魔アル"},
    "Asuna": {"canonical": "一之瀬アスナ", "ko": "이치노세 아스나", "ja": "一之瀬アスナ"},
    "Ayane": {"canonical": "奥空アヤネ", "ko": "오쿠소라 아야네", "ja": "奥空アヤネ"},
    "Azusa": {"canonical": "白洲アズサ", "ko": "시라스 아즈사", "ja": "白洲アズサ"},
    "Black Suit": {"canonical": "黒服", "ko": "검은 양복", "ja": "黒服"},
    "Chihiro": {"canonical": "各務チヒロ", "ko": "카가미 치히로", "ja": "各務チヒロ"},
    "Chinatsu": {"canonical": "火宮チナツ", "ko": "히노미야 치나츠", "ja": "火宮チナツ"},
    "Hanae": {"canonical": "朝顔ハナエ", "ko": "아사가오 하나에", "ja": "朝顔ハナエ"},
    "Hare": {"canonical": "小鈎ハレ", "ko": "오마가리 하레", "ja": "小鈎ハレ"},
    "Haruka": {"canonical": "伊草ハルカ", "ko": "이구사 하루카", "ja": "伊草ハルカ"},
    "Haruna": {"canonical": "黒舘ハルナ", "ko": "쿠로다테 하루나", "ja": "黒舘ハルナ"},
    "Himari": {"canonical": "明星ヒマリ", "ko": "아케보시 히마리", "ja": "明星ヒマリ"},
    "Hina": {"canonical": "空崎ヒナ", "ko": "소라사키 히나", "ja": "空崎ヒナ"},
    "Hinata": {"canonical": "若葉ヒナタ", "ko": "와카바 히나타", "ja": "若葉ヒナタ"},
    "Hoshino": {"canonical": "小鳥遊ホシノ", "ko": "타카나시 호시노", "ja": "小鳥遊ホシノ"},
    "Ibuki": {"canonical": "丹花イブキ", "ko": "탄가 이부키", "ja": "丹花イブキ"},
    "Izumi": {"canonical": "獅子堂イズミ", "ko": "시시도우 이즈미", "ja": "獅子堂イズミ"},
    "Izuna": {"canonical": "久田イズナ", "ko": "쿠다 이즈나", "ja": "久田イズナ"},
    "Junko": {"canonical": "赤司ジュンコ", "ko": "아카시 준코", "ja": "赤司ジュンコ"},
    "Kaya": {"canonical": "不知火カヤ", "ko": "시라누이 카야", "ja": "不知火カヤ"},
    "Kayoko": {"canonical": "鬼方カヨコ", "ko": "오니카타 카요코", "ja": "鬼方カヨコ"},
    "Kazusa": {"canonical": "杏山カズサ", "ko": "쿄야마 카즈사", "ja": "杏山カズサ"},
    "Kikyou": {"canonical": "桐生キキョウ", "ko": "키류 키쿄", "ja": "桐生キキョウ"},
    "Kirino": {"canonical": "中務キリノ", "ko": "나카츠카사 키리노", "ja": "中務キリノ"},
    "Kokona": {"canonical": "春原ココナ", "ko": "스노하라 코코나", "ja": "春原ココナ"},
    "Kotama": {"canonical": "音瀬コタマ", "ko": "오토세 코타마", "ja": "音瀬コタマ"},
    "Maki": {"canonical": "小塗マキ", "ko": "코누리 마키", "ja": "小塗マキ"},
    "Makoto": {"canonical": "羽沼マコト", "ko": "하누마 마코토", "ja": "羽沼マコト"},
    "Mari": {"canonical": "伊落マリー", "ko": "이오치 마리", "ja": "伊落マリー"},
    "Midori": {"canonical": "才羽ミドリ", "ko": "사이바 미도리", "ja": "才羽ミドリ"},
    "Mika": {"canonical": "聖園ミカ", "ko": "미소노 미카", "ja": "聖園ミカ"},
    "Mine": {"canonical": "蒼森ミネ", "ko": "아오모리 미네", "ja": "蒼森ミネ"},
    "Miyako": {"canonical": "月雪ミヤコ", "ko": "츠키유키 미야코", "ja": "月雪ミヤコ"},
    "Miyu": {"canonical": "霞沢ミユ", "ko": "카스미자와 미유", "ja": "霞沢ミユ"},
    "Moe": {"canonical": "風倉モエ", "ko": "카자쿠라 모에", "ja": "風倉モエ"},
    "Momoi": {"canonical": "才羽モモイ", "ko": "사이바 모모이", "ja": "才羽モモイ"},
    "Mutsuki": {"canonical": "浅黄ムツキ", "ko": "아사기 무츠키", "ja": "浅黄ムツキ"},
    "Nagusa": {"canonical": "御稜ナグサ", "ko": "미사사기 나구사", "ja": "御稜ナグサ"},
    "Noa": {"canonical": "生塩ノア", "ko": "우시오 노아", "ja": "生塩ノア"},
    "Plana": {"canonical": "プラナ", "ko": "프라나", "ja": "プラナ"},
    "Reisa": {"canonical": "宇沢レイサ", "ko": "우자와 레이사", "ja": "宇沢レイサ"},
    "Renge": {"canonical": "不破レンゲ", "ko": "후와 렌게", "ja": "不破レンゲ"},
    "Saori": {"canonical": "錠前サオリ", "ko": "조마에 사오리", "ja": "錠前サオリ"},
    "Saki": {"canonical": "空井サキ", "ko": "소라이 사키", "ja": "空井サキ"},
    "Sena": {"canonical": "氷室セナ", "ko": "히무로 세나", "ja": "氷室セナ"},
    "Sensei": {"canonical": "先生", "ko": "선생", "ja": "先生"},
    "Shiroko": {"canonical": "砂狼シロコ", "ko": "스나오오카미 시로코", "ja": "砂狼シロコ"},
    "Suzumi": {"canonical": "守月スズミ", "ko": "모리츠키 스즈미", "ja": "守月スズミ"},
    "Ui": {"canonical": "古関ウイ", "ko": "코제키 우이", "ja": "古関ウイ"},
    "Yukari": {"canonical": "勘解由小路ユカリ", "ko": "카데노코지 유카리", "ja": "勘解由小路ユカリ"},
    "Yuuka": {"canonical": "早瀬ユウカ", "ko": "하야세 유우카", "ja": "早瀬ユウカ"},
    "各務チヒロ": {"canonical": "各務チヒロ", "ko": "카가미 치히로", "ja": "各務チヒロ"},
    "明星ヒマリ": {"canonical": "明星ヒマリ", "ko": "아케보시 히마리", "ja": "明星ヒマリ"},
}


FULL_NAME_TO_LOCALIZATION: dict[str, Localization] = {
    values["canonical"]: {"ko": values["ko"], "ja": values["ja"]}
    for values in BLUE_ARCHIVE_NAMES.values()
}
FULL_NAME_TO_LOCALIZATION.update(
    {
        "伊落マリー": {"ko": "이오치 마리", "ja": "伊落マリー"},
        "小鳥遊ホシノ": {"ko": "타카나시 호시노", "ja": "小鳥遊ホシノ"},
        "水羽ミモリ": {"ko": "미즈하 미모리", "ja": "水羽ミモリ"},
        "狐坂ワカモ": {"ko": "코사카 와카모", "ja": "狐坂ワカモ"},
        "白洲アズサ": {"ko": "시라스 아즈사", "ja": "白洲アズサ"},
        "陸八魔アル": {"ko": "리쿠하치마 아루", "ja": "陸八魔アル"},
        "愛清フウカ": {"ko": "아이키요 후우카", "ja": "愛清フウカ"},
    }
)


VARIANT_TO_BASE: dict[str, tuple[str, str]] = {
    "Hina (dress)": ("Hina", "dress"),
    "Hina (pajamas)": ("Hina", "pajamas"),
    "Hina (swimsuit)": ("Hina", "swimsuit"),
    "Mari (idol)": ("Mari", "idol"),
    "Midori (maid)": ("Midori", "maid"),
    "Momoi (maid)": ("Momoi", "maid"),
    "Chihiro (pajamas)": ("Chihiro", "pajamas"),
    "伊落マリー(体操服)": ("伊落マリー", "体操服"),
    "愛清フウカ(正月)": ("愛清フウカ", "正月"),
    "フウカ(正月)": ("愛清フウカ", "正月"),
}


VARIANT_REVIEW_ONLY: dict[EntityKey, str] = {
    ("Blue Archive", "Kei (new Body)"): "Kei",
}


GROUP_TAGS: dict[EntityKey, str] = {
    ("Blue Archive", "Gourmet Research Society"): "group",
    ("Blue Archive", "Problem Solver 68"): "group",
    ("Blue Archive", "Rabbit Platoon"): "group",
    ("Blue Archive", "Veritas"): "group",
    ("Blue Archive", "Occult Studies Club"): "group",
    ("Blue Archive", "Justice Task Force Member"): "group",
}


GENERAL_TAGS: dict[EntityKey, str] = {
    ("Blue Archive", "タイツ"): "general",
    ("Blue Archive", "メガネ"): "general",
    ("Blue Archive", "白タイツ"): "general",
}


NIKKE_KO_TRANSLITERATIONS: dict[EntityKey, str] = {
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


def add_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


def ensure_review(entry: dict[str, Any]) -> dict[str, Any]:
    review = entry.get("_review")
    if not isinstance(review, dict):
        review = {}
        entry["_review"] = review
    return review


def merge_review(target: dict[str, Any], source_review: dict[str, Any] | None) -> None:
    if not source_review:
        return
    target_review = ensure_review(target)
    for key, value in source_review.items():
        if key not in target_review:
            target_review[key] = copy.deepcopy(value)
        elif isinstance(target_review[key], list) and isinstance(value, list):
            for item in value:
                if item not in target_review[key]:
                    target_review[key].append(copy.deepcopy(item))


def add_missing_localizations(entry: dict[str, Any], values: Localization, summary: dict[str, int]) -> None:
    locs = entry.setdefault("localizations", {})
    for locale in ("ko", "ja"):
        if locale in values and locale not in locs:
            locs[locale] = values[locale]
            summary[f"{locale}_added"] += 1


def merge_localizations(
    target: dict[str, Any],
    source: dict[str, Any],
    report: dict[str, Any],
) -> None:
    target_locs = target.setdefault("localizations", {})
    for locale, display_name in source.get("localizations", {}).items():
        if locale not in target_locs:
            target_locs[locale] = display_name
        elif (
            locale in {"ko", "ja"}
            and source.get("canonical") == target.get("canonical")
            and target_locs[locale] != display_name
        ):
            old_value = target_locs[locale]
            target_locs[locale] = display_name
            report["warnings"].append(
                {
                    "type": "official_localization_preferred_from_official_canonical",
                    "locale": locale,
                    "source_canonical": source.get("canonical"),
                    "target_canonical": target.get("canonical"),
                    "replaced_value": old_value,
                    "preferred_value": display_name,
                }
            )
        elif (
            locale == "en"
            and source.get("canonical") == target.get("canonical")
            and target_locs[locale] != display_name
        ):
            old_value = target_locs[locale]
            add_unique(target.setdefault("aliases", []), old_value)
            target_locs[locale] = display_name
            report["warnings"].append(
                {
                    "type": "english_display_preferred_from_official_canonical",
                    "locale": locale,
                    "source_canonical": source.get("canonical"),
                    "target_canonical": target.get("canonical"),
                    "preserved_alias": old_value,
                    "preferred_value": display_name,
                }
            )
        elif target_locs[locale] != display_name:
            add_unique(target.setdefault("aliases", []), display_name)
            report["warnings"].append(
                {
                    "type": "localization_conflict_preserved_as_alias",
                    "locale": locale,
                    "source_canonical": source.get("canonical"),
                    "target_canonical": target.get("canonical"),
                    "source_value": display_name,
                    "target_value": target_locs[locale],
                }
            )


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


def mark_localization_check(entry: dict[str, Any], reason: str) -> None:
    review = ensure_review(entry)
    review["needs_localization_check"] = True
    review.setdefault("reason", reason)


def mark_canonical_check(entry: dict[str, Any], reason: str) -> None:
    review = ensure_review(entry)
    review["needs_canonical_check"] = True
    review.setdefault("reason", reason)


def mark_variant_on_target(target: dict[str, Any], source: dict[str, Any], variant: str) -> None:
    review = ensure_review(target)
    merged = review.setdefault("merged_variants", [])
    item = {
        "source_canonical": source.get("canonical"),
        "variant": variant,
        "reason": "costume/variant tag merged into base character",
    }
    if item not in merged:
        merged.append(item)


def target_for(entry: dict[str, Any]) -> tuple[str, str, str | None]:
    series = entry.get("parent_series", "")
    canonical = entry.get("canonical", "")
    if series == "Blue Archive" and canonical in VARIANT_TO_BASE:
        base, variant = VARIANT_TO_BASE[canonical]
        base_canonical = BLUE_ARCHIVE_NAMES.get(base, {}).get("canonical", base)
        return base_canonical, "variant", variant
    if series == "Blue Archive" and canonical in BLUE_ARCHIVE_NAMES:
        return BLUE_ARCHIVE_NAMES[canonical]["canonical"], "canonical", None
    return canonical, "unchanged", None


def seed_entry(source: dict[str, Any], target_canonical: str) -> dict[str, Any]:
    entry = copy.deepcopy(source)
    old_canonical = entry.get("canonical")
    entry["canonical"] = target_canonical
    aliases = list(entry.get("aliases", []))
    if old_canonical != target_canonical:
        add_unique(aliases, old_canonical)
    for value in source.get("localizations", {}).values():
        add_unique(aliases, value)
    entry["aliases"] = aliases
    return entry


def merge_entry(target: dict[str, Any], source: dict[str, Any], report: dict[str, Any]) -> None:
    aliases = target.setdefault("aliases", [])
    add_unique(aliases, source.get("canonical"))
    for alias in source.get("aliases", []):
        add_unique(aliases, alias)
    for value in source.get("localizations", {}).values():
        add_unique(aliases, value)
    merge_localizations(target, source, report)
    merge_review(target, source.get("_review"))


def apply_reviews(entry: dict[str, Any], source: dict[str, Any]) -> None:
    key = (source.get("parent_series", ""), source.get("canonical", ""))
    if key in GROUP_TAGS:
        mark_group_or_general(entry, GROUP_TAGS[key])
    if key in GENERAL_TAGS:
        mark_group_or_general(entry, GENERAL_TAGS[key])
    if key in VARIANT_REVIEW_ONLY:
        review = ensure_review(entry)
        review["variant_tag"] = True
        review["base_character_candidate"] = VARIANT_REVIEW_ONLY[key]
        review.setdefault(
            "reason",
            "variant tag; base canonical was not normalized automatically",
        )
        mark_localization_check(entry, "ko/ja variant official name not verified")

    series = source.get("parent_series", "")
    if series == "Trickcal":
        mark_localization_check(entry, "ko/ja official name not verified")
        mark_canonical_check(entry, "official original canonical not verified")
    if series == "Nikke":
        if key in NIKKE_KO_TRANSLITERATIONS:
            entry.setdefault("localizations", {}).setdefault("ko", NIKKE_KO_TRANSLITERATIONS[key])
            mark_localization_check(entry, "ko localization is transliteration candidate")
        else:
            mark_localization_check(entry, "ko/ja official name not verified")
        mark_canonical_check(entry, "official original canonical not verified")
    if series == "Horuhara":
        mark_localization_check(entry, "fan-work or crossover tag; ko/ja official name not verified")
        mark_canonical_check(entry, "official original canonical not verified")

    if series == "Blue Archive" and key not in GROUP_TAGS and key not in GENERAL_TAGS:
        if not entry.get("localizations", {}).get("ko") and not entry.get("localizations", {}).get("ja"):
            mark_localization_check(entry, "ko/ja official name not verified")
        if source.get("canonical") == entry.get("canonical") and source.get("canonical") not in FULL_NAME_TO_LOCALIZATION:
            if source.get("canonical") not in VARIANT_REVIEW_ONLY.values():
                mark_canonical_check(entry, "official Japanese full-name canonical not verified")


def normalize(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    output = copy.deepcopy(data)
    output["characters"] = []

    report: dict[str, Any] = {
        "summary": {
            "ko_added": 0,
            "ja_added": 0,
            "canonical_changed": 0,
            "entities_merged": 0,
            "review_items": 0,
            "variant_items": 0,
            "group_general_candidates": 0,
            "ambiguous_items": 0,
        },
        "canonical_changes": [],
        "merges": [],
        "review_items": [],
        "warnings": [],
    }
    summary = report["summary"]

    index_by_key: dict[EntityKey, int] = {}

    for source in data.get("characters", []):
        series = source.get("parent_series", "")
        old_canonical = source.get("canonical", "")
        new_canonical, reason_type, variant = target_for(source)
        target_key = (series, new_canonical)

        if target_key in index_by_key:
            target = output["characters"][index_by_key[target_key]]
            merge_entry(target, source, report)
            summary["entities_merged"] += 1
            report["merges"].append(
                {
                    "type": "canonical_merge",
                    "from": old_canonical,
                    "to": new_canonical,
                    "parent_series": series,
                    "reason": (
                        "variant/costume tag merged into base character"
                        if reason_type == "variant"
                        else "short or duplicate canonical merged into official Japanese full name"
                    ),
                }
            )
        else:
            target = seed_entry(source, new_canonical)
            index_by_key[target_key] = len(output["characters"])
            output["characters"].append(target)

        if old_canonical != new_canonical:
            summary["canonical_changed"] += 1
            report["canonical_changes"].append(
                {
                    "from": old_canonical,
                    "to": new_canonical,
                    "parent_series": series,
                    "reason": reason_type,
                }
            )

        if reason_type == "variant" and variant:
            mark_variant_on_target(target, source, variant)

        if series == "Blue Archive" and new_canonical in FULL_NAME_TO_LOCALIZATION:
            add_missing_localizations(target, FULL_NAME_TO_LOCALIZATION[new_canonical], summary)

        apply_reviews(target, source)

    for entry in output["characters"]:
        review = entry.get("_review")
        if not review:
            continue
        summary["review_items"] += 1
        if review.get("variant_tag") or review.get("merged_variants"):
            summary["variant_items"] += 1
        if review.get("possibly_general_or_group_tag"):
            summary["group_general_candidates"] += 1
        if review.get("ambiguous_candidates"):
            summary["ambiguous_items"] += 1
        report["review_items"].append(
            {
                "canonical": entry.get("canonical"),
                "parent_series": entry.get("parent_series", ""),
                "review": review,
            }
        )

    return output, report


def validate(original: dict[str, Any], output: dict[str, Any], report: dict[str, Any]) -> None:
    if not isinstance(output.get("characters"), list):
        raise AssertionError("characters must remain a list")
    if not isinstance(output.get("series"), list):
        raise AssertionError("series must remain a list")
    if len(output.get("series", [])) != len(original.get("series", [])):
        raise AssertionError("series count changed")

    output_by_key = {
        (entry.get("parent_series", ""), entry.get("canonical", "")): entry
        for entry in output.get("characters", [])
    }
    for source in original.get("characters", []):
        series = source.get("parent_series", "")
        old_canonical = source.get("canonical", "")
        new_canonical, _, _ = target_for(source)
        target = output_by_key.get((series, new_canonical))
        if target is None:
            raise AssertionError(f"missing normalized entry for {series}/{old_canonical}")
        if "parent_series" not in target:
            raise AssertionError(f"parent_series removed for {new_canonical}")
        aliases = target.get("aliases", [])
        if old_canonical != new_canonical and old_canonical not in aliases:
            raise AssertionError(f"old canonical not preserved as alias: {old_canonical}")
        for alias in source.get("aliases", []):
            if alias not in aliases:
                raise AssertionError(f"alias removed: {alias}")
        for locale in ("ko", "ja"):
            old_value = source.get("localizations", {}).get(locale)
            if old_value and target.get("localizations", {}).get(locale) != old_value:
                raise AssertionError(f"{locale} localization overwritten for {old_canonical}")

    if "summary" not in report or "canonical_changes" not in report or "merges" not in report:
        raise AssertionError("report structure is incomplete")


def main() -> None:
    original = load_json(INPUT_PATH)
    output, report = normalize(original)
    validate(original, output, report)
    dump_json(output, OUTPUT_PATH)
    dump_json(report, REPORT_PATH)
    validate(original, load_json(OUTPUT_PATH), load_json(REPORT_PATH))

    print("Tag pack canonical normalization completed")
    print(f"output: {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"report: {REPORT_PATH.relative_to(ROOT)}")
    for key, value in report["summary"].items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
