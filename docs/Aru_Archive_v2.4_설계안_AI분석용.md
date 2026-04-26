# Aru Archive 최종 개발 착수용 설계안 v2.4

## 메타데이터

- **문서 버전**: 2.4 (최종 통합본)
- **작성일**: 2026-04-26
- **기준 문서**: 최종 개발 착수용 설계안 v2.3 + v2.3.1 상태값 정합성 패치
- **목적**: AI 코드 생성 및 분석 요청 시 참조 컨텍스트 (개발 착수 확정판)
- **개발 언어**: Python 3.12 (백엔드/메인앱), JavaScript (브라우저 확장 MV3)
- **대상 플랫폼**: Windows 11, Chrome / Naver Whale

---

## 1. 개정 요약

### 1.1 v2.3에서 유지한 구조 (변경 없음)

| 항목 | v2.3 확정 내용 |
|------|---------------|
| BMP 저장 정책 | original 보존 + PNG managed 생성 + PNG에 JSON/XMP 기록 |
| GIF animated 저장 정책 | original 보존 + WebP managed 생성 + WebP에 JSON/XMP 기록 |
| GIF static 저장 정책 | original 보존 + sidecar only (파일 우선 원칙의 예외) |
| artwork_groups / artwork_files 구조 | UUID 기반 그룹-파일 분리 모델 |
| save_jobs / job_pages | 저장 작업 진행률 추적 (총 12개 테이블) |
| thumbnail_cache Hybrid path 방식 | BLOB 없음, `.thumbcache/` 디렉토리 + DB 인덱스 |
| IPC 토큰 인증 | X-Aru-Token 헤더, 세션별 UUID |
| operation_locks 키 정책 | `save:{site}:{id}`, `classify:{group_id}` 등 6종 키 패턴 |
| classify_mode | `save_only` / `immediate` / `review` |
| MVP-A/B/C 구조 | MVP-A: 저장 파이프라인, MVP-B: 분류/Undo, MVP-C: 태그 별칭 |
| X 어댑터 | Post-MVP |
| undo_status 값 | `pending` / `completed` / `failed` / `expired` |

### 1.2 v2.3.1에서 통합한 패치 내용

| 항목 | 변경 내용 |
|------|----------|
| `metadata_sync_status` | 9개 → **11개** (`convert_failed`, `metadata_write_failed` 추가) |
| `no_metadata_queue.fail_reason` | 9개 → **13개** (`bmp_convert_failed`, `managed_file_create_failed`, `metadata_write_failed`, `xmp_write_failed` 추가) |
| `embed_failed` 역할 | 범용 폴백으로 명시 (세부 reason 우선 사용) |
| managed 변환 공통 상태 전이 | BMP/animated GIF/ugoira 공통 4단계 파이프라인 문서화 |
| BMP 실패 케이스 매핑표 | 6개 케이스 전체 매핑 (metadata_sync_status × fail_reason × 파일 상태) |
| static GIF 예외 정책 | 파일 우선 원칙의 예외임을 명시, 적용 사유 문서화 |
| `xmp_write_failed` 처리 | no_metadata_queue 기록 안 함, UI Warning 배지로 처리 |
| `undo_status` 명칭 | `pending` 유지 (변경 없음), UI 레이블 매핑 명시 |

### 1.3 v2.4 최종 확정 사항

- **구조적 변경 없음**: v2.4는 v2.3 + v2.3.1의 통합본이며, 새로운 설계 결정을 추가하지 않는다.
- **enum 정합성 완료**: `metadata_sync_status` 11개, `fail_reason` 13개로 모든 파이프라인 케이스를 빠짐없이 커버한다.
- **static GIF 예외 정책 확정**: 파일 우선 원칙의 한시적 예외로 문서에 명시된다.
- **이 문서가 유일한 개발 착수 기준 문서**다. v2.3, v2.3.1 패치는 이 문서에 흡수 완료.

### 1.4 설계 핵심 원칙 (변경 없음)

| 원칙 | 설명 |
|------|------|
| 파일 우선 메타데이터 | 메타데이터 원본은 항상 파일 내부. DB는 검색 보조 인덱스 전용 |
| 복사 기반 분류 | 분류 시 원본을 이동하지 않고 복사. Inbox 파일은 항상 보존 |
| 2단계 저장 | Inbox 저장 → 메타데이터 임베딩 → (분류 폴더 복사) |
| 포터블 배포 | PyInstaller 단일 폴더 빌드, 설치 없이 실행 가능 |
| 확장 가능 구조 | Pixiv 우선 구현, 어댑터 패턴으로 추후 사이트 추가 |

---

## 2. MVP 정책 최종 정리

### 2.1 MVP 단계별 범위

| 기능 | MVP-A | MVP-B | MVP-C | Post-MVP |
|------|-------|-------|-------|----------|
| 브라우저 확장 → Native Host 저장 | ✅ | ✅ | ✅ | ✅ |
| Inbox 저장 + 메타데이터 임베딩 | ✅ | ✅ | ✅ | ✅ |
| BMP → PNG managed 변환 | ✅ | ✅ | ✅ | ✅ |
| GIF animated → WebP managed 변환 | ✅ | ✅ | ✅ | ✅ |
| No Metadata Queue 기록 | ✅ | ✅ | ✅ | ✅ |
| classify_mode = save_only | ✅ | - | - | - |
| save_jobs / job_pages 진행률 추적 | ✅ | ✅ | ✅ | ✅ |
| PySide6 Inbox 뷰어 (기본 그리드) | ✅ | ✅ | ✅ | ✅ |
| SQLite 보조 인덱스 | ✅ | ✅ | ✅ | ✅ |
| 분류 규칙 엔진 (immediate/review) | ❌ | ✅ | ✅ | ✅ |
| 분류 미리보기 UI | ❌ | ✅ | ✅ | ✅ |
| Undo / 작업 로그 UI | ❌ | ✅ | ✅ | ✅ |
| copy_records 보존 관리 | ❌ | ✅ | ✅ | ✅ |
| thumbnail_cache (hybrid) + 가상화 그리드 | ❌ | ✅ | ✅ | ✅ |
| ExifTool XMP 생성 | ❌ | ✅ | ✅ | ✅ |
| 태그 별칭 (tag_aliases) | ❌ | ❌ | ✅ | ✅ |
| X(트위터) 어댑터 | ❌ | ❌ | ❌ | ✅ |

### 2.2 classify_mode 정책

```
classify_mode: save_only   (MVP-A 기본, 분류 엔진 없음)
               immediate   (MVP-B, 저장 직후 자동 분류)
               review      (MVP-B, 분류 미리보기 후 사용자 확인)
```

- **MVP-A**: `config.json`에 `"classify_mode": "save_only"` 고정
- **MVP-B 활성화**: 설정 UI에서 `immediate` / `review` 선택 가능
- **classify_mode 변경 시**: 변경 시점 이후 신규 저장분부터 적용 (소급 없음)

### 2.3 MVP-A 최소 완성 조건

1. 브라우저 확장에서 저장 버튼 → Inbox에 파일 저장 + 메타데이터 임베딩 완료
2. BMP → PNG managed 변환 동작 확인
3. animated GIF → WebP managed 변환 동작 확인
4. PySide6 갤러리 뷰에서 Inbox 파일 썸네일 표시 및 클릭 상세 보기
5. No Metadata 파일은 `no_metadata_queue`에 기록, UI에 카운터 표시
6. `save_jobs` 진행률 실시간 폴링 동작
7. SQLite artworks DB 색인 완료
8. 포터블 exe 빌드 + `install_host.bat` 레지스트리 등록 동작

---

## 3. 메타데이터 저장 정책

### 3.1 이중 저장 구조

```
AruArchive JSON (필수, MVP-A)
  · 완전한 스키마 (schema_version, provenance, ugoira 포함)
  · 파일 형식별 저장 위치 (§3.2 참조)

XMP 표준 필드 (선택, MVP-B, ExifTool 필요)
  · dc:title, dc:creator, dc:subject (tags), xmp:CreateDate
  · ExifTool 없으면 이 단계 skip (경고 로그만)
```

### 3.2 파일 형식별 저장 정책 (v2.4 확정)

| 파일 형식 | 처리 방식 | AruArchive JSON | XMP |
|-----------|-----------|-----------------|-----|
| JPEG | original 보존 | EXIF UserComment (`0x9286`, UTF-16LE) | EXIF XMP 세그먼트 (ExifTool) |
| PNG | original 보존 | iTXt chunk (keyword=`AruArchive`) | iTXt chunk (`XML:com.adobe.xmp`) |
| WebP (ugoira/BMP/GIF 변환본) | managed 파일 | EXIF UserComment (JPEG와 동일) | EXIF XMP 세그먼트 (ExifTool) |
| ZIP (우고이라 원본) | original 보존 + WebP managed | ZIP comment(식별자) + `.aru.json` sidecar | 미적용 (sidecar only) |
| **BMP** | **original 보존 + PNG managed 생성** | **PNG iTXt chunk** | **PNG XMP (ExifTool)** |
| **GIF (animated)** | **original 보존 + WebP managed 생성** | **WebP EXIF UserComment** | **WebP XMP (ExifTool)** |
| **GIF (static)** | **original 보존** | **`.aru.json` sidecar** | **미적용** |

> **BMP 처리 근거**: BMP는 메타데이터 삽입 표준이 없고 파일 크기가 비효율적이다.  
> PNG로 변환하면 무손실 압축 + 메타데이터 표준(iTXt) 지원이 동시에 해결된다.  
> 원본 BMP는 Inbox에 보존하고, PNG managed는 동일 그룹의 `file_role='managed'`로 등록한다.

> **GIF animated 처리 근거**: animated GIF는 ugoira WebP와 동일한 처리 파이프라인을 사용한다.  
> Pillow의 `Image.is_animated` 속성으로 animated 여부를 판별한다.  
> 원본 GIF는 Inbox에 보존하고 WebP managed를 생성한다.

