# Aru Archive v2.2 BMP 처리 정책 패치

- **패치 대상**: Aru Archive 최종 개발 착수용 설계안 v2.2
- **패치 작성일**: 2026-04-26
- **패치 범위**: BMP 파일 처리 정책 전면 수정 (§3, §4, §11, §12, §13, §14)
- **적용 우선순위**: 즉시 반영 필수 (확정 결정사항)

---

## 1. 변경 이유

### 1.1 v2.2의 문제점

v2.2 §3.2 파일 형식별 저장 위치 표에는 BMP가 다음과 같이 기록되어 있다.

```
| BMP | `.aru.json` sidecar | 미적용 |
```

이 정책은 세 가지 이유에서 근본적으로 부적합하다.

**① 파일 우선 메타데이터 원칙 위반**

Aru Archive의 설계 핵심 원칙은 "메타데이터 원본은 항상 파일 내부"이다.  
sidecar-only 방식은 메타데이터가 파일 외부에만 존재하므로, 이 원칙을 직접적으로 위반한다.  
BMP 파일만 Inbox에서 꺼내면 메타데이터가 없는 파일이 되고, sidecar가 소실되면 복원 불가다.

**② 분류 대상 파일 부재**

Classifier는 `file_role='original'` 또는 `file_role='managed'` 파일을 Classified 폴더로 복사한다.  
sidecar 파일은 분류 복사 대상이 아니다.  
BMP를 sidecar-only로 관리하면, 메타데이터를 담은 파일이 Classified 폴더에 복사될 수 없다.  
결과적으로 BMP 작품은 분류 기능 자체가 작동하지 않는다.

**③ 갤러리 검색/필터 품질 저하**

갤러리 UI에서 태그 검색, 작가 필터, 시리즈 필터 등은 `artwork_files` 테이블과 파일 내부 메타데이터를 기준으로 동작한다.  
sidecar JSON은 이 파이프라인에서 부수적인 역할만 하도록 설계되어 있으며,  
sidecar를 주 메타데이터 소스로 사용하면 재색인, 이동 감지, metadata_sync_status 갱신 등의 로직이 불일치를 일으킨다.

### 1.2 sidecar-only 정책이 부적합한 이유 요약

| 관점 | sidecar-only의 문제 |
|------|---------------------|
| 파일 이식성 | BMP 파일만 이동하면 메타데이터 분리됨 |
| 분류 기능 | Classified 폴더에 메타데이터 포함 파일 복사 불가 |
| 재색인 | BMP sidecar를 기준으로 재색인하는 경로가 없음 |
| 썸네일 | BMP 원본에서 생성하면 메타데이터 연결 파일 기준이 불명확 |
| 검색 | 파일 내부 메타데이터 기반 검색 파이프라인에서 누락 |

### 1.3 PNG managed 방식 채택 이유

BMP는 파일 내부에 메타데이터를 삽입하는 표준이 없고, 무손실이지만 압축 효율이 낮다.  
PNG는 BMP와 동일하게 무손실이며 `iTXt` 청크를 통해 AruArchive JSON과 XMP를 파일 내부에 삽입할 수 있다.  
따라서 BMP → PNG 변환은 **화질 손실 없이** 파일 우선 메타데이터 원칙을 충족하는 최적의 방법이다.

```
BMP 원본 보존 (파일 무결성)
  +
PNG 관리본 생성 (메타데이터 내장 + 분류 가능 + 검색 가능)
  =
파일 우선 원칙 준수 + 분류 기능 완전 지원
```

---

## 2. BMP 최종 처리 정책

### 2.1 핵심 정책 선언

> **BMP는 직접 메타데이터 삽입 대상이 아니다.**  
> **BMP는 원본을 보존하고, PNG 관리본을 생성하여 처리한다.**  
> **AruArchive JSON과 XMP는 PNG 관리본에 기록한다.**  
> **sidecar는 원본 BMP와 PNG 관리본의 연결 정보를 보조하는 선택적 수단이다.**

### 2.2 역할 분리 표

| 파일 | file_role | 목적 | 메타데이터 | 분류 대상 |
|------|-----------|------|-----------|---------|
| `{name}.bmp` | `original` | 원본 무결성 보존 | 삽입 안 함 | ❌ |
| `{name}_managed.png` | `managed` | 메타데이터 기록 + 관리 주체 | AruArchive JSON + XMP | ✅ |
| `{name}.bmp.aru.json` | `sidecar` | 원본-관리본 연결 보조 (선택) | 연결 정보 | ❌ |

### 2.3 파일 경로 규칙

```
Inbox/pixiv/
├── 141100516_p0.bmp               ← BMP 원본 (original, metadata_embedded=0)
├── 141100516_p0_managed.png       ← PNG 관리본 (managed, metadata_embedded=1)
└── 141100516_p0.bmp.aru.json      ← sidecar (선택적, 원본↔관리본 연결 정보)
```

