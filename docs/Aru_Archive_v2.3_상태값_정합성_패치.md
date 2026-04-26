# Aru Archive v2.3 상태값 정합성 패치

- **패치 대상**: 최종 개발 착수용 설계안 v2.3
- **패치 작성일**: 2026-04-26
- **패치 번호**: v2.3.1 (구조 변경 없음, enum 정합성 보강)
- **패치 범위**: `metadata_sync_status`, `fail_reason`, static GIF 예외 정책, `undo_status` 명칭 검토

---

## 1. 패치 목적

### 1.1 v2.3에서 이미 올바르게 반영된 항목

아래 항목은 v2.3에서 확정 반영되었으며 이번 패치에서 건드리지 않는다.

| 항목 | v2.3 상태 |
|------|-----------|
| BMP → original 보존 + PNG managed 생성 | ✅ 확정 |
| animated GIF → original 보존 + WebP managed 생성 | ✅ 확정 |
| static GIF → sidecar only | ✅ 구조 반영됨 (예외 사유 명시 필요) |
| `artwork_groups` / `artwork_files` 구조 | ✅ 유지 |
| `save_jobs` / `job_pages` 복구 | ✅ 유지 |
| `thumbnail_cache` Hybrid path 방식 | ✅ 유지 |
| IPC 토큰 인증 / `operation_locks` 키 정책 | ✅ 유지 |
| `metadata_sync_status` 기본값 `pending` | ✅ 확정 |

### 1.2 아직 남은 enum 불일치

| 항목 | v2.3 값 | 누락 값 |
|------|---------|---------|
| `metadata_sync_status` | 9개 (`file_write_failed` 포함) | `convert_failed`, `metadata_write_failed` 2개 누락 |
| `no_metadata_queue.fail_reason` | 9개 (`embed_failed` 포함) | `bmp_convert_failed`, `managed_file_create_failed`, `metadata_write_failed`, `xmp_write_failed` 4개 누락 |
| static GIF 예외 사유 | 구조만 있음 | 예외 정책 명시 및 `metadata_sync_status` 처리 없음 |
| `undo_status` 명칭 | `pending` | 의미 명확성 검토 필요 |

### 1.3 이번 패치의 범위

1. `metadata_sync_status` 최종 enum 11개로 확장
2. `no_metadata_queue.fail_reason` 최종 enum 13개로 확장
3. BMP / managed 변환 공통 상태 전이표 추가
4. BMP 실패 케이스 매핑표 추가
5. static GIF sidecar-only 예외 정책 명시
6. `undo_status` 명칭 최종 결정

---

## 2. metadata_sync_status 최종 enum

### 2.1 최종 값 목록 (11개)

v2.3의 9개에 `convert_failed`, `metadata_write_failed` 2개를 추가한다.

| 순번 | 값 | 신규 여부 |
|------|----|---------|
| 1 | `pending` | v2.3 |
| 2 | `full` | v2.3 |
| 3 | `json_only` | v2.3 |
| 4 | `out_of_sync` | v2.3 |
| 5 | `file_write_failed` | v2.3 |
| 6 | `convert_failed` | **패치 추가** |
| 7 | `metadata_write_failed` | **패치 추가** |
| 8 | `xmp_write_failed` | v2.3 |
| 9 | `db_update_failed` | v2.3 |
| 10 | `needs_reindex` | v2.3 |
| 11 | `metadata_missing` | v2.3 |

### 2.2 각 상태 의미 (전체 정의)