> **GIF static 예외 정책**: static GIF는 MVP 단계에서 **파일 우선 메타데이터 원칙의 예외**로 sidecar-only 방식을 채택한다. 이는 GIF 포맷의 메타데이터 처리 안정성, 색상 손실 가능성, 낮은 발생 빈도, 구현 범위를 고려한 한시적 정책이다. 향후 필요 시 static GIF도 PNG managed 또는 WebP managed 생성 정책으로 전환할 수 있다. 전환 시 BMP/animated GIF와 동일한 "원본 보존 + managed 변환본 생성" 파이프라인을 사용한다.
>
> - `metadata_sync_status = 'json_only'`: sidecar 생성 성공 (no_metadata_queue 기록 안 함)
> - `metadata_sync_status = 'metadata_write_failed'`: sidecar 생성 실패 (`fail_reason='metadata_write_failed'`)
>
> static GIF의 `json_only`는 파일 내부 JSON이 아니라 sidecar JSON만 존재한다는 의미의 예외적 사용이다.

### 3.3 AruArchive JSON 스키마 (최종)

```json
{
  "schema_version": "1.0",
  "source_site": "pixiv",
  "artwork_id": "141100516",
  "artwork_url": "https://www.pixiv.net/artworks/141100516",
  "artwork_title": "作品タイトル",
  "page_index": 0,
  "total_pages": 3,
  "original_filename": "141100516_p0.jpg",
  "artist_id": "12345678",
  "artist_name": "作家名",
  "artist_url": "https://www.pixiv.net/users/12345678",
  "tags": ["tag1", "tag2", "オリジナル"],
  "character_tags": ["キャラ名"],
  "series_tags": ["シリーズ名"],
  "downloaded_at": "2026-04-26T15:30:00+09:00",
  "is_ugoira": false,
  "ugoira_frames": null,
  "ugoira_delays": null,
  "ugoira_frame_count": null,
  "ugoira_total_duration_ms": null,
  "ugoira_webp_path": null,
  "rating": null,
  "custom_notes": "",
  "_provenance": {
    "source": "extension_dom",
    "confidence": "high",
    "captured_at": "2026-04-26T15:30:00+09:00",
    "user_agent": "Chrome/124"
  }
}
```

### 3.4 BMP → PNG 변환 상세

```python
# core/format_converter.py
from PIL import Image

def convert_bmp_to_png(bmp_path: str, dest_dir: str) -> str:
    """BMP → PNG 무손실 변환. PNG 경로 반환."""
    img = Image.open(bmp_path)
    png_filename = Path(bmp_path).stem + '_managed.png'
    png_path = Path(dest_dir) / png_filename
    img.save(str(png_path), format='PNG', optimize=True)
    return str(png_path)
```

### 3.5 GIF animated 판별 및 변환

```python
# core/format_converter.py
def is_animated_gif(gif_path: str) -> bool:
    with Image.open(gif_path) as img:
        return getattr(img, 'is_animated', False) and getattr(img, 'n_frames', 1) > 1

def convert_gif_to_webp(gif_path: str, dest_dir: str) -> str:
    """animated GIF → animated WebP 변환. WebP 경로 반환."""
    img = Image.open(gif_path)
    frames, durations = [], []
    for i in range(img.n_frames):
        img.seek(i)
        frames.append(img.copy().convert('RGBA'))
        durations.append(img.info.get('duration', 100))
    webp_filename = Path(gif_path).stem + '_managed.webp'
    webp_path = Path(dest_dir) / webp_filename
    frames[0].save(
        str(webp_path), format='WEBP',
        save_all=True, append_images=frames[1:],
        duration=durations, loop=0
    )
    return str(webp_path)
```

### 3.6 managed 변환 공통 상태 전이

BMP → PNG managed, animated GIF → WebP managed, ugoira ZIP → WebP managed는 모두 **"원본 보존 + managed 변환본 생성"** 공통 파이프라인을 따른다. 아래 상태 전이는 세 케이스 모두에 재사용 가능한 공통 모델이다.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 "원본 보존 + managed 변환본 생성" 공통 상태 전이
 적용 대상: BMP → PNG managed
           animated GIF → WebP managed
           ugoira ZIP → WebP managed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[시작]
artwork_groups.metadata_sync_status = 'pending'
    │
    ▼
[STEP 1] 원본 파일 Inbox 저장
artwork_files INSERT (file_role='original', metadata_embedded=0)
    │
    ├── 저장 실패 (디스크 부족, 권한 오류, 파일 잠금 등)
    │     → metadata_sync_status = 'file_write_failed'
    │     → no_metadata_queue: fail_reason = 'network_error' 또는 'embed_failed'
    │     → [종료: 원본도 없거나 불완전]
    │
    └── 저장 성공 → STEP 2
    │
    ▼
[STEP 2] managed 파일 변환 시도
(BMP→PNG, animated GIF→WebP, ugoira ZIP→WebP)
    │
    ├── 변환 실패 (Pillow 오류, 손상 파일 등)
    │     → metadata_sync_status = 'convert_failed'
    │     → no_metadata_queue: BMP의 경우 fail_reason = 'bmp_convert_failed'
    │                          기타 managed의 경우 fail_reason = 'managed_file_create_failed'
    │     → 원본은 보존됨 (file_role='original')
    │     → thumbnail: 원본에서 임시 생성 가능
    │     → [종료: managed 없음]
    │
    └── 변환 성공 → STEP 3
    artwork_files INSERT (file_role='managed', metadata_embedded=0)
    │
    ▼
[STEP 3] AruArchive JSON 임베딩
(PNG → iTXt chunk, WebP/JPEG → EXIF UserComment)
    │
    ├── 임베딩 실패 (파일 쓰기 오류 등)
    │     → metadata_sync_status = 'metadata_write_failed'
    │     → artwork_files UPDATE metadata_embedded=0 (유지)
    │     → no_metadata_queue: fail_reason = 'metadata_write_failed'
    │     → 원본 + managed(metadata_embedded=0) 모두 보존됨
    │     → [종료: 파일 존재, JSON 없음]
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
    │     → [종료: JSON 완료, XMP 없음 — 정상]
    │
    ├── ExifTool 있음 + 기록 실패
    │     → metadata_sync_status = 'xmp_write_failed'
    │     → no_metadata_queue: 기록하지 않음 (§6.2 참조)
    │     → UI: ⚠️ Warning 배지, 상세 패널 [XMP 재시도] 버튼
    │     → [종료: JSON 완료, XMP 실패]
    │
    └── ExifTool 있음 + 기록 성공
          → metadata_sync_status = 'full'
          → no_metadata_queue: 기록하지 않음
          → [종료: 완전 성공]
```

**포맷별 STEP 2 fail_reason 대응**:

| 포맷 | STEP 2 fail_reason | STEP 3 JSON 위치 | STEP 4 XMP |
|------|--------------------|-----------------|------------|
| BMP → PNG managed | `bmp_convert_failed` | PNG iTXt chunk | PNG XMP (ExifTool) |
| animated GIF → WebP managed | `managed_file_create_failed` | WebP EXIF UserComment | WebP XMP (ExifTool) |
| ugoira ZIP → WebP managed | `managed_file_create_failed` | WebP EXIF UserComment | WebP XMP (ExifTool) |

**단순 포맷 (원본 직접 임베딩) 비교**: JPEG, PNG, native WebP는 STEP 2 없이 STEP 1 → STEP 3 → STEP 4로 진행한다. `convert_failed`는 "원본 보존 + managed 변환" 파이프라인에서만 발생한다.

### 3.7 ExifTool 통합 정책

| 항목 | 내용 |
|------|------|
| 번들 방식 | `exiftool.exe`를 PyInstaller 빌드 폴더에 포함 (optional) |
| 실행 방식 | `subprocess.run(['exiftool', ...])` — 배치 플래그 활용 |
| 없을 때 동작 | AruArchive JSON만 저장, 경고 로그, `metadata_sync_status='json_only'` |
| 있을 때 동작 | JSON 임베딩 후 ExifTool로 XMP 추가 → `metadata_sync_status='full'` |
| MVP-A | ExifTool 없어도 정상 동작 |
| MVP-B | ExifTool exe 빌드 폴더에 포함 |

---

## 4. 데이터 모델 최종안

### 4.1 전체 테이블 목록 (v2.4 확정, 12개)

| 테이블 | 설명 | MVP |
|--------|------|-----|
| `artwork_groups` | 작품 단위 그룹 (다중 페이지 묶음) | A |
| `artwork_files` | 개별 파일 (original/managed/sidecar/classified_copy) | A |
| `tags` | 정규화 태그 인덱스 | A |
| `save_jobs` | 저장 작업 단위 (진행률 추적) | A |
| `job_pages` | 저장 작업 내 개별 페이지 상태 | A |
| `no_metadata_queue` | 메타데이터 없는 파일 보류 큐 | A |
| `undo_entries` | Undo 작업 로그 항목 | B |
| `copy_records` | Undo 항목별 개별 파일 복사 기록 | B |
| `classify_rules` | 분류 규칙 | B |
| `thumbnail_cache` | 썸네일 캐시 인덱스 (path 기반) | B |
| `tag_aliases` | 태그 별칭 → 정규 태그 매핑 | C |
| `operation_locks` | SQLite 동시 쓰기 잠금 | A |

### 4.2 artwork_groups 테이블

```sql
CREATE TABLE artwork_groups (
    group_id              TEXT PRIMARY KEY,          -- UUID v4
    source_site           TEXT NOT NULL DEFAULT 'pixiv',
    artwork_id            TEXT NOT NULL,
    artwork_url           TEXT,
    artwork_title         TEXT,
    artist_id             TEXT,
    artist_name           TEXT,
    artist_url            TEXT,
    artwork_kind          TEXT NOT NULL DEFAULT 'single_image',
                          -- single_image | multi_page | ugoira
    total_pages           INTEGER NOT NULL DEFAULT 1,
    cover_file_id         TEXT,                      -- artwork_files.file_id FK (lazy)
    tags_json             TEXT,                      -- JSON array
    character_tags_json   TEXT,
    series_tags_json      TEXT,
    downloaded_at         TEXT NOT NULL,             -- ISO 8601
    indexed_at            TEXT NOT NULL,
    updated_at            TEXT,
    status                TEXT NOT NULL DEFAULT 'inbox',
                          -- inbox | classified | partial | error
    metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
                          -- pending | full | json_only | out_of_sync |
                          -- file_write_failed | convert_failed | metadata_write_failed |
                          -- xmp_write_failed | db_update_failed |
                          -- needs_reindex | metadata_missing
    schema_version        TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(artwork_id, source_site)
);
```

#### metadata_sync_status 값 정의 (최종, 11개)

| 값 | 의미 | 발생 조건 | 다음 상태 |
|----|------|-----------|-----------|
| `pending` | **기본값**. 처리 파이프라인 진입 전 또는 진행 중 | 저장 작업 시작 직후 | full / json_only / 실패 값 중 하나 |
| `full` | AruArchive JSON + XMP 모두 임베딩 완료 | JSON + ExifTool XMP 모두 성공 | out_of_sync (외부 파일 변경 감지 시) |
| `json_only` | AruArchive JSON만 임베딩 (ExifTool 없음 또는 생략) | JSON 성공 + ExifTool 없음. static GIF sidecar 성공 포함 | full (ExifTool 번들 후 재처리) |
| `out_of_sync` | DB의 메타데이터와 실제 파일 내부 불일치 | 재색인 또는 헬스체크 시 감지 | full (재동기화 후) |
| `file_write_failed` | **원본 파일 저장 또는 파일 I/O 자체 실패** | 디스크 부족, 권한 오류, 파일 잠금 | pending (재시도) |
| `convert_failed` | **원본 저장 성공, managed 파일 변환 실패** | BMP→PNG 실패, animated GIF→WebP 실패, ugoira→WebP 실패 | pending (재시도) |
| `metadata_write_failed` | **managed 파일 생성 성공, AruArchive JSON 임베딩 실패** | PNG iTXt 쓰기 실패, WebP EXIF 쓰기 실패, static GIF sidecar 쓰기 실패 | pending (재임베딩 시도) |
| `xmp_write_failed` | AruArchive JSON 성공, ExifTool XMP 단계만 실패 | ExifTool 오류, 권한 문제, 미지원 포맷 | json_only (수동 강등) 또는 full (재시도) |
| `db_update_failed` | 파일 처리 성공, DB 업데이트만 실패 | SQLite I/O 오류, 잠금 타임아웃 | needs_reindex (재색인으로 복구) |
| `needs_reindex` | DB 상태가 파일 실제 상태와 다름, 재색인 필요 | db_update_failed 이후 | full (재색인 완료 후) |
| `metadata_missing` | 파일 내 AruArchive JSON 없음 | 외부 편집, 파일 교체 의심 | pending (재임베딩 시도) |

**핵심 구분 — 연속된 실패 단계 4개**:

```
file_write_failed    → 파일 저장 자체 실패 (원본도 없거나 불완전)
        ↓
