"""ZZZ Phase A: 젠레스 존 제로 캐릭터 사전 보강 스크립트.

1. 기존 JSON 단일명 alias 정리 (Nicole / Ellen / Jane)
2. accept 18명 신규 seed
3. campaign CSV에 ZZZ 행 추가 (applied 4 + accept 18 + hold 2 + needs_review 8)
JSON version: 1.1.0 → 1.2.0

나무위키 검증 기반 주요 수정:
- Anby Demara KO: 엔비 데마라 (NOT 안비 드마라)
- Von Lycaon KO: 본 리카온 (NOT 폰 리카온)
- Anton Ivanov KO: 앤톤 이바노프 (NOT 안톤)
"""
import csv, io, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CSV_PATH = Path("docs/audit/dictionary_enrichment_candidates_campaign.csv")
JSON_PATH = Path("resources/tag_packs/zenless_zone_zero.json")

CAMPAIGN = "ZZZ_phase_A"
PARENT  = "Zenless Zone Zero"
EVIDENCE = "나무위키 젠레스 존 제로 에이전트 목록 기준"

# ─── accept 신규 seed ──────────────────────────────────────────────────────────
# (EN, JA, KO, ko_in_aliases, faction, version, notes)
ZZZ_ACCEPT = [
    ("Anby Demara",      "アンビー・デマーラ",  "엔비 데마라",     True, "Cunning Hares",             "v1.0", "나무위키 '엔비 데마라'"),
    ("Billy Kid",        "ビリー・キッド",       "빌리 키드",       True, "Cunning Hares",             "v1.0", ""),
    ("Corin Wickes",     "カリン・ウィックス",   "코린 위크스",     True, "Victoria Housekeeping Co.", "v1.0", "JA カリン 인게임 확인"),
    ("Ben Bigger",       "ベン・ビガー",         "벤 비거",         True, "Belobog Heavy Industries",  "v1.0", ""),
    ("Grace Howard",     "グレース・ハワード",   "그레이스 하워드", True, "Belobog Heavy Industries",  "v1.0", ""),
    ("Anton Ivanov",     "アントン・イヴァノフ", "앤톤 이바노프",   True, "Belobog Heavy Industries",  "v1.0", "나무위키 '앤톤'. JA アントン 표준 음역"),
    ("Zhu Yuan",         "朱鳶",                 "주연",            True, "CIST",                      "v1.0", "朱鳶→주연"),
    ("Von Lycaon",       "フォン・リカオン",     "본 리카온",       True, "Victoria Housekeeping Co.", "v1.0", "나무위키 '본 리카온'. Von→본(V→B 렌더링)"),
    ("Seth Lowell",      "セス・ロウエル",       "세스 로웰",       True, "CIST",                      "v1.1", ""),
    ("Qingyi",           "青依",                 "청의",            True, "CIST",                      "v1.1", "青依→청의"),
    ("Soukaku",          "蒼角",                 "소우카쿠",        True, "Section 6",                 "v1.2", "蒼角→소우카쿠"),
    ("Burnice White",    "バーニス・ホワイト",   "버니스 화이트",   True, "Sons of Calydon",           "v1.2", ""),
    ("Caesar King",      "シーザー・キング",     "카이사르 킹",     True, "Sons of Calydon",           "v1.2", ""),
    ("Lighter",          "ライター",             "라이터",          True, "Sons of Calydon",           "v1.3", ""),
    ("Miyabi",           "星見雅",               "호시미 미야비",   True, "Section 6",                 "v1.4", "인게임 EN=Miyabi. 전체명 Hoshimi Miyabi. JA 星見雅"),
    ("Harumasa",         "悠真",                 "아사바 하루마사", True, "Section 6",                 "v1.4", "인게임 EN=Harumasa. 전체명 Asaba Harumasa. JA 悠真"),
    ("Astra Yao",        "アストラ・ヤオ",       "아스트라 야오",   True, "Yunkui Summit",             "v1.5", ""),
    ("Evelyn Chevalier", "イヴリン",             "이블린 슈발리에", True, "Victoria Housekeeping Co.", "v1.5", "전체명 이블린 슈발리에. 진영 확인 필요"),
]

# ─── hold (CSV만, JSON 미반영) ─────────────────────────────────────────────────
# (EN, JA_tentative, KO, faction, version, notes)
ZZZ_HOLD = [
    ("Piper",  "パイパー", "파이퍼", "Sons of Calydon",       "v1.0", "전체명 Piper vs Piper Wheel 불확실. 나무위키 '파이퍼 휠'"),
    ("Koleda", "クレタ",   "콜레다", "Belobog Heavy Industries", "v1.0", "JA クレタ 불확실. 전체명 Koleda Belobog? 나무위키 확인 필요"),
]