| 값 | 의미 | 발생 조건 | 다음 상태 |
|----|------|-----------|-----------|
| `pending` | 기본값. 처리 파이프라인 진입 전 또는 진행 중 | 저장 작업 시작 직후 | full / json_only / 실패 값 중 하나 |
| `full` | AruArchive JSON + XMP 모두 임베딩 완료 | JSON + ExifTool XMP 모두 성공 | out_of_sync (외부 파일 변경 감지 시) |
| `json_only` | AruArchive JSON만 임베딩 (ExifTool 없음 또는 생략) | JSON 성공 + ExifTool 없음 | full (ExifTool 번들 후 재실행) |
| `out_of_sync` | DB의 메타데이터와 실제 파일 내부 메타데이터 불일치 | 재색인 또는 헬스체크 시 감지 | full (재동기화 후) |
| `file_write_failed` | **원본 파일 저장 또는 파일 I/O 자체 실패** | 디스크 부족, 권한 오류, 파일 잠금 | pending (재시도) |
| `convert_failed` | **원본 저장 성공, managed 파일 변환 실패** | BMP→PNG 실패, animated GIF→WebP 실패, ugoira→WebP 실패 | pending (재시도) |
| `metadata_write_failed` | **managed 파일 생성 성공, AruArchive JSON 임베딩 실패** | PNG iTXt 쓰기 실패, WebP EXIF 쓰기 실패 등 | pending (재임베딩 시도) |
| `xmp_write_failed` | AruArchive JSON 성공, ExifTool XMP 단계만 실패 | ExifTool 오류, 권한 문제, 미지원 포맷 | json_only (강등) 또는 full (재시도) |
| `db_update_failed` | 파일 처리 성공, DB 업데이트만 실패 | SQLite I/O 오류, 잠금 타임아웃 | needs_reindex (재색인으로 복구) |
| `needs_reindex` | DB 상태가 파일 실제 상태와 다름, 재색인 필요 | db_update_failed 이후 | full (재색인 완료 후) |
| `metadata_missing` | 파일 내 AruArchive JSON 없음 | 외부 편집, 파일 교체 의심 | pending (재임베딩 시도) |

### 2.3 핵심 구분: 인접한 실패 값 3개

```
file_write_failed    → 파일 저장 자체 실패
                        (원본도 없거나 불완전)
        ↓
convert_failed       → 원본은 저장됨
                        managed 변환이 실패
        ↓
metadata_write_failed → 원본 + managed 모두 저장됨
                         JSON 임베딩만 실패
        ↓
xmp_write_failed     → 원본 + managed + JSON 모두 완료
                         XMP만 실패
```

이 순서는 "얼마나 많이 진행했는가"를 나타낸다.  
`file_write_failed`가 가장 이른 단계의 실패, `xmp_write_failed`가 가장 늦은 단계의 실패다.

### 2.4 artwork_groups DDL 수정안

v2.3 §4.2의 `metadata_sync_status` 컬럼 주석을 다음과 같이 교체한다.

**수정 전 (v2.3)**:
```sql
metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
                      -- pending | full | json_only | out_of_sync |
                      -- file_write_failed | xmp_write_failed |
                      -- db_update_failed | needs_reindex | metadata_missing
```

**수정 후 (패치 적용)**:
```sql
metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
                      -- pending | full | json_only | out_of_sync |
                      -- file_write_failed | convert_failed | metadata_write_failed |
                      -- xmp_write_failed | db_update_failed |
                      -- needs_reindex | metadata_missing
```

---

## 3. BMP / managed 변환 공통 상태 전이

### 3.1 "원본 보존 + managed 변환본 생성" 공통 파이프라인

BMP → PNG managed, animated GIF → WebP managed, ugoira ZIP → WebP managed는 모두 동일한 처리 구조를 따른다. 아래 상태 전이는 이 세 케이스 모두에 재사용 가능한 공통 모델이다.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 "원본 보존 + managed 변환본 생성" 공통 상태 전이
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[시작]
artwork_groups.metadata_sync_status = 'pending'
    │
    ▼
[STEP 1] 원본 파일 Inbox 저장
artwork_files INSERT (file_role='original', metadata_embedded=0)
    │
    ├── 저장 실패 (I/O 오류 등)
    │     → metadata_sync_status = 'file_write_failed'
    │     → no_metadata_queue: fail_reason = 'network_error' 또는 'embed_failed'
    │     → [종료: 원본도 불완전]
    │
    └── 저장 성공 → STEP 2
    │
    ▼
[STEP 2] managed 파일 변환 시도
(BMP→PNG, animated GIF→WebP, ugoira ZIP→WebP)
    │
    ├── 변환 실패 (Pillow 오류, 손상 파일 등)
    │     → metadata_sync_status = 'convert_failed'
    │     → no_metadata_queue: fail_reason = 'bmp_convert_failed'
    │                          또는 'managed_file_create_failed'
    │     → 원본은 보존됨 (file_role='original')
    │     → thumbnail: 원본에서 임시 생성
    │     → [종료: managed 없음]
    │
    └── 변환 성공 → STEP 3
    artwork_files INSERT (file_role='managed', metadata_embedded=0)
    │
    ▼
