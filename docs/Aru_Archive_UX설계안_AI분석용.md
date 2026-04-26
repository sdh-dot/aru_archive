# Aru Archive UX 보강 설계안 (AI 분석용)

## 메타데이터

- **문서 버전**: 2.0 (UX 보강)
- **기준 문서**: Aru_Archive_설계안_AI분석용.md v1.0
- **작성일**: 2026-04-26
- **목적**: 기존 기술 설계에 UX 설계를 통합한 개발 착수용 문서
- **원칙**: 기존 기술 구조 유지, UX 레이어 추가 및 필요 시 DB/모델 확장

---

## 1. UX 관점 총평

### 1.1 기존 설계의 장점

| 항목 | 평가 |
|------|------|
| 파일 우선 메타데이터 | DB 손실 시에도 파일에서 완전 복구 가능 — 사용자 데이터 안전성 매우 높음 |
| 복사 기반 분류 | 원본 손실 위험 없음 — UX 신뢰도의 기반 |
| Inbox 원본 보존 | 규칙 변경 후 재분류 가능 — 실수 복구의 여지 |
| 어댑터 패턴 | 사이트 추가 시 사용자 경험 일관성 유지 가능 |
| 2단계 저장 플로우 | 상태 추적 UX를 자연스럽게 붙일 수 있는 구조 |

### 1.2 사용성 리스크 (UX 개선 전)

| # | 리스크 | 영향 | 우선순위 |
|---|--------|------|----------|
| R1 | 저장 진행 중 상태를 알 수 없음 | 저장이 됐는지 불명확, 중복 클릭 유발 | 최상 |
| R2 | 분류 결과가 왜 그렇게 나왔는지 불명확 | 사용자 신뢰 저하, 규칙 수정 불가 | 최상 |
| R3 | 잘못된 분류 복구 흐름 없음 | 수백 개 복사본 수동 삭제 필요 | 최상 |
| R4 | 복사 기반 용량 증가 예측 불가 | 디스크 초과 충격, 앱 불신 | 상 |
| R5 | 메타데이터 없는 파일이 그냥 사라짐 | 소중한 이미지 분류 누락 | 상 |
| R6 | 규칙 편집 UI가 개발자식 조건문 | 일반 사용자 접근 불가 | 상 |
| R7 | 브라우저 확장 초기 연결 설정 난이도 | 첫 사용 포기율 상승 | 상 |
| R8 | 우고이라/BMP 파일 여러 개가 따로 보임 | 갤러리 혼란, 동일 작품 중복 표시 | 중 |
| R9 | 메타데이터 출처/신뢰도 불명확 | 잘못된 메타데이터 발견 어려움 | 중 |
| R10 | 다중 페이지 저장 시 부분 실패 처리 없음 | 일부 페이지 누락 인지 불가 | 중 |

### 1.3 핵심 개선 방향

```
1. "지금 무슨 일이 일어나는지" 항상 보여준다  → 상태 표시 / 진행률
2. "왜 이렇게 됐는지" 언제든 확인 가능하게   → 분류 근거 / 메타데이터 출처
3. "실수해도 되돌릴 수 있다"는 안심감         → Undo / 작업 로그
4. "전문 지식 없이도 규칙을 만들 수 있다"     → 초보자 모드 규칙 편집
5. "파일이 아닌 작품 단위로 본다"             → 작품 카드 UI
```

---

## 2. 핵심 사용자 시나리오

### 시나리오 A: 브라우저에서 Pixiv 단일 이미지 저장

```
1. 사용자가 Pixiv 작품 페이지 방문
2. 확장 아이콘 클릭 → 팝업 열림
3. [Aru Archive로 저장] 버튼 클릭
4. 팝업에 진행 상태 표시:
   ✓ 메타데이터 수집 완료
   ↻ 이미지 다운로드 중 (1/1)...
5. 완료:
   ✓ 저장 완료  141100516_p0.jpg
   ✓ 분류 완료  → Classified/작가/作家名/
   [Inbox 보기] [분류 폴더 열기] [Aru Archive 열기]
```

**UX 포인트**: 버튼 클릭 후 1초 이내에 시각적 피드백 필수.

### 시나리오 B: 다중 페이지 작품 저장

```
1. 작품 페이지 방문 (3페이지 작품)
2. [전체 저장 (3장)] 버튼 클릭
3. 팝업 진행률 바:

   저장 중... 2 / 3
   ████████░░ 67%

   p0 ✓ 저장 완료
   p1 ✓ 저장 완료
   p2 ↻ 다운로드 중...

4. 완료 후 요약:
   ✓ 3/3 저장 완료  (+분류 폴더 복사 9개)
   [전체 보기]

   (부분 실패 시)
   ⚠ 2/3 저장 완료, 1개 실패
   p2: 네트워크 오류  [재시도]  [건너뜀]
```

### 시나리오 C: 우고이라 저장

```
1. 우고이라 작품 페이지 방문
2. [Aru Archive로 저장] 클릭
3. 팝업 상태:
   ✓ 메타데이터 수집 (48 프레임, 3.8초)
   ↻ ZIP 다운로드 중... (12.4 MB)
   ↻ WebP 변환 중...
   ✓ 완료
   [미리보기] [분류 폴더 열기]
```

### 시나리오 D: 기존 폴더 가져오기 / 재색인

```
메인 앱 → 도구 → 재색인
→ 폴더 선택 다이얼로그
→ 스캔 시작:
   스캔 중... 1,247 / 3,842 파일
   메타데이터 발견: 1,102개
   메타데이터 없음: 145개 → No Metadata 큐 자동 등록
→ 완료 요약:
   새로 인덱싱: 1,102개
   No Metadata 큐 추가: 145개
   [No Metadata 큐 보기]
```

### 시나리오 E: 검토 후 분류 실행

```
새 파일 저장 → 분류 미리보기 알림 뱃지 표시 (하단 패널)
사용자 클릭 → 분류 미리보기 화면

분류 예정: 12개 파일
생성 복사본: 34개
예상 추가 용량: 412 MB
충돌: 2건

[파일 목록 확인] → 개별 파일별 규칙 / 목적지 확인
[전체 실행] [선택 제외] [규칙 수정] [취소]
```

### 시나리오 F: 잘못된 분류 되돌리기

```
메인 앱 → Recent Jobs → 작업 선택
작업 상세:
  2026-04-26 15:31  Pixiv 141100516 (3페이지)
  원본: Inbox/pixiv/ 3개
  복사본: Classified/ 9개

[복사본 제거] 클릭
→ 확인 다이얼로그:
  "Classified/ 의 복사본 9개를 삭제합니다.
   Inbox 원본은 보존됩니다."
  [삭제 실행] [취소]
→ 완료 후 재분류 제안:
  [새 규칙으로 다시 분류]
```

### 시나리오 G: 메타데이터 없는 파일 복구

