"""HSR Phase B2: accept 19개를 honkai_star_rail.json에 seed.

Xianzhou Luofu 10 + Misc 9 (Ruan Mei 포함) = 19인
CSV action: accept → applied (Ruan Mei 중복행 모두 처리)
JSON version: 1.2.0 → 1.3.0
"""
import csv, io, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CSV_PATH = Path("docs/audit/dictionary_enrichment_candidates_campaign.csv")
JSON_PATH = Path("resources/tag_packs/honkai_star_rail.json")

# (EN, JA, KO, ko_in_aliases, notes)
# Xianzhou Luofu: JA = Chinese kanji (게임 JA판 동일 한자 사용)
XIANZHOU_SEED = [
    ("Yanqing",   "彦卿",   "연경",   True),
    ("Bailu",     "白露",   "백로",   True),
    ("Qingque",   "青雀",   "청작",   True),
    ("Tingyun",   "停云",   "정운",   True),
    ("Yukong",    "驭空",   "유공",   True),
    ("Fu Xuan",   "符玄",   "부현",   True),
    ("Hanya",     "寒鴉",   "한야",   True),
    ("Xueyi",     "雪儀",   "설의",   True),
    ("Huohuo",    "貂鼠",   "활활",   True),
    # Dan Heng 변신 형태 — 게임 내 별도 플레이어블 캐릭터, KO 음월(2음절)
    ("Dan Heng · Imbibitor Lunae", "丹恒飲月", "음월", True),
]

# Misc accept: JA 표기는 캐릭터 특성에 따라 한자 or 카타카나
MISC_SEED = [
    # Xianzhou 출신이나 기사단 캐릭터 — JA 카타카나
    ("Argenti",    "アルジェンティ", "아르젠티", True),
    # Herta Space Station 연구원 — JA 한자
    ("Ruan Mei",   "阮梅",           "완매",     True),
    # 이하 서구권/범우주 캐릭터 — JA 카타카나
    ("Sparkle",    "スパークル",     "스파클",   True),
    ("Misha",      "ミーシャ",       "미샤",     True),
    ("Robin",      "ロビン",         "로빈",     True),
    ("Boothill",   "ブートヒル",     "부트힐",   True),
    ("Acheron",    "アチェロン",     "아케론",   True),
    ("Aventurine", "アベンチュリン", "아벤투린", True),
    ("Gallagher",  "ギャラガー",     "갤러거",   True),
]

ALL_SEED = XIANZHOU_SEED + MISC_SEED
SEED_CANONICALS = {en for en, *_ in ALL_SEED}

# ─── 1. UPDATE honkai_star_rail.json ─────────────────────────────────────────
data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
data["version"] = "1.3.0"

new_chars = []
for en, ja, ko, ko_in_aliases in ALL_SEED:
    aliases = [en, ja]
    if ko_in_aliases:
        aliases.append(ko)
    new_chars.append({
        "canonical":    en,
        "parent_series": "Honkai: Star Rail",
        "aliases":      aliases,
        "localizations": {"ko": ko, "ja": ja, "en": en},
    })

data["characters"] = data.get("characters", []) + new_chars
JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ─── 2. UPDATE campaign CSV ───────────────────────────────────────────────────
text = CSV_PATH.read_text(encoding="utf-8-sig", newline="")
reader = csv.DictReader(io.StringIO(text))
old_rows = list(reader)
headers = reader.fieldnames

seeded_canonicals_seen: set[str] = set()
for r in old_rows:
    if (r.get("canonical_series") == "Honkai: Star Rail"
            and r.get("action") == "accept"
            and r.get("suggested_canonical") in SEED_CANONICALS):
        en = r["suggested_canonical"]
        if en not in seeded_canonicals_seen:
            seeded_canonicals_seen.add(en)
            r["action"] = "applied"
            r["notes"] = (r.get("notes", "") + " [applied] Phase B2 seed 반영").strip()
        else:
            # 중복행(Ruan Mei 구행 등)도 applied로 통일
            r["action"] = "applied"
            r["notes"] = (r.get("notes", "") + " [applied] Phase B2 중복행 갱신").strip()

out = io.StringIO()
writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n")
writer.writeheader()
writer.writerows(old_rows)
CSV_PATH.write_text(out.getvalue(), encoding="utf-8-sig", newline="")

# ─── 3. REPORT ────────────────────────────────────────────────────────────────
all_hsr = [r for r in old_rows if r.get("canonical_series") == "Honkai: Star Rail"]
by_action: dict[str, int] = {}
for r in all_hsr:
    by_action[r["action"]] = by_action.get(r["action"], 0) + 1

print("HSR CSV distribution (after Phase B2):")
for k, v in sorted(by_action.items()):
    print(f"  {k}: {v}")
print()
print(f"New chars seeded:         {len(new_chars)}")
print(f"Total chars in JSON:      {len(data['characters'])} (was 20)")
print(f"JSON version:             {data['version']}")
print(f"CSV rows marked applied:  {len(seeded_canonicals_seen)} canonicals")