> **관리본 명명 규칙**: `{원본 파일명 stem}_managed.png`  
> 이는 동일 그룹에 native PNG 파일이 있을 경우 (`{name}.png`)와의 충돌을 방지한다.

### 2.4 BMP 원본에 대한 절대 금지 사항

- BMP 원본 파일에 직접 메타데이터 삽입 시도 금지
- BMP 원본을 Classified 폴더로 복사 금지 (분류 복사 대상 아님)
- BMP 원본을 갤러리 카드의 대표 파일로 사용 금지 (PNG managed가 우선)

---

## 3. 파일 형식별 저장 정책 수정안

### 3.1 v2.2 기존 행 (폐기)

```
| BMP | `.aru.json` sidecar | 미적용 |
```

위 행은 완전히 폐기한다. sidecar-only 정책은 확정 취소되었다.

### 3.2 수정 후 표 (확정)

v2.2 §3.2의 파일 형식별 저장 위치 표를 아래와 같이 교체한다.

| 파일 형식 | 처리 방식 | AruArchive JSON 저장 위치 | XMP 저장 위치 |
|-----------|-----------|--------------------------|--------------|
| JPEG | original 보존 | EXIF UserComment (`0x9286`, UTF-16LE) | EXIF XMP 세그먼트 (ExifTool) |
| PNG | original 보존 | iTXt chunk (keyword=`AruArchive`) | iTXt chunk (`XML:com.adobe.xmp`) |
| WebP (변환본) | managed 파일 | EXIF UserComment (JPEG와 동일) | EXIF XMP 세그먼트 (ExifTool) |
| ZIP (우고이라 원본) | original 보존 + WebP managed | ZIP comment(식별자) + `.aru.json` sidecar | 미적용 |
| **BMP** | **original 보존 + PNG managed 생성** | **PNG managed의 iTXt chunk** | **PNG managed의 XMP (ExifTool)** |
| GIF | `.aru.json` sidecar | — | — |

> **BMP 처리 원칙**:  
> - BMP 원본 자체에는 메타데이터를 삽입하지 않는다.  
> - AruArchive JSON과 XMP는 반드시 PNG 관리본 내부에 기록한다.  
> - sidecar(`.bmp.aru.json`)는 원본-관리본 연결 정보를 보조하는 선택적 파일이며, 주 메타데이터 저장소가 아니다.

---

## 4. artwork_files 반영

### 4.1 BMP 1건 처리 시 artwork_files 생성 행

BMP 파일 1건이 Inbox에 저장될 때 `artwork_files` 테이블에는 최소 2개, 최대 3개의 행이 생성된다.

#### 행 1: BMP 원본 (original)

```sql
INSERT INTO artwork_files (
    file_id, group_id, page_index,
    file_role, file_path, file_format,
    file_hash, file_size,
    metadata_embedded, file_status,
    created_at
) VALUES (
    'uuid-bmp-001', '<group_id>', 0,
    'original',                                     -- BMP 원본
    'D:/AruArchive/Inbox/pixiv/141100516_p0.bmp',
    'bmp',
    '<sha256>', <size>,
    0,                                              -- 메타데이터 삽입 안 함 (확정)
    'present',
    datetime('now')
);
```

#### 행 2: PNG 관리본 (managed) — 필수

```sql
INSERT INTO artwork_files (
    file_id, group_id, page_index,
    file_role, file_path, file_format,
    file_hash, file_size,
    metadata_embedded, file_status,
    source_file_id,                                 -- BMP original과 연결
    created_at
) VALUES (
    'uuid-png-001', '<group_id>', 0,
    'managed',                                      -- PNG 관리본
    'D:/AruArchive/Inbox/pixiv/141100516_p0_managed.png',
    'png',
    '<sha256>', <size>,
    1,                                              -- AruArchive JSON 기록 완료
    'present',
    'uuid-bmp-001',                                 -- BMP original의 file_id
    datetime('now')
);
```

#### 행 3: sidecar (선택적)

```sql
INSERT INTO artwork_files (
    file_id, group_id, page_index,
    file_role, file_path, file_format,
    metadata_embedded, file_status,
    source_file_id,
    created_at
) VALUES (
    'uuid-sidecar-001', '<group_id>', 0,
    'sidecar',
    'D:/AruArchive/Inbox/pixiv/141100516_p0.bmp.aru.json',
    'json',
    0, 'present',
    'uuid-bmp-001',                                 -- BMP original 연결
    datetime('now')
);
```

### 4.2 source_file_id 연결 관계도

```
artwork_groups
  └─ group_id: '<group_id>'
       │
       ├─ artwork_files [file_role='original', file_format='bmp']
       │      file_id: 'uuid-bmp-001'
       │      source_file_id: NULL  ← 원본이므로 없음
       │      metadata_embedded: 0
       │
       ├─ artwork_files [file_role='managed', file_format='png']
       │      file_id: 'uuid-png-001'
       │      source_file_id: 'uuid-bmp-001'  ← BMP original 참조
       │      metadata_embedded: 1
       │
       └─ artwork_files [file_role='sidecar', file_format='json']  (선택)
              file_id: 'uuid-sidecar-001'
              source_file_id: 'uuid-bmp-001'  ← BMP original 참조
              metadata_embedded: 0
```

