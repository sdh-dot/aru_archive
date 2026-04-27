# 작업 마법사 (Workflow Wizard)

Aru Archive의 **작업 마법사**([🧭 작업 마법사])는 새 사용자가 파일 수집부터 분류 실행까지 9단계로 안내받을 수 있는 순서형 워크플로우입니다.

---

## 진입

툴바 맨 왼쪽의 **[🧭 작업 마법사]** 버튼 클릭.

기존 고급 도구 버튼은 그대로 유지됩니다. 마법사는 기존 기능의 래퍼이며, 순서를 안내하는 역할입니다.

---

## 9단계 구조

### Step 1 — Archive Root

- 현재 Archive Root 경로 표시
- **[Select Root]** 버튼으로 루트 폴더 선택
- **[폴더 열기]** 버튼으로 탐색기에서 확인
- 루트가 설정되지 않았거나 폴더가 없으면 경고 표시

### Step 2 — Scan / Load

- Inbox 폴더 경로, 파일 수, DB 그룹 수·파일 수 표시
- **[🔍 Inbox 스캔 실행]** — 배경 스레드(`_ScanThread`)로 InboxScanner 실행
  - 신규·스킵·실패 결과를 즉시 표시
  - 완료 후 Step 3으로 이동하여 메타데이터 상태 확인 권장

### Step 3 — 메타데이터 확인

파일 상태 요약 (`build_workflow_file_status_summary`) 표시:

| 항목 | 설명 |
|------|------|
| 총 작품 수 | `artwork_groups` 전체 건수 |
| metadata_missing | 메타데이터 없는 그룹 수 |
| json_only | AruArchive JSON만 있는 그룹 수 |
| full | XMP + JSON 모두 완료된 그룹 수 |
| 분류 가능 | full + json_only + xmp_write_failed |
| 분류 불가 | total - 분류 가능 |
| Pixiv ID 있음 | artwork_id 추출 가능한 그룹 수 |
| inbox / classified | 상태별 그룹 수 |

경고 배지 (`classify_workflow_warnings`):

| 수준 | 코드 | 조건 |
|------|------|------|
| warning | `metadata_missing` | metadata_missing 그룹 > 0 |
| info | `pending_candidates` | 검토 대기 태그 후보 > 0 |
| info | `staged_external_entries` | staged 외부 사전 항목 > 0 |
| danger | `no_classifiable` | 분류 가능 항목 = 0이고 total > 0 |

### Step 4 — 메타데이터 보강

- `metadata_missing` + `artwork_id` 있는 그룹 목록 표시
- **[🌐 보강 실행]** — 배경 스레드(`_EnrichThread`)로 각 파일에 `enrich_file_from_pixiv` 실행
- 진행 표시: `(3 / 12) 보강 중…`
- 완료 후 Step 3의 metadata_missing 수가 줄어들면 정상

### Step 5 — 사전 정규화

사전 상태 요약 (`build_dictionary_status_summary`) 표시:

| 항목 | 설명 |
|------|------|
| tag_aliases | 활성 alias 총 수 |
| series_aliases | 시리즈 alias 수 |
| character_aliases | 캐릭터 alias 수 |
| tag_localizations | 현지화 항목 수 |
| pending_candidates | 검토 대기 태그 후보 수 |
| staged_external | staged 외부 사전 항목 수 |
| accepted_external | accepted 외부 사전 항목 수 |
| classification_failure_candidates | 분류 실패 태그 후보 수 |

버튼:
- **[🏷 후보 태그]** → TagCandidateView 열기
- **[🌐 사전 가져오기]** → DictionaryImportView 열기
- **[📤 사전 내보내기]** → export_public_tag_pack

> 태그 alias가 변경되면 **반드시 Step 6 (태그 재분류)** 를 실행해야 분류 결과에 반영됩니다.

### Step 6 — 태그 재분류

- 총 작품 수, 분류 가능 수, character_tags 있음/없음 표시
- **[🏷 전체 태그 재분류]** — 배경 스레드(`_RetagThread`)로 `retag_groups_from_existing_tags` 실행
- **⚠ 주의:** 사전(aliases) 변경 후 재분류를 건너뛰면 분류 결과가 최신 alias를 반영하지 않습니다.

### Step 7 — 분류 미리보기

- **대상** 콤보: 전체 분류 가능 항목 / 현재 목록 (메인 창 필터)
- **폴더명 언어** 콤보: canonical / 한국어 / 일본어 / 영어
- **[📋 미리보기 생성]** — 배경 스레드(`_PreviewThread`)로 `build_classify_batch_preview` 실행
- 결과 테이블: 대상 수, 분류 가능, 제외, 예상 복사본 수, 예상 용량, series+character, author_fallback, 충돌 수, deduped 목적지

#### 위험도 계산 (`compute_preview_risk_level`)

| 위험도 | 조건 |
|--------|------|
| **낮음** (🟢) | excluded < 30%, conflict_ratio ≤ 5%, fallback ≤ 20%, total ≤ 500 |
| **보통** (🟡) | fallback_ratio > 20% **또는** conflict_ratio > 5% **또는** total > 500 |
| **높음** (🔴) | excluded > 30% **또는** conflict_ratio > 20% |

