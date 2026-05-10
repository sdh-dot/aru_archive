# Idolmaster Tag Pack Structure Notes (Phase D)

## 왜 Idolmaster는 group/unit/entity seed가 중요한가

Idolmaster 팬덤은 캐릭터 단위뿐 아니라 **유닛(unit)** 단위 소비가 매우 강하다.
작화/동인/픽시브 검색 시 "란티카", "노크칠", "New Generations" 등 유닛 태그가
개별 캐릭터 태그 못지않게 자주 쓰인다. Blue Archive의 부대·동아리와 같은 위상이다.

에이전시(사무소) 또한 팬 검색의 핵심 단위다:
- 765프로, 346프로 등은 단독 검색 키워드로 충분히 자립한다.
- 시리즈 canonical과 에이전시 canonical이 다른 경우가 많다.

따라서 Idolmaster는 `groups` 배열을 통해 에이전시와 유닛을 seed하는 장르로 분류한다.

---

## 단일 파일 vs 브랜드별 파일

| 항목 | 단일 파일 | 브랜드별 파일 |
|---|---|---|
| 통합 alias 관리 | 쉬움 | 약간 복잡 |
| 규모 관리 | 파일 비대화 위험 (CG만 200+ 캐릭터) | 브랜드별 독립 |
| 테스트 분리 | 어려움 | pack_id별 테스트 가능 |
| repo 관례 | genshin/hsr/zzz 각각 분리 | 일치 |
| 브랜드별 canonical 정책 차이 | 반영 어려움 | 자연스럽게 분리 |

**결정: 브랜드별 파일 (Option B)**

Genshin Impact / Honkai: Star Rail / Zenless Zone Zero가 별도 파일인 것과 동일한
관례를 따른다. Cinderella Girls는 200+ 캐릭터가 있으므로 단일 파일 구조로는 관리 불가.

---

## Pack 파일 목록 (Phase D 생성)

| 파일 | 브랜드 | 시리즈 canonical | 에이전시 |
|---|---|---|---|
| `idolmaster_765.json` | THE iDOLM@STER | THE iDOLM@STER | 765PRO |
| `idolmaster_cinderella_girls.json` | Cinderella Girls | THE iDOLM@STER Cinderella Girls | 346PRO |
| `idolmaster_million_live.json` | Million Live! | THE iDOLM@STER Million Live! | 765 MILLIONSTARS |
| `idolmaster_sidem.json` | SideM | THE iDOLM@STER SideM | 315PRO |
| `idolmaster_shiny_colors.json` | Shiny Colors | THE iDOLM@STER Shiny Colors | 283PRO |
| `idolmaster_gakuen.json` | Gakuen iDOLM@STER | Gakuen iDOLM@STER | Hatsuboshi Gakuen |

---

## 배열 분리 방침

```
series[]      — 시리즈/브랜드 (1개 per 파일)
groups[]      — 에이전시 + 유닛 (characters와 혼재 금지)
characters[]  — 개별 아이돌 캐릭터
```

`characters`와 `groups`는 같은 배열에 섞지 않는다.
현 schema의 `tag_type` 컬럼 (`series` / `character` / `group`) 으로 구분.

**캐릭터 canonical 정책: JA canonical**

Blue Archive와 동일. Idolmaster는 일본 원작 게임이며
일본어 이름이 사실상 표준이다 (`天海春香`, `如月千早` 등).
KO/EN 표기는 `localizations` 필드로 관리.

---

## 에이전시 JA localization 특이사항

`765 MILLIONSTARS` — 공식 JA 표기가 영문 그대로이나, locale-mismatch lint
(≥30% CJK/가나 요건)를 통과하기 위해 `ja: "765ミリオンスターズ"` 로 저장.
이는 팬 커뮤니티에서도 통용되는 표기이며, 별칭 alias에 원문 `765 MILLIONSTARS`도 포함한다.

`SideM`, `283PRO`, `315PRO` 등 영문 위주 에이전시 이름은
`{숫자}プロ` 패턴으로 JA localization 처리 (가나 ≥30% 충족).

---

## Phase D 범위 제한 이유

Cinderella Girls 단독 200+ 캐릭터, 전체 합산 500+ 캐릭터 이상.
CSV 후보 정리 없이 바로 JSON applied 처리를 하면:
- KO 표기 오류가 대량 발생할 위험
- 테스트 부담 급증
- 추후 수정 시 diff가 거대해짐

따라서 Phase D에서는 구조 설계 + CSV 후보 정리에 집중하고,
브랜드별로 단계적 applied 처리를 진행한다.

---

## 권장 후속 단계

| Phase | 대상 | 내용 |
|---|---|---|
| D-1 (현재) | 전 브랜드 | skeleton JSON + CSV 후보 |
| D-2 | 765PRO | 13 오리지널 캐릭터 applied |
| D-3 | Cinderella Girls | New Generations 등 대표 캐릭터 applied |
| D-4 | Million Live! | illumination STARS 등 대표 캐릭터 applied |
| D-5 | Shiny Colors | 5유닛 캐릭터 applied |
| D-6 | SideM | Jupiter 등 유닛별 applied |
| D-7 | Gakuen iDOLM@STER | 신작 캐릭터 applied |

---

## 알려진 충돌/주의사항

1. **illumination STARS 동명 유닛** — 밀리마스(ML)와 샤니마스(SC) 양쪽에 존재.
   `parent_series` 스코프로 구분 필수.

2. **츠바사 동음이의** — `伊吹翼`(ML Tsubasa Ibuki)와 `柏木翼`(SideM Tsubasa Kashiwagi).
   KO 표기가 모두 "츠바사"이므로 단독 alias 금지, `parent_series` + `canonical` 조합으로 검색.

3. **765 MILLIONSTARS vs 765PRO** — 두 그룹 모두 "765"를 포함.
   `parent_series`로 분리 (ML vs THE iDOLM@STER).

4. **히라가나 포함 캐릭터명** — `高槻やよい`, `三浦あずさ`, `八宮めぐる` 등.
   JA locale 검증 시 히라가나도 CJK/가나 범주에 포함되어 있으므로 문제없음.