### 4.3 cover_file_id 정책

`artwork_groups.cover_file_id`는 그룹의 대표 파일을 가리킨다.  
BMP 그룹의 경우 PNG managed(`uuid-png-001`)를 `cover_file_id`로 설정한다.  
BMP original을 `cover_file_id`로 설정하지 않는다.

```python
# BMP 처리 완료 후
db.execute("""
    UPDATE artwork_groups
    SET cover_file_id = ?
    WHERE group_id = ?
""", (png_managed_file_id, group_id))
```

---

## 5. BMP 처리 플로우

### 5.1 전체 처리 흐름

```
[CoreWorker] BMP 파일 처리

Step 1: BMP 파일 수신
  ↓
Step 2: artwork_groups INSERT (metadata_sync_status='pending')

Step 3: BMP 원본 Inbox 저장
  · Inbox/pixiv/141100516_p0.bmp 저장
  · artwork_files INSERT:
      file_role='original'
      file_format='bmp'
      metadata_embedded=0
  ↓
Step 4: BMP 원본에 메타데이터 삽입 시도 → 시도하지 않음 (정책)

Step 5: PNG 관리본 생성 시도
  ┌── 성공 → Step 6
  └── 실패 → Step 5-FAIL

  [Step 5-FAIL: PNG 생성 실패]
    · artwork_groups UPDATE metadata_sync_status='convert_failed'
    · no_metadata_queue INSERT:
        fail_reason='bmp_convert_failed'
        raw_context='{error_detail}'
    · thumbnail_cache 생성: BMP 원본에서 임시 생성
    · artwork_files 행 1(BMP original)은 그대로 유지
    → CoreWorker 이 그룹 처리 종료 (저장은 성공, 관리본 없음 상태)

Step 6: PNG 관리본에 AruArchive JSON 임베딩 시도
  ┌── 성공 → Step 7
  └── 실패 → Step 6-FAIL

  [Step 6-FAIL: JSON 임베딩 실패]
    · artwork_groups UPDATE metadata_sync_status='metadata_write_failed'
    · no_metadata_queue INSERT:
        fail_reason='metadata_write_failed'
    · PNG 파일은 생성되었으나 metadata_embedded=0 상태로 등록
    → Step 8로 진행 (썸네일만 생성)

Step 7: XMP 표준 필드 기록 시도 (ExifTool 있는 경우)
  ┌── ExifTool 없음 → metadata_sync_status='json_only'
  ├── ExifTool 있음, 성공 → metadata_sync_status='full'
  └── ExifTool 있음, 실패 → metadata_sync_status='xmp_write_failed'
                           + no_metadata_queue INSERT: fail_reason='xmp_write_failed'

Step 8: artwork_files INSERT (PNG managed)
  · file_role='managed'
  · file_format='png'
  · source_file_id=<bmp_original_file_id>
  · metadata_embedded=1 (Step 6 성공 시) 또는 0 (Step 6-FAIL 시)

Step 9: sidecar 생성 (선택적)
  · Inbox/pixiv/141100516_p0.bmp.aru.json 저장
  · artwork_files INSERT: file_role='sidecar'
  · 내용: {bmp_original_file_id, png_managed_file_id, group_id, timestamp}

Step 10: artwork_groups 갱신
  · cover_file_id = <png_managed_file_id>
  · metadata_sync_status = 최종 결정값

Step 11: thumbnail_cache 생성
  · PNG managed 기준으로 생성 (Step 5 성공 시)
  · BMP 원본 기준 임시 생성 (Step 5-FAIL 시)

Step 12: tags INSERT, 완료 응답
```

### 5.2 성공 케이스 요약

```
입력: 141100516_p0.bmp

결과:
  Inbox/pixiv/141100516_p0.bmp          ← original (metadata_embedded=0)
  Inbox/pixiv/141100516_p0_managed.png  ← managed  (metadata_embedded=1)
  Inbox/pixiv/141100516_p0.bmp.aru.json ← sidecar  (선택)

artwork_groups.metadata_sync_status:
  ExifTool 있음 → 'full'
  ExifTool 없음 → 'json_only'

artwork_groups.cover_file_id → PNG managed file_id
```

### 5.3 실패 케이스별 처리

| 실패 케이스 | metadata_sync_status | no_metadata_queue fail_reason | BMP 원본 | PNG managed |
|-------------|---------------------|-------------------------------|---------|-------------|
| PNG 생성 실패 | `convert_failed` | `bmp_convert_failed` | 보존됨 | 없음 |
| PNG 생성 성공, JSON 임베딩 실패 | `metadata_write_failed` | `metadata_write_failed` | 보존됨 | 생성됨 (metadata_embedded=0) |
| JSON 성공, XMP 실패 | `xmp_write_failed` | `xmp_write_failed` | 보존됨 | 생성됨 (metadata_embedded=1, XMP 없음) |
| PNG 생성 성공, ExifTool 없음 | `json_only` | — (정상 처리) | 보존됨 | 생성됨 (full JSON, XMP 없음) |

