"""HSR 캐릭터 후보 CSV 생성 + 1차 seed 스크립트.

1차 seed: Astral Express 5인 + Belobog 10인 = 15인
CSV accept: Xianzhou 10인 + 기타 9인 = 19인
CSV needs_review: 특수/불확실 12인
기존 Ruan Mei needs_review → accept 갱신
"""
import csv, io, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CSV_PATH = Path("docs/audit/dictionary_enrichment_candidates_campaign.csv")
JSON_PATH = Path("resources/tag_packs/honkai_star_rail.json")

# ─── CHARACTER DATA ───────────────────────────────────────────────────────────
# applied (1차 seed): (EN, JA, KO, ko_in_aliases, subgroup, confidence, notes)

ASTRAL_SEED = [
    ("March 7th", "三月七",  "삼칠이", True,  "Astral Express", "high",
     "삼칠이는 공식 KO명. v2.4 신속 변신 동일 canonical 유지"),
    ("Dan Heng",  "丹恒",    "단항",   True,  "Astral Express", "high",
     "丹恒→단항. 음월(飲月) 변신은 별도 캐릭터 항목"),
    ("Himeko",    "姫子",    "히메코", True,  "Astral Express", "high",
     "HI3 공유명. parent_series=Honkai: Star Rail 스코핑"),
    ("Welt",      "ヴェルト","웰트",   True,  "Astral Express", "high",
     "HI3 공유명. parent_series=Honkai: Star Rail 스코핑"),
    ("Asta",      "アスタ",  "아스타", True,  "Astral Express", "high", ""),
]

BELOBOG_SEED = [
    ("Gepard",  "ゲパルト",  "게파르트", True,  "Belobog", "high", ""),
    ("Pela",    "ペラ",      "펠라",     True,  "Belobog", "high", ""),
    ("Serval",  "セルバル",  "세르발",   True,  "Belobog", "high", ""),
    ("Natasha", "ナターシャ","나타샤",   True,  "Belobog", "high", ""),
    ("Hook",    "フック",    "훅",       False, "Belobog", "high",
     "KO 훅(1음절) aliases 제외, localizations.ko에만 보존"),
    ("Sampo",   "サンポ",    "삼포",     True,  "Belobog", "high", ""),
    ("Luka",    "ルカ",      "루카",     True,  "Belobog", "high", ""),
    ("Sushang", "素裳",      "수상",     True,  "Belobog", "high", "素裳→수상"),
    ("Arlan",   "アーラン",  "아를란",   True,  "Belobog", "high", ""),
    ("Lynx",    "リンクス",  "린스",     True,  "Belobog", "high", ""),
]

# accept (차기 seed 대상): same tuple format
XIANZHOU_ACCEPT = [
    ("Yanqing",  "彦卿",   "연경", True, "Xianzhou Luofu", "high",   "차기 seed 대상"),
    ("Bailu",    "白露",   "백로", True, "Xianzhou Luofu", "high",   "차기 seed 대상"),
    ("Qingque",  "青雀",   "청작", True, "Xianzhou Luofu", "high",   "차기 seed 대상"),
    ("Tingyun",  "停云",   "정운", True, "Xianzhou Luofu", "high",   "차기 seed 대상"),
    ("Yukong",   "驭空",   "유공", True, "Xianzhou Luofu", "high",   "차기 seed 대상. JA 확인 필요"),
    ("Fu Xuan",  "符玄",   "부현", True, "Xianzhou Luofu", "high",   "차기 seed 대상"),
    ("Hanya",    "寒鴉",   "한야", True, "Xianzhou Luofu", "high",   "차기 seed 대상"),
    ("Xueyi",    "雪儀",   "설의", True, "Xianzhou Luofu", "high",   "차기 seed 대상"),
    ("Huohuo",   "貂鼠",   "활활", True, "Xianzhou Luofu", "medium", "활활 KO 확인 필요. 貂鼠→JA 확인. 차기 seed 대상"),
    ("Dan Heng · Imbibitor Lunae", "丹恒飲月", "음월",
     True, "Xianzhou Luofu", "high", "단항 변신 형태. 별도 캐릭터. 차기 seed 대상"),
]