```
No Metadata 큐 → 파일 목록 확인
파일 클릭 → 상세:
  원인: Pixiv ID 파일명에서 추출 실패
  파일명: illust_141100516_20260426.jpg
  추정 ID: 141100516 (낮은 신뢰도)
  [이 ID로 Pixiv 메타데이터 가져오기]
  [Pixiv URL 직접 입력]
  [수동 메타데이터 입력]
  [분류 제외 유지]
```

---

## 3. 화면 구조 설계

### 3.1 첫 실행 설정 마법사 (10단계)

```
┌──────────────────────────────────────────────────────────┐
│  Aru Archive 처음 시작하기            2 / 10  [●●○○○○○○○○] │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  📁 Archive 루트 폴더를 선택해주세요                       │
│                                                          │
│  모든 이미지와 설정이 이 폴더에 저장됩니다.                 │
│                                                          │
│  [D:\AruArchive                          ] [찾아보기]     │
│                                                          │
│  자동 생성될 폴더:                                        │
│  ├── Inbox/       (원본 저장)                            │
│  ├── Classified/  (분류 결과)                            │
│  └── aru_archive.db                                      │
│                                                          │
│  ⚠ 충분한 여유 공간이 있는 드라이브를 권장합니다.           │
│  현재 D: 드라이브 여유: 234 GB                            │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                           [이전]  [다음 →]               │
└──────────────────────────────────────────────────────────┘
```

**마법사 단계 목록:**

| 단계 | 화면 내용 | 성공 조건 |
|------|-----------|-----------|
| 1/10 | 시작 환영 화면 + 간략 소개 | — |
| 2/10 | Archive 루트 폴더 선택 | 경로 쓰기 가능 |
| 3/10 | Inbox / Classified 하위 폴더 자동 생성 확인 | 폴더 생성 성공 |
| 4/10 | Native Messaging Host 등록 | 레지스트리 등록 성공 |
| 5/10 | Chrome 확장 연결 확인 | ping 응답 수신 |
| 6/10 | Whale 확장 연결 확인 | ping 응답 수신 (건너뛰기 가능) |
| 7/10 | 기본 분류 규칙 선택 (프리셋) | — |
| 8/10 | 분류 모드 선택 (즉시 / 검토 후) | — |
| 9/10 | Pixiv 저장 테스트 (샘플 작품 URL 입력) | 저장 성공 |
| 10/10 | 설정 완료 요약 | — |

**단계 5/10 브라우저 연결 확인 UI:**
```
┌──────────────────────────────────────────────────────────┐
│  브라우저 연결 확인                       5 / 10          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  🟢 Chrome       연결됨        (버전: 1.0.0)              │
│  🔴 Whale        연결 안 됨                               │
│  🟢 Native Host  등록 완료                                │
│                                                          │
│  Whale 연결이 필요하신 경우:                               │
│  [Whale 연결 설정]  [문제 해결 가이드]                     │
│                                                          │
│  ℹ Chrome만 연결되어도 모든 기능 사용 가능합니다.           │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                    [건너뛰기]  [연결 테스트]  [다음 →]    │
└──────────────────────────────────────────────────────────┘
```

---

