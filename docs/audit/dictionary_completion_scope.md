# 분류 사전 100% 보강 캠페인 — 시리즈별 완료 기준 정의

작성일: 2026-05-10  
브랜치: data/dictionary-completion-campaign  
캠페인 단계: Phase 1 (후보 CSV + 구조 설계 + accept 항목 seed 반영)

---

## 공통 원칙

- **canonical**: 영문 풀네임 (Blue Archive, Genshin Impact 관례 통일). 단, Idolmaster는 일본어 original canonical 유지.
- **ko localization**: 나무위키 한국어 표제어 기준. 공식 한국어 로컬라이즈가 있으면 우선.
- **ja localization**: 원작 표기(한자/가나). 영문 IP인 경우 영문 그대로.
- **en localization**: 공식 EN 표기. 없으면 transliteration.
- **aliases**: canonical + ko/ja/en을 포함한 검색용 추가 표기.  
  일반명사·묘사·장르 태그는 aliases에서 제외.
- **parent_series**: character/group 필수 필드. series 항목에는 없음.
- **hold 처리**: 표기 불확실·동명이인 충돌 위험·공식 출처 미확인 항목.
- **needs_review 처리**: 커뮤니티 표기 혼재·비공식 약칭 단독 사용 위험 항목.
- **의상/버전(복장명, 학기 버전 등)**: 별도 canonical 금지. aliases 또는 evidence로 보존.
- **R-18·묘사·인기 태그**: seed 금지. reject로 분류.

---

## 1. Blue Archive (블루 아카이브)

### 완료 기준
- 나무위키 「블루 아카이브/등장인물」 기준 **플레이어블 캐릭터 전원** (현재 v1.7.0에서 122명)
- NPC 중 이름이 알려진 주요 등장인물 (선생님, Sensei 제외)
- 학교(트리니티, 게헨나 등) group seed
- 동아리·소속 부대 group seed (이미 9개 groups 존재)

### 포함 범위
- 현재 일본/글로벌 서버 기준 출시된 플레이어블 캐릭터 전원
- 동일 캐릭터의 다른 복장(로리·여름·마이드·수영복 등)은 **별도 canonical 생성 금지**,  
  aliases에 "(복장명)" 형태로 포함

### 제외 범위
- 아직 공개되지 않은 캐릭터(스포일러 레벨)
- 일반 병사·군중 NPC
- R-18 파생 묘사 태그

### alias 허용 원칙
- jp_full (한자+가나 풀네임) + jp_short (성 또는 이름 단독) + en_full + ko_full + ko_short
- 최대 5개 alias (구조 제한 준수)
- 대안 로마자 표기 (예: 와시미/鷲見 vs 수미) 금지

### 다음 증분 체크
- 2026년 1~5월 신규 캐릭터 추가 여부 확인 필요

---

## 2. Trickcal Re:VIVE (트릭컬 Re:VIVE)

### 완료 기준
- 나무위키 「트릭컬 리:바이브/캐릭터」 기준 전 캐릭터
- EN/JA 표기 공식 확인된 항목만 accept

### 포함 범위
- 현재 출시된 플레이어블 캐릭터 전원
- 주요 세력/종족이 분류에 유용하면 group 후보화

### 제외 범위
- EN 공식 표기 불확실 항목 → hold
- 단일명(단독 이름만 있는 캐릭터)은 parent_series 명확한 경우에만 accept

### 현재 누락 분석
- 30명 기록 중 ja_localization 21개 누락 → 우선 보강 대상
- en_localization 4개 누락 → 공식 확인 후 accept

### alias 허용 원칙
- ko (나무위키 표제어) + ja (원문) + en (공식 또는 transliteration)
- 단일명 alias는 parent_series scope로만 사용

---

## 3. Genshin Impact (원신)

### 완료 기준
- 나무위키 「원신/등장인물」 기준 **플레이어블 캐릭터 전원**
- 현재 v5.x 기준 약 90명 이상 → 현재 7명만 등록, 대규모 보강 필요

### 포함 범위
- 모든 플레이어블 캐릭터 (주인공 제외 또는 별도 처리)
- 주요 세력(나시다·풍마 기사단 등)은 evidence로 보존, group seed는 phase 2에서

### 제외 범위
- NPC (공식 이름 있어도 분류에 무관한 경우 제외)
- Traveler(공주/왕자) — 성별 variants 처리 방침 별도 결정 필요 → hold

### alias 허용 원칙
- en_name (공식 영문) + ko_name (나무위키 한국어) + ja_name (원문 한자/가나)
- 중국어 원문도 evidence에 보존

### 우선순위
- 현재 7명 외 나머지 ~83명 → phase 1 대상
- 최신 캐릭터(나타 지역 이후)는 공식 표기 확인 후 accept

---

