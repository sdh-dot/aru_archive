"""Wuthering Waves Gap A: 누락 캐릭터 seed 및 CSV 갱신.

- CSV 기존 NR → applied 승격: Roccia, Brant, Zani, Ciaccona (나무위키 확인 완료)
- 신규 seed: Youhu (v1.3, CSV 누락), Roccia(v2.0), Brant(v2.1), Zani(v2.3), Ciaccona(v2.4)
- 신규 needs_review: v2.5+ 14인 (표기 불확실/지식 한계)
- Rover: 기존 NR 유지 (주인공 복수 변형 정책 미결)
- Cartethyia KO 교정 후보: 카르테시아 → 카르티시아 (CSV existing_entry_update 기록)
JSON version: 1.0.0 → 1.1.0
"""
import csv, io, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CSV_PATH = Path("docs/audit/dictionary_enrichment_candidates_campaign.csv")
JSON_PATH = Path("resources/tag_packs/wuthering_waves.json")

CAMPAIGN = "WW_gap_A"
PARENT   = "Wuthering Waves"
EVIDENCE = "나무위키 명조: 워더링 웨이브 공명자 목록 기준"

# ─── accept: JSON seed 대상 ───────────────────────────────────────────────────
# (EN, JA, KO, ko_in_aliases, version, notes)
WW_ACCEPT = [
    ("Youhu",    "釉瑚",      "유호",   True, "v1.3", "釉瑚→유호. CSV 미등록 → 신규 추가"),
    ("Roccia",   "ロココ",    "로코코", True, "v2.0", "Rococo 테마 캐릭터. 나무위키 '로코코'. 기존 NR → applied"),
    ("Brant",    "ブラント",  "브렌트", True, "v2.1", "나무위키 '브렌트'. 기존 NR → applied"),
    ("Zani",     "ザンニー",  "젠니",   True, "v2.3", "赞妮→젠니. 나무위키 '젠니'. 기존 NR → applied"),
    ("Ciaccona", "シャコンヌ","샤콘",   True, "v2.4", "Chaconne 테마. 나무위키 '샤콘'. 기존 NR → applied"),
]
ACCEPT_CANONICALS = {en for en, *_ in WW_ACCEPT}

# ─── needs_review: v2.5+, 표기 불확실 ────────────────────────────────────────
# (EN, JA, KO, version, notes)
WW_NR = [
    ("Phrolova",     "フローヴァ",          "플로로",     "v2.5", "v2.5 recent. 나무위키 확인 필요"),
    ("Augusta",      "オーガスタ",          "아우구스타", "v2.6", "v2.6. 나무위키 확인 필요"),
    ("Iuno",         "ユーノ",              "유노",       "v2.6", "v2.6. JA ユーノ 불확실. 나무위키 확인 필요"),
    ("Galbrena",     "ガルブレーナ",        "갈브레나",   "v2.7", "v2.7. 나무위키 확인 필요"),
    ("Qiuyuan",      "仇遠",               "구원",       "v2.7", "仇遠→구원. v2.7"),
    ("Chisa",        "千咲",               "치사",       "v2.8", "千咲→치사. v2.8. 치샤(Chixia)와 혼동 주의"),
    ("Buling",       "卜霊",               "부링",       "v2.8", "卜霊→부링. v2.8. KO 표기 confidence medium"),
    ("Lynae",        "リンネー",            "린네",       "v3.0", "v3.0. 나무위키 확인 필요"),
    ("Mornye",       "モーニエ",            "모니에",     "v3.0", "v3.0. 나무위키 확인 필요"),
    ("Aemeath",      "エイメス",            "에이메스",   "v3.1", "v3.1. 나무위키 확인 필요"),
    ("Luuk Herssen", "リューク・ヘルセン",  "루크·헤르센","v3.1", "v3.1. KO 복합명 루크·헤르센"),
    ("Sigrika",      "シグリカ",            "시그리카",   "v3.2", "v3.2. 나무위키 확인 필요"),
    ("Hiyuki",       "緋雪",               "히유키",     "v3.3", "緋雪→히유키. v3.3. 나무위키 확인 필요"),
    ("Denia",        "ダーニャ",            "데니아",     "v3.3", "v3.3. 나무위키 확인 필요"),
]