convert_failed       → 원본은 저장됨, managed 변환 실패
        ↓
metadata_write_failed → 원본 + managed 모두 저장됨, JSON 임베딩 실패
        ↓
xmp_write_failed     → 원본 + managed + JSON 모두 완료, XMP만 실패
```

이 순서는 "얼마나 많이 진행했는가"를 나타낸다. `file_write_failed`가 가장 이른 단계의 실패, `xmp_write_failed`가 가장 늦은 단계의 실패다.

> **기본값을 `pending`으로 정한 이유**: `full`을 기본값으로 하면 임베딩 실패 시 상태가 갱신되지 않아도 `full`로 표시되는 버그가 생긴다. `pending`을 기본값으로 하면 임베딩 완료 후 명시적으로 갱신해야 하므로 누락 감지가 용이하다.

### 4.3 artwork_files 테이블

```sql
CREATE TABLE artwork_files (
    file_id               TEXT PRIMARY KEY,          -- UUID v4
    group_id              TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    page_index            INTEGER NOT NULL DEFAULT 0,
    file_role             TEXT NOT NULL,
                          -- original | managed | sidecar | classified_copy
    file_path             TEXT NOT NULL UNIQUE,      -- 절대 경로
    file_format           TEXT NOT NULL,             -- jpg|png|webp|zip|gif|bmp|json
    file_hash             TEXT,                      -- SHA-256
    file_size             INTEGER,                   -- bytes
    metadata_embedded     INTEGER NOT NULL DEFAULT 0,
    file_status           TEXT NOT NULL DEFAULT 'present',
                          -- present | missing | moved | orphan
    created_at            TEXT NOT NULL,
    modified_at           TEXT,
    last_seen_at          TEXT,
    source_file_id        TEXT REFERENCES artwork_files(file_id),
    classify_rule_id      TEXT,
    provenance_json       TEXT
);
```

**file_role 값 정의**:

| 값 | 설명 |
|----|------|
| `original` | Inbox의 원본 파일 (BMP, GIF, ZIP 포함) |
| `managed` | 원본에서 변환된 관리본 (PNG, WebP) — 메타데이터 임베딩 대상 |
| `sidecar` | `.aru.json` 사이드카 파일 (ZIP, static GIF) |
| `classified_copy` | 분류 규칙에 의해 Classified 폴더에 복사된 파일 |

### 4.4 tags 테이블

```sql
CREATE TABLE tags (
    group_id    TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    tag_type    TEXT NOT NULL DEFAULT 'general',
                -- general | character | series
    canonical   TEXT,                               -- tag_aliases 정규화 후 값 (MVP-C)
    PRIMARY KEY (group_id, tag, tag_type)
);
CREATE INDEX idx_tags_tag ON tags(tag);
CREATE INDEX idx_tags_canonical ON tags(canonical);
```

> **컬럼명 `group_id` 사용 이유**: `artwork_id`는 Pixiv의 작품 번호(예: `"141100516"`)와 혼동될 수 있다. `group_id`는 DB 내부 UUID 식별자임을 명확히 하며, FK 참조 대상인 `artwork_groups.group_id`와 일치한다.

### 4.5 save_jobs 테이블

```sql
CREATE TABLE save_jobs (
    job_id          TEXT PRIMARY KEY,               -- UUID v4
    source_site     TEXT NOT NULL DEFAULT 'pixiv',
    artwork_id      TEXT NOT NULL,
    group_id        TEXT REFERENCES artwork_groups(group_id),
    status          TEXT NOT NULL DEFAULT 'pending',
                    -- pending | running | completed | failed | partial
    total_pages     INTEGER NOT NULL DEFAULT 1,
    saved_pages     INTEGER NOT NULL DEFAULT 0,
    failed_pages    INTEGER NOT NULL DEFAULT 0,
    classify_mode   TEXT,                           -- 작업 시작 당시 설정값 스냅샷
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT
);
CREATE INDEX idx_save_jobs_status ON save_jobs(status);
CREATE INDEX idx_save_jobs_started ON save_jobs(started_at);
```

### 4.6 job_pages 테이블

```sql
CREATE TABLE job_pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL REFERENCES save_jobs(job_id) ON DELETE CASCADE,
    page_index      INTEGER NOT NULL,
    url             TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_id         TEXT REFERENCES artwork_files(file_id),
    status          TEXT NOT NULL DEFAULT 'pending',
                    -- pending | downloading | embed_pending | saved | failed
    error_message   TEXT,
    download_bytes  INTEGER,                        -- 실제 다운로드 바이트 수
    saved_at        TEXT
);
CREATE INDEX idx_job_pages_job_id ON job_pages(job_id);
```

**job_pages.status 전이**:
```
pending → downloading → embed_pending → saved
                     ↘ failed