[STEP 3] AruArchive JSON 임베딩
(JPEG/WebP: EXIF UserComment, PNG: iTXt chunk)
    │
    ├── 임베딩 실패 (파일 쓰기 오류 등)
    │     → metadata_sync_status = 'metadata_write_failed'
    │     → artwork_files UPDATE metadata_embedded=0
    │     → no_metadata_queue: fail_reason = 'metadata_write_failed'
    │     → 원본 + managed(metadata_embedded=0) 모두 보존됨
    │     → [종료: JSON 없음]
    │
    └── 임베딩 성공 → STEP 4
    artwork_files UPDATE metadata_embedded=1
    │
    ▼
[STEP 4] XMP 표준 필드 기록 (ExifTool, MVP-B)
    │
    ├── ExifTool 없음
    │     → metadata_sync_status = 'json_only'
    │     → no_metadata_queue: 기록하지 않음 (정상 처리)
    │     → [종료: JSON 완료, XMP 없음]
    │
    ├── ExifTool 있음 + 기록 실패
    │     → metadata_sync_status = 'xmp_write_failed'
    │     → Warning 배지 (UI), no_metadata_queue: 선택적 기록 (§4.4 참조)
    │     → [종료: JSON 완료, XMP 실패]
    │
    └── ExifTool 있음 + 기록 성공
          → metadata_sync_status = 'full'
          → no_metadata_queue: 기록하지 않음
          → [종료: 완전 성공]
```

### 3.2 포맷별 적용

| 포맷 | STEP 2 (변환) | STEP 3 (JSON) | STEP 4 (XMP) |
|------|--------------|--------------|--------------|
| BMP → PNG managed | `bmp_convert_failed` | PNG iTXt 쓰기 | PNG XMP (ExifTool) |
| animated GIF → WebP managed | `managed_file_create_failed` | WebP EXIF UserComment | WebP XMP (ExifTool) |
| ugoira ZIP → WebP managed | `managed_file_create_failed` | WebP EXIF UserComment | WebP XMP (ExifTool) |

### 3.3 단순 포맷 (원본 직접 임베딩) 상태 전이 비교

JPEG, PNG, native WebP처럼 원본에 직접 메타데이터를 삽입하는 포맷은 STEP 2 없이 동작한다.

```
[시작] pending
    │
    ├── 원본 저장 실패         → file_write_failed
    ├── JSON 임베딩 실패       → metadata_write_failed
    ├── JSON 성공, XMP 없음   → json_only
    ├── JSON 성공, XMP 실패   → xmp_write_failed
    └── JSON + XMP 성공       → full