미리보기 완료 후 자동으로 Step 8의 [▶ 분류 실행] 버튼이 활성화됩니다.

### Step 8 — 분류 실행

- 예상 복사본 수·예상 용량 표시
- **[▶ 분류 실행]** — Step 7 미리보기 없으면 비활성; 확인 다이얼로그 후 `_ExecuteThread` 실행
- 원본 파일을 **이동·삭제하지 않습니다.** Classified 폴더에 복사본만 생성합니다.
- 완료 후 `undo_entries`에 기록 → Step 9에서 확인 가능

### Step 9 — 결과 / Undo

- 최근 `undo_entries` 목록 표시 (최대 20건)
- **[🕘 작업 로그]** → WorkLogView 열기 (Undo 포함)
- **[📂 Classified 폴더]** → 탐색기에서 폴더 열기

---

## 내비게이션

| 버튼 | 동작 |
|------|------|
| **◀ 이전** | 이전 단계로 이동 (Step 1에서 비활성) |
| **다음 ▶** | 다음 단계로 이동 (Step 9에서 비활성) |
| **🔄 새로고침** | 현재 단계 UI를 DB에서 다시 로드 |
| **닫기** | 마법사 종료 (메인 창 갤러리·카운트 자동 갱신) |
| 헤더 단계 버튼 클릭 | 임의 단계로 바로 이동 |

---

## 기술 세부 사항

### 배경 스레드

| 클래스 | 역할 |
|--------|------|
| `_ScanThread` | InboxScanner 실행 |
| `_EnrichThread` | enrich_file_from_pixiv 일괄 실행 |
| `_RetagThread` | retag_groups_from_existing_tags 실행 |
| `_PreviewThread` | build_classify_batch_preview 실행 |
| `_ExecuteThread` | execute_classify_batch 실행 |

### Step 7 → Step 8 신호 연결

```python
_Step7Preview.preview_ready  →  _Step8Execute.set_preview(batch_preview)
```

`set_preview` 호출 시 [▶ 분류 실행] 버튼이 활성화됩니다.

### conn_factory 패턴

마법사는 `conn_factory: () -> sqlite3.Connection` 를 주입받습니다.
각 배경 스레드 및 즉시 DB 조회는 개별 커넥션을 생성·소멸합니다.

---

## 권장 워크플로우

```
Step 1  Archive Root 설정
Step 2  Inbox 스캔
Step 3  메타데이터 상태 확인 → metadata_missing 수 파악
        [선택] 완전 중복 검사 (범위: Inbox / Managed) → 보존 파일 확인 → 삭제 미리보기 → 영구 삭제
        [선택] 시각적 중복 검사 (범위: Inbox / Managed) → 비교 확인 → 삭제 미리보기 → 영구 삭제
Step 4  (필요시) 메타데이터 보강
Step 5  사전 확인 → 후보 태그 승인 / 외부 사전 가져오기
        [선택] Localized Tag Pack 가져오기 → ko/ja localization 보강
Step 6  태그 재분류 (Step 5에서 alias 변경이 있었다면 필수)
Step 7  분류 미리보기 생성 → 위험도 확인
Step 8  분류 실행
Step 9  결과 확인 / 필요시 Undo
```

---

## 중복 검사 기본 범위

Step 3의 중복 검사 버튼은 기본적으로 **Inbox / Managed** 파일만 검사합니다.

| 검사 버튼 | 기본 범위 | Classified 포함 |
|----------|----------|----------------|
| 🧬 완전 중복 검사 | Inbox / Managed | 제외 |
| 👁 시각적 중복 검사 | Inbox / Managed | 제외 |

Classified 폴더의 복사본은 기본 제외됩니다. 이는 분류 결과물이 원본과 중복으로 오탐되는 것을 방지하기 위함입니다.

전체 Archive 검사가 필요하면 툴바 버튼에서 `config.json → duplicates.allow_all_archive_scan: true` 설정 후 사용하세요.

---

## 삭제 경고

중복 검사에서 삭제를 진행할 때 다음 사항을 주의하세요.

- **모든 삭제는 영구 삭제**입니다. 복구할 수 없습니다.
- original 파일이 포함된 경우 `DeletePreviewDialog`에서 `DELETE`를 직접 입력해야 합니다.
- 삭제 결과는 `delete_batches` / `delete_records` 테이블에 기록됩니다.
- 자세한 정책: [file-deletion.md](file-deletion.md)

---

## Localized Tag Pack Import 워크플로우

Step 5 (사전 정규화) 단계의 `[📦 Localized Tag Pack 가져오기]` 버튼을 사용합니다.

```
1. JSON 파일 선택 (docs/tag_pack_export_localized_ko_ja.json 등)
2. validate_localized_tag_pack() — 구조 검증
3. import 미리보기 요약 표시
4. 확인 후 import_localized_tag_pack() 실행
5. tag_aliases / tag_localizations 갱신
6. 태그 재분류 실행 안내 표시
```

**_review 항목 처리**:
- `merge_candidate` → 자동 병합하지 않음, report에만 표시
- `variant_tag` → 자동 병합하지 않음
- `possibly_general_or_group_tag` → tag_type 자동 변경 안 함
- import 완료 메시지에 review_items 수, merge_candidate 목록 표시