---

## 6. 분류 엔진 반영

### 6.1 분류 대상 파일 선택 정책

분류 엔진(Classifier)은 `artwork_groups` 단위로 실행되며, 각 그룹에서 분류 복사 대상 파일을 아래 우선순위로 선택한다.

```
분류 대상 선택 우선순위:

1. file_role='managed' 파일이 있으면 managed를 분류 대상으로 사용
2. managed가 없으면 file_role='original' 파일을 분류 대상으로 사용
3. 단, file_format='bmp'인 original 파일은 이 우선순위에서 제외
   → BMP original은 managed 없이 직접 분류되지 않는다
4. BMP original만 있고 PNG managed가 없는 경우
   → PNG managed 생성을 먼저 시도
   → 생성 성공 시 managed를 분류 대상으로 사용
   → 생성 실패 시 no_metadata_queue에 등록, 분류 skip
```

### 6.2 Classifier 코드 반영

```python
# core/classifier.py

def select_classify_target(group_id: str, db) -> ArtworkFile | None:
    """분류 대상 파일 선택. managed 우선, BMP original 직접 분류 금지."""
    files = db.execute("""
        SELECT * FROM artwork_files
        WHERE group_id = ?
          AND file_status = 'present'
        ORDER BY
            CASE file_role
                WHEN 'managed' THEN 1
                WHEN 'original' THEN 2
                ELSE 3
            END
    """, (group_id,)).fetchall()

    for f in files:
        if f['file_role'] == 'managed':
            return f  # managed 우선 반환
        if f['file_role'] == 'original' and f['file_format'] == 'bmp':
            continue  # BMP original 건너뜀
        if f['file_role'] == 'original':
            return f  # 비-BMP original 반환

    # managed 없는 BMP original만 존재하는 경우
    bmp_original = next(
        (f for f in files if f['file_format'] == 'bmp' and f['file_role'] == 'original'),
        None
    )
    if bmp_original:
        # PNG managed 생성 재시도
        png_path = attempt_bmp_to_png(bmp_original['file_path'])
        if png_path:
            # 생성 성공 → artwork_files INSERT 후 분류 진행
            return register_png_managed(png_path, bmp_original, db)
        else:
            # 생성 실패 → no_metadata_queue 등록
            register_no_metadata(
                bmp_original['file_path'],
                fail_reason='managed_file_create_failed',
                db=db
            )
    return None  # 분류 skip
```

### 6.3 분류 복사 대상 정책표

| 파일 | 분류 복사 대상 | 이유 |
|------|--------------|------|
| BMP original | ❌ | 원본 보존용. 메타데이터 없음 |
| PNG managed | ✅ | 메타데이터 내장. Classified 폴더로 복사 |
| sidecar (.aru.json) | ❌ | 보조 파일. 분류 대상 아님 |

### 6.4 Classified 폴더 복사 결과

```
Classified/
└── 작가/作家名/
    └── 141100516_p0_managed.png   ← PNG managed 복사본 (메타데이터 포함)

Inbox/pixiv/
├── 141100516_p0.bmp               ← BMP original (영구 보존, 이동/복사 없음)
├── 141100516_p0_managed.png       ← PNG managed (원본 위치 유지)
└── 141100516_p0.bmp.aru.json      ← sidecar (위치 유지)
```

---

## 7. metadata_sync_status / fail_reason 반영

### 7.1 metadata_sync_status 추가 값

v2.2의 기존 4개 값(`pending`, `full`, `json_only`, `out_of_sync`)에 다음을 추가한다.

| 값 | 의미 | 발생 조건 | 다음 상태 |
|----|------|-----------|-----------|
| `convert_failed` | **신규** PNG/WebP 변환 자체 실패 | BMP→PNG 변환 중 Pillow 오류 등 | `pending` (재시도) |
| `metadata_write_failed` | **신규** 메타데이터 파일 임베딩 실패 | PNG 생성 후 iTXt 쓰기 실패 등 | `pending` (재시도) |
| `xmp_write_failed` | **신규** JSON 성공, XMP 단계만 실패 | ExifTool 오류, 권한 문제 등 | `json_only` (강등) 또는 `full` (재시도) |

> **`file_write_failed`와의 구분**:
> - `file_write_failed`: 파일 저장(write) 자체가 실패한 경우 (디스크 풀, 권한 거부 등)
> - `metadata_write_failed`: 파일은 생성되었으나 메타데이터 임베딩 단계에서 실패한 경우
> - `convert_failed`: 변환(BMP→PNG, GIF→WebP 등) 자체가 실패한 경우

**BMP 처리 시 metadata_sync_status 전이표**:

```
BMP 저장 시작
  artwork_groups.metadata_sync_status = 'pending'
  │
  ├── PNG 생성 실패
  │     → 'convert_failed'
  │
  ├── PNG 생성 성공 + JSON 임베딩 실패
  │     → 'metadata_write_failed'
  │
  ├── PNG 생성 성공 + JSON 성공 + XMP 실패
  │     → 'xmp_write_failed'
  │
  ├── PNG 생성 성공 + JSON 성공 + ExifTool 없음
  │     → 'json_only'
  │
  └── PNG 생성 성공 + JSON 성공 + XMP 성공
        → 'full'
```

### 7.2 no_metadata_queue.fail_reason 추가 값

v2.2의 기존 5개 값에 다음을 추가한다.

| 값 | 발생 시점 | 권장 UI 대응 |
|----|-----------|-------------|
| `bmp_convert_failed` | **신규** BMP→PNG 변환 실패 | "PNG 관리본 생성 실패" 표시 + 재시도 버튼 |
| `managed_file_create_failed` | **신규** managed 파일 생성/등록 실패 (범용) | "관리본 생성 실패" 표시 + 재시도 버튼 |
| `metadata_write_failed` | **신규** 파일 생성 후 메타데이터 임베딩 실패 | "메타데이터 기록 실패" 표시 + 재임베딩 버튼 |
| `xmp_write_failed` | **신규** AruArchive JSON 성공, XMP만 실패 | "XMP 기록 실패 (JSON 완료)" 표시 + XMP 재시도 버튼 |

**BMP 실패 시 no_metadata_queue 기록 예시**:

```python
# BMP → PNG 변환 실패 시
db.execute("""
    INSERT INTO no_metadata_queue
        (queue_id, file_path, source_site, detected_at, fail_reason, raw_context)
    VALUES (?, ?, ?, datetime('now'), ?, ?)
""", (
    str(uuid4()),
    bmp_original_path,
    'pixiv',
    'bmp_convert_failed',
    json.dumps({
        'error': str(exception),
        'bmp_path': bmp_original_path,
        'target_png_path': expected_png_path,
    })
))
```

### 7.3 v2.2 artwork_groups 테이블 DDL 패치

v2.2 §4.2의 `metadata_sync_status` 컬럼 주석을 다음과 같이 교체한다.

```sql
-- 기존 (v2.2)
metadata_sync_status  TEXT NOT NULL DEFAULT 'full',
                      -- full | json_only | out_of_sync | pending

-- 수정 후 (패치 적용)
metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
                      -- pending | full | json_only | out_of_sync |
                      -- convert_failed | metadata_write_failed | xmp_write_failed
```

> **기본값 변경 주목**: `full` → `pending`으로 변경.  
> BMP 처리 과정에서 중간 상태 추적이 필수이므로, 임베딩 완료 전에는 반드시 `pending`이어야 한다.

### 7.4 v2.2 no_metadata_queue 테이블 DDL 패치

v2.2 §4.5의 `fail_reason` 주석을 다음과 같이 교체한다.

```sql
-- 기존 (v2.2)
fail_reason   TEXT NOT NULL,
              -- no_dom_data | parse_error | network_error |
              --  unsupported_format | manual_add

-- 수정 후 (패치 적용)
fail_reason   TEXT NOT NULL,
              -- no_dom_data | parse_error | network_error |
              -- unsupported_format | manual_add |
              -- bmp_convert_failed | managed_file_create_failed |
              -- metadata_write_failed | xmp_write_failed
```

---

## 8. UI / UX 반영

### 8.1 갤러리 카드 (1작품 = 1카드)

BMP 원본과 PNG 관리본을 **별도 카드로 표시하지 않는다**.  
`artwork_groups` 단위로 하나의 카드를 표시하며, 카드의 대표 파일은 PNG managed를 우선한다.

```
┌─────────────────────────────┐
│  [PNG managed 썸네일]        │
│                             │
│  141100516_p0               │
│  作家名                      │
│                             │
│  BMP + PNG 관리본            │  ← 파일 구성 요약
│  ✅ 메타데이터 기록 완료       │
│                             │
│  태그: オリジナル, 女の子 ...  │
└─────────────────────────────┘
```

**상태별 카드 표시**:

| 상태 | 카드 표시 | 배지 |
|------|----------|------|
| PNG managed 있음, 메타데이터 완료 | 정상 | ✅ |
| PNG managed 있음, JSON만 (XMP 없음) | 정상 | ⚠️ (XMP 없음) |
| PNG managed 없음 (변환 실패) | 경고 | ❌ PNG 관리본 없음 |
| PNG managed 있음, 메타데이터 실패 | 경고 | ⚠️ 메타데이터 재기록 필요 |

### 8.2 상세 패널 — 파일 구성 탭

작품 상세 보기의 "파일 구성" 탭에는 group에 속한 모든 파일을 아래 형식으로 표시한다.