MISC_ACCEPT = [
    ("Argenti",    "アルジェンティ","아르젠티", True, "Xianzhou Luofu",                "high",   "차기 seed 대상"),
    ("Ruan Mei",   "阮梅",          "완매",     True, "Herta Space Station",           "high",   "旧 needs_review 항목. 阮梅→완매 확정. 차기 seed 대상"),
    ("Sparkle",    "スパークル",    "스파클",   True, "Masked Fools",                  "high",   "차기 seed 대상"),
    ("Misha",      "ミーシャ",      "미샤",     True, "Penacony",                      "high",   "차기 seed 대상"),
    ("Robin",      "ロビン",        "로빈",     True, "Penacony",                      "high",   "차기 seed 대상"),
    ("Boothill",   "ブートヒル",    "부트힐",   True, "Galaxy Rangers",                "high",   "차기 seed 대상"),
    ("Acheron",    "アチェロン",    "아케론",   True, "Galaxy Rangers",                "high",   "차기 seed 대상. JA 카타카나 확인 필요"),
    ("Aventurine", "アベンチュリン","아벤투린", True, "Interastral Peace Corporation", "high",   "차기 seed 대상"),
    ("Gallagher",  "ギャラガー",    "갤러거",   True, "Penacony",                      "high",   "차기 seed 대상"),
]

# needs_review: (EN, JA, KO, subgroup, confidence, notes) — 별도 포맷
NEEDS_REVIEW = [
    ("Trailblazer", "開拓者", "개척자", "Astral Express", "medium",
     "성별·운명의 길 변형 다수(파멸/보존/화합/기억). 카엘루스(남)/스텔레(여). 단일 canonical 정책 결정 필요"),
    ("Seele",       "ゼーレ", "제레",   "Belobog",        "medium",
     "HI3 공유명. parent_series 스코핑 검토 필요"),
    ("Firefly",     "ファイアフライ","불꽃이","Penacony",  "medium",
     "KO 불꽃이 공식명 확인 필요. 진명 サム(Sam). needs_review 유지"),
    ("Luocha",      "羅刹",   "낙차",   "Xianzhou Luofu", "medium",
     "KO 낙차(Luocha 음역) vs 나찰(羅刹 한자독음) 나무위키 확인 필요"),
    ("Dr. Ratio",   "ドクター・ラシオ","닥터 라샤","Interastral Peace Corporation","medium",
     "KO 닥터 라샤 vs 닥터 레이시오 나무위키 확인 필요"),
    ("Jade",        "翡翠",   "제이드",  "Interastral Peace Corporation","medium",
     "KO 제이드(EN transliteration) vs 翡翠 한자독음 확인 필요"),
    ("Guinaifen",   "桂乃芬", "귀나이펀","Xianzhou Luofu","medium",
     "KO 표기 불확실. 桂乃芬→귀나이펀 또는 다른 표기 나무위키 확인 필요"),
    ("Topaz",       "托帕",   "토파",    "Interastral Peace Corporation","medium",
     "KO 토파 vs 토파즈(EN) 확인 필요. Numby 파트너 포함"),
    ("Feixiao",     "飛霄",   "페이샤오","Xianzhou Luofu","medium",
     "KO 페이샤오 vs 비소(飞霄 한자독음) 나무위키 확인 필요"),
    ("Lingsha",     "凌沙",   "링샤",    "Xianzhou Luofu","medium",
     "KO 링샤 나무위키 확인 필요"),
    ("Moze",        "莫澤",   "모제",    "Xianzhou Luofu","medium",
     "KO 모제 나무위키 확인 필요"),
    ("Rappa",       "刃芭",   "라파",    "Galaxy Rangers","medium",
     "v2.6 캐릭터. KO 라파 나무위키 확인 필요. JA 확인 필요"),
]