### 3.2 메인 화면

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Aru Archive  v1.0          🔔 3       검색: [_________________] [필터 ▾] │
├───────────────────┬─────────────────────────────────┬───────────────────┤
│ 라이브러리         │ 갤러리                           │ 메타데이터 패널    │
│                   │                                 │                   │
│ ▼ 라이브러리       │ [정렬 ▾][그룹 ▾]  [■■■ ▾]   4,217개 │ 141100516_p0.jpg  │
│   📥 Inbox   847  │                                 │                   │
│   🗂 Managed  4.2k │ [작품카드][작품카드][작품카드]   │ ── 작품 정보 ────  │
│   📁 Classified   │ [작품카드][작품카드][작품카드]   │ 제목: タイトル     │
│   ⚠ No Metadata 23│ [작품카드][작품카드][작품카드]   │ 작가: 作家名       │
│   ✗ Failed     5  │                                 │ ID: 141100516      │
│   🕐 Recent Jobs  │                                 │ 페이지: 1 / 3      │
│                   │                                 │                   │
│ ▼ 분류 보기        │                                 │ ── 태그 ──────── │
│   📚 By Series    │                                 │ 🟢 キャラ名        │
│   👤 By Character │                                 │ 🟢 Blue Archive    │
│   🎨 By Author    │                                 │ 🟢 オリジナル      │
│   🏷 By Tag       │                                 │                   │
│                   │                                 │ ── 분류 상태 ──── │
│ ▼ 도구             │                                 │ ✓ 분류됨           │
│   ⚙ 규칙 관리      │                                 │ 규칙: BA 캐릭터    │
│   ✏ 일괄 편집      │                                 │ → Classified/시리즈│
│   🔄 재색인        │                                 │   /Blue Archive/   │
│   ⚙ 설정          │                                 │   キャラ名/        │
│                   │                                 │                   │
│                   │                                 │ [분류 근거 보기]   │
│                   │                                 │ [재분류]           │
│                   │                                 │ [Pixiv 열기]       │
│                   │                                 │ [폴더 열기]        │
├───────────────────┴─────────────────────────────────┴───────────────────┤
│ 🕐 최근 작업: Pixiv 141100516  3페이지 저장 완료  2분 전  [되돌리기] [로그]│
└─────────────────────────────────────────────────────────────────────────┘
```

**작품 카드 (갤러리 그리드 단위):**
```
┌──────────────┐
│  [썸네일]    │  ← 우고이라: 애니메이션 미리보기
│              │
│ 🎬 48f 3.8s  │  ← 유형 배지: 우고이라 / BMP / 다중페이지
└──────────────┘
│ タイトル     │
│ 作家名  p3   │  ← 다중페이지: p3 = 3페이지
│ ✓ 분류됨     │  ← 상태 배지
└──────────────┘
```

---

### 3.3 상세 메타데이터 패널 (우측 패널 확장)

```
┌─────────────────────────────────────────────────────────┐
│ 141100516_p0.jpg                              [✕ 닫기]  │
├─────────────────────────────────────────────────────────┤
│ [대형 미리보기 / 우고이라 플레이어]                       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ 탭: [기본 정보] [태그] [분류 이력] [파일 정보]            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ 작품 제목  タイトル                        🟢 Pixiv 확인 │
│ 작가명    作家名                           🟢 Pixiv 확인 │
│ 작품 ID   141100516                       🟢 Pixiv 확인 │
│ 작품 URL  https://pixiv.net/artworks/...  🟢 Pixiv 확인 │
│ 다운로드  2026-04-26 15:30                🟢 자동       │
│ 페이지    1 / 3                           🟢 자동       │
│           (← p0) (→ p1)                               │
│                                                         │
│ 캐릭터    キャラ名                         🟢 Pixiv 확인 │
│ 시리즈    Blue Archive                    🟢 Pixiv 확인 │
│ 일반 태그  オリジナル, ソロ, ...           🟢 Pixiv 확인 │
│                                                         │
│ [+ 태그 추가]  [✏ 수동 편집]                            │
│                                                         │
│ 신뢰도 범례:  🟢 Pixiv  🟡 파일명 추정  🔵 수동  🔴 누락  │
├─────────────────────────────────────────────────────────┤
│ [분류 근거 보기]  [재분류]  [Pixiv 열기]  [폴더 열기]    │
└─────────────────────────────────────────────────────────┘
```

---

### 3.4 분류 미리보기 화면

```
┌───────────────────────────────────────────────────────────────┐
│ 분류 미리보기                                        [✕]      │
├───────────────────────────────────────────────────────────────┤
│ 분류 예정: 12개  |  생성 복사본: 34개  |  추가 용량: 412 MB   │
│ 충돌: 2건                                   [충돌 먼저 보기]  │
├───────────────────────────────────────────────────────────────┤
│ 파일                  | 적용 규칙          | 복사 위치         │
├───────────────────────┼────────────────────┼───────────────────┤
│ 141100516_p0.jpg      │ BA 캐릭터 분류     │ 시리즈/Blue...    │
│                       │ BA 시리즈 분류     │ 작가/作家名/      │
├───────────────────────┼────────────────────┼───────────────────┤
│ ⚠ 141100517_p0.jpg    │ 충돌: skip 적용    │ 시리즈/Blue... ⚠  │
│   (이미 존재)          │                   │ → 건너뜀 예정     │
├───────────────────────┼────────────────────┼───────────────────┤
│ 141100518_ugoira.webp │ BA 시리즈 분류     │ 시리즈/Blue...    │
└───────────────────────┴────────────────────┴───────────────────┘
│ ☑ 분류 후 No Metadata 큐 파일은 제외                          │
│ ☑ 최대 3개 폴더까지만 복사                                    │
├───────────────────────────────────────────────────────────────┤
│       [충돌 처리 설정]  [규칙 수정]  [취소]  [전체 실행 →]   │
└───────────────────────────────────────────────────────────────┘
```

---

### 3.5 분류 근거 패널

```
┌───────────────────────────────────────────────┐
│ 분류 근거                              [✕]    │
├───────────────────────────────────────────────┤
│ 파일: 141100516_p0.jpg                        │
│                                               │
│ 이 파일은 2개 규칙으로 분류되었습니다.          │
│                                               │
│ 규칙 1: BA 캐릭터 분류         (우선순위: 10) │
│ ──────────────────────────────────────────── │
│ 조건 (AND):                                  │
│   ✓ series_tags에 "Blue Archive" 포함         │
│   ✓ character_tags에 "Rikuhachima Aru" 포함   │
│                                               │
│ 복사 위치:                                    │
│ → Classified/시리즈/Blue Archive/             │
│     Rikuhachima Aru/                          │
│                                               │
│ 규칙 2: 작가 자동 분류         (우선순위: 50) │
│ ──────────────────────────────────────────── │
│ 조건 (AND):                                  │
│   ✓ source_site = "pixiv" (항상 참)           │
│                                               │
│ 복사 위치:                                    │
│ → Classified/작가/作家名/                     │
│                                               │
│ 분류일: 2026-04-26 15:31:04                  │
├───────────────────────────────────────────────┤
│ [규칙 1 수정]  [규칙 2 수정]  [이 파일 재분류] │
└───────────────────────────────────────────────┘
```

---

### 3.6 규칙 편집 화면 — 초보자 모드

```
┌───────────────────────────────────────────────────────────────┐
│ 규칙 편집                      모드: [초보자 ▾] [고급]  [✕]  │
├───────────────────────────────────────────────────────────────┤
│ 규칙 이름: [BA 캐릭터 분류___________]  활성화: [●]           │
│                                                               │
│ ── 조건 설정 ──────────────────────────────────────────────── │
│                                                               │
│ [캐릭터 태그 ▾]  [포함 ▾]  [Rikuhachima Aru_______]  [✕]    │
│ + [시리즈 태그  ▾]  [포함 ▾]  [Blue Archive__________]  [✕]  │
│                                                               │
│ [+ 조건 추가]    조건 결합: [모두 만족 (AND) ▾]               │
│                                                               │
│ ── 저장 위치 ──────────────────────────────────────────────── │
│                                                               │
│ 방식: ● 시리즈/캐릭터 자동 구성   ○ 직접 경로 입력            │
│                                                               │
│ 구성 미리보기:                                                │
│ Classified/시리즈/Blue Archive/Rikuhachima Aru/              │
│                                                               │
│ 충돌 시: [건너뜀 ▾]                                          │
│ 우선순위: [10] (낮을수록 먼저 적용)                            │
│                                                               │
│ ── 적용 미리보기 ──────────────────────────────────────────── │
│ 현재 Inbox에서 이 규칙에 매칭되는 파일: 23개                   │
│ [미리보기 보기]                                               │
├───────────────────────────────────────────────────────────────┤
│                            [취소]  [저장]  [저장 후 즉시 실행] │
└───────────────────────────────────────────────────────────────┘
```

**초보자 모드 프리셋 선택 화면:**
```
┌─────────────────────────────────────────────────────────┐
│ 기본 규칙 프리셋 선택                                    │
├─────────────────────────────────────────────────────────┤
│ ☑ 작가별 분류      → Classified/작가/{작가명}/          │
│ ☑ 시리즈별 분류    → Classified/시리즈/{시리즈명}/      │
│ ☑ 캐릭터별 분류    → Classified/캐릭터/{캐릭터명}/      │
│ ☐ 태그별 분류      → Classified/태그/{태그명}/          │
│   (태그는 복사본이 많이 생길 수 있어 기본 비활성)        │
├─────────────────────────────────────────────────────────┤
│ [+ 직접 규칙 추가]            [선택 완료 →]             │
└─────────────────────────────────────────────────────────┘
```

---

### 3.7 규칙 편집 화면 — 고급 모드

```
┌───────────────────────────────────────────────────────────────┐
│ 규칙 편집                      모드: [초보자] [고급 ▾]  [✕]  │
├───────────────────────────────────────────────────────────────┤
│ rule_id:  [rule-001___]  name: [BA 캐릭터 분류_________]      │
│ priority: [10]  enabled: [●]  logic: [AND ▾]                  │
│                                                               │
│ ── 조건 목록 (JSON 편집 가능) ─────────────────────────────── │
│ [                                                             │
│   {                                                           │
│     "field": "character_tags",                                │
│     "op": "contains",                                         │
│     "value": "Rikuhachima Aru"                                │
│   },                                                          │
│   {                                                           │
│     "field": "series_tags",                                   │
│     "op": "contains",                                         │
│     "value": "Blue Archive"                                   │
│   }                                                           │
│ ]                                                             │
│                                                               │
│ ── dest_template ──────────────────────────────────────────── │
│ [{classified_dir}/시리즈/{series_tags[0]}/{character_tags[0]}]│
│                                                               │
│ 사용 가능한 변수:                                              │
│ {classified_dir} {artist_name} {artist_id} {source_site}     │
│ {artwork_id} {character_tags[0]} {series_tags[0]}            │
│                                                               │
│ on_conflict: [skip ▾]                                        │
├───────────────────────────────────────────────────────────────┤
│ [취소]  [초보자 모드로 전환]  [저장]  [저장 후 즉시 실행]     │
└───────────────────────────────────────────────────────────────┘
```

---

### 3.8 작업 로그 / Recent Jobs 화면

```
┌───────────────────────────────────────────────────────────────┐
│ 최근 작업 로그                        [🗑 오래된 로그 정리]   │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│ 오늘 2026-04-26                                               │
│ ────────────────────────────────────────────────────────────  │
│ 15:31  Pixiv #141100516  3페이지 저장                  ✓ 완료 │
│        원본 3개  |  복사본 9개  |  +24 MB              [▼]   │
│                                                               │
│        ▼ 상세 (펼침)                                         │
│        p0  Inbox/pixiv/141100516_p0.jpg                      │
│            → Classified/시리즈/Blue Archive/キャラ/           │
│            → Classified/작가/作家名/                          │
│            → Classified/캐릭터/キャラ/                        │
│        p1  (동일 구조)                                        │
│        p2  (동일 구조)                                        │
│                                                               │
│        [복사본 제거 (Undo)]  [다시 분류]  [폴더 열기]         │
│                                                               │
│ ────────────────────────────────────────────────────────────  │
│ 14:10  Pixiv #141100480  우고이라 저장                 ✓ 완료 │
│        원본 2개 (ZIP + WebP)  |  복사본 6개  |  +87 MB [▼]   │
│                                                               │
│ ────────────────────────────────────────────────────────────  │
│ 어제 2026-04-25                                               │
│ ────────────────────────────────────────────────────────────  │
│ 22:14  재색인 실행     3,842개 스캔   [로그 보기]     ✓ 완료  │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