```
파일 구성
─────────────────────────────────────────────

◼ 원본 파일
  파일명: 141100516_p0.bmp
  역할:   original
  형식:   BMP
  상태:   보존됨 ✅
  메타데이터: 삽입 안 함 (정책)

◼ 관리본 파일
  파일명: 141100516_p0_managed.png
  역할:   managed
  형식:   PNG
  상태:   정상 ✅
  메타데이터: AruArchive JSON ✅ / XMP ✅
  분류 대상: 예

◼ sidecar (보조)
  파일명: 141100516_p0.bmp.aru.json
  역할:   sidecar
  형식:   JSON
  상태:   보존됨 ✅
  내용:   원본↔관리본 연결 정보

─────────────────────────────────────────────
[PNG 관리본 열기]  [BMP 원본 위치 열기]  [재처리]
```

**PNG managed 없는 경우 (convert_failed)**:

```
파일 구성
─────────────────────────────────────────────

◼ 원본 파일
  파일명: 141100516_p0.bmp
  역할:   original
  상태:   보존됨 ✅

◼ 관리본 파일
  상태:   ❌ PNG 관리본 생성 실패
  오류:   [오류 내용]

─────────────────────────────────────────────
[PNG 관리본 재생성 시도]  [No Metadata 큐에서 확인]
```

### 8.3 썸네일 기준 정책

```
BMP 파일 처리 시 thumbnail_cache 생성 기준:

1. PNG managed 있음
   → PNG managed에서 썸네일 생성
   → artwork_groups.cover_file_id = PNG managed file_id
   → thumbnail_cache.file_id = PNG managed file_id

2. PNG managed 없음 (변환 실패)
   → BMP 원본에서 임시 썸네일 생성 (Pillow로 가능)
   → artwork_groups.cover_file_id = BMP original file_id (임시)
   → thumbnail_cache.file_id = BMP original file_id (임시)
   → PNG managed 생성 성공 시 → thumbnail_cache 갱신 + cover_file_id 갱신

3. PNG managed 생성 성공 후 나중에 삭제된 경우 (file_status='missing')
   → 갤러리 카드: [?] 아이콘 + "관리본 없음" 배지
   → BMP 원본에서 임시 썸네일 재생성 시도
```

```python
# core/thumbnail_manager.py

def get_thumbnail_source(group_id: str, db) -> ArtworkFile | None:
    """썸네일 생성 기준 파일 선택: managed 우선, BMP original 폴백."""
    # PNG managed 우선
    managed = db.execute("""
        SELECT * FROM artwork_files
        WHERE group_id=? AND file_role='managed'
          AND file_format='png' AND file_status='present'
        LIMIT 1
    """, (group_id,)).fetchone()
    if managed:
        return managed

    # BMP original 폴백 (임시)
    original = db.execute("""
        SELECT * FROM artwork_files
        WHERE group_id=? AND file_role='original'
          AND file_status='present'
        LIMIT 1
    """, (group_id,)).fetchone()
    return original
```

### 8.4 No Metadata 큐 패널 — BMP 항목

```
No Metadata 패널
─────────────────────────────────────────────
[썸네일]  141100516_p0.bmp
         오류: PNG 관리본 생성 실패 (bmp_convert_failed)
         저장 시각: 2026-04-26 15:30

         [PNG 관리본 재생성]  [수동 입력]  [무시]
─────────────────────────────────────────────
```

| fail_reason | 표시 메시지 | 제공 버튼 |
|-------------|-----------|---------|
| `bmp_convert_failed` | PNG 관리본 생성 실패 | 재생성, 원본 파일 열기, 무시 |
| `managed_file_create_failed` | 관리본 파일 생성 실패 | 재생성, 원본 파일 열기, 무시 |
| `metadata_write_failed` | 메타데이터 기록 실패 | 재임베딩 시도, 수동 입력, 무시 |
| `xmp_write_failed` | XMP 기록 실패 (JSON은 완료) | XMP 재시도, 무시 (json_only로 유지) |

---

## 9. v2.2 본문 수정 위치

### 9.1 §3.2 파일 형식별 저장 위치 (필수 수정)

**수정 전**:
```
| GIF | `.aru.json` sidecar | 미적용 |
| BMP | `.aru.json` sidecar | 미적용 |
```

**수정 후**:
```
| BMP | original 보존 + PNG managed 생성 | PNG managed의 iTXt chunk | PNG managed의 XMP (ExifTool) |
```

> sidecar 명명 안내 주석에 다음 내용을 추가한다:  
> "BMP 처리 시 생성되는 sidecar는 원본-관리본 연결 정보를 담으며, 주 메타데이터 저장소가 아니다."

---

### 9.2 §4.1 전체 테이블 목록 (설명 보완)

`artwork_files` 행의 설명을 다음과 같이 수정한다.

**수정 전**:
```
artwork_files | 개별 파일 (원본/사이드카/분류복사본) | A
```

**수정 후**:
```
artwork_files | 개별 파일 (original/managed/sidecar/classified_copy). BMP는 original+managed 2행 생성 | A
```

---

### 9.3 §4.2 artwork_groups 테이블 (metadata_sync_status 수정)

**수정 전 DDL 주석**:
```sql
metadata_sync_status  TEXT NOT NULL DEFAULT 'full',
                      -- full | json_only | out_of_sync | pending
```