```

### 4.7 no_metadata_queue 테이블

```sql
CREATE TABLE no_metadata_queue (
    queue_id      TEXT PRIMARY KEY,                 -- UUID v4
    file_path     TEXT NOT NULL,
    source_site   TEXT,
    job_id        TEXT REFERENCES save_jobs(job_id),-- 연관 저장 작업 (있는 경우)
    detected_at   TEXT NOT NULL,
    fail_reason   TEXT NOT NULL,
                  -- no_dom_data | parse_error | network_error |
                  -- unsupported_format | manual_add |
                  -- embed_failed | partial_data | artwork_restricted | api_error |
                  -- bmp_convert_failed | managed_file_create_failed |
                  -- metadata_write_failed | xmp_write_failed
    raw_context   TEXT,                             -- 오류 당시 부분 데이터 JSON
    resolved      INTEGER NOT NULL DEFAULT 0,
    resolved_at   TEXT,
    notes         TEXT
);
```

**fail_reason enum 최종 정의 (13개)**:

| 값 | 발생 시점 | UI 표시 메시지 | 권장 액션 버튼 |
|----|-----------|--------------|--------------|
| `no_dom_data` | content_script가 preload_data를 찾지 못함 | 페이지 데이터를 찾을 수 없습니다 | 재시도, 수동 입력, 무시 |
| `parse_error` | 메타데이터 파싱 중 예외 발생 | 데이터 파싱 오류 | 신고, 수동 입력, 무시 |
| `network_error` | httpx 다운로드 실패 | 네트워크 오류 | 재다운로드, 수동 입력, 무시 |
| `unsupported_format` | 지원하지 않는 파일 형식 | 지원하지 않는 파일 형식 | 수동 입력, 무시 |
| `manual_add` | 사용자가 수동으로 큐에 추가 | 수동 추가된 파일 | 메타데이터 입력, 무시 |
| `embed_failed` | **기타 임베딩 오류의 범용 폴백** | 메타데이터 저장 실패 (파일 오류) | 재시도, 수동 입력, 무시 |
| `partial_data` | 일부 필드 누락된 불완전한 메타데이터 | 일부 정보가 누락되었습니다 | 수동 보완, 그대로 저장, 무시 |
| `artwork_restricted` | R-18 또는 프리미엄 잠금 작품 (접근 제한) | 접근 제한 작품 | 로그인 확인 후 재시도, 무시 |
| `api_error` | Pixiv AJAX API 응답 오류 (4xx/5xx) | Pixiv API 응답 오류 | 재시도, 수동 입력, 무시 |
| `bmp_convert_failed` | BMP → PNG managed 변환 실패 | PNG 관리본 생성 실패 | PNG 재생성, 원본 파일 열기, 무시 |
| `managed_file_create_failed` | BMP 외 managed 파일 생성 실패 (GIF→WebP, ugoira→WebP 등) | 관리본 생성 실패 | 재생성, 원본 파일 열기, 무시 |
| `metadata_write_failed` | 파일 생성 후 AruArchive JSON 임베딩 실패 | 메타데이터 기록 실패 (파일은 보존됨) | 메타데이터 재기록, 수동 입력, 무시 |
| `xmp_write_failed` | JSON 성공, XMP 기록 실패 | (**no_metadata_queue에 기록하지 않음** — UI 배지로 처리) | XMP 재시도 (상세 패널) |

> **`embed_failed` 역할 (범용 폴백 정책)**: `bmp_convert_failed`, `managed_file_create_failed`, `metadata_write_failed` 등 세부 fail_reason으로 분류할 수 없는 기타 임베딩 오류에 대한 폴백 값이다. 신규 코드에서는 세부 reason을 우선 기록하고, `embed_failed`는 해당 분류에 속하지 않는 예외적 케이스에만 사용한다.
>
> **`xmp_write_failed` 큐 기록 정책**: AruArchive JSON이 파일 내부에 완전히 보존된 상태이므로 no_metadata_queue에 INSERT하지 않는다. 검색·분류·표시 기능이 모두 정상 동작한다. 향후 별도의 warning 큐 또는 XMP 재처리 큐를 만들 경우 이 값을 재사용할 수 있으므로 enum에는 유지한다.

### 4.8 undo_entries 테이블

```sql
CREATE TABLE undo_entries (
    entry_id        TEXT PRIMARY KEY,               -- UUID v4
    operation_type  TEXT NOT NULL,                  -- 'classify'
    performed_at    TEXT NOT NULL,
    undo_expires_at TEXT NOT NULL,                  -- performed_at + 보존 기간
    undo_status     TEXT NOT NULL DEFAULT 'pending',
                    -- pending | completed | failed | expired
    undone_at       TEXT,
    undo_error      TEXT,                           -- 실패 시 오류 메시지
    description     TEXT
);
```

**undo_status 값 정의 및 UI 매핑**:

| DB 값 | 의미 | UI 표시 레이블 | Undo 버튼 |
|-------|------|--------------|---------|
| `pending` | Undo 작업이 아직 실행되지 않음 (Undo 가능 상태) | **"Undo 가능"** | 활성화 |
| `completed` | Undo 성공적으로 완료됨 | **"Undo 완료"** | 비활성화 |
| `failed` | Undo 시도했으나 실패 (`undo_error`에 상세 기록) | **"Undo 실패"** | 비활성화 (재시도 버튼 별도) |
| `expired` | `undo_expires_at` 경과, Undo 불가 | **"Undo 만료"** | 비활성화 |

> **`pending`의 의미**: 코드 상에서 `pending`은 "Undo 작업이 아직 실행되지 않았음"을 의미한다. UI에서는 사용자에게 "Undo 가능"으로 표시한다. 상태값(`pending`)과 UI 레이블("Undo 가능")은 별개다.
>
> **만료 처리**: `undo_expires_at < now()` 감지 시 `undo_status='expired'`로 업데이트. UI는 `undo_status='pending'` 항목만 Undo 버튼 활성화.

### 4.9 copy_records 테이블 (B-2 정책)

```sql
CREATE TABLE copy_records (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id             TEXT NOT NULL REFERENCES undo_entries(entry_id) ON DELETE CASCADE,
    src_file_id          TEXT REFERENCES artwork_files(file_id),
    dest_file_id         TEXT REFERENCES artwork_files(file_id),
    src_path             TEXT NOT NULL,
    dest_path            TEXT NOT NULL,
    rule_id              TEXT,
    dest_file_size       INTEGER NOT NULL,           -- 만료 후에도 보존 (Recent Jobs 표시용)
    dest_mtime_at_copy   TEXT,                       -- 만료 후 NULL
    dest_hash_at_copy    TEXT,                       -- 만료 후 NULL
    manually_modified    INTEGER DEFAULT 0,
    copied_at            TEXT NOT NULL
);
```

### 4.10 thumbnail_cache 테이블 (Hybrid path 방식)

```sql
CREATE TABLE thumbnail_cache (
    file_id       TEXT PRIMARY KEY REFERENCES artwork_files(file_id) ON DELETE CASCADE,
    thumb_path    TEXT NOT NULL UNIQUE,             -- 절대 경로 (.thumbcache 디렉토리 내)
    thumb_size    TEXT NOT NULL DEFAULT '256x256',
    source_hash   TEXT NOT NULL,                    -- 원본 file_hash (갱신 판단용)
    file_size     INTEGER,                          -- 썸네일 파일 크기 (bytes)
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_thumbnail_source_hash ON thumbnail_cache(source_hash);
```

> BLOB 컬럼 없음. 썸네일 실제 파일은 `.thumbcache/` 디렉토리에 저장 (§9.1 참조).

### 4.11 classify_rules 테이블

```sql
CREATE TABLE classify_rules (
    rule_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    priority      INTEGER NOT NULL DEFAULT 100,
    conditions_json TEXT NOT NULL,
    logic         TEXT NOT NULL DEFAULT 'AND',      -- AND | OR
    dest_template TEXT NOT NULL,
    on_conflict   TEXT NOT NULL DEFAULT 'skip',     -- skip | overwrite | rename
    created_at    TEXT NOT NULL,
    updated_at    TEXT
);
```

### 4.12 tag_aliases 테이블 (MVP-C, 스키마는 MVP-A에 생성)

```sql
CREATE TABLE tag_aliases (
    alias         TEXT PRIMARY KEY,
    canonical     TEXT NOT NULL,
    source_site   TEXT DEFAULT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_tag_aliases_canonical ON tag_aliases(canonical);
```

### 4.13 operation_locks 테이블

```sql
CREATE TABLE operation_locks (
    lock_name     TEXT PRIMARY KEY,
    locked_by     TEXT NOT NULL,                    -- 'native_host' | 'main_app' | 'reindex'
    locked_at     TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
```

**operation_locks 키 명명 정책**:

| 키 패턴 | 용도 | 타임아웃 |
|---------|------|---------|
| `save:{source_site}:{artwork_id}` | 특정 작품 저장 (중복 저장 방지) | 120초 |
| `classify:{group_id}` | 특정 그룹 분류 실행 | 60초 |
| `reindex` | 전체 Inbox 재색인 | 600초 |
| `thumbnail:{file_id}` | 특정 파일 썸네일 생성 | 30초 |
| `undo:{entry_id}` | Undo 실행 | 60초 |
| `db_maintenance` | DB 정리 작업 (만료 Undo 정리 등) | 120초 |

> **키 설계 원칙**: 세분화된 키로 서로 다른 작품의 병렬 저장을 허용하되, 동일 작품의 중복 저장은 `save:{site}:{id}` 잠금으로 방지한다.

---

## 5. BMP / managed 변환 실패 처리

### 5.1 BMP 실패 케이스 매핑표 (전체 6케이스)

| 상황 | `metadata_sync_status` | `no_metadata_queue.fail_reason` | BMP 원본 | PNG managed | `metadata_embedded` | UI 메시지 | 재시도 |
|------|----------------------|--------------------------------|---------|------------|-------------------|---------|--------|
| BMP 원본 저장 실패 | `file_write_failed` | `network_error` 또는 `embed_failed` | 없음/불완전 | 없음 | — | "파일 저장 실패" | ✅ |
| PNG managed 변환 실패 | `convert_failed` | `bmp_convert_failed` | 보존 ✅ | 없음 | — | "PNG 관리본 생성 실패" | ✅ |
| PNG managed 생성 후 JSON 기록 실패 | `metadata_write_failed` | `metadata_write_failed` | 보존 ✅ | 있음 | 0 | "메타데이터 기록 실패 (파일은 보존됨)" | ✅ |
| JSON 성공, XMP 실패 | `xmp_write_failed` | **기록 안 함** (UI 배지) | 보존 ✅ | 있음 | 1 | ⚠️ "XMP 기록 실패, JSON 완료" | ✅ |
| JSON 성공, ExifTool 없음 | `json_only` | **기록 안 함** (정상) | 보존 ✅ | 있음 | 1 | — (정상) | — |
| JSON + XMP 모두 성공 | `full` | **기록 안 함** | 보존 ✅ | 있음 | 1 | — (정상) | — |

### 5.2 animated GIF / ugoira 실패 케이스 비교

animated GIF와 ugoira는 BMP와 동일한 파이프라인을 사용하며, STEP 2 fail_reason만 다르다.

| 포맷 | STEP 2 fail_reason | 그 외 케이스 |
|------|--------------------|------------|
| BMP → PNG | `bmp_convert_failed` | BMP 매핑표와 동일 |
| animated GIF → WebP | `managed_file_create_failed` | BMP 매핑표에서 fail_reason만 교체 |
| ugoira ZIP → WebP | `managed_file_create_failed` | BMP 매핑표에서 fail_reason만 교체 |

### 5.3 no_metadata_queue 기록 여부 요약

```
기록함 (사용자 개입 필요):
  file_write_failed        → 파일 자체 없음, 재다운로드 필요
  convert_failed           → 원본은 있으나 managed 없음, 재변환 필요
  metadata_write_failed    → 파일 있으나 메타데이터 없음, 재기록 필요

기록 안 함 (자동 처리 또는 경미한 이슈):
  xmp_write_failed         → AruArchive JSON 완전 보존 → UI ⚠️ 배지로 처리
  json_only                → ExifTool 미존재 → 정상 처리
  full                     → 완전 성공
```

### 5.4 xmp_write_failed Warning 처리 상세

`xmp_write_failed` 상태에서의 처리 방침:

```
1. artwork_groups.metadata_sync_status = 'xmp_write_failed' 기록
2. 갤러리 카드에 ⚠️ 배지 표시 ("XMP 없음, JSON 완료")
3. 작품 상세 패널 > 메타데이터 탭에 [XMP 재시도] 버튼 제공
4. 설정 화면 > ExifTool 섹션에 "XMP 실패 항목 일괄 재처리" 기능 제공 (MVP-B)
```

> AruArchive JSON이 온전하므로 앱 내부 검색·분류·표시 기능은 모두 정상 동작한다.  
> `xmp_write_failed`는 fail_reason enum에는 존재하나 no_metadata_queue에는 INSERT하지 않는다.  
> 향후 warning 큐 또는 XMP 재처리 큐를 별도로 만들 경우 이 enum 값을 재사용한다.

### 5.5 재시도 가능 여부 상세

| 상태 | 재시도 방법 | 재시도 후 기대 상태 |
|------|-----------|-------------------|
| `file_write_failed` | 저장 작업 전체 재실행 | `pending` → 성공 시 `full` 또는 `json_only` |
| `convert_failed` | managed 재생성 버튼 | `pending` → `full` 또는 `json_only` |
| `metadata_write_failed` | 메타데이터 재기록 버튼 | `pending` → `full` 또는 `json_only` |
| `xmp_write_failed` | ExifTool XMP 재시도 버튼 | `xmp_write_failed` → `full` |
| `json_only` | ExifTool 번들 추가 후 재처리 (MVP-B) | `json_only` → `full` |

---

## 6. No Metadata 큐 정책

### 6.1 기록하는 케이스 (사용자 개입 필요)

- NativeHost가 메타데이터 없는 저장 요청을 받는 모든 경우
- content_script가 DOM 파싱에 실패한 경우 (`no_dom_data`, `parse_error`)
- httpx 다운로드 실패 (`network_error`)
- 파일 다운로드 성공 후 기타 임베딩 실패 (`embed_failed` — 범용 폴백)
- 접근 제한 작품 저장 시도 (`artwork_restricted`)
- Pixiv AJAX API 오류 응답 (`api_error`)
- BMP → PNG managed 변환 실패 (`bmp_convert_failed`)
- animated GIF/ugoira → WebP managed 변환 실패 (`managed_file_create_failed`)
- managed 파일 생성 후 AruArchive JSON 임베딩 실패 (`metadata_write_failed`)

### 6.2 기록하지 않는 케이스

| 케이스 | 이유 |
|--------|------|
| `xmp_write_failed` | AruArchive JSON 완전 보존 상태. 앱 기능 정상. UI 배지로 대체 |
| `json_only` (ExifTool 없음) | 정상 처리. ExifTool은 선택 사항 (MVP-B) |
| `full` | 완전 성공 |

### 6.3 embed_failed 범용 폴백 정책

`embed_failed`는 아래 구체적 fail_reason으로 분류할 수 없는 **기타 임베딩 오류의 폴백 값**이다.

- 세부 reason이 명확히 적용되는 케이스: `bmp_convert_failed`, `managed_file_create_failed`, `metadata_write_failed`, `xmp_write_failed` 우선 사용
- 위 분류에 해당하지 않는 임베딩 오류: `embed_failed` 사용
- 신규 코드 작성 시: 세부 reason을 먼저 검토하고, 해당하지 않을 때만 `embed_failed` 기록

### 6.4 fail_reason별 UI 액션 버튼 (전체)

| fail_reason | 표시 메시지 | 제공 버튼 |
|-------------|-----------|---------|
| `no_dom_data` | 페이지 데이터를 찾을 수 없습니다 | 재시도, 수동 입력, 무시 |
| `parse_error` | 데이터 파싱 오류 | 신고, 수동 입력, 무시 |
| `network_error` | 네트워크 오류 | 재다운로드, 수동 입력, 무시 |
| `unsupported_format` | 지원하지 않는 파일 형식 | 수동 입력, 무시 |
| `manual_add` | 수동 추가된 파일 | 메타데이터 입력, 무시 |
| `embed_failed` | 메타데이터 저장 실패 (파일 오류) | 재시도, 수동 입력, 무시 |
| `partial_data` | 일부 정보가 누락되었습니다 | 수동 보완, 그대로 저장, 무시 |
| `artwork_restricted` | 접근 제한 작품 | 로그인 확인 후 재시도, 무시 |
| `api_error` | Pixiv API 응답 오류 | 재시도, 수동 입력, 무시 |
| `bmp_convert_failed` | PNG 관리본 생성 실패 | PNG 재생성, 원본 파일 열기, 무시 |
| `managed_file_create_failed` | 관리본 생성 실패 | 재생성, 원본 파일 열기, 무시 |
| `metadata_write_failed` | 메타데이터 기록 실패 (파일은 보존됨) | 메타데이터 재기록, 수동 입력, 무시 |
| `xmp_write_failed` | *(no_metadata_queue에 기록하지 않음 — 상세 패널 배지로 처리)* | XMP 재시도 (상세 패널) |

---

## 7. Undo / copy_records 보존 정책

### 7.1 B-2 정책 요약

| 항목 | 내용 |
|------|------|
| 채택 이유 | Undo 안전성(hash 체크)과 저장 공간 절약 균형 달성 |
| 보존 기간 | `config.json`의 `undo_retention_days` (기본값: 7일) |
| 만료 시 처리 | `dest_hash_at_copy`, `dest_mtime_at_copy` → NULL (UPDATE) |
| 보존 항목 | `dest_file_size` — Recent Jobs 패널 파일 크기 표시에 사용 |
| 만료 후 상태 | `undo_status='expired'`, Undo 버튼 비활성화 |

### 7.2 undo_status 값 및 UI 표시 매핑

| DB 값 | 코드 의미 | UI 표시 | Undo 버튼 |
|-------|---------|---------|---------|
| `pending` | Undo 작업 미실행 (실행 가능) | **"Undo 가능"** | ✅ 활성화 |
| `completed` | Undo 완료됨 | **"Undo 완료"** | ❌ 비활성화 |
| `failed` | Undo 실패 (`undo_error` 참조) | **"Undo 실패"** | ❌ 비활성화 |
| `expired` | 보존 기간 만료 | **"Undo 만료"** | ❌ 비활성화 |

> `pending`은 코드상 "Undo가 아직 실행되지 않음"을 의미하며, UI에서는 "Undo 가능"으로 표시한다. 상태값 자체와 UI 레이블은 별개로 관리한다.

### 7.3 Undo 실행 흐름

```
사용자: Undo 버튼 클릭
  │
  ▼ [undo_status 확인]
  'expired' | 'completed' | 'failed' → 버튼 비활성 (이 경로 도달 불가)
  'pending' → 계속

  ▼ [3-field 안전성 체크]
  for each copy_record:
      ① dest_file_size == os.path.getsize(dest_path)?
      ② dest_mtime_at_copy == os.path.getmtime(dest_path)?  (NULL → 만료)
      ③ dest_hash_at_copy == sha256(dest_path)?              (NULL → 만료)
  
  모두 통과 → 삭제 진행
  불일치 → 확인 다이얼로그 ("파일이 수정된 것으로 보입니다. 그래도 삭제하시겠습니까?")
  삭제 성공 → undo_entries UPDATE undo_status='completed', undone_at=now()
  삭제 실패 → undo_entries UPDATE undo_status='failed', undo_error='...'
```

### 7.4 만료 처리 스케줄

```python
# 메인앱 시작 시 1회 + 24시간마다 QTimer 반복
def expire_undo_entries(conn):
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE undo_entries
        SET undo_status = 'expired'
        WHERE undo_expires_at < ?
          AND undo_status = 'pending'
    """, (now,))
    conn.execute("""
        UPDATE copy_records
        SET dest_mtime_at_copy = NULL,
            dest_hash_at_copy = NULL
        WHERE entry_id IN (
            SELECT entry_id FROM undo_entries
            WHERE undo_status = 'expired'
              AND undone_at IS NULL
        )
    """)
    conn.commit()
```

---

## 8. 프로세스 구조

### 8.1 프로세스 다이어그램

```
[Browser Extension]
  Chrome / Whale MV3
  service_worker.js
        │
        │ Native Messaging (stdin/stdout JSON, 4byte length prefix)
        ▼
[Native Messaging Host]          native_host/host.py
  · 메시지 루프 (stdin/stdout)
  · 액션 라우팅
        │
        ├──── MainApp 실행 중? ──── YES ──▶ HTTP POST localhost:{port}
        │                                    X-Aru-Token: {session_token}
        │                                    MainApp이 CoreWorker 작업 큐에 추가
        │
        └──── MainApp 없음? ──────── NO ──▶ CoreWorker 서브프로세스 직접 spawn
                                            완료 후 결과를 Extension에 반환

[Core Worker]                    core/worker.py
  · 실제 파일 다운로드 (httpx)
  · 메타데이터 임베딩
  · BMP → PNG / GIF → WebP 변환
  · SQLite 업데이트
  · (MVP-B) Classifier 실행

[Main App]                       app/main_window.py (PySide6)
  · HTTP 서버 localhost:{port} (QThread)
  · 세션 토큰 발급 및 검증
  · UI 갱신 (갤러리, 진행률)
  · 설정, 규칙 편집
```

### 8.2 IPC 프로토콜 (NativeHost ↔ MainApp)

**Base URL**: `http://127.0.0.1:{http_port}/api`  
**인증 헤더**: `X-Aru-Token: {session_token}` (모든 요청에 필수)

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/ping` | GET | MainApp 실행 여부 확인 (토큰 검증 포함) |
| `/api/jobs` | POST | 저장 작업 큐에 추가 |
| `/api/jobs/{job_id}` | GET | 작업 상태 폴링 |
| `/api/notify` | POST | MainApp UI 갱신 알림 |

### 8.3 HTTP IPC 토큰 인증

```
토큰 생명주기:
  MainApp 시작 시 → secrets.token_hex(32) 생성
                  → {data_dir}/.runtime/ipc_token 파일에 저장 (0o600)
  MainApp 종료 시 → ipc_token 파일 삭제
  MainApp 재시작 시 → ipc_token 파일 덮어쓰기 (항상 재생성)

NativeHost 동작:
  HTTP 요청 전    → ipc_token 파일 읽기 (MainApp 실행 중이면 존재)
                  → 파일 없음 = MainApp 미실행 → CoreWorker spawn으로 전환
  HTTP 요청 헤더  → X-Aru-Token: {token}

MainApp HTTP 서버:
  모든 /api/* 요청 → X-Aru-Token 헤더 확인
  불일치 → HTTP 401 Unauthorized 반환
  일치   → 정상 처리
```

```python
# app/http_server.py
import secrets
from pathlib import Path

class AppHttpServer(threading.Thread):
    PORT = 18456

    def __init__(self, data_dir: str):
        super().__init__(daemon=True)
        self.token = secrets.token_hex(32)
        self.token_file = Path(data_dir) / '.runtime' / 'ipc_token'

    def run(self):
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(self.token)
        self.token_file.chmod(0o600)
        try:
            server = HTTPServer(('127.0.0.1', self.PORT), self._make_handler())
            server.serve_forever()
        finally:
            self.token_file.unlink(missing_ok=True)

    def _validate_token(self, request_token: str) -> bool:
        return secrets.compare_digest(self.token, request_token)
```

```python
# native_host/host.py
def read_ipc_token(data_dir: str) -> str | None:
    token_file = Path(data_dir) / '.runtime' / 'ipc_token'
    if token_file.exists():
        return token_file.read_text().strip()
    return None  # MainApp 미실행
```

### 8.4 operation_locks 획득/해제 패턴

```python
# db/database.py
from contextlib import contextmanager

@contextmanager
def locked_operation(conn, lock_name: str, locked_by: str, timeout_sec: int = 30):
    if not acquire_lock(conn, lock_name, locked_by, timeout_sec):
        raise LockAcquisitionError(f"Cannot acquire lock: {lock_name}")
    try:
        yield
    finally:
        release_lock(conn, lock_name)

def acquire_lock(conn, lock_name: str, locked_by: str, timeout_sec: int) -> bool:
    expires_at = (datetime.now() + timedelta(seconds=timeout_sec)).isoformat()
    try:
        conn.execute(
            "INSERT INTO operation_locks (lock_name, locked_by, locked_at, expires_at) "
            "VALUES (?, ?, datetime('now'), ?)",
            (lock_name, locked_by, expires_at)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT expires_at FROM operation_locks WHERE lock_name=?", (lock_name,)
        ).fetchone()
        if row and row['expires_at'] < datetime.now().isoformat():
            conn.execute("DELETE FROM operation_locks WHERE lock_name=?", (lock_name,))
            conn.commit()
            return acquire_lock(conn, lock_name, locked_by, timeout_sec)
        return False
```

### 8.5 SQLite 동시 접근 정책

```python
conn = sqlite3.connect(db_path, timeout=5.0)  # busy_timeout=5000ms
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA foreign_keys=ON")
conn.row_factory = sqlite3.Row
```

| 접근자 | 읽기 | 쓰기 | 비고 |
|--------|------|------|------|
| NativeHost / CoreWorker | ✅ | ✅ | 저장 작업 시 쓰기 |
| MainApp (UI Thread) | ✅ | ❌ | UI는 읽기 전용 |
| MainApp (Worker Thread) | ✅ | ✅ | 재색인, Undo 실행 시 |
| Reindex Job | ✅ | ✅ | 단독 실행 |

---

## 9. 썸네일 캐시 / 대량 파일 성능

### 9.1 Hybrid Path 방식

**저장 위치**: `{data_dir}/.thumbcache/{file_id[0:2]}/{file_id}.webp`

```
D:/AruArchive/
└── .thumbcache/
    ├── 3a/
    │   ├── 3a7f2c1d-...webp
    │   └── 3ab89e2f-...webp
    ├── f2/
    │   └── f2c4d901-...webp
    └── ...
```

| 방식 | 장점 | 단점 |
|------|------|------|
| BLOB (v2.2) | 단일 파일 관리, 백업 편의 | DB 비대화, OS 파일 캐시 미활용 |
| Path 기반 (채택) | DB 경량화, OS 캐시 활용, 대용량 성능 우수 | 별도 디렉토리 관리 필요 |

> 10,000개 이상 파일 환경에서 BLOB 방식은 DB 크기가 수백 MB에 달할 수 있다. Path 기반으로 전환하면 SQLite는 경량 인덱스로 유지되고 OS 파일 시스템 캐시를 활용할 수 있다.

### 9.2 썸네일 생성 정책

| 항목 | 값 |
|------|-----|
| 크기 | 256×256 px (표준), 128×128 (소형 그리드) |
| 형식 | WebP (품질 85) |
| 저장 경로 | `{data_dir}/.thumbcache/{id[0:2]}/{file_id}.webp` |
| 갱신 조건 | `source_hash != artwork_files.file_hash` |
| 생성 시점 | 파일 저장 완료 직후 (CoreWorker 내) |

### 9.3 managed 우선 썸네일 정책

BMP, animated GIF, ugoira는 managed 파일(PNG, WebP)을 썸네일 소스로 우선 사용한다.

| 포맷 | 썸네일 소스 | 조건 |
|------|-----------|------|
| JPEG, PNG, native WebP | original 파일 직접 | — |
| BMP | PNG managed | managed 존재 시. 없으면 BMP original에서 임시 생성 |
| animated GIF | WebP managed | managed 존재 시. 없으면 GIF 첫 프레임 |
| static GIF | original GIF | sidecar-only이므로 original에서 직접 |
| ugoira | WebP managed | managed 존재 시. 없으면 ZIP 첫 프레임 |

### 9.4 썸네일 없는 경우 플레이스홀더

| 상황 | 플레이스홀더 |
|------|------------|
| 생성 중 | 회전 스피너 오버레이 |
| ZIP/ugoira (WebP managed 없음) | 필름 아이콘 |
| `file_status=missing` | `?` 아이콘 + 흐린 처리 |
| GIF static (sidecar only) | 파일 형식 아이콘 |
| BMP (PNG managed 없음) | BMP 원본에서 임시 생성 또는 파일 형식 아이콘 |

### 9.5 썸네일 관리 코드

```python
# core/thumbnail_manager.py
def get_thumb_path(data_dir: str, file_id: str) -> Path:
    prefix = file_id[:2]
    return Path(data_dir) / '.thumbcache' / prefix / f'{file_id}.webp'

def generate_thumbnail(file_path: str, data_dir: str, file_id: str,
                        source_hash: str, size: tuple = (256, 256)) -> str:
    thumb_path = get_thumb_path(data_dir, file_id)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(file_path)
    img.thumbnail(size, Image.LANCZOS)
    img.save(str(thumb_path), format='WEBP', quality=85)
    db.execute("""
        INSERT OR REPLACE INTO thumbnail_cache
            (file_id, thumb_path, thumb_size, source_hash, file_size, created_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (file_id, str(thumb_path), f'{size[0]}x{size[1]}',
          source_hash, thumb_path.stat().st_size))
    return str(thumb_path)

def purge_orphan_thumbnails(db, data_dir: str):
    """DB에 없는 고아 썸네일 파일 정리."""
    thumb_dir = Path(data_dir) / '.thumbcache'
    for webp in thumb_dir.rglob('*.webp'):
        file_id = webp.stem
        if not db.execute(
            "SELECT 1 FROM thumbnail_cache WHERE file_id=?", (file_id,)
        ).fetchone():
            webp.unlink()
```

### 9.6 가상화 그리드 정책

- **적용 기준**: 표시 항목 500개 초과 시 QListView 가상화 모드 활성화
- **구현**: `QAbstractItemModel` + `QListView.setUniformItemSizes(True)`
- **썸네일 로드**: 뷰포트 내 카드만 thumb_path에서 로드 (lazy load)
- **성능 목표**: 10,000개 항목에서 60fps 스크롤

---

## 10. 주요 처리 흐름

### 10.1 일반 이미지 저장 (JPEG/PNG, classify_mode=save_only)

```
사용자 클릭 (Pixiv 페이지)
  │
  ▼ [content_scripts/pixiv.js]
  1. preload_data JSON 파싱 → 메타데이터 수집
  2. GET /ajax/illust/{id}/pages → 전체 페이지 URL 수집
  3. 파싱 실패 → fail_reason 설정, partial_data 수집
  │
  ▼ [service_worker.js → Native Messaging]
  4. {action: 'save_artwork', metadata, pages} 전송
  │
  ▼ [NativeHost]
  5. ipc_token 파일 확인 → MainApp 실행 여부 판단
  6. MainApp 실행 중 → HTTP POST /api/jobs (X-Aru-Token)
     MainApp 없음   → CoreWorker 서브프로세스 spawn
  │
  ▼ [CoreWorker]
  7.  operation_locks 획득: save:pixiv:{artwork_id}
  8.  save_jobs INSERT (status='running')
  9.  artwork_groups INSERT (metadata_sync_status='pending')
  10. 각 페이지:
      a. job_pages UPDATE status='downloading'
      b. httpx.get(page_url) → bytes (Referer: https://www.pixiv.net)
      c. Inbox/{source_site}/{filename} 저장
      d. artwork_files INSERT (file_role='original')
      e. job_pages UPDATE status='embed_pending'
      f. AruArchive JSON 직접 임베딩
         (JPEG → EXIF UserComment, PNG → iTXt chunk)
      g. (ExifTool 있음, MVP-B) XMP 표준 필드 추가
      h. metadata_sync_status 갱신 (full / json_only / 실패값)
      i. thumbnail_cache 생성
      j. job_pages UPDATE status='saved'
  11. tags INSERT (group_id 컬럼)
  12. classify_mode == 'save_only' → 분류 skip
  13. operation_locks 해제
  14. save_jobs UPDATE status='completed'
  15. MainApp HTTP 알림
```

### 10.2 BMP 저장 및 PNG managed 생성

```
[CoreWorker] — BMP 파일 감지 시
  1. BMP httpx 다운로드
  2. Inbox/{source_site}/{filename}.bmp 저장
     artwork_files INSERT (file_role='original')
     ├── 실패 → metadata_sync_status='file_write_failed'
     │          no_metadata_queue INSERT (fail_reason='network_error' 또는 'embed_failed')
     │          [종료]
     └── 성공 → 계속

  3. convert_bmp_to_png(bmp_path, inbox_dir) 실행
     artwork_files INSERT (file_role='managed', metadata_embedded=0)
     ├── 실패 → metadata_sync_status='convert_failed'
     │          no_metadata_queue INSERT (fail_reason='bmp_convert_failed')
     │          thumbnail: BMP original에서 임시 생성
     │          [종료]
     └── 성공 → 계속

  4. PNG managed에 AruArchive JSON 임베딩 (iTXt chunk)
     ├── 실패 → metadata_sync_status='metadata_write_failed'
     │          artwork_files UPDATE metadata_embedded=0
     │          no_metadata_queue INSERT (fail_reason='metadata_write_failed')
     │          [종료]
     └── 성공 → artwork_files UPDATE metadata_embedded=1

  5. (ExifTool 있음, MVP-B) PNG XMP 기록
     ├── 없음  → metadata_sync_status='json_only'
     ├── 실패  → metadata_sync_status='xmp_write_failed' (배지 처리, 큐 기록 안 함)
     └── 성공  → metadata_sync_status='full'

  6. thumbnail_cache 생성 (PNG managed 사용)
```

### 10.3 animated GIF 저장 및 WebP managed 생성

```
[CoreWorker] — animated GIF 감지 시 (is_animated_gif() == True)
  1. GIF httpx 다운로드
  2. Inbox/{source_site}/{filename}.gif 저장
     artwork_files INSERT (file_role='original')
     ├── 실패 → metadata_sync_status='file_write_failed' [종료]
     └── 성공 → 계속

  3. convert_gif_to_webp(gif_path, inbox_dir) 실행
     artwork_files INSERT (file_role='managed', metadata_embedded=0)
     ├── 실패 → metadata_sync_status='convert_failed'
     │          no_metadata_queue INSERT (fail_reason='managed_file_create_failed')
     │          [종료]
     └── 성공 → 계속

  4. WebP managed에 AruArchive JSON 임베딩 (EXIF UserComment)
     ├── 실패 → metadata_sync_status='metadata_write_failed' [종료]
     └── 성공 → artwork_files UPDATE metadata_embedded=1

  5. (ExifTool 있음, MVP-B) WebP XMP 기록
     → BMP와 동일 처리 (json_only / xmp_write_failed / full)

  6. thumbnail_cache 생성 (WebP managed 사용)
```

### 10.4 static GIF 저장

```
[CoreWorker] — static GIF 감지 시 (is_animated_gif() == False)
  1. GIF httpx 다운로드
  2. Inbox/{source_site}/{filename}.gif 저장
     artwork_files INSERT (file_role='original')
     ├── 실패 → metadata_sync_status='file_write_failed' [종료]
     └── 성공 → 계속

  3. {filename}.gif.aru.json sidecar 파일 생성
     artwork_files INSERT (file_role='sidecar')
     ├── 실패 → metadata_sync_status='metadata_write_failed'
     │          no_metadata_queue INSERT (fail_reason='metadata_write_failed')
     │          [종료]
     └── 성공 → metadata_sync_status='json_only'
                (파일 우선 원칙의 예외 — sidecar-only 정책)

  4. XMP 미적용 (static GIF는 XMP 처리 없음)
  5. thumbnail_cache 생성 (GIF original에서 직접)

  ※ static GIF의 metadata_sync_status='json_only'는 파일 내부 JSON이 아니라
     sidecar JSON만 존재함을 의미하는 예외적 사용이다.
```

### 10.5 우고이라 ZIP + WebP managed 처리

```
[CoreWorker] — ugoira 저장 요청 시
  1. GET /ajax/illust/{id}/ugoira_meta → 프레임 목록, 딜레이 수집
  2. ZIP httpx 다운로드
  3. Inbox/{source_site}/{artwork_id}_ugoira.zip 저장
     ZIP comment 삽입: aru:v1:{artwork_id}:{page_index}
     artwork_files INSERT (file_role='original')
     ├── 실패 → metadata_sync_status='file_write_failed' [종료]
     └── 성공 → 계속

  4. {artwork_id}_ugoira.zip.aru.json sidecar 생성 (ZIP 전용 메타데이터)
     artwork_files INSERT (file_role='sidecar')

  5. ugoira_converter.py: ZIP → animated WebP 생성
     artwork_files INSERT (file_role='managed', metadata_embedded=0)
     ├── 실패 → metadata_sync_status='convert_failed'
     │          no_metadata_queue INSERT (fail_reason='managed_file_create_failed')
     │          [종료]
     └── 성공 → 계속

  6. WebP managed에 AruArchive JSON 임베딩 (EXIF UserComment)
     ├── 실패 → metadata_sync_status='metadata_write_failed' [종료]
     └── 성공 → artwork_files UPDATE metadata_embedded=1

  7. (ExifTool 있음, MVP-B) WebP XMP 기록
  8. thumbnail_cache 생성 (WebP managed 사용)
```

### 10.6 메타데이터 쓰기 실패 처리

```
[CoreWorker] — JSON 임베딩 실패 감지
  1. artwork_files UPDATE metadata_embedded=0
  2. artwork_groups UPDATE metadata_sync_status='metadata_write_failed'
  3. no_metadata_queue INSERT:
     queue_id = UUID
     file_path = managed 파일 경로 (또는 original)
     job_id = 현재 job_id
     fail_reason = 'metadata_write_failed'
     raw_context = 오류 직전 부분 데이터 JSON
  4. save_jobs UPDATE failed_pages += 1
  5. job_pages UPDATE status='failed', error_message='metadata_write_failed'
  6. 나머지 페이지 계속 처리 (전체 실패로 중단하지 않음)
```

### 10.7 XMP 쓰기 실패 처리

```
[CoreWorker] — ExifTool XMP 쓰기 실패 감지
  1. artwork_groups UPDATE metadata_sync_status='xmp_write_failed'
  2. no_metadata_queue에 INSERT하지 않음
  3. artwork_files의 metadata_embedded=1 유지 (JSON은 정상)
  4. MainApp에 알림: type='xmp_warning', group_id=...
  5. MainApp UI: 갤러리 카드에 ⚠️ 배지 추가
     상세 패널 > 메타데이터 탭에 [XMP 재시도] 버튼 표시
```

### 10.8 No Metadata 큐 등록

```
[NativeHost 또는 CoreWorker] — 큐 등록 조건 충족 시
  1. no_metadata_queue INSERT (fail_reason 세부값 또는 embed_failed fallback)
  2. 파일 다운로드가 완료된 경우: Inbox에 파일 보존 (삭제 안 함)
  3. MainApp HTTP 알림 (실행 중인 경우)
  
[MainApp UI]
  · 상단 배너: "메타데이터 없는 파일 N개"
  · No Metadata 패널: 썸네일 + fail_reason 메시지 + 액션 버튼
  · 각 항목: "수동 입력" / "재시도" / "무시" (fail_reason별 버튼 §6.4 참조)
```

### 10.9 Undo 실행

```
[MainApp UI] 작업 로그 패널 → Undo 버튼 클릭
  │
  ▼ [undo_status 확인]
  'pending'이 아닌 값 → 버튼 비활성 (도달 불가)
  'pending' → 계속
  │
  ▼ [MainApp WorkerThread]
  1. operation_locks 획득: undo:{entry_id}
  2. copy_records 조회 (entry_id 기준)
  3. dest_mtime_at_copy IS NULL → undo_status='expired' 방어 체크
  4. 3-field 안전성 체크 (size / mtime / hash)
  5. 불일치 → 확인 다이얼로그
  6. 통과 → os.remove(dest_path)
  7. artwork_files UPDATE file_status='missing' (classified_copy 행)
  8. undo_entries UPDATE undo_status='completed', undone_at=now()
  9. operation_locks 해제: undo:{entry_id}
  10. artwork_groups UPDATE status='inbox'
  11. UI 갱신 (작업 로그, 갤러리)
```

### 10.10 재색인

```
[MainApp WorkerThread]
  1. operation_locks 획득: reindex (timeout 600초)
  2. Inbox 폴더 전체 순회
  3. 각 파일:
     a. 파일 읽기 → AruArchive JSON 추출
     b. JSON 없음 → metadata_sync_status='metadata_missing'
                    no_metadata_queue 기록 검토
     c. artwork_groups UPSERT
     d. artwork_files UPSERT (file_status='present', last_seen_at=now())
     e. tags 재구성 (group_id 기준)
     f. thumbnail_cache 갱신 (hash 변경 시 invalidate 후 재생성)
  4. DB에 있으나 파일 없는 항목 → file_status='missing'
  5. artwork_groups.metadata_sync_status 재평가
  6. operation_locks 해제: reindex
```

---

## 11. 최종 체크리스트

### 11.1 Sprint 계획

| Sprint | 목표 | 핵심 산출물 | MVP |
|--------|------|-----------|-----|
| S1 | DB 스키마 + 메타데이터 읽기/쓰기 | `db/schema.sql` (12개 테이블), `core/metadata_writer.py`, `metadata_reader.py` | A |
| S2 | 파일 변환 + Native Host 기반 | `core/format_converter.py`, `core/ugoira_converter.py`, `native_host/host.py` | A |
| S3 | 브라우저 확장 + Pixiv 어댑터 + IPC 토큰 | `extension/`, `core/adapters/pixiv.py`, `app/http_server.py` | A |
| S4 | PySide6 기본 앱 + 포터블 빌드 | `app/`, `build/`, `install_host.bat`, `core/thumbnail_manager.py` | A |
| S5 | 분류 엔진 + Undo 기반 | `core/classifier.py`, Undo DB 로직 | B |
| S6 | 분류 미리보기 UI + 작업 로그 | `app/views/classify_preview.py`, `work_log_view.py` | B |
| S7 | thumbnail_cache hybrid + 가상화 그리드 | Hybrid path 전환, 가상화 QListView | B |
| S8 | ExifTool 통합 + No Metadata 수동 처리 | ExifTool wrapper, `no_metadata_view.py` (확장 fail_reason) | B |
| S9 | 태그 별칭 + 패키징 최종화 | `tag_aliases`, `tag_normalizer.py`, installer 최종화 | C |
| Post | X 어댑터 | `core/adapters/x.py` | Post-MVP |

### 11.2 Sprint 1 개발 착수 전 확인 항목

- [ ] 전체 SQLite 스키마 생성 (12개 테이블)
- [ ] `save_jobs`, `job_pages` 포함
- [ ] `no_metadata_queue.fail_reason` — **13개 enum 주석** (`bmp_convert_failed` 등 포함)
- [ ] `operation_locks` 포함 (키 명명 정책 주석 포함)
- [ ] `artwork_groups.metadata_sync_status` — **11개 enum 주석** + 기본값 `'pending'`
- [ ] `artwork_files.file_status` 컬럼 포함
- [ ] `undo_entries.undo_status` 컬럼 포함 (기본값 `'pending'`)
- [ ] `tags.group_id` (artwork_id 아님)
- [ ] `thumbnail_cache`: BLOB 없음, `thumb_path TEXT`
- [ ] `tag_aliases` 테이블 생성 (데이터는 S9)
- [ ] `metadata_sync_status` DDL 주석에 `convert_failed`, `metadata_write_failed` 포함 확인

### 11.3 변경 시 위험한 구조적 결정

아래 항목을 변경하려면 전체 파이프라인 재검토가 필요하다.

| 항목 | 위험도 | 변경 시 영향 범위 |
|------|--------|----------------|
| `artwork_groups` / `artwork_files` 분리 구조 | 매우 높음 | 전체 DB 스키마, CoreWorker, UI 모델 |
| `metadata_sync_status` 기본값 `'pending'` | 높음 | 저장 파이프라인 전체 상태 흐름 |
| "원본 보존 + managed 변환" 파이프라인 | 높음 | BMP/GIF/ugoira 저장 로직, classifier, thumbnail |
| `file_role` enum | 높음 | 분류 로직, Undo, 썸네일 선택 정책 |
| IPC 토큰 파일 위치 | 중간 | NativeHost + MainApp 양쪽 수정 필요 |
| `tags.group_id` 컬럼명 | 중간 | 태그 검색 쿼리 전체 |
| operation_locks 키 패턴 | 낮음 | 키 사용 코드 전체 |

### 11.4 Post-MVP로 미룬 기능

| 기능 | 이유 | 재검토 조건 |
|------|------|------------|
| X(트위터) 어댑터 | Pixiv 완성 우선. 어댑터 패턴으로 코드 변경 없이 추가 가능 | MVP-C 완성 후 |
| `xmp_write_failed` 일괄 재처리 | MVP-B ExifTool 통합 후 필요성 재평가 | MVP-B 완성 후 |
| static GIF → PNG/WebP managed 전환 | 발생 빈도 낮음. 현재 sidecar-only로 충분 | 실사용 중 static GIF 비중 증가 시 |
| Undo `pending → available` 명칭 변경 | 변경 비용 > 이득. 다른 테이블과 일관성 중요 | 전체 테이블 마이그레이션 시 |
| `tag_aliases` 데이터 구축 | 스키마만 S1에 생성. 초기 alias 데이터는 S9 | MVP-C Sprint |
| Edge 브라우저 지원 | Chrome/Whale 완성 후 검토 | Post-MVP |

### 11.5 config.json 기본 구조

```json
{
  "schema_version": "1.0",
  "inbox_dir": "D:/AruArchive/Inbox",
  "classified_dir": "D:/AruArchive/Classified",
  "classify_mode": "save_only",
  "undo_retention_days": 7,
  "exiftool_path": null,
  "preferred_browser": null,
  "http_port": 18456,
  "thumbnail_size": "256x256",
  "ui_language": "ko"
}
```

### 11.6 기술 스택 최종 확정

| 영역 | 기술 | 버전 | MVP |
|------|------|------|-----|
| 메인 앱 UI | PySide6 | 6.x | A |
| HTTP 클라이언트 | httpx | 0.27+ | A |
| JPEG/WebP EXIF | piexif | 1.1.x | A |
| 이미지 처리 | Pillow | 10.x | A |
| DB | SQLite3 | 내장 | A |
| 패키징 | PyInstaller | 6.x | A |
| 브라우저 확장 | Manifest V3 | Chrome/Whale | A |
| XMP 표준 필드 | ExifTool (선택) | 12.x | B |

### 11.7 최종 파일 구조

```
aru_archive/
├── extension/
│   ├── manifest.json
│   ├── content_scripts/pixiv.js
│   ├── background/service_worker.js
│   └── popup/popup.html, popup.js
├── native_host/
│   ├── host.py                  # stdin/stdout 루프 + IPC 토큰 읽기
│   ├── handlers.py
│   ├── manifest_chrome.json
│   └── manifest_whale.json
├── core/
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── pixiv.py
│   ├── metadata_writer.py
│   ├── metadata_reader.py
│   ├── format_converter.py      ← BMP→PNG, animated GIF→WebP
│   ├── ugoira_converter.py
│   ├── thumbnail_manager.py     ← Hybrid path 썸네일 관리
│   ├── classifier.py            (MVP-B)
│   ├── tag_normalizer.py        (MVP-C)
│   └── worker.py
├── db/
│   ├── database.py
│   └── schema.sql               # 12개 테이블 (v2.4 확정 스키마)
├── app/
│   ├── main_window.py
│   ├── http_server.py           # localhost IPC + 토큰 인증
│   ├── views/
│   │   ├── gallery_view.py
│   │   ├── detail_view.py
│   │   ├── rules_view.py        (MVP-B)
│   │   ├── work_log_view.py     (MVP-B)
│   │   └── no_metadata_view.py
│   └── widgets/
│       ├── ugoira_player.py
│       └── provenance_badge.py
├── build/
│   ├── install_host.bat
│   ├── uninstall_host.bat
│   └── aru_archive.spec
├── config.json
├── aru_archive.db
└── .thumbcache/                 ← thumbnail_cache 실제 파일
    └── {prefix}/{file_id}.webp
```

### 11.8 주요 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|--------|--------|------|
| Pixiv preload_data 구조 변경 | 중 | 파싱 실패 → `no_metadata_queue` (`parse_error`) 자동 기록 |
| BMP PNG 변환 중 색상 프로파일 손실 | 낮 | Pillow `ImageCms`로 ICC 프로파일 보존 옵션 검토 |
| animated GIF 판별 오탐 | 낮 | `is_animated` + `n_frames > 1` 이중 조건 |
| SQLite 동시 접근 충돌 | 낮 | operation_locks 세분화 키 + `busy_timeout=5000` |
| `.thumbcache` 디렉토리 고아 파일 | 중 | `purge_orphan_thumbnails()` 주 1회 실행 |
| IPC 토큰 파일 잔류 (비정상 종료) | 중 | MainApp 시작 시 항상 ipc_token 덮어쓰기 |
| 대용량 Inbox (10,000+) 재색인 느림 | 중 | 재색인 진행률 UI + 백그라운드 QThread |
| X 어댑터 지연 | 확정 | 어댑터 패턴으로 기반 코드 변경 없이 추가 가능 |

---

## 부록: enum 빠른 참조

### metadata_sync_status 최종 11개

```
pending              기본값. 파이프라인 진입 전/진행 중
full                 JSON + XMP 모두 완료
json_only            JSON만 완료 (ExifTool 없음 / static GIF sidecar 성공)
out_of_sync          DB와 파일 메타데이터 불일치
file_write_failed    원본 파일 저장 자체 실패         ← 1단계 실패
convert_failed       원본 저장 성공, managed 변환 실패 ← 2단계 실패
metadata_write_failed managed 생성 성공, JSON 임베딩 실패 ← 3단계 실패
xmp_write_failed     JSON 성공, XMP만 실패            ← 4단계 실패
db_update_failed     파일 처리 성공, DB 업데이트 실패
needs_reindex        재색인 필요
metadata_missing     파일 내 JSON 없음 (외부 편집 의심)
```

### no_metadata_queue.fail_reason 최종 13개

```
no_dom_data              DOM 파싱 실패
parse_error              메타데이터 파싱 예외
network_error            다운로드 실패
unsupported_format       지원 안 하는 형식
manual_add               사용자 수동 추가
embed_failed             기타 임베딩 오류 (범용 폴백)
partial_data             불완전 메타데이터
artwork_restricted       접근 제한 작품
api_error                Pixiv API 4xx/5xx
bmp_convert_failed       BMP → PNG managed 변환 실패
managed_file_create_failed  기타 managed 파일 생성 실패
metadata_write_failed    파일 생성 후 JSON 임베딩 실패
xmp_write_failed         JSON 성공 후 XMP 실패 ※큐에 기록 안 함
```

---

*이 문서는 Aru Archive v2.4 최종 개발 착수용 통합 설계안입니다.*  
*v2.3 설계안 + v2.3.1 상태값 정합성 패치가 완전히 통합되었습니다.*  
*v2.3, v2.3.1 패치 문서를 별도로 참조할 필요 없이 이 문서만으로 개발 착수가 가능합니다.*