---

### 3.9 No Metadata / Failed 화면

```
┌───────────────────────────────────────────────────────────────┐
│ No Metadata  (23개)          [전체 선택]  [일괄 처리 ▾]       │
├───────────────────────────────────────────────────────────────┤
│ 원인별 그룹                                                    │
│                                                               │
│ 📁 Pixiv ID 파일명 추출 실패  (12개)              [그룹 처리] │
│ ─────────────────────────────────────────────────────────── │
│ ☐ illust_12345_abc.jpg   추정ID: 12345 (낮은 신뢰)  [처리]   │
│ ☐ image001.jpg           ID 추출 불가               [처리]   │
│ ...                                                           │
│                                                               │
│ 🌐 Pixiv 페이지 접근 실패  (4개)                  [그룹 처리] │
│ ─────────────────────────────────────────────────────────── │
│ ☐ 141100999_p0.jpg       Pixiv 삭제된 작품         [처리]    │
│                                                               │
│ 📄 지원하지 않는 파일명 형식  (7개)               [그룹 처리] │
│ ─────────────────────────────────────────────────────────── │
│ ☐ 스크린샷_20260101.png                            [처리]    │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│ 선택 파일 처리:                                               │
│ [파일명 재추출]  [Pixiv URL 직접 입력]  [수동 입력]  [제외]   │
└───────────────────────────────────────────────────────────────┘
```

**파일 상세 처리 다이얼로그:**
```
┌───────────────────────────────────────────────┐
│ 메타데이터 복구: illust_141100516_abc.jpg      │
├───────────────────────────────────────────────┤
│ 추정 Pixiv ID: 141100516 (낮은 신뢰)          │
│                                               │
│ ○ 이 ID로 Pixiv에서 메타데이터 가져오기        │
│   → https://pixiv.net/artworks/141100516      │
│   [가져오기 실행]                             │
│                                               │
│ ○ Pixiv URL 직접 입력:                        │
│   [https://______________________]            │
│   [가져오기]                                  │
│                                               │
│ ○ 수동 입력 (최소 필드만)                     │
│   작가명: [_________]                         │
│   작품 제목: [_________]                      │
│   [저장 (출처: 수동)]                         │
│                                               │
│ ○ 영구 제외 (분류 없이 보존)                  │
│   [제외로 표시]                               │
├───────────────────────────────────────────────┤
│                    [취소]                     │
└───────────────────────────────────────────────┘
```

---

### 3.10 설정 화면

```
┌───────────────────────────────────────────────────────────────┐
│ 설정                                                   [✕]   │
├──────────────┬────────────────────────────────────────────────┤
│ 일반         │ ── 분류 동작 ──────────────────────────────── │
│ 저장 경로    │                                               │
│ 분류 설정    │ 분류 모드:                                    │
│ 브라우저 연결│   ● 검토 후 분류  (권장, 기본값)              │
│ 고급         │   ○ 즉시 자동 분류                            │
│              │                                               │
│              │ 복사 제한:                                    │
│              │   ☑ 동일 파일 최대 복사 폴더 수: [5 ▾]개      │
│              │   ☑ 일반 태그(ByTag)는 자동 분류 제외         │
│              │   ☑ 기본 자동 분류 대상:                      │
│              │      ☑ ByAuthor  ☑ BySeries  ☑ ByCharacter  │
│              │      ☐ ByTag  (수동 분류만 허용)              │
│              │                                               │
│              │ 중복 감지:                                    │
│              │   ● SHA-256 해시 비교   ○ 파일명 비교         │
│              │                                               │
│              │ Undo 보존 기간:                               │
│              │   [30일 ▾]  (이후 로그 자동 삭제)             │
│              │                                               │
│              │ WebP 변환 품질: [90___] (0-100)               │
│              │ 썸네일 크기: [200___] px                      │
└──────────────┴────────────────────────────────────────────────┘
```

---

## 4. 상태 표시 설계

### 4.1 저장 진행 상태 — 브라우저 확장 팝업

**상태 순서 및 표시 방식:**

| 상태 ID | 표시 텍스트 | 아이콘 | 상태 색상 |
|---------|------------|--------|-----------|
| `pending` | 저장 요청 대기 중 | ⏳ | 회색 |
| `collecting` | 메타데이터 수집 중 | 🔄 | 파랑 |
| `downloading` | 이미지 다운로드 중 ({n}/{total}) | ↓ | 파랑 |
| `embedding` | 메타데이터 기록 중 | ✍ | 파랑 |
| `classifying` | 분류 규칙 적용 중 | 🗂 | 파랑 |
| `copying` | 분류 폴더 복사 중 | 📋 | 파랑 |
| `done` | 저장 완료 | ✅ | 초록 |
| `partial_fail` | 일부 실패 ({n}/{total} 저장됨) | ⚠️ | 노랑 |
| `failed` | 저장 실패 | ❌ | 빨강 |