```

`convert_failed`는 "원본 보존 + managed 변환본 생성" 파이프라인에서만 발생한다.

---

## 4. no_metadata_queue.fail_reason 최종 enum

### 4.1 최종 값 목록 (13개)

v2.3의 9개에 4개를 추가한다.

| 순번 | 값 | 신규 여부 |
|------|----|---------|
| 1 | `no_dom_data` | v2.3 |
| 2 | `parse_error` | v2.3 |
| 3 | `network_error` | v2.3 |
| 4 | `unsupported_format` | v2.3 |
| 5 | `manual_add` | v2.3 |
| 6 | `embed_failed` | v2.3 |
| 7 | `partial_data` | v2.3 |
| 8 | `artwork_restricted` | v2.3 |
| 9 | `api_error` | v2.3 |
| 10 | `bmp_convert_failed` | **패치 추가** |
| 11 | `managed_file_create_failed` | **패치 추가** |
| 12 | `metadata_write_failed` | **패치 추가** |
| 13 | `xmp_write_failed` | **패치 추가** |

### 4.2 기존 `embed_failed`와 신규 값의 구분

v2.3의 `embed_failed`와 신규 추가 값 사이에는 다음 차이가 있다.

| 값 | 적용 대상 | 발생 단계 | 세분화 |
|----|-----------|-----------|--------|
| `embed_failed` | 모든 포맷 (범용) | 다운로드 후 임베딩 단계 | 기존 범용 값 |
| `bmp_convert_failed` | BMP 전용 | STEP 2 (변환) | 포맷 특화 |
| `managed_file_create_failed` | BMP 외 managed 변환 | STEP 2 (변환) | 포맷 특화 |
| `metadata_write_failed` | 모든 포맷 | STEP 3 (JSON 임베딩) | 단계 특화 |
| `xmp_write_failed` | 모든 포맷 | STEP 4 (XMP 기록) | 단계 특화 |

> **정책**: 신규 값이 적용되는 케이스에서는 범용 `embed_failed` 대신 신규 값을 우선 사용한다.  
> `embed_failed`는 위 분류에 해당하지 않는 기타 임베딩 오류의 폴백으로 유지한다.

### 4.3 각 신규 값 상세 정의

**`bmp_convert_failed`**
- 발생: BMP → PNG managed 변환 과정에서 Pillow 오류 발생
- BMP 원본은 Inbox에 보존됨 (파일 손실 없음)
- UI 메시지: "PNG 관리본 생성 실패"
- 권장 액션 버튼: [PNG 재생성], [원본 파일 열기], [무시]

**`managed_file_create_failed`**
- 발생: BMP 외 포맷의 managed 파일 생성 실패 (animated GIF→WebP, ugoira→WebP 등)
- 원본은 Inbox에 보존됨
- UI 메시지: "관리본 생성 실패"
- 권장 액션 버튼: [재생성], [원본 파일 열기], [무시]

**`metadata_write_failed`**
- 발생: managed 파일(또는 직접 임베딩 포맷의 원본)이 생성되었으나, AruArchive JSON 임베딩 실패
- 파일은 존재하나 `metadata_embedded=0` 상태
- UI 메시지: "메타데이터 기록 실패 (파일은 보존됨)"
- 권장 액션 버튼: [메타데이터 재기록], [수동 입력], [무시]

**`xmp_write_failed`**
- 발생: AruArchive JSON 임베딩 성공 후 ExifTool XMP 기록 단계 실패
- AruArchive JSON은 파일 내부에 온전히 존재함 (`metadata_embedded=1`)
- UI 메시지: "XMP 기록 실패 (JSON 메타데이터는 보존됨)"
- 권장 액션 버튼: [XMP 재시도], [무시]

### 4.4 `xmp_write_failed` 큐 기록 정책 최종 결정

`xmp_write_failed`를 `no_metadata_queue`에 넣을지 여부는 명확히 결정이 필요하다.

**결론: no_metadata_queue에 넣지 않는다. UI 배지(Warning)로 처리한다.**

| 관점 | 근거 |
|------|------|
| no_metadata_queue의 의미 | "메타데이터 없음 / 불완전하여 사용자 개입 필요" |
| xmp_write_failed 상태 | AruArchive JSON 완전 보존 → 검색·분류·표시 모두 정상 동작 |
| XMP의 위치 | MVP-B에서 활성화되는 외부 도구 호환성 기능 (필수 아님) |
| 사용자 혼란 방지 | no_metadata_queue에 넣으면 "메타데이터 없음"처럼 오해될 수 있음 |

**대신 다음과 같이 처리한다**:

```
1. artwork_groups.metadata_sync_status = 'xmp_write_failed' 기록
2. 갤러리 카드에 ⚠️ 배지 표시 ("XMP 없음, JSON 완료")
3. 작품 상세 패널 > 메타데이터 탭에 재시도 버튼 제공
4. 설정 화면 > ExifTool 섹션에 "XMP 실패 항목 일괄 재처리" 기능 제공 (MVP-B)
```

> **단, fail_reason 값으로는 enum에 존재해야 한다.**  
> 향후 별도 warning 큐 또는 재처리 큐를 만들 경우 이 값을 재사용할 수 있다.

### 4.5 no_metadata_queue DDL 수정안

v2.3 §4.7의 `fail_reason` 주석을 다음과 같이 교체한다.

**수정 전 (v2.3)**:
```sql
fail_reason   TEXT NOT NULL,
              -- no_dom_data | parse_error | network_error |
              -- unsupported_format | manual_add |
              -- embed_failed | partial_data | artwork_restricted | api_error