# ─── 1. UPDATE CAMPAIGN CSV ───────────────────────────────────────────────────
text = CSV_PATH.read_text(encoding="utf-8-sig", newline="")
reader = csv.DictReader(io.StringIO(text))
old_rows = list(reader)
headers = reader.fieldnames

# Ruan Mei: needs_review → accept
for r in old_rows:
    if (r.get("canonical_series") == "Honkai: Star Rail"
            and r.get("suggested_canonical") == "Ruan Mei"
            and r.get("action") == "needs_review"):
        r["action"] = "accept"
        r["notes"] = (r.get("notes", "") + " [accept] 阮梅→완매 확정. 차기 seed 대상").strip()


def make_row(en, ja, ko, ko_in_aliases, subgroup, action, confidence, notes):
    aliases = [en, ja]
    if ko_in_aliases:
        aliases.append(ko)
    return {
        "campaign":               "HSR_phase_B1",
        "source_series":          "Honkai: Star Rail",
        "canonical_series":       "Honkai: Star Rail",
        "tag_type":               "character",
        "raw_name":               ko,
        "suggested_canonical":    en,
        "suggested_ko":           ko,
        "suggested_ja":           ja,
        "suggested_en":           en,
        "aliases":                ",".join(aliases),
        "parent_series":          "Honkai: Star Rail",
        "subgroup_or_affiliation":subgroup,
        "source_url":             "",
        "evidence":               "나무위키 붕괴: 스타레일 플레이어블 캐릭터 목록 기준",
        "confidence":             confidence,
        "action":                 action,
        "issue_type":             "new_character",
        "notes":                  notes,
    }


new_rows = []
for en, ja, ko, ko_in_aliases, sub, conf, notes in ASTRAL_SEED + BELOBOG_SEED:
    new_rows.append(make_row(en, ja, ko, ko_in_aliases, sub, "applied", conf, notes))
for en, ja, ko, ko_in_aliases, sub, conf, notes in XIANZHOU_ACCEPT + MISC_ACCEPT:
    new_rows.append(make_row(en, ja, ko, ko_in_aliases, sub, "accept", conf, notes))
for en, ja, ko, sub, conf, notes in NEEDS_REVIEW:
    ko_in_aliases = len(ko) > 1
    new_rows.append(make_row(en, ja, ko, ko_in_aliases, sub, "needs_review", conf, notes))

all_rows = old_rows + new_rows
out = io.StringIO()
writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n")
writer.writeheader()
writer.writerows(all_rows)
CSV_PATH.write_text(out.getvalue(), encoding="utf-8-sig", newline="")

# ─── 2. UPDATE honkai_star_rail.json ─────────────────────────────────────────
data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
data["version"] = "1.2.0"

seed_chars = []
for en, ja, ko, ko_in_aliases, *_ in ASTRAL_SEED + BELOBOG_SEED:
    aliases = [en, ja]
    if ko_in_aliases:
        aliases.append(ko)
    seed_chars.append({
        "canonical":    en,
        "parent_series":"Honkai: Star Rail",
        "aliases":      aliases,
        "localizations":{"ko": ko, "ja": ja, "en": en},
    })

data["characters"] = data.get("characters", []) + seed_chars
JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ─── 3. REPORT ────────────────────────────────────────────────────────────────
hsr_all = [r for r in all_rows if r.get("canonical_series") == "Honkai: Star Rail"]
by_action: dict[str, int] = {}
for r in hsr_all:
    by_action[r["action"]] = by_action.get(r["action"], 0) + 1

print("HSR CSV distribution:")
for k, v in sorted(by_action.items()):
    print(f"  {k}: {v}")
print()
print(f"New rows added:           {len(new_rows)}")
print(f"Total chars in JSON:      {len(data['characters'])} (was 5)")
print(f"JSON version:             {data['version']}")