**완료 후 팝업:**
```
┌─────────────────────────────────────────┐
│ ✅ 저장 완료                            │
│                                         │
│ Blue Archive / Rikuhachima Aru          │
│ 3페이지 저장  |  복사본 9개  |  +24 MB  │
│                                         │
│ [Inbox 열기]  [분류 폴더 열기]          │
│ [Aru Archive 열기]  [로그 보기]         │
└─────────────────────────────────────────┘
```

**부분 실패 팝업:**
```
┌─────────────────────────────────────────┐
│ ⚠️ 2/3 저장 완료                        │
│                                         │
│ ✅ p0  저장 완료                        │
│ ✅ p1  저장 완료                        │
│ ❌ p2  네트워크 타임아웃                 │
│                                         │
│ [p2 재시도]  [건너뜀]  [로그 보기]      │
└─────────────────────────────────────────┘
```

### 4.2 메인 앱 하단 상태 바

```
하단 상태 바 (항상 표시):
┌─────────────────────────────────────────────────────────────────┐
│ [📥 Inbox: 847] [🗂 분류 미리보기 대기: 12] [⚠ No Metadata: 23]│
│                                    저장 중: p1/3 ↓ 8.2 MB/s    │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 오류 상태 처리

| 오류 유형 | 표시 방식 | 사용자 액션 |
|-----------|-----------|-------------|
| 네트워크 타임아웃 | 팝업 내 인라인 오류 | [재시도] [건너뜀] |
| Pixiv 로그인 필요 | 팝업 경고 배너 | [Pixiv 열기 (로그인)] |
| 디스크 공간 부족 | 모달 경고 | [설정 열기] [취소] |
| 메타데이터 임베딩 실패 | No Metadata 큐 자동 추가 | No Metadata 화면에서 처리 |
| Native Host 연결 실패 | 팝업 오류 + 가이드 링크 | [문제 해결 가이드] |

---

## 5. 자동 분류 UX

### 5.1 즉시 분류 vs 검토 후 분류 비교

| 항목 | 즉시 분류 | 검토 후 분류 (기본값) |
|------|-----------|----------------------|
| 실행 타이밍 | 저장 직후 자동 | 사용자 확인 후 |
| 미리보기 | 없음 | 분류 미리보기 화면 표시 |
| 용량 예측 | 사후 확인 | 실행 전 표시 |
| 충돌 처리 | 설정값 자동 적용 | 파일별 선택 가능 |
| 대상 사용자 | 규칙을 완전히 신뢰하는 사용자 | 규칙 초보 / 신중한 사용자 |

**모드 전환:** 설정 화면 또는 분류 미리보기 화면에서 즉시 변경 가능.

### 5.2 분류 미리보기 데이터 모델

```python
@dataclass
class ClassifyPreview:
    preview_id: str              # UUID
    generated_at: str            # ISO8601
    items: list[ClassifyPreviewItem]
    total_source_files: int
    total_copies: int
    estimated_bytes: int
    conflicts: list[ConflictInfo]
    max_copies_per_file: int     # 설정값 반영

@dataclass
class ClassifyPreviewItem:
    artwork_db_id: int
    inbox_path: str
    file_size_bytes: int
    matched_rules: list[MatchedRule]
    dest_paths: list[str]       # 생성될 복사본 경로 목록
    conflicts: list[ConflictInfo]
    excluded: bool               # 사용자가 이 파일을 제외했는지

@dataclass
class MatchedRule:
    rule_id: str
    rule_name: str
    dest_path: str
    matched_conditions: list[str]  # "series_tags contains 'Blue Archive'" 형식 텍스트

@dataclass
class ConflictInfo:
    dest_path: str
    conflict_type: str           # 'file_exists' | 'hash_duplicate'
    existing_file_hash: str | None
    resolution: str              # 'skip' | 'overwrite' | 'rename' | 'pending_user'
```

### 5.3 복사 용량 UX 계산

```python
# 분류 미리보기 생성 시 계산
def calculate_preview_stats(items: list[ClassifyPreviewItem]) -> dict:
    total_copies = sum(len(i.dest_paths) for i in items if not i.excluded)
    estimated_bytes = sum(
        i.file_size_bytes * len(i.dest_paths)
        for i in items if not i.excluded
    )
    conflicts = [c for i in items for c in i.conflicts]
    return {
        'total_source_files': len([i for i in items if not i.excluded]),
        'total_copies': total_copies,
        'estimated_bytes': estimated_bytes,
        'estimated_human': format_bytes(estimated_bytes),  # "412 MB"
        'conflict_count': len(conflicts),
    }
```

### 5.4 복사 제한 정책 (설정 화면 연동)

```python
@dataclass
class ClassifyPolicy:
    max_copies_per_file: int = 5         # 동일 파일 최대 복사 폴더 수
    auto_classify_by_tag: bool = False   # ByTag 자동 분류 여부
    auto_classify_targets: list[str] = field(
        default_factory=lambda: ['ByAuthor', 'BySeries', 'ByCharacter']
    )
    manual_only_tag: bool = True         # 일반 태그는 수동 분류만
```

---

## 6. 규칙 편집 UX

### 6.1 초보자 모드 — 필드/연산자 매핑

**드롭다운 레이블 → 내부 field 값:**

| UI 레이블 | 내부 field |
|-----------|------------|
| 작가 ID | artist_id |
| 작가명 | artist_name |
| 캐릭터 태그 | character_tags |
| 시리즈 태그 | series_tags |
| 일반 태그 | tags |
| 출처 사이트 | source_site |
| 작품 ID | artwork_id |

**드롭다운 연산자 → 내부 op 값:**

| UI 레이블 | 내부 op |
|-----------|---------|
| 포함 | contains |
| 일치 | eq |
| 포함 (목록) | in |
| 시작 | startswith |
| 정규식 (고급만) | regex |

### 6.2 문장형 규칙 편집 UI 구조

```
[ 조건 필드 ▾ ] 에 [ 연산자 ▾ ] [ 값 입력 ] 가 있으면
↓
[ 저장 위치 방식 ▾ ] 폴더로 복사

방식 옵션:
  시리즈/캐릭터 자동  → {classified_dir}/시리즈/{series}/캐릭터/{char}/
  작가별              → {classified_dir}/작가/{artist_name}/
  직접 경로 입력      → [경로 직접 입력]