# ─── needs_review (CSV만, JSON 미반영) ────────────────────────────────────────
# (EN, JA_tentative, KO, faction, version, notes)
ZZZ_NR = [
    ("Nekomata",  "猫又",     "네코마타",     "Cunning Hares",             "v1.0",
     "인게임 코드명 Nekomata. 실명 네코미야 마나. 나무위키 페이지명 '네코미야 마나'. canonical 정책 결정 필요"),
    ("Soldier 11","11号",     "솔저 11",      "Victoria Housekeeping Co.", "v1.0",
     "KO 솔저 11 vs 11호. 실명 Harin. 나무위키 '11호' 확인 필요"),
    ("Lucy",      "ルーシー", "루시",         "Sons of Calydon",           "v1.0",
     "인게임 약칭 Lucy. 전체명 루시아나 드 몬테피오. canonical 결정 필요"),
    ("Rina",      "リナ",     "리나",         "Victoria Housekeeping Co.", "v1.0",
     "인게임 코드명 Rina. 전체명 알렉산드리나 세바스티안. canonical 결정 필요"),
    ("Wise",      "アキラ",   "와이즈",       "Cunning Hares",             "v1.0",
     "주인공(남). Belle & Wise 쌍 정체성. 나무위키 '벨 & 와이즈' 통합 페이지"),
    ("Belle",     "リン",     "벨",           "Cunning Hares",             "v1.0",
     "주인공(여). Wise와 쌍 정체성. 단일명 '벨' 전역 alias 금지"),
    ("Trigger",   "トリガー", "트리거",       "Mockingbird",               "v1.6",
     "v1.6 최신. 표기 안정성 확인 필요"),
    ("Vivian",    "ビビアン", "비비안 밴시",  "Angels of Delusion",        "v1.7",
     "v1.7 very recent. 전체명 비비안 밴시. 나무위키 확인 필요"),
]

# ─── already applied (기존 JSON seed, CSV applied 행으로만 기록) ─────────────
ALREADY_APPLIED = [
    ("Nicole Demara", "ニコル・デマーラ", "니콜 드마라", "Cunning Hares",             "v1.0", "기존 seed. 단일명 alias 'Nicole' 제거"),
    ("Ellen Joe",     "エレン・ジョー",   "엘런 조",     "Victoria Housekeeping Co.", "v1.0", "기존 seed. 단일명 alias 'Ellen' 제거"),
    ("Yanagi",        "柳",               "야나기",      "Section 6",                 "v1.3", "기존 seed"),
    ("Jane Doe",      "ジェーン",         "제인",        "CIST",                      "v1.1", "기존 seed. 단일명 alias 'Jane' 제거"),
]


# ─── 1. UPDATE zenless_zone_zero.json ─────────────────────────────────────────
data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
data["version"] = "1.2.0"

# 기존 캐릭터 단일명 alias 제거
single_name_remove = {"Nicole", "Ellen", "Jane"}
for char in data["characters"]:
    char["aliases"] = [a for a in char["aliases"] if a not in single_name_remove]

# 신규 캐릭터 추가 (멱등: 이미 있으면 skip)
existing_canonicals = {c["canonical"] for c in data["characters"]}
for en, ja, ko, ko_in_aliases, *_ in ZZZ_ACCEPT:
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

JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 2. UPDATE campaign CSV ────────────────────────────────────────────────────
def make_row(en, ja, ko, ko_in_aliases, faction, action, confidence, notes):
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
        "subgroup_or_affiliation": faction,
        "source_url":              "",
        "evidence":                EVIDENCE,
        "confidence":              confidence,
        "action":                  action,
        "issue_type":              "new_character",
        "notes":                   notes,
    }


text = CSV_PATH.read_text(encoding="utf-8-sig", newline="")
reader = csv.DictReader(io.StringIO(text))
old_rows = list(reader)
headers = reader.fieldnames

# 기존 ZZZ 행 제거 (중복 방지: 이 스크립트가 전체 ZZZ 행을 재작성)
non_zzz_rows = [r for r in old_rows if r.get("canonical_series") != PARENT]

new_rows = []

# applied (기존 seed - JSON에 이미 있음)
for en, ja, ko, faction, _ver, notes in ALREADY_APPLIED:
    new_rows.append(make_row(en, ja, ko, True, faction, "applied", "high", notes))

# applied (이번에 새로 seed)
for en, ja, ko, ko_in_aliases, faction, ver, notes in ZZZ_ACCEPT:
    new_rows.append(make_row(en, ja, ko, ko_in_aliases, faction, "applied", "high",
                             f"{notes} [applied] Phase A seed 반영".strip()))

# hold
for en, ja, ko, faction, ver, notes in ZZZ_HOLD:
    new_rows.append(make_row(en, ja, ko, len(ko) > 1, faction, "hold", "medium", notes))

# needs_review
for en, ja, ko, faction, ver, notes in ZZZ_NR:
    new_rows.append(make_row(en, ja, ko, len(ko) > 1, faction, "needs_review", "medium", notes))

all_rows = non_zzz_rows + new_rows
out = io.StringIO()
writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n")
writer.writeheader()
writer.writerows(all_rows)
CSV_PATH.write_text(out.getvalue(), encoding="utf-8-sig", newline="")


# ─── 3. REPORT ─────────────────────────────────────────────────────────────────
zzz_all = [r for r in all_rows if r.get("canonical_series") == PARENT]
by_action: dict[str, int] = {}
for r in zzz_all:
    by_action[r["action"]] = by_action.get(r["action"], 0) + 1

print("ZZZ CSV distribution (Phase A):")
for k, v in sorted(by_action.items()):
    print(f"  {k}: {v}")
print()
print(f"신규 accept seed:         {len(ZZZ_ACCEPT)}")
print(f"hold (CSV only):          {len(ZZZ_HOLD)}")
print(f"needs_review (CSV only):  {len(ZZZ_NR)}")
print(f"Total chars in JSON:      {len(data['characters'])} (was 4)")
print(f"JSON version:             {data['version']}")
print(f"단일명 alias 제거:         Nicole, Ellen, Jane")