**수정 후 DDL 주석**:
```sql
metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
                      -- pending | full | json_only | out_of_sync |
                      -- convert_failed | metadata_write_failed | xmp_write_failed
```

**수정 전 metadata_sync_status 값 정의 표**:

| 값 | 의미 |
|----|------|
| `full` | AruArchive JSON + XMP 모두 임베딩 완료 |
| `json_only` | AruArchive JSON만 임베딩 (ExifTool 없음) |
| `out_of_sync` | DB와 파일 메타데이터 불일치 감지 |
| `pending` | 임베딩 작업 진행 중 |

**수정 후 metadata_sync_status 값 정의 표**:

| 값 | 의미 | 다음 상태 |
|----|------|-----------|
| `pending` | 기본값. 임베딩 시작 전 또는 진행 중 | full / json_only / convert_failed 등 |
| `full` | AruArchive JSON + XMP 모두 임베딩 완료 | out_of_sync (파일 변경 감지 시) |
| `json_only` | AruArchive JSON만 임베딩 (ExifTool 없음) | full (ExifTool 추가 후 재실행) |
| `out_of_sync` | DB와 파일 메타데이터 불일치 감지 | full (재동기화 후) |
| `convert_failed` | **추가** 파일 변환 자체 실패 (BMP→PNG 등) | pending (재시도) |
| `metadata_write_failed` | **추가** 변환 성공, 메타데이터 임베딩 실패 | pending (재시도) |
| `xmp_write_failed` | **추가** JSON 성공, XMP 단계만 실패 | json_only 또는 full (재시도) |

---

### 9.4 §4.3 artwork_files 테이블 (file_role 설명 보완)

`file_role` 값 정의 표를 다음과 같이 수정한다.

**수정 전**:

| 값 | 의미 |
|----|------|
| `original` | Inbox에 저장된 최초 다운로드 파일 |
| `managed` | 변환된 관리 파일 (ugoira → WebP 변환본) |
| `sidecar` | `.aru.json` 사이드카 파일 |
| `classified_copy` | Classified 폴더로 복사된 파일 |

**수정 후**:

| 값 | 의미 |
|----|------|
| `original` | Inbox에 저장된 최초 다운로드 파일. BMP original은 metadata_embedded=0 |
| `managed` | 변환된 관리 파일. ugoira→WebP, **BMP→PNG managed** 포함. metadata_embedded=1 |
| `sidecar` | 보조 파일. ZIP식별자 sidecar, **BMP 원본-관리본 연결 sidecar** 포함 |
| `classified_copy` | Classified 폴더로 복사된 파일. BMP original은 포함되지 않음 |

---

### 9.5 §4.5 no_metadata_queue 테이블 (fail_reason 추가)

**수정 전 DDL 주석**:
```sql
fail_reason   TEXT NOT NULL,
              -- no_dom_data | parse_error | network_error |
              --  unsupported_format | manual_add
```

**수정 후 DDL 주석**:
```sql
fail_reason   TEXT NOT NULL,
              -- no_dom_data | parse_error | network_error |
              -- unsupported_format | manual_add |
              -- bmp_convert_failed | managed_file_create_failed |
              -- metadata_write_failed | xmp_write_failed
```

**수정 전 fail_reason 표 (5개)**:

| 값 | 발생 시점 |
|----|-----------|
| `no_dom_data` | content_script가 preload_data를 찾지 못함 |
| `parse_error` | 메타데이터 파싱 중 예외 발생 |
| `network_error` | 다운로드 실패 (httpx 오류) |
| `unsupported_format` | 지원하지 않는 파일 형식 |
| `manual_add` | 사용자가 수동으로 큐에 추가 |

**수정 후 fail_reason 표 (9개)**:

| 값 | 발생 시점 | 권장 대응 |
|----|-----------|-----------|
| `no_dom_data` | content_script preload_data 찾지 못함 | 페이지 새로고침 후 재시도 |
| `parse_error` | 메타데이터 파싱 중 예외 | 개발자 신고 |
| `network_error` | 다운로드 실패 | 재다운로드 |
| `unsupported_format` | 지원하지 않는 형식 | 수동 입력 |
| `manual_add` | 사용자 수동 추가 | 메타데이터 직접 입력 |
| `bmp_convert_failed` | **추가** BMP→PNG 변환 실패 | PNG 재생성 시도 |
| `managed_file_create_failed` | **추가** managed 파일 생성/등록 실패 | 재생성 시도 |
| `metadata_write_failed` | **추가** 파일 생성 후 메타데이터 임베딩 실패 | 재임베딩 시도 |
| `xmp_write_failed` | **추가** JSON 성공, XMP 단계만 실패 | XMP 재시도 또는 json_only 유지 |

---

### 9.6 §11 썸네일 캐시 / 성능 (BMP 항목 추가)

**썸네일 없는 경우 플레이스홀더** 표에 다음 행을 추가한다:

| 상황 | 플레이스홀더 |
|------|------------|
| BMP 원본만 있음 (convert_failed) | BMP 아이콘 + "관리본 없음" 배지 |
| BMP 원본 + PNG managed 있음 | PNG managed 썸네일 사용 (정상) |

**썸네일 생성 정책**에 다음 내용을 추가한다:

> **BMP 파일의 썸네일**:  
> PNG managed가 생성된 이후에는 PNG managed를 기준으로 `thumbnail_cache`를 생성한다.  
> PNG managed가 없는 경우(변환 실패 상태), BMP 원본에서 임시 썸네일을 생성할 수 있다.  
> PNG managed가 나중에 생성되면 기존 BMP 기준 썸네일을 invalidate하고 PNG 기준으로 재생성한다.

---

### 9.7 §12 No Metadata 큐 정책 (BMP 기록 시점 추가)

**기록 시점** 목록에 다음을 추가한다:

- BMP → PNG 변환 실패 시 (`bmp_convert_failed`)
- PNG managed 생성은 성공했으나 메타데이터 임베딩 실패 시 (`metadata_write_failed`)
- XMP 기록만 실패 시 (`xmp_write_failed`)

---

### 9.8 §13.1 저장 플로우 (BMP 처리 분기 추가)

CoreWorker의 "형식별 처리" 단계에 BMP 분기를 추가한다.

**수정 전**:
```
e. 파일 형식별 처리:
     JPEG/WebP → piexif EXIF UserComment (AruArchive JSON)
     PNG → iTXt chunk (AruArchive JSON)
     ZIP → ZIP comment + .aru.json sidecar
     GIF/BMP → .aru.json sidecar
```

**수정 후**:
```
e. 파일 형식별 처리:
     JPEG/WebP → piexif EXIF UserComment (AruArchive JSON)
     PNG → iTXt chunk (AruArchive JSON)
     ZIP → ZIP comment + .aru.json sidecar
     GIF → .aru.json sidecar
     BMP → [별도 BMP 처리 파이프라인 실행]
              1. BMP 원본 Inbox 저장 (metadata_embedded=0)
              2. PNG managed 생성 (Pillow)
              3. PNG managed에 AruArchive JSON 임베딩
              4. (ExifTool) PNG managed에 XMP 기록
              5. artwork_files INSERT: original(bmp) + managed(png) + sidecar(json, 선택)
              6. artwork_groups.cover_file_id = PNG managed file_id
              → 실패 시 no_metadata_queue INSERT (fail_reason=bmp_convert_failed 등)
```

---

### 9.9 §14 Sprint 반영 사항 (Sprint 1 추가 항목)

Sprint 1 필수 구현 항목에 다음을 추가한다:

```
☑  no_metadata_queue fail_reason: bmp_convert_failed, managed_file_create_failed,
                                   metadata_write_failed, xmp_write_failed 추가
☑  artwork_groups.metadata_sync_status: convert_failed, metadata_write_failed,
                                         xmp_write_failed 값 추가
☑  metadata_sync_status 기본값: 'pending' (full 아님)
```

Sprint 2 필수 구현 항목에 다음을 추가한다:

```
☑  core/format_converter.py: bmp_to_png() 구현 + 단위 테스트
☑  BMP 처리 파이프라인 통합 테스트 (성공/실패 케이스 각각)
☑  thumbnail_manager.py: BMP 원본 임시 썸네일 + PNG managed 전환 로직
☑  no_metadata_queue 기록 검증 (bmp_convert_failed 케이스)
```

---

## 적용 체크리스트

패치 적용 완료 여부를 확인하기 위한 체크리스트:

- [ ] §3.2 표에서 `BMP = .aru.json sidecar / 미적용` 행 삭제
- [ ] §3.2 표에 BMP 처리 방식 (original+managed+sidecar) 행 추가
- [ ] §4.2 DDL에서 `metadata_sync_status` 기본값 `full` → `pending` 변경
- [ ] §4.2 metadata_sync_status 표에 `convert_failed`, `metadata_write_failed`, `xmp_write_failed` 추가
- [ ] §4.3 file_role 표 설명에 BMP original / BMP→PNG managed 내용 반영
- [ ] §4.5 DDL fail_reason 주석에 4개 BMP 관련 값 추가
- [ ] §4.5 fail_reason 표 9개로 확장
- [ ] §11 썸네일 정책에 BMP 원본 vs PNG managed 기준 추가
- [ ] §12 No Metadata 기록 시점에 BMP 실패 케이스 추가
- [ ] §13.1 저장 플로우 BMP 처리 분기 추가
- [ ] §14 Sprint 1/2 구현 항목에 BMP 관련 항목 추가
- [ ] 전체 문서에서 "GIF/BMP → .aru.json sidecar" 표현 수정
- [ ] 전체 문서에서 "BMP는 XMP 미적용" 표현 수정

---

*이 문서는 v2.2 BMP 정책 패치이며, v2.3 이후 설계안에는 본 내용이 통합 반영되어야 한다.*