```

### 6.3 프리셋 규칙 정의 (내장)

```python
BUILTIN_PRESETS = [
    ClassifyRule(
        rule_id='preset-author',
        name='작가별 분류 (기본)',
        priority=100,
        conditions=[Condition('source_site', 'eq', 'pixiv')],
        dest_template='{classified_dir}/작가/{artist_name}',
        on_conflict='skip',
    ),
    ClassifyRule(
        rule_id='preset-series',
        name='시리즈별 분류 (기본)',
        priority=50,
        conditions=[Condition('series_tags', 'contains', '__any__')],
        dest_template='{classified_dir}/시리즈/{series_tags[0]}',
        on_conflict='skip',
    ),
    ClassifyRule(
        rule_id='preset-character',
        name='캐릭터별 분류 (기본)',
        priority=40,
        conditions=[Condition('character_tags', 'contains', '__any__')],
        dest_template='{classified_dir}/캐릭터/{character_tags[0]}',
        on_conflict='skip',
    ),
]
# __any__: 해당 필드에 값이 하나라도 있으면 매칭
```

---

## 7. 작업 로그와 Undo 설계

### 7.1 작업 단위 정의

- **1 작업(Job)** = 브라우저에서 1회 저장 요청 (단일/다중 페이지 무관)
- **1 분류 작업** = Classifier가 1회 실행된 결과 (수동 재분류 포함)
- Undo는 **분류 작업 단위**로 실행 (복사본 생성 단위로 롤백)

### 7.2 Undo 가능 범위와 제한

| 항목 | 정책 |
|------|------|
| Inbox 원본 | 삭제하지 않음 (항상 보존) |
| Classified 복사본 | 삭제 가능 (Undo 대상) |
| 사용자 수동 수정 파일 | 삭제 전 개별 확인 다이얼로그 |
| Undo 보존 기간 | 기본 30일 (설정 가능: 7일/30일/90일/무제한) |
| Undo 불가 케이스 | 사용자가 복사본을 외부에서 이동/삭제한 경우 → 경고 후 스킵 |

### 7.3 Undo 실행 흐름

```
[복사본 제거] 클릭
→ 검증: 각 copy_records 경로 존재 여부 확인
→ 불일치 발견 시:
   "3개 파일이 이미 없거나 변경되었습니다. 나머지 6개만 삭제합니다."
   [계속] [취소]
→ 삭제 실행 (Classified 복사본만)
→ undo_entries.undo_status = 'done' 으로 업데이트
→ 빈 폴더 자동 정리 (옵션)
→ 완료 알림: "복사본 9개 제거 완료. Inbox 원본 3개는 보존됨."
→ [새 규칙으로 다시 분류] 버튼 제공
```

### 7.4 로그 보존 정책

```python
def cleanup_expired_undo_entries(db, retention_days: int):
    """retention_days 이전 로그 삭제. undo_status='available'인 항목만."""
    cutoff = datetime.now() - timedelta(days=retention_days)
    db.execute(
        "DELETE FROM undo_entries WHERE created_at < ? AND undo_status != 'available'",
        (cutoff.isoformat(),)
    )
    # undo_status='available'인 오래된 항목: 경고만, 삭제 안 함
```

---

## 8. 메타데이터 UX

### 8.1 메타데이터 Provenance 모델

```python
@dataclass
class MetadataProvenance:
    field: str         # 'artwork_title', 'artist_name', 'character_tags', ...
    value: Any         # 실제 값
    source: str        # 아래 표 참조
    confidence: str    # 'high' | 'medium' | 'low' | 'manual'
    captured_at: str   # ISO8601
    raw_value: Any     # 파싱 전 원본 (디버깅용)
```

**source 값 정의:**

| source 값 | UI 표시 | 배지 색상 | 신뢰도 |
|-----------|---------|-----------|--------|
| `pixiv_api` | Pixiv API | 🟢 초록 | high |
| `pixiv_dom` | Pixiv 페이지 | 🟢 초록 | high |
| `filename_parse` | 파일명 추정 | 🟡 노랑 | medium/low |
| `user_input` | 수동 입력 | 🔵 파랑 | manual |
| `saucenao` | SauceNao (미래) | 🟣 보라 | medium |
| `missing` | 누락 | 🔴 빨강 | — |

### 8.2 파일 내 Provenance 저장 방식

메타데이터 JSON에 `_provenance` 필드 추가 (파일에 함께 임베딩):

```json
{
  "schema_version": "1.0",
  "artwork_title": "タイトル",
  "artist_name": "作家名",
  "_provenance": {
    "artwork_title":   {"source": "pixiv_api",      "confidence": "high",   "captured_at": "2026-04-26T15:30:00+09:00"},
    "artist_name":     {"source": "pixiv_api",      "confidence": "high",   "captured_at": "2026-04-26T15:30:00+09:00"},
    "character_tags":  {"source": "user_input",     "confidence": "manual", "captured_at": "2026-04-26T16:00:00+09:00"},
    "artwork_id":      {"source": "filename_parse", "confidence": "medium", "captured_at": "2026-04-26T15:30:00+09:00"}
  }
}
```

### 8.3 수동 편집 UX

- 필드 클릭 → 인라인 편집 전환
- 저장 시 자동으로 `source=user_input`, `confidence=manual` 기록
- 수동 편집한 필드는 파란색 배지 표시

### 8.4 일괄 편집 UX

```
도구 → 메타데이터 일괄 편집

필터: [작가명: 作家名 ▾]  [시리즈: Blue Archive ▾]  → 12개 파일 선택됨

선택된 파일에 적용:
  캐릭터 태그 추가: [Rikuhachima Aru________]  [추가]
  시리즈 태그 변경: [Blue Archive___________]  [일괄 변경]