```

**수정 후 (패치 적용)**:
```sql
fail_reason   TEXT NOT NULL,
              -- no_dom_data | parse_error | network_error |
              -- unsupported_format | manual_add |
              -- embed_failed | partial_data | artwork_restricted | api_error |
              -- bmp_convert_failed | managed_file_create_failed |
              -- metadata_write_failed | xmp_write_failed
```

---

## 5. BMP 실패 케이스 매핑표

### 5.1 전체 케이스 매핑

| 상황 | `metadata_sync_status` | `no_metadata_queue.fail_reason` | BMP 원본 | PNG managed | `metadata_embedded` | UI 메시지 | 재시도 |
|------|----------------------|--------------------------------|---------|------------|-------------------|---------|--------|
| BMP 원본 저장 실패 | `file_write_failed` | `network_error` 또는 `embed_failed` | 없음 | 없음 | — | "파일 저장 실패" | ✅ |
| PNG managed 변환 실패 | `convert_failed` | `bmp_convert_failed` | 보존 ✅ | 없음 | — | "PNG 관리본 생성 실패" | ✅ |
| PNG managed 생성 후 JSON 기록 실패 | `metadata_write_failed` | `metadata_write_failed` | 보존 ✅ | 있음 (빈 파일) | 0 | "메타데이터 기록 실패" | ✅ |
| JSON 성공, XMP 실패 | `xmp_write_failed` | **기록 안 함** (배지만) | 보존 ✅ | 있음 | 1 | ⚠️ "XMP 기록 실패, JSON 완료" | ✅ |
| JSON 성공, ExifTool 없음 | `json_only` | **기록 안 함** (정상 처리) | 보존 ✅ | 있음 | 1 | — (정상) | — |
| JSON + XMP 모두 성공 | `full` | **기록 안 함** | 보존 ✅ | 있음 | 1 | — (정상) | — |

### 5.2 no_metadata_queue 기록 여부 요약

```
기록함 (사용자 개입 필요):
  file_write_failed  → BMP 저장 실패 (파일 자체 없음)
  convert_failed     → BMP 있으나 PNG 없음 (관리본 누락)
  metadata_write_failed → PNG 있으나 메타데이터 없음 (사용은 가능, 검색 불가)

기록 안 함 (정상 또는 자동 처리):
  xmp_write_failed   → JSON 완전 보존, XMP만 없음 → UI 배지로 처리
  json_only          → ExifTool 미존재 → 정상 처리
  full               → 완전 성공