## 4. 붕괴: 스타레일 (Honkai: Star Rail)

### 완료 기준
- 나무위키 「붕괴: 스타레일/등장인물」 기준 **플레이어블 캐릭터 전원**
- 현재 v3.x 기준 약 70~80명 → 현재 5명, 대규모 보강 필요

### 포함 범위
- 모든 플레이어블 캐릭터
- Trailblazer(개척자) — 성별 variants → hold

### 제외 범위
- NPCPath/Aeon 개념 태그 (분류 오용 가능성 높음) → reject

### alias 허용 원칙
- en_name + ko_name + ja_name
- HoYoLAB/나무위키 기준 우선

---

## 5. 젠레스 존 제로 (Zenless Zone Zero)

### 완료 기준
- 나무위키 「젠레스 존 제로/등장인물」 기준 **플레이어블 캐릭터 전원**
- 현재 v1.x 기준 약 30~40명 → 현재 4명, 대규모 보강 필요

### 포함 범위
- 모든 플레이어블 캐릭터
- 주요 팩션(빅토리아 하우스키핑 등)은 group 후보화

### alias 허용 원칙
- en_name + ko_name + ja_name
- 팩션 alias는 공식 EN 표기 기준

---

## 6. 명조 (Wuthering Waves)

### 완료 기준
- 나무위키 「명조: 워더링 웨이브」 기준 **플레이어블 캐릭터 전원**
- 현재 28명 → v2.x 기준 약 30~35명 예상, 비교적 가까운 편

### 포함 범위
- 모든 플레이어블 캐릭터
- 주요 세력(베레스트럼 등)은 phase 2에서

### alias 허용 원칙
- en_name + ko_name + ja_name
- 중국어 원문은 evidence 보존

---

## 7. 아이돌 마스터 (THE iDOLM@STER)

### 완료 기준 (Phase 1)
- 브랜드별 **후보 CSV 100% 수집** (seed 반영은 검수 완료분만)
- Phase 1에서 대규모 자동 seed 금지

### 포함 범위
- 765PRO: 13 오리지널 아이돌 — Phase D-2 (accept 가능)
- Cinderella Girls: 전 캐릭터 후보 CSV 작성 → 검수 후 단계적 반영
- Million Live!: 전 캐릭터 후보 CSV → 단계적 반영
- SideM: 전 캐릭터 후보 CSV → 단계적 반영
- Shiny Colors: 전 캐릭터 후보 CSV → 단계적 반영
- Gakuen iDOLM@STER: 전 캐릭터 후보 CSV → 단계적 반영

### 대표 IP 관계
- 모든 하위 브랜드의 canonical_series는 해당 브랜드명 사용
  (예: "THE iDOLM@STER Cinderella Girls")
- 나무위키 표기 "아이돌 마스터" = 대표 IP 명칭
- 하위 시리즈명은 lower_series/notes에 보존, 대표 IP를 흔들지 않음

### 알려진 충돌
- illumination STARS: 밀리마스·샤니마스 양쪽 존재 → parent_series로 구분
- 츠바사(翼): 이부키 츠바사(ML) vs 카시와기 츠바사(SideM) → 단독 alias 금지
- 765 MILLIONSTARS vs 765PRO → parent_series 분리 필수

### alias 허용 원칙
- canonical: JA original (한자/가나)
- ko: 나무위키 한국어 표제어
- en: 공식 transliteration
- 에이전시·유닛 alias: 영문 원문 + ko 팬덤 표기

---

## 전체 Phase 1 완료 기준 정의

| 시리즈 | Phase 1 목표 | 예상 규모 | 현재 |
|---|---|---|---|
| Blue Archive | 신규 캐릭터 추가 + 누락 보강 | ~130명 | 122명 |
| Trickcal Re:VIVE | ja/en 누락 보강 + 신규 | ~35명 | 30명 |
| Genshin Impact | 플레이어블 전원 | ~90명 | 7명 |
| Honkai: Star Rail | 플레이어블 전원 | ~75명 | 5명 |
| Zenless Zone Zero | 플레이어블 전원 | ~35명 | 4명 |
| Wuthering Waves | 신규 캐릭터 보강 | ~35명 | 28명 |
| Idolmaster 765 | 13명 accept | 13명 | 0명 |
| Idolmaster 기타 | 후보 CSV 수집 | 500명+ | 0명 |

---

## 다음 Phase 제안

| Phase | 내용 |
|---|---|
| Phase 1 | 후보 CSV + accept 항목 seed 반영 (이번 브랜치) |
| Phase 2 | 검수 완료 hold 항목 accept 전환 |
| Phase 3 | Idolmaster 765 이외 브랜드 단계적 seed 반영 |
| Phase 4 | group/faction seed 보강 (세력·소속·유닛) |