[미리보기]  [적용]
```

---

## 9. 특수 파일 UX

### 9.1 작품 카드 단위 표시 방식

내부적으로 여러 파일이 존재해도 UI에서는 **1 작품 = 1 카드**로 표시.
카드에 유형 배지를 붙여 파일 구성 명시.

**우고이라 카드:**
```
┌──────────────────────┐
│  [WebP 애니메이션]   │
│  48f / 3.8s          │
├──────────────────────┤
│ タイトル             │
│ 作家名               │
│ 🎬 우고이라          │  ← 유형 배지
│ ZIP ✓  WebP ✓        │  ← 파일 상태
│ ✓ 분류됨            │
└──────────────────────┘
```

**다중 페이지 카드:**
```
┌──────────────────────┐
│  [p0 썸네일]    3P   │  ← 우상단: 총 페이지 수
├──────────────────────┤
│ タイトル             │
│ 作家名               │
│ 📄 3페이지           │  ← 유형 배지
│ ✓ 분류됨            │
└──────────────────────┘
```

카드 클릭 시 상세 패널에서 페이지 전환 UI 제공 (`← p0  p1  p2 →`).

### 9.2 우고이라 파일 구성 표시 (상세 패널)

```
파일 정보 탭:
┌─────────────────────────────────────────────┐
│ 유형: 우고이라                               │
│                                             │
│ 원본 (ZIP)  ✓ 보존됨                        │
│   141100480_ugoira.zip  |  12.4 MB          │
│                                             │
│ 메타데이터  ✓ 기록 완료                     │
│   141100480_ugoira.zip.aru.json             │
│                                             │
│ 관리본 (WebP)  ✓ 생성됨                     │
│   141100480_ugoira.webp  |  3.2 MB          │
│   48 프레임  /  3.8초                       │
│                                             │
│   [WebP 재생성]  [원본 ZIP 열기]            │
└─────────────────────────────────────────────┘
```

### 9.3 sidecar 파일 노출 정책

- **.aru.json sidecar**: UI에 노출하지 않음. 파일 정보 탭에서 "메타데이터 기록 완료"로만 표시.
- 갤러리 그리드: sidecar 파일을 독립 항목으로 표시하지 않음.
- 파일 탐색기 연동(폴더 열기) 시에는 sidecar가 보일 수 있음 — 이는 허용.

---

## 10. UX MVP 제안

### 10.1 1차 MVP 필수 UX (Phase 1~5와 병행)

| # | UX 기능 | 근거 |
|---|---------|------|
| 1 | 저장 진행 상태 표시 (브라우저 팝업) | 없으면 저장 여부 불명확, 중복 클릭 유발 |
| 2 | 저장 완료 후 폴더 열기 버튼 | 기본 사용성 |
| 3 | 분류 미리보기 + 검토 후 분류 모드 | 잘못된 복사본 대량 생성 방지 |
| 4 | 작업 로그 (save_jobs + undo_entries) | Undo의 기반 데이터 |
| 5 | Undo — 복사본 제거 | 복사 기반 분류의 필수 안전장치 |
| 6 | No Metadata 큐 목록 화면 | 누락 파일 방치 방지 |
| 7 | 파일별 분류 근거 보기 | 분류 결과 신뢰도의 핵심 |
| 8 | 충돌 발생 시 사용자 선택 다이얼로그 | 자동 skip으로 누락 발생 방지 |
| 9 | 기본 규칙 프리셋 (작가/시리즈/캐릭터) | 규칙 0개에서 시작 방지 |
| 10 | 첫 실행 설정 마법사 | Native Host 연결 실패율 감소 |

### 10.2 2차 개발 UX

| # | UX 기능 | 이유 |
|---|---------|------|
| 11 | 메타데이터 Provenance 배지 UI | 있으면 좋지만 1차엔 텍스트로 대체 가능 |
| 12 | 일괄 메타데이터 편집 | 단일 편집이 먼저 |
| 13 | 고급 규칙 편집기 (regex/JSON) | 초보자 모드 검증 후 |
| 14 | 저장공간 사용량 대시보드 | 분류 로그로 대체 가능 |
| 15 | No Metadata → Pixiv URL 자동 가져오기 | 수동 입력으로 우선 대체 |
| 16 | 재색인 진행 UI (상세) | 기본 완료 알림으로 우선 대체 |

### 10.3 후순위 고급 UX

| # | UX 기능 |
|---|---------|
| 17 | SauceNao 연동 메타데이터 자동 복구 |
| 18 | X(트위터) 어댑터 UI |
| 19 | 저장 기록 통계 대시보드 |
| 20 | 다크 모드 |
| 21 | 태그 자동완성 |
| 22 | 외부 이미지 뷰어 연동 |

---

## 11. 기존 기술 설계에 반영할 변경점

### 11.1 신규 DB 테이블

#### save_jobs — 저장 작업 추적

```sql
CREATE TABLE save_jobs (
    job_id          TEXT PRIMARY KEY,    -- UUID
    created_at      TEXT NOT NULL,
    source_site     TEXT NOT NULL,
    artwork_id      TEXT NOT NULL,
    artwork_title   TEXT,
    total_pages     INTEGER DEFAULT 1,
    status          TEXT DEFAULT 'pending',
    -- pending|collecting|downloading|embedding|classifying|copying|done|partial_fail|failed
    pages_done      INTEGER DEFAULT 0,
    pages_failed    INTEGER DEFAULT 0,
    classify_mode   TEXT DEFAULT 'review', -- 'immediate' | 'review'
    completed_at    TEXT,
    error_message   TEXT
);
```

#### job_pages — 페이지별 상태

```sql
CREATE TABLE job_pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES save_jobs(job_id) ON DELETE CASCADE,
    page_index  INTEGER NOT NULL,
    status      TEXT DEFAULT 'pending',
    -- pending|downloading|embedding|done|failed
    inbox_path  TEXT,
    error       TEXT,
    started_at  TEXT,
    done_at     TEXT
);
```

#### undo_entries — Undo 가능한 분류 작업 로그

```sql
CREATE TABLE undo_entries (
    entry_id      TEXT PRIMARY KEY,  -- UUID
    job_id        TEXT REFERENCES save_jobs(job_id),
    action        TEXT NOT NULL,     -- 'auto_classify' | 'manual_classify' | 'reindex_classify'
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,     -- created_at + retention_days
    artwork_id    TEXT,
    source_site   TEXT,
    undo_status   TEXT DEFAULT 'available'
    -- available | partial | expired | done
);
```

#### copy_records — 복사본 기록 (classify_log 대체/확장)

```sql
CREATE TABLE copy_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id            TEXT NOT NULL REFERENCES undo_entries(entry_id),
    artwork_db_id       INTEGER REFERENCES artworks(id),
    src_path            TEXT NOT NULL,
    dest_path           TEXT NOT NULL,
    rule_id             TEXT,
    file_hash           TEXT NOT NULL,     -- SHA-256, Undo 시 검증용
    manually_modified   INTEGER DEFAULT 0, -- 사용자가 외부에서 수정했는지
    copied_at           TEXT NOT NULL
);
```

#### metadata_provenance — 필드별 메타데이터 출처

```sql
CREATE TABLE metadata_provenance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artwork_db_id INTEGER NOT NULL REFERENCES artworks(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    value_text  TEXT,              -- JSON 직렬화
    source      TEXT NOT NULL,
    -- pixiv_api|pixiv_dom|filename_parse|user_input|saucenao|missing
    confidence  TEXT NOT NULL,     -- high|medium|low|manual
    captured_at TEXT NOT NULL,
    raw_value   TEXT               -- 파싱 전 원본 (디버깅용)
);
CREATE INDEX idx_provenance_artwork ON metadata_provenance(artwork_db_id);
```

#### no_metadata_queue — 메타데이터 없는 파일 관리

```sql
CREATE TABLE no_metadata_queue (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path           TEXT NOT NULL UNIQUE,
    discovered_at       TEXT NOT NULL,
    fail_reason         TEXT NOT NULL,
    -- no_exif|parse_fail|unsupported_format|missing_required_fields|pixiv_deleted
    extracted_artwork_id TEXT,     -- 파일명에서 추정한 ID (있을 경우)
    extracted_confidence TEXT,     -- high|medium|low
    last_attempted      TEXT,
    attempt_count       INTEGER DEFAULT 0,
    status              TEXT DEFAULT 'pending'
    -- pending|retrying|resolved|excluded
);
```

### 11.2 기존 artworks 테이블 컬럼 추가

```sql
-- 기존 artworks 테이블에 추가
ALTER TABLE artworks ADD COLUMN artwork_type TEXT DEFAULT 'image';
-- 'image' | 'ugoira' | 'manga' (다중페이지)