```

### 5.3 재시도 가능 여부 상세

| 상태 | 재시도 방법 | 재시도 후 기대 상태 |
|------|-----------|-------------------|
| `file_write_failed` | 저장 작업 전체 재실행 | `pending` → 성공 시 `full` 또는 `json_only` |
| `convert_failed` | PNG managed 재생성 버튼 | `pending` → `full` 또는 `json_only` |
| `metadata_write_failed` | 메타데이터 재기록 버튼 | `pending` → `full` 또는 `json_only` |
| `xmp_write_failed` | ExifTool XMP 재시도 버튼 | `json_only` → `full` |
| `json_only` | ExifTool 번들 추가 후 재처리 (MVP-B) | `json_only` → `full` |

---

## 6. static GIF 예외 정책 명시

### 6.1 v2.3의 현재 상태

v2.3 §3.2에서 static GIF는 다음과 같이 처리된다.

```
GIF (static): original 보존 + .aru.json sidecar
```

구조는 올바르나, 이 정책이 왜 "파일 우선 메타데이터 원칙"의 예외인지 문서에 명시되어 있지 않다.

### 6.2 예외 인정 사유

**static GIF를 sidecar-only로 관리하는 이유:**

| 이유 | 내용 |
|------|------|
| 메타데이터 삽입 표준 부재 | GIF 포맷은 파일 내부 메타데이터 삽입 표준이 사실상 없음 |
| 변환 시 색상 손실 위험 | GIF는 최대 256색. PNG 변환 시 색상 공간 변경 가능성 |
| Pixiv에서 발생 빈도 낮음 | Pixiv는 정적 이미지를 JPEG/PNG로 제공. static GIF는 희귀 케이스 |
| 구현 복잡도 대비 효용 | managed 변환 파이프라인 추가 대비 실사용 효과 미미 |

**따라서 다음 원칙을 v2.3 §3.2에 명시한다:**

> static GIF는 MVP 전 단계에서 `파일 우선 메타데이터 원칙`의 **예외**로 관리한다.  
> 이는 GIF 포맷의 메타데이터 처리 안정성과 구현 범위를 고려한 **한시적 정책**이다.  
> 향후 필요 시 PNG managed 또는 WebP managed 생성 정책으로 전환할 수 있다.  
> 전환 시 BMP/animated GIF와 동일한 "원본 보존 + managed 변환본 생성" 파이프라인을 사용한다.

### 6.3 static GIF의 metadata_sync_status 처리

static GIF는 sidecar만 존재하므로, 직접 임베딩 성공/실패 개념이 다르다.

| 상황 | `metadata_sync_status` | `no_metadata_queue` |
|------|----------------------|---------------------|
| sidecar 생성 성공 | `json_only` | 기록 안 함 |
| sidecar 생성 실패 | `metadata_write_failed` | `fail_reason='metadata_write_failed'` |

> **`json_only`를 사용하는 이유**: static GIF sidecar는 AruArchive JSON을 포함하므로  
> "JSON은 있으나 파일 내부 임베딩은 없음"이라는 의미의 `json_only`가 가장 정확하다.  
> 파일 내부 임베딩이 없다는 점에서 ExifTool 없는 JPEG와 동일한 상태 수준이다.

### 6.4 향후 전환 경로

```
현재 (MVP 전 단계):
  static GIF → sidecar only → metadata_sync_status='json_only'

향후 전환 (선택적):
  static GIF → original 보존 + WebP managed 생성
             → metadata_sync_status = full / json_only / convert_failed
             → BMP/animated GIF와 완전히 동일한 파이프라인 사용