NR_CANONICALS = {en for en, *_ in WW_NR}


def make_row(en, ja, ko, ko_in_aliases, action, confidence, notes):
    aliases_list = [en, ja]
    if ko_in_aliases:
        aliases_list.append(ko)
    return {
        "campaign":                CAMPAIGN,
        "source_series":           PARENT,
        "canonical_series":        PARENT,
        "tag_type":                "character",
        "raw_name":                ko,
        "suggested_canonical":     en,
        "suggested_ko":            ko,
        "suggested_ja":            ja,
        "suggested_en":            en,
        "aliases":                 ",".join(aliases_list),
        "parent_series":           PARENT,
        "subgroup_or_affiliation": "",
        "source_url":              "",
        "evidence":                EVIDENCE,
        "confidence":              confidence,
        "action":                  action,
        "issue_type":              "new_character",
        "notes":                   notes,
    }


# ─── 1. UPDATE wuthering_waves.json ──────────────────────────────────────────
data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
data["version"] = "1.1.0"

existing_canonicals = {c["canonical"] for c in data["characters"]}
added = []
for en, ja, ko, ko_in_aliases, *_ in WW_ACCEPT:
    if en in existing_canonicals:
        continue
    aliases = [en, ja]
    if ko_in_aliases:
        aliases.append(ko)
    data["characters"].append({
        "canonical":     en,
        "parent_series": PARENT,
        "aliases":       aliases,
        "localizations": {"ko": ko, "ja": ja, "en": en},
    })
    added.append(en)

JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 2. UPDATE campaign CSV ───────────────────────────────────────────────────
text = CSV_PATH.read_text(encoding="utf-8-sig", newline="")
reader = csv.DictReader(io.StringIO(text))
old_rows = list(reader)
headers = reader.fieldnames

# 기존 WW needs_review 행 중 accept 승격 대상 제거 (재기록)
# Rover + 기존 28 applied는 그대로 유지
def keep_row(r):
    if r.get("canonical_series") != PARENT:
        return True
    if r.get("action") == "needs_review" and r.get("suggested_canonical") in ACCEPT_CANONICALS:
        return False  # 제거: applied로 재기록
    return True

kept_rows = [r for r in old_rows if keep_row(r)]

new_rows = []

# accept → applied (Youhu + 승격 4인)
for en, ja, ko, ko_in_aliases, ver, notes in WW_ACCEPT:
    new_rows.append(make_row(en, ja, ko, ko_in_aliases, "applied", "high",
                             f"{notes} [applied] Gap A seed 반영".strip()))

# needs_review v2.5+
for en, ja, ko, ver, notes in WW_NR:
    new_rows.append(make_row(en, ja, ko, len(ko) > 1, "needs_review", "medium", notes))

# Cartethyia KO 교정 후보 기록
new_rows.append({
    **make_row("Cartethyia", "カルテジア", "카르테시아", True, "needs_review", "medium",
               "기존 KO '카르테시아' → 나무위키 표기 '카르티시아' 교정 필요. JSON 직접 수정 전 검토 필요"),
    "issue_type": "existing_entry_update",
})

all_rows = kept_rows + new_rows
out = io.StringIO()
writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n")
writer.writeheader()
writer.writerows(all_rows)
CSV_PATH.write_text(out.getvalue(), encoding="utf-8-sig", newline="")


# ─── 3. REPORT ────────────────────────────────────────────────────────────────
ww_all = [r for r in all_rows if r.get("canonical_series") == PARENT]
by_action: dict[str, int] = {}
for r in ww_all:
    by_action[r["action"]] = by_action.get(r["action"], 0) + 1

print("WW CSV distribution (Gap A):")
for k, v in sorted(by_action.items()):
    print(f"  {k}: {v}")
print()
print(f"신규 JSON seed:           {len(added)} ({', '.join(added)})")
print(f"Total chars in JSON:      {len(data['characters'])} (was 28)")
print(f"JSON version:             {data['version']}")
print(f"NR 승격:                  Roccia, Brant, Zani, Ciaccona → applied")
print(f"신규 needs_review:        {len(WW_NR)}인 (v2.5+)")
print(f"Cartethyia 교정 후보:     existing_entry_update 기록")