ALTER TABLE artworks ADD COLUMN parent_artwork_id TEXT;
-- 다중페이지: 첫 번째 페이지의 artwork_id 참조 (그룹핑용)
```

### 11.3 브라우저 확장 메시지 프로토콜 추가

**진행률 업데이트 메시지 (Host → Extension, 폴링 응답):**

```json
{
  "type": "progress_update",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "downloading",
  "pages_done": 2,
  "pages_failed": 0,
  "total_pages": 5,
  "current_page_index": 2,
  "message": "이미지 다운로드 중... (3/5)",
  "timestamp": "2026-04-26T15:30:01+09:00"
}
```

**분류 미리보기 요청 메시지 (Extension → Host):**

```json
{
  "action": "get_classify_preview",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**분류 실행 승인 메시지 (Extension → Host):**

```json
{
  "action": "execute_classify",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "excluded_artwork_ids": [12, 15],
  "conflict_resolutions": {
    "Classified/시리즈/Blue Archive/p0.jpg": "overwrite"
  }
}
```

### 11.4 Native Messaging Host 액션 추가

| action | 방향 | 설명 |
|--------|------|------|
| `get_job_status` | Extension → Host | job_id 기준 진행률 폴링 |
| `get_classify_preview` | Extension/App → Host | 분류 미리보기 생성 |
| `execute_classify` | Extension/App → Host | 미리보기 승인 후 분류 실행 |
| `undo_classify` | App → Host | 분류 Undo (복사본 제거) |
| `get_no_metadata_queue` | App → Host | No Metadata 큐 목록 조회 |
| `resolve_no_metadata` | App → Host | No Metadata 항목 처리 |

### 11.5 GUI 추가 모듈

```
app/views/
├── wizard_view.py           ← 첫 실행 설정 마법사
├── classify_preview_view.py ← 분류 미리보기 화면
├── classify_reason_panel.py ← 분류 근거 패널
├── recent_jobs_view.py      ← 작업 로그 / Recent Jobs
├── no_metadata_view.py      ← No Metadata / Failed 큐
app/widgets/
├── progress_banner.py       ← 하단 상태 표시 배너
├── provenance_badge.py      ← 메타데이터 출처 배지
├── conflict_dialog.py       ← 충돌 처리 다이얼로그
├── undo_confirm_dialog.py   ← Undo 확인 다이얼로그
```

---

## 12. 최종 권장 개발 순서 (Sprint 계획)

### Sprint 0 — 기반 구조 (2주)

```
- DB 스키마 전체 확정 (artworks + 신규 5개 테이블)
- config.json 스키마 확정 (classify_policy 포함)
- 어댑터 인터페이스 확정
- 데이터 모델 클래스 전체 정의
- 테스트 픽스처 준비
```

### Sprint 1 — 저장 코어 (2주)

```
- core/metadata_writer.py (JPEG/PNG/ZIP/WebP)
- core/ugoira_converter.py
- core/adapters/pixiv.py
- native_host/host.py + handlers.py (save_artwork)
- save_jobs + job_pages DB 기록
```

### Sprint 2 — 저장 상태 UX (2주)

```
- 브라우저 팝업 진행률 표시 (get_job_status 폴링)
- 완료/실패/부분실패 팝업 UI
- 완료 후 버튼 (Inbox 열기, 폴더 열기, Aru Archive 열기)
- 부분 실패 재시도 흐름
```

### Sprint 3 — 분류 엔진 + 미리보기 (2주)

```
- core/classifier.py (규칙 매칭, dest_template 치환)
- 분류 미리보기 생성 (get_classify_preview)
- 검토 후 분류 모드 실행 (execute_classify)
- 즉시 분류 모드 옵션
- 복사 용량 계산 표시
- 충돌 처리 다이얼로그
```

### Sprint 4 — 기본 분류 Undo + 로그 (2주)

```
- undo_entries + copy_records DB 기록
- Undo 실행 (undo_classify handler)
- 파일 존재 검증 + 불일치 경고
- Recent Jobs 화면 기본 뷰
```

### Sprint 5 — PySide6 메인 앱 골격 (2주)

```
- 메인 윈도우 3패널 레이아웃
- 갤러리 뷰 (썸네일 그리드, 작품 카드)
- 좌측 라이브러리 트리
- 상세 메타데이터 패널 (기본 정보 탭)
- 우고이라 / 다중페이지 카드 UI
- 하단 상태 배너
```

### Sprint 6 — No Metadata + 분류 근거 (2주)

```
- No Metadata 큐 화면
- 파일명 재추출 로직
- 수동 메타데이터 입력 다이얼로그
- 분류 근거 패널 (classify_reason_panel.py)
- 메타데이터 Provenance 배지 (기본)
```

### Sprint 7 — 규칙 편집 UI (2주)

```
- 초보자 모드 규칙 편집 (문장형 드롭다운)
- 기본 프리셋 적용 화면
- 고급 모드 규칙 편집 (JSON 직접)
- 규칙 목록 관리 (순서, 활성/비활성)
- 적용 미리보기 연동
```

### Sprint 8 — 첫 실행 마법사 + 설정 (2주)

```
- 첫 실행 설정 마법사 (10단계)
- 브라우저 연결 상태 표시 + 테스트
- Native Host 자동 등록 스크립트 연동
- 설정 화면 (분류 정책, Undo 기간, WebP 품질 등)
- install_host.bat 개선
```

### Sprint 9 — 패키징 + QA (2주)

```
- PyInstaller 패키징 (메인 앱 + Native Host 분리 빌드)
- 클린 Windows 환경 포터블 실행 테스트
- 엔드투엔드 시나리오 테스트 (시나리오 A~G)
- 성능 테스트 (1,000개 이상 썸네일 로딩)
- 오류 메시지 / 예외 처리 완성도 점검
```

---

## 부록: 모델 간 관계도

```
save_jobs (1)
  └── job_pages (N)             저장 작업 내 페이지별 상태

save_jobs (1)
  └── undo_entries (N)          분류 단위 Undo 로그
        └── copy_records (N)    복사본 경로 기록

artworks (1)
  ├── tags (N)                  태그 인덱스
  ├── metadata_provenance (N)   필드별 출처 기록
  └── classified_paths (text)   JSON array (분류 결과 경로)

no_metadata_queue (독립)        메타데이터 없는 파일 큐

classify_log (레거시)           → copy_records로 대체
```

---

*이 문서는 AI 코드 생성 요청 시 기술 설계안(v1.0)과 함께 컨텍스트로 첨부하기 위한 UX 보강 설계 요약입니다.*
*기술 구현 상세는 Aru_Archive_설계안_AI분석용.md 를 병행 참조하세요.*