```

---

## 7. undo_status 명칭 검토

### 7.1 두 안 비교

**안 A — v2.3 유지: `pending | completed | failed | expired`**

| 장점 | 단점 |
|------|------|
| 기존 v2.3과 완전 호환 | `pending`이 "Undo 대기 중"처럼 읽혀 의미 모호 |
| DB DDL 및 코드 변경 없음 | UI 레이블로 사용 시 추가 변환 로직 필요 |
| `save_jobs.status`의 `pending`과 일관된 네이밍 | "이 항목은 Undo 가능하다"는 상태를 직접 표현 못 함 |

**안 B — 명칭 변경: `available | completed | failed | expired`**

| 장점 | 단점 |
|------|------|
| `available`이 "Undo 가능" 의미를 직접 표현 | DB DDL, undo_entries 관련 코드 전체 수정 필요 |
| UI에서 추가 변환 없이 직접 레이블로 사용 가능 | v2.3 문서와의 불일치 (수정 범위 발생) |
| 사용자 관점에서 직관적 | `pending`으로 일관된 네이밍 스타일 깨짐 |

### 7.2 최종 결정: 안 A 유지 (`pending`)

**결정 이유**:

1. **`pending`은 충분히 명확하다**: `undo_status='pending'`은 "Undo 작업이 아직 실행되지 않았음"을 의미하며, 코드 레벨에서는 혼동이 없다. `available`과 `pending`은 의미론적으로 동치다.

2. **변경 비용이 이득을 초과한다**: `undo_status`를 참조하는 모든 DDL, 쿼리, UI 코드를 수정해야 한다. 이 비용은 네이밍 명확성이라는 이득을 정당화하지 못한다.

3. **UI 레이블은 별도로 정의한다**: UI에서 `pending` 상태의 Undo 항목을 표시할 때는 코드값 `pending`이 아니라 UI 문자열 `"Undo 가능"` 또는 `"취소 가능"`을 사용하면 된다. 상태값과 UI 레이블은 별개다.

4. **일관성 유지**: `save_jobs.status`, `job_pages.status`, `operation_locks` 등 다른 테이블도 초기 상태에 `pending`을 사용한다. `undo_entries`만 다른 패턴을 사용하면 코드베이스 일관성이 깨진다.

**안 B 적용 조건 (향후 재검토 시)**:
- 다른 테이블들도 동시에 `pending → available` 전체 마이그레이션을 진행할 경우
- UI 프레임워크에서 상태값을 레이블로 직접 표시하는 구조가 되는 경우

**결론**: `undo_status`는 v2.3의 `pending | completed | failed | expired`를 그대로 유지한다.

---

## 8. v2.3 본문 수정 위치

### 8.1 §4.2 artwork_groups 테이블

**수정 항목 1**: DDL `metadata_sync_status` 주석 교체 (§2.4 참조)

**수정 항목 2**: `metadata_sync_status 값 정의` 표를 9개 → 11개로 교체

수정 전 표 제목: `metadata_sync_status 값 정의 (v2.3 확장, 9개)`  
수정 후 표 제목: `metadata_sync_status 값 정의 (패치 확장, 11개)`

교체할 표:

| 값 | 의미 | 발생 조건 | 다음 상태 |
|----|------|-----------|-----------|
| `pending` | 기본값. 처리 파이프라인 진입 전 또는 진행 중 | 저장 작업 시작 직후 | full / json_only / 실패 값 |
| `full` | AruArchive JSON + XMP 모두 임베딩 완료 | JSON + ExifTool XMP 모두 성공 | out_of_sync |
| `json_only` | AruArchive JSON만 임베딩 (ExifTool 없음) | JSON 성공 + ExifTool 없음 | full |
| `out_of_sync` | DB 메타데이터와 파일 내부 불일치 | 재색인 또는 헬스체크 시 감지 | full |
| `file_write_failed` | 원본 파일 저장 또는 I/O 자체 실패 | 디스크 부족, 권한 오류, 파일 잠금 | pending |
| `convert_failed` | ★ 원본 저장 성공, managed 변환 실패 | BMP→PNG 실패, GIF→WebP 실패 등 | pending |
| `metadata_write_failed` | ★ managed 파일 생성 성공, JSON 임베딩 실패 | PNG iTXt 쓰기 실패 등 | pending |
| `xmp_write_failed` | JSON 성공, ExifTool XMP 단계만 실패 | ExifTool 오류, 권한 문제 | json_only 또는 full |
| `db_update_failed` | 파일 처리 성공, DB 업데이트 실패 | SQLite I/O 오류 | needs_reindex |
| `needs_reindex` | 재색인이 필요한 상태 | db_update_failed 이후 | full |
| `metadata_missing` | 파일 내 AruArchive JSON 없음 | 외부 편집 의심 | pending |

> ★ = 패치에서 추가된 값. `convert_failed`와 `metadata_write_failed`는 "원본 보존 + managed 변환본 생성" 파이프라인(BMP, animated GIF, ugoira)에서 발생하는 단계별 실패를 정확히 표현한다.

---

### 8.2 §4.7 no_metadata_queue 테이블

**수정 항목 1**: DDL `fail_reason` 주석 교체 (§4.5 참조)

**수정 항목 2**: `fail_reason enum` 표를 9개 → 13개로 교체

교체할 표:

| 값 | 발생 시점 | 권장 대응 |
|----|-----------|-----------|
| `no_dom_data` | content_script preload_data 찾지 못함 | 페이지 새로고침 후 재시도 |
| `parse_error` | 메타데이터 파싱 중 예외 | 개발자 신고 |
| `network_error` | httpx 다운로드 실패 | 재다운로드 |
| `unsupported_format` | 지원하지 않는 파일 형식 | 수동 입력 |
| `manual_add` | 사용자 수동 추가 | 메타데이터 직접 입력 |
| `embed_failed` | 기타 임베딩 오류 (범용 폴백) | 재시도, 수동 입력 |
| `partial_data` | 일부 필드 누락된 불완전 메타데이터 | 누락 필드 수동 보완 |
| `artwork_restricted` | R-18/프리미엄 접근 제한 | 로그인 상태 확인 |
| `api_error` | Pixiv AJAX API 4xx/5xx | 잠시 후 재시도 |
| `bmp_convert_failed` | ★ BMP→PNG managed 변환 실패 | PNG 재생성 시도 |
| `managed_file_create_failed` | ★ BMP 외 managed 파일 생성 실패 (GIF→WebP 등) | 재생성 시도 |
| `metadata_write_failed` | ★ 파일 생성 후 AruArchive JSON 기록 실패 | 재임베딩 시도 |
| `xmp_write_failed` | ★ JSON 성공, XMP 기록 실패 | **no_metadata_queue에 기록하지 않음.** UI 배지로 처리 |

> ★ = 패치에서 추가된 값.  
> `xmp_write_failed`는 enum에는 존재하나 실제로 no_metadata_queue에 INSERT하지 않는다. 향후 warning 큐 또는 XMP 재처리 큐를 별도로 만들 경우 이 값을 사용한다.

---

### 8.3 §3.2 파일 형식별 저장 정책

`GIF (static)` 행 하단의 설명 주석에 다음 내용을 추가한다.

**추가할 주석**:

> **GIF static 예외 정책**: static GIF는 MVP 전 단계에서 파일 우선 메타데이터 원칙의 **예외**로 sidecar-only 방식을 채택한다. GIF 포맷의 메타데이터 삽입 표준 부재, 색상 손실 위험, 낮은 발생 빈도를 고려한 임시 정책이다. `metadata_sync_status='json_only'` (sidecar 성공) 또는 `'metadata_write_failed'` (sidecar 실패)로 처리한다. 향후 필요 시 animated GIF와 동일한 WebP managed 생성 방식으로 전환 가능하다.

---

### 8.4 §13.1 저장 플로우

BMP 처리 분기에서 `metadata_sync_status` 갱신 케이스를 다음과 같이 구체화한다.

v2.3 현재:
```
     f. metadata_sync_status 갱신 (full / json_only / file_write_failed 등)
```

교체:
```
     f. metadata_sync_status 갱신:
          원본 저장 실패          → file_write_failed
          PNG managed 변환 실패  → convert_failed
          JSON 임베딩 실패        → metadata_write_failed
          JSON 성공, XMP 실패    → xmp_write_failed  (no_metadata_queue 기록 안 함)
          JSON 성공, ExifTool 없음 → json_only        (no_metadata_queue 기록 안 함)
          JSON + XMP 성공        → full               (no_metadata_queue 기록 안 함)
```

---

### 8.5 §12 No Metadata 큐 정책

**§12.1 기록 시점**에 다음 항목을 추가한다:

- BMP → PNG managed 변환 실패 시 (`bmp_convert_failed`)
- animated GIF → WebP managed 변환 실패 시 (`managed_file_create_failed`)
- managed 파일 생성 후 AruArchive JSON 임베딩 실패 시 (`metadata_write_failed`)

**§12.1 기록 안 하는 케이스**를 명시한다:

- `xmp_write_failed`: AruArchive JSON 완전 보존 상태 → UI 배지로 처리, 큐에 기록 안 함
- `json_only` (ExifTool 없음): 정상 처리 → 큐에 기록 안 함

---

## 패치 적용 체크리스트

| 항목 | 위치 | 완료 |
|------|------|------|
| `metadata_sync_status` DDL 주석 교체 (11개) | §4.2 artwork_groups | ☐ |
| `metadata_sync_status` 값 정의 표 교체 | §4.2 | ☐ |
| `no_metadata_queue.fail_reason` DDL 주석 교체 (13개) | §4.7 | ☐ |
| `fail_reason` 값 정의 표 교체 | §4.7 | ☐ |
| GIF static 예외 정책 주석 추가 | §3.2 | ☐ |
| 저장 플로우 BMP 분기 상태값 구체화 | §13.1 | ☐ |
| No Metadata 큐 기록 시점 항목 추가 | §12.1 | ☐ |
| No Metadata 큐 기록 안 하는 케이스 명시 | §12.1 | ☐ |
| `undo_status` v2.3 유지 확인 (변경 없음) | §4.8 | ☐ |

---

*이 문서는 v2.3의 구조적 변경 없이 enum 정합성만 보강한 패치(v2.3.1)입니다.*  
*v2.4 이상 문서 생성 시 본 패치 내용이 통합 반영되어야 합니다.*
