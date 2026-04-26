# Aru Archive 최종 개발 착수용 설계안 v2.3

## 메타데이터

- **문서 버전**: 2.3
- **작성일**: 2026-04-26
- **기준 문서**: 최종 개발 착수용 설계안 v2.2
- **목적**: AI 코드 생성 및 분석 요청 시 참조 컨텍스트 (최종 확정판)
- **개발 언어**: Python 3.12 (백엔드/메인앱), JavaScript (브라우저 확장 MV3)
- **대상 플랫폼**: Windows 11, Chrome / Naver Whale

---

## 1. 개정 요약

### v2.2 → v2.3 변경 사항 (12개)

| # | 항목 | v2.2 | v2.3 결정 |
|---|------|------|-----------|
| 1 | BMP 저장 정책 | sidecar only | original 보존 + PNG managed 생성 + PNG에 JSON/XMP 기록 |
| 2 | GIF 저장 정책 | sidecar only (미확정) | animated → WebP managed 생성; static → sidecar only |
| 3 | save_jobs / job_pages 테이블 | 목록 누락 | 최종 테이블 목록에 복구 (총 12개) |
| 4 | metadata_sync_status 값 | 4개 (full/json_only/out_of_sync/pending) | 9개로 확장 (file_write_failed 등 5개 추가) |
| 5 | metadata_sync_status 기본값 | `full` | `pending` (임베딩 완료 후 full/json_only로 갱신) |
| 6 | undo_entries | undo_status 없음 | `undo_status` 컬럼 추가 (pending/completed/failed/expired) |
| 7 | operation_locks 키 정책 | 키 명명 규칙 없음 | 키 패턴 정의: `save:pixiv:{artwork_id}` 등 |
| 8 | localhost HTTP IPC | 인증 없음 | `X-Aru-Token` 헤더 토큰 인증 추가 (세션별 UUID) |
| 9 | thumbnail_cache 저장 방식 | SQLite BLOB | Hybrid: 파일 경로 기반 + DB 인덱스 (BLOB 제거) |
| 10 | X 어댑터 일정 | MVP-C | Post-MVP로 이동 |
| 11 | tags.artwork_id 컬럼명 | artwork_id | group_id로 수정 (artwork_groups FK와 일치) |
| 12 | no_metadata_queue fail_reason | 5개 | 9개로 확장 (embed_failed 등 4개 추가) |

### 설계 핵심 원칙 (변경 없음)

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

### 2.2 classify_mode 정책 (변경 없음)

```
classify_mode: save_only   (MVP-A 기본, 분류 엔진 없음)
               immediate   (MVP-B, 저장 직후 자동 분류)
               review      (MVP-B, 분류 미리보기 후 사용자 확인)
```

- **MVP-A**: config.json에 `"classify_mode": "save_only"` 고정
- **MVP-B 활성화**: 설정 UI에서 immediate / review 선택 가능
- **classify_mode 변경 시**: 변경 시점 이후 신규 저장분부터 적용 (소급 없음)

### 2.3 MVP-A 최소 완성 조건

1. 브라우저 확장에서 저장 버튼 → Inbox에 파일 저장 + 메타데이터 임베딩 완료
2. BMP → PNG managed 변환 동작 확인
3. animated GIF → WebP managed 변환 동작 확인
4. PySide6 갤러리 뷰에서 Inbox 파일 썸네일 표시 및 클릭 상세 보기
5. No Metadata 파일은 no_metadata_queue에 기록, UI에 카운터 표시
6. save_jobs 진행률 실시간 폴링 동작
7. SQLite artworks DB 색인 완료
8. 포터블 exe 빌드 + install_host.bat 레지스트리 등록 동작

---

## 3. 메타데이터 저장 정책

### 3.1 이중 저장 구조 (변경 없음)

```
AruArchive JSON (필수, MVP-A)
  · 완전한 스키마 (schema_version, provenance, ugoira 포함)
  · 파일 형식별 저장 위치 (아래 표)

XMP 표준 필드 (선택, MVP-B, ExifTool 필요)
  · dc:title, dc:creator, dc:subject (tags), xmp:CreateDate
  · ExifTool 없으면 이 단계 skip (경고 로그만)
```

### 3.2 파일 형식별 저장 정책 (v2.3 확정)

| 파일 형식 | 처리 방식 | AruArchive JSON | XMP |
|-----------|-----------|-----------------|-----|
| JPEG | original 보존 | EXIF UserComment (`0x9286`, UTF-16LE) | EXIF XMP 세그먼트 (ExifTool) |
| PNG | original 보존 | iTXt chunk (keyword=`AruArchive`) | iTXt chunk (`XML:com.adobe.xmp`) |
| WebP (ugoira/BMP 변환본) | managed 파일 | EXIF UserComment (JPEG와 동일) | EXIF XMP 세그먼트 (ExifTool) |
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

> **GIF static 처리 근거**: 정적 GIF는 PNG 변환 시 색상 손실 위험이 있다.  
> 변환 없이 원본 보존 + sidecar 방식을 채택한다.

### 3.3 AruArchive JSON 스키마 (최종, 변경 없음)

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
        return getattr(img, 'is_animated', False)

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

### 3.6 ExifTool 통합 정책 (변경 없음)

| 항목 | 내용 |
|------|------|
| 번들 방식 | `exiftool.exe`를 PyInstaller 빌드 폴더에 포함 (optional) |
| 실행 방식 | `subprocess.run(['exiftool', ...])` — 배치 플래그 활용 |
| 없을 때 동작 | AruArchive JSON만 저장, 경고 로그, `metadata_sync_status='json_only'` |
| 있을 때 동작 | JSON 임베딩 후 ExifTool로 XMP 추가 → `metadata_sync_status='full'` |
| MVP-A | ExifTool 없어도 정상 동작 / MVP-B에서 ExifTool 번들 포함 |

---

## 4. 데이터 모델 최종안

### 4.1 전체 테이블 목록 (v2.3 확정, 12개)

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
                          -- file_write_failed | xmp_write_failed |
                          -- db_update_failed | needs_reindex | metadata_missing
    schema_version        TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(artwork_id, source_site)
);
```

#### metadata_sync_status 값 정의 (v2.3 확장, 9개)

| 값 | 의미 | 다음 상태 |
|----|------|-----------|
| `pending` | **기본값**. 임베딩 작업 시작 전 또는 진행 중 | full / json_only / file_write_failed 등 |
| `full` | AruArchive JSON + XMP 모두 임베딩 완료 | out_of_sync (파일 변경 감지 시) |
| `json_only` | AruArchive JSON만 임베딩 (ExifTool 없음) | full (ExifTool 추가 후 재실행 시) |
| `out_of_sync` | DB와 파일 메타데이터 불일치 감지 | full (재동기화 후) |
| `file_write_failed` | 파일에 메타데이터 쓰기 자체 실패 (I/O 오류 등) | pending (재시도) |
| `xmp_write_failed` | JSON 임베딩은 성공했으나 ExifTool XMP 단계 실패 | json_only (수동 강등) 또는 full (재시도) |
| `db_update_failed` | 파일 쓰기는 성공했으나 DB 업데이트 실패 | needs_reindex (재색인으로 복구) |
| `needs_reindex` | 재색인이 필요한 상태 (db_update_failed 후 등) | full (재색인 완료 후) |
| `metadata_missing` | 파일 내 AruArchive JSON을 찾을 수 없음 (외부 편집 의심) | pending (재임베딩 시도) |

> **기본값 변경 이유**: `full`을 기본값으로 하면 임베딩 실패 시 상태가 갱신되지 않아도 `full`로 표시되는 버그가 생긴다.  
> `pending`을 기본값으로 하면 임베딩 완료 후 명시적으로 갱신해야 하므로 누락 감지가 용이하다.

### 4.3 artwork_files 테이블 (변경 없음)

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

### 4.4 tags 테이블 (컬럼명 수정: artwork_id → group_id)

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

> **컬럼명 수정 이유**: `artwork_id`는 Pixiv의 작품 번호(예: `"141100516"`)와 혼동될 수 있다.  
> `group_id`는 DB 내부 UUID 식별자임을 명확히 하며, FK 참조 대상인 `artwork_groups.group_id`와 일치한다.

### 4.5 save_jobs 테이블 (복구)

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

### 4.6 job_pages 테이블 (복구)

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

### 4.7 no_metadata_queue 테이블 (fail_reason 확장)

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
                  -- embed_failed | partial_data |
                  -- artwork_restricted | api_error
    raw_context   TEXT,                             -- 오류 당시 부분 데이터 JSON
    resolved      INTEGER NOT NULL DEFAULT 0,
    resolved_at   TEXT,
    notes         TEXT
);
```

**fail_reason enum (v2.3 확장, 9개)**:

| 값 | 발생 시점 | 권장 대응 |
|----|-----------|-----------|
| `no_dom_data` | content_script가 preload_data를 찾지 못함 | 페이지 새로고침 후 재시도 |
| `parse_error` | 메타데이터 파싱 중 예외 발생 | 개발자에게 신고 |
| `network_error` | httpx 다운로드 실패 | 재다운로드 시도 |
| `unsupported_format` | 지원하지 않는 파일 형식 | 수동 메타데이터 입력 |
| `manual_add` | 사용자가 수동으로 큐에 추가 | 메타데이터 직접 입력 |
| `embed_failed` | 파일 다운로드 성공 후 메타데이터 임베딩 실패 | 파일 권한/잠금 확인 후 재시도 |
| `partial_data` | 일부 필드 누락된 불완전한 메타데이터 | 누락 필드 수동 보완 |
| `artwork_restricted` | R-18 또는 프리미엄 잠금 작품 (접근 제한) | 로그인 상태 확인 |
| `api_error` | Pixiv AJAX API 응답 오류 (4xx/5xx) | 잠시 후 재시도 |

### 4.8 undo_entries 테이블 (undo_status 추가)

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

**undo_status 값 정의**:

| 값 | 의미 |
|----|------|
| `pending` | Undo 가능 상태 (기본값) |
| `completed` | Undo 성공적으로 완료됨 |
| `failed` | Undo 시도했으나 실패 (`undo_error`에 상세 기록) |
| `expired` | `undo_expires_at` 경과, Undo 불가 |

> **만료 처리**: `undo_expires_at < now()` 감지 시 `undo_status='expired'` 업데이트.  
> UI는 `undo_status='pending'` 항목만 Undo 버튼 활성화.

### 4.9 copy_records 테이블 (B-2 정책, 변경 없음)

```sql
CREATE TABLE copy_records (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id             TEXT NOT NULL REFERENCES undo_entries(entry_id) ON DELETE CASCADE,
    src_file_id          TEXT REFERENCES artwork_files(file_id),
    dest_file_id         TEXT REFERENCES artwork_files(file_id),
    src_path             TEXT NOT NULL,
    dest_path            TEXT NOT NULL,
    rule_id              TEXT,
    dest_file_size       INTEGER NOT NULL,           -- 만료 후에도 보존
    dest_mtime_at_copy   TEXT,                       -- 만료 후 NULL
    dest_hash_at_copy    TEXT,                       -- 만료 후 NULL
    manually_modified    INTEGER DEFAULT 0,
    copied_at            TEXT NOT NULL
);
```

### 4.10 thumbnail_cache 테이블 (v2.3: Hybrid path 방식)

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

> BLOB 컬럼 제거. 썸네일 실제 파일은 별도 디렉토리에 저장 (§11 참조).

### 4.11 classify_rules 테이블 (변경 없음)

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

### 4.12 tag_aliases 테이블 (MVP-C, 스키마 MVP-A)

```sql
CREATE TABLE tag_aliases (
    alias         TEXT PRIMARY KEY,
    canonical     TEXT NOT NULL,
    source_site   TEXT DEFAULT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_tag_aliases_canonical ON tag_aliases(canonical);
```

### 4.13 operation_locks 테이블 (키 정책 추가)

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

> **키 설계 원칙**: 세분화된 키로 서로 다른 작품의 병렬 저장을 허용하되,  
> 동일 작품의 중복 저장은 `save:{site}:{id}` 잠금으로 방지한다.

---

## 5. Undo / copy_records 보존 정책

### 5.1 B-2 정책 요약 (변경 없음)

| 항목 | 내용 |
|------|------|
| 채택 이유 | Undo 안전성(hash 체크)과 저장 공간 절약 균형 달성 |
| 보존 기간 | `config.json`의 `undo_retention_days` (기본값: 7일) |
| 만료 시 처리 | `dest_hash_at_copy`, `dest_mtime_at_copy` → NULL (UPDATE) |
| 보존 항목 | `dest_file_size` — Recent Jobs 패널 파일 크기 표시에 사용 |
| 만료 후 상태 | `undo_status='expired'`, Undo 버튼 비활성화 |

### 5.2 Undo 실행 흐름 (v2.3: undo_status 반영)

```
사용자: Undo 버튼 클릭
  │
  ▼ [undo_status 확인]
  'expired' → 버튼 비활성 (이 경로 도달 불가)
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

### 5.3 만료 처리 스케줄

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

## 6. 브라우저 연결 정책 (변경 없음)

### 6.1 지원 브라우저

| 브라우저 | 지원 여부 | 비고 |
|---------|----------|------|
| Google Chrome (Stable) | ✅ 필수 지원 | HKCU NativeMessaging 등록 |
| Naver Whale | ✅ 필수 지원 | HKCU NativeMessaging 등록 |
| Chrome Beta/Dev/Canary | ❌ 미지원 | 레지스트리 경로 상이 |
| Edge | ❌ 미지원 | Post-MVP 검토 |

### 6.2 동시 연결 정책

- Chrome OR Whale 중 ≥1 연결 필수: 둘 다 없으면 메인앱 초기화 경고
- 양쪽 동시 연결 시: 첫 실행 시 "기본 브라우저 선택" UI 표시 → config.json 저장
- `install_host.bat` 실행 시 Chrome + Whale 레지스트리 동시 등록

### 6.3 레지스트리 등록 경로

```
Chrome:
HKCU\Software\Google\Chrome\NativeMessagingHosts\net.aru_archive.host
  → {install_dir}\native_host\manifest_chrome.json

Whale:
HKCU\Software\Naver\Whale\NativeMessagingHosts\net.aru_archive.host
  → {install_dir}\native_host\manifest_whale.json
```

---

## 7. 프로세스 구조

### 7.1 프로세스 다이어그램

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

### 7.2 IPC 프로토콜 (NativeHost ↔ MainApp)

**Base URL**: `http://127.0.0.1:{http_port}/api`  
**인증 헤더**: `X-Aru-Token: {session_token}` (모든 요청에 필수)

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/ping` | GET | MainApp 실행 여부 확인 (토큰 검증 포함) |
| `/api/jobs` | POST | 저장 작업 큐에 추가 |
| `/api/jobs/{job_id}` | GET | 작업 상태 폴링 |
| `/api/notify` | POST | MainApp UI 갱신 알림 |

### 7.3 HTTP IPC 토큰 인증

```
토큰 생명주기:
  MainApp 시작 시 → secrets.token_hex(32) 생성
                  → {data_dir}/.runtime/ipc_token 파일에 저장 (0o600)
  MainApp 종료 시 → ipc_token 파일 삭제

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

> **토큰 설계 근거**: localhost-only 통신이므로 외부 공격 위험은 낮다.  
> 그러나 동일 머신의 다른 프로세스(악성 코드 포함)가 포트에 접근하는 경우를 방지하기 위해  
> 세션별 랜덤 토큰으로 간단한 인증을 추가한다.  
> PKI 수준의 보안은 오버엔지니어링이므로 채택하지 않는다.

### 7.4 CoreWorker 서브프로세스 모드 (변경 없음)

```python
# native_host/host.py
def spawn_core_worker(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, '-m', 'core.worker', '--json-stdin'],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=120
    )
    return json.loads(proc.stdout)
```

---

## 8. SQLite 동시 접근 정책

### 8.1 기본 설정 (변경 없음)

```python
conn = sqlite3.connect(db_path, timeout=5.0)  # busy_timeout=5000ms
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA foreign_keys=ON")
conn.row_factory = sqlite3.Row
```

### 8.2 접근 패턴 정책

| 접근자 | 읽기 | 쓰기 | 비고 |
|--------|------|------|------|
| NativeHost / CoreWorker | ✅ | ✅ | 저장 작업 시 쓰기 |
| MainApp (UI Thread) | ✅ | ❌ | UI는 읽기 전용 |
| MainApp (Worker Thread) | ✅ | ✅ | 재색인, Undo 실행 시 |
| Reindex Job | ✅ | ✅ | 단독 실행 |

### 8.3 operation_locks 획득/해제 패턴

```python
# db/database.py
from contextlib import contextmanager

@contextmanager
def locked_operation(conn, lock_name: str, locked_by: str, timeout_sec: int = 30):
    """컨텍스트 매니저로 잠금 획득 → 작업 → 자동 해제."""
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
            # 만료된 잠금 강제 해제 후 재시도
            conn.execute("DELETE FROM operation_locks WHERE lock_name=?", (lock_name,))
            conn.commit()
            return acquire_lock(conn, lock_name, locked_by, timeout_sec)
        return False
```

**사용 예시**:
```python
# 저장 시 중복 방지 잠금
with locked_operation(conn, f'save:pixiv:{artwork_id}', 'native_host', 120):
    # 저장 로직 실행
    ...

# 재색인 잠금
with locked_operation(conn, 'reindex', 'main_app', 600):
    # 재색인 로직 실행
    ...
```

### 8.4 WAL 체크포인트 정책 (변경 없음)

- 자동 체크포인트 (SQLite 기본값 1000 페이지) 유지
- MainApp 정상 종료 시: `PRAGMA wal_checkpoint(TRUNCATE)` 실행

---

## 9. 파일 경로 변경 / Missing 파일 대응 (변경 없음)

### 9.1 file_status 갱신 정책

| 트리거 | 동작 |
|--------|------|
| 갤러리 뷰 파일 로드 | 해당 파일 `file_status` 확인 → missing이면 배지 표시 |
| 재색인(reindex) 실행 | 전체 artwork_files 경로 존재 여부 순차 확인 후 갱신 |
| 메인앱 시작 | Inbox 폴더 quick scan (파일명 비교, hash 없이) |

### 9.2 Missing 파일 UI 대응

```
갤러리 썸네일 카드:
  [?] 아이콘 오버레이 + 흐린 처리
  우클릭 메뉴: "파일 재연결", "DB에서 제거", "재다운로드 시도"

파일 재연결 다이얼로그:
  1. 파일 선택 다이얼로그 열기
  2. 선택한 파일 hash == 기존 file_hash? → 자동 경로 업데이트
  3. hash 불일치 → "다른 파일인 것 같습니다. 그래도 연결하시겠습니까?" 확인
```

---

## 10. 태그 정규화 / 별칭 (변경 없음)

### 10.1 정책

- **목적**: Pixiv 다국어 태그 및 오탈자를 단일 정규 태그로 통합
- **방향**: alias → canonical 단방향 매핑
- **적용 시점**: 검색/필터 시 동적 적용 (원본 태그 보존)
- **구현 시점**: MVP-C (스키마는 MVP-A Sprint 1에서 생성)

### 10.2 초기 alias 데이터 예시

```json
[
  {"alias": "オリジナル",    "canonical": "original",   "source_site": "pixiv"},
  {"alias": "original",     "canonical": "original",   "source_site": null},
  {"alias": "r-18",         "canonical": "R-18",       "source_site": "pixiv"},
  {"alias": "女の子",        "canonical": "girl",       "source_site": "pixiv"}
]
```

---

## 11. 썸네일 캐시 / 성능

### 11.1 Hybrid Path 방식 (v2.3 변경)

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
| Path 기반 (v2.3) | DB 경량화, OS 캐시 활용, 대용량 성능 우수 | 별도 디렉토리 관리 필요 |
| Hybrid (채택) | DB는 경로 인덱스만, 실제 파일은 OS 관리 | 썸네일 파일과 DB 동기화 필요 |

> **Hybrid 채택 이유**: 10,000개 이상 파일 환경에서 BLOB 방식은 DB 크기가 수백 MB에 달할 수 있다.  
> Path 기반으로 전환하면 SQLite는 경량 인덱스로 유지되고, OS 파일 시스템 캐시를 활용할 수 있다.

### 11.2 썸네일 생성 정책

| 항목 | 값 |
|------|-----|
| 크기 | 256×256 px (표준), 128×128 (소형 그리드) |
| 형식 | WebP (품질 85) |
| 저장 경로 | `{data_dir}/.thumbcache/{id[0:2]}/{file_id}.webp` |
| 갱신 조건 | `source_hash != artwork_files.file_hash` |
| 생성 시점 | 파일 저장 완료 직후 (CoreWorker 내) |

### 11.3 썸네일 관리

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

def invalidate_thumbnail(db, data_dir: str, file_id: str):
    row = db.execute(
        "SELECT thumb_path FROM thumbnail_cache WHERE file_id=?", (file_id,)
    ).fetchone()
    if row:
        Path(row['thumb_path']).unlink(missing_ok=True)
        db.execute("DELETE FROM thumbnail_cache WHERE file_id=?", (file_id,))
        db.commit()

def purge_orphan_thumbnails(db, data_dir: str):
    """DB에 없는 고아 썸네일 파일 정리."""
    thumb_dir = Path(data_dir) / '.thumbcache'
    for webp in thumb_dir.rglob('*.webp'):
        file_id = webp.stem
        row = db.execute(
            "SELECT 1 FROM thumbnail_cache WHERE file_id=?", (file_id,)
        ).fetchone()
        if not row:
            webp.unlink()
```

### 11.4 가상화 그리드 정책 (변경 없음)

- **적용 기준**: 표시 항목 500개 초과 시 QListView 가상화 모드 활성화
- **구현**: `QAbstractItemModel` + `QListView.setUniformItemSizes(True)`
- **썸네일 로드**: 뷰포트 내 카드만 thumb_path에서 로드 (lazy load)
- **성능 목표**: 10,000개 항목에서 60fps 스크롤

### 11.5 썸네일 없는 경우 플레이스홀더

| 상황 | 플레이스홀더 |
|------|------------|
| 생성 중 | 회전 스피너 오버레이 |
| ZIP/ugoira (WebP 없음) | 필름 아이콘 |
| file_status=missing | `?` 아이콘 + 흐린 처리 |
| GIF static (sidecar only) | 파일 형식 아이콘 |
| BMP (원본, PNG managed 있음) | PNG managed 썸네일 사용 |

---

## 12. No Metadata 큐 정책

### 12.1 기록 시점 (MVP-A Sprint 1부터)

- NativeHost가 메타데이터 없는 저장 요청을 받는 모든 경우
- content_script가 DOM 파싱에 실패한 경우 (partial_data와 함께 기록)
- 파일 다운로드 성공 후 메타데이터 임베딩 실패한 경우 (`embed_failed`)
- 접근 제한 작품 저장 시도 (`artwork_restricted`)
- Pixiv AJAX API 오류 응답 (`api_error`)

### 12.2 큐 처리 흐름

```
[Extension] content_script 파싱 실패
  │
  ▼ {action: 'save_no_metadata', file_url, fail_reason, partial_data}
  │
[NativeHost] → 파일 다운로드 (메타데이터 없이) or 다운로드 시도
  │           → Inbox에 파일 저장 (성공 시)
  │           → no_metadata_queue INSERT (job_id 연결)
  │
[MainApp] UI 상단 배너: "메타데이터 없는 파일 3개"
  → No Metadata 패널 열기
  → 각 항목: 썸네일, 파일명, fail_reason, "수동 입력" / "재시도" / "무시" 버튼
```

### 12.3 fail_reason별 UI 액션 버튼

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

---

## 13. 수정된 주요 처리 흐름

### 13.1 저장 플로우 (MVP-A, classify_mode=save_only)

```
사용자 클릭 (Pixiv 페이지)
  │
  ▼ [content_scripts/pixiv.js]
  1. preload_data JSON 파싱 → 메타데이터 수집
  2. GET /ajax/illust/{id}/pages → 전체 페이지 URL 수집
  3. (우고이라) GET /ajax/illust/{id}/ugoira_meta → 프레임/딜레이 수집
  4. 파싱 실패 → fail_reason 설정, partial_data 수집
  │
  ▼ [service_worker.js → Native Messaging]
  5. {action: 'save_artwork' | 'save_no_metadata', metadata, pages} 전송
  │
  ▼ [NativeHost]
  6. ipc_token 파일 확인 → MainApp 실행 여부 판단
  7. save_no_metadata → no_metadata_queue INSERT (job_id 포함), 파일만 저장 후 종료
  8. save_artwork:
     a. MainApp 실행 중 → HTTP POST /api/jobs (X-Aru-Token 헤더)
     b. MainApp 없음   → CoreWorker 서브프로세스 spawn
  │
  ▼ [CoreWorker]
  9.  operation_locks 획득: save:pixiv:{artwork_id}
 10. save_jobs INSERT (status='running')
 11. artwork_groups INSERT (metadata_sync_status='pending')
 12. 각 페이지:
     a. job_pages UPDATE status='downloading'
     b. httpx.get(page_url) → bytes (Referer: https://www.pixiv.net)
     c. Inbox/{source_site}/{filename} 저장
     d. artwork_files INSERT (file_role='original', file_status='present')
     e. job_pages UPDATE status='embed_pending'
     f. 형식별 처리:
          JPEG/PNG/WebP → AruArchive JSON 직접 임베딩
          ZIP (우고이라) → ZIP comment + .aru.json sidecar
          BMP           → original 보존 + PNG managed 생성 + PNG에 JSON 임베딩
          GIF animated  → original 보존 + WebP managed 생성 + WebP에 JSON 임베딩
          GIF static    → original 보존 + .aru.json sidecar
     g. (ExifTool 있음) XMP 표준 필드 추가
     h. metadata_sync_status 갱신 (full / json_only / file_write_failed 등)
     i. thumbnail_cache 생성 (hybrid path)
     j. job_pages UPDATE status='saved'
 13. (우고이라/GIF animated) WebP 변환 → EXIF UserComment 삽입
 14. classify_mode == 'save_only' → 분류 skip
 15. tags INSERT (group_id 컬럼 사용)
 16. operation_locks 해제: save:pixiv:{artwork_id}
 17. save_jobs UPDATE status='completed'
 18. artwork_groups UPDATE metadata_sync_status 최종 확정
 19. MainApp HTTP 알림 (실행 중인 경우)
 20. 완료 응답 → Extension
```

### 13.2 분류 플로우 (MVP-B, classify_mode=immediate)

```
[CoreWorker] (저장 완료 후)
  1. operation_locks 획득: classify:{group_id}
  2. Classifier.evaluate(group) → 매칭 규칙 목록
  3. 규칙 없음 → status='inbox' 유지, 종료
  4. 규칙 있음:
     a. undo_entries INSERT (undo_status='pending', expires_at=now+7d)
     b. for each (file, rule):
          dest_path = render_template(rule.dest_template, metadata)
          shutil.copy2(src_path, dest_path)
          dest_hash = sha256(dest_path)
          copy_records INSERT (dest_file_size, dest_mtime_at_copy, dest_hash_at_copy)
          artwork_files INSERT (file_role='classified_copy')
     c. artwork_groups UPDATE status='classified'
  5. operation_locks 해제: classify:{group_id}
  6. MainApp HTTP 알림
```

### 13.3 Undo 플로우 (MVP-B)

```
[MainApp UI] 작업 로그 패널 → Undo 버튼 클릭
  │
  ▼ [undo_status 체크]
  'expired'   → 버튼 비활성 (도달 불가)
  'completed' → 버튼 비활성 (이미 완료)
  'pending'   → 계속
  │
  ▼ [MainApp WorkerThread]
  1. operation_locks 획득: undo:{entry_id}
  2. copy_records 조회 (entry_id 기준)
  3. dest_mtime_at_copy IS NULL → undo_status='expired' 확인 (방어 코드)
  4. 3-field 체크 (size / mtime / hash)
  5. 불일치 → 확인 다이얼로그
  6. 통과 → os.remove(dest_path)
  7. artwork_files UPDATE file_status='missing' (classified_copy)
  8. undo_entries UPDATE undo_status='completed', undone_at=now()
  9. operation_locks 해제: undo:{entry_id}
 10. artwork_groups UPDATE status='inbox'
 11. UI 갱신
```

### 13.4 재색인 플로우

```
[MainApp WorkerThread]
  1. operation_locks 획득: reindex (timeout 600초)
  2. Inbox 폴더 전체 순회
  3. 각 파일:
     a. 파일 읽기 → AruArchive JSON 추출
     b. JSON 없음 → metadata_sync_status='metadata_missing', no_metadata_queue 기록 검토
     c. artwork_groups UPSERT
     d. artwork_files UPSERT (file_status='present', last_seen_at=now())
     e. tags 재구성 (group_id 기준)
     f. thumbnail_cache 갱신 (hash 변경 시 invalidate 후 재생성)
  4. DB에 있으나 파일 없는 항목 → file_status='missing'
  5. artwork_groups.metadata_sync_status 재평가
  6. operation_locks 해제: reindex
```

### 13.5 진행률 폴링 플로우 (MVP-A)

```
[Extension service_worker.js]
  저장 요청 후 → job_id 수신
  │
  ▼ setInterval(pollJobStatus, 500)
  GET /api/jobs/{job_id} (X-Aru-Token)
  │
  ▼ {status, total_pages, saved_pages, failed_pages}
  → popup UI 진행률 바 갱신
  → status='completed' → 폴링 중단, 완료 알림
  → status='failed'    → 폴링 중단, 오류 표시
```

---

## 14. Sprint 반영 사항

### Sprint 계획 (MVP-A: S1~S4, MVP-B: S5~S8, MVP-C: S9, Post-MVP: 별도)

| Sprint | 목표 | 핵심 산출물 | MVP |
|--------|------|-----------|-----|
| S1 | DB 스키마 + 메타데이터 읽기/쓰기 | `db/schema.sql` (12개 테이블), `core/metadata_writer.py`, `metadata_reader.py` | A |
| S2 | 파일 변환 + Native Host 기반 | `core/format_converter.py`, `core/ugoira_converter.py`, `native_host/host.py` | A |
| S3 | 브라우저 확장 + Pixiv 어댑터 + IPC 토큰 | `extension/`, `core/adapters/pixiv.py`, `app/http_server.py` | A |
| S4 | PySide6 기본 앱 + 포터블 빌드 | `app/`, `build/`, `install_host.bat`, `core/thumbnail_manager.py` | A |
| S5 | 분류 엔진 + Undo 기반 | `core/classifier.py`, Undo DB 로직 (`undo_status` 포함) | B |
| S6 | 분류 미리보기 UI + 작업 로그 | `app/views/classify_preview.py`, `work_log_view.py` | B |
| S7 | thumbnail_cache hybrid + 가상화 그리드 | Hybrid path 전환, 가상화 QListView | B |
| S8 | ExifTool 통합 + No Metadata 수동 처리 | ExifTool wrapper, `no_metadata_view.py` (확장 fail_reason) | B |
| S9 | 태그 별칭 + 패키징 최종화 | `tag_aliases`, `tag_normalizer.py`, installer 최종화 | C |
| Post | X 어댑터 | `core/adapters/x.py` | Post-MVP |

### Sprint 1 필수 구현 항목 (v2.3 기준)

- [ ] 전체 SQLite 스키마 생성 (12개 테이블)
- [ ] `save_jobs`, `job_pages` 포함
- [ ] `no_metadata_queue` 포함 (9개 fail_reason enum)
- [ ] `operation_locks` 포함 (키 명명 정책 주석 포함)
- [ ] `artwork_groups.metadata_sync_status` 기본값 `'pending'`
- [ ] `artwork_files.file_status` 컬럼 포함
- [ ] `undo_entries.undo_status` 컬럼 포함
- [ ] `tags.group_id` (artwork_id 아님)
- [ ] `thumbnail_cache`: BLOB 없음, `thumb_path` TEXT
- [ ] `tag_aliases` 테이블 생성 (데이터는 S9)

### Sprint 2 필수 구현 항목

- [ ] `core/format_converter.py`: BMP → PNG, GIF animated → WebP
- [ ] `is_animated_gif()` 판별 로직
- [ ] ugoira ZIP → animated WebP (기존 로직 유지)
- [ ] 모든 변환 함수 단위 테스트

### Sprint 3 필수 구현 항목

- [ ] `app/http_server.py`: 세션 토큰 발급 + 검증 (X-Aru-Token)
- [ ] `.runtime/ipc_token` 파일 생성/삭제
- [ ] `native_host/host.py`: ipc_token 파일 읽기 + HTTP 헤더 첨부
- [ ] HTTP 401 응답 시 CoreWorker spawn 폴백

---

## 15. 최종 권장안

### 15.1 개발 착수 순서 권장

```
1순위 (S1): DB 스키마 확정 → metadata_writer + reader 단위 테스트
            핵심 체크포인트: metadata_sync_status='pending' → 임베딩 후 갱신 흐름 검증

2순위 (S2): format_converter → BMP/GIF/ugoira 변환 파이프라인 검증
            핵심 체크포인트: animated GIF 판별 정확도, BMP PNG 무손실 확인

3순위 (S3): 브라우저 확장 + NativeHost → CoreWorker 전체 파이프라인
            핵심 체크포인트: save_jobs 진행률 폴링, IPC 토큰 인증 동작

4순위 (S4): PySide6 갤러리 + 포터블 빌드
            (이 시점에 MVP-A 완성, 실사용 테스트 가능)
```

### 15.2 주요 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|--------|--------|------|
| Pixiv preload_data 구조 변경 | 중 | 파싱 실패 → no_metadata_queue (`parse_error`) 자동 기록 |
| BMP PNG 변환 중 색상 프로파일 손실 | 낮 | Pillow `ImageCms`로 ICC 프로파일 보존 옵션 검토 |
| animated GIF 판별 오탐 | 낮 | `n_frames > 1` 추가 조건으로 보강 |
| SQLite 동시 접근 충돌 | 낮 | operation_locks 세분화 키 + busy_timeout=5000 |
| .thumbcache 디렉토리 고아 파일 | 중 | purge_orphan_thumbnails() 주기적 실행 (주 1회) |
| IPC 토큰 파일 잔류 (비정상 종료) | 중 | MainApp 시작 시 ipc_token 덮어쓰기 (항상 재생성) |
| 대용량 Inbox (10,000+) 재색인 느림 | 중 | 재색인 진행률 UI + 백그라운드 실행 (QThread) |
| X 어댑터 지연 (Post-MVP) | 확정 | 어댑터 패턴으로 기반 코드 변경 없이 추가 가능 |

### 15.3 config.json 기본 구조 (변경 없음)

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

### 15.4 기술 스택 최종 확정

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

### 15.5 최종 파일 구조

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
│   ├── format_converter.py      ← NEW: BMP→PNG, GIF→WebP
│   ├── ugoira_converter.py
│   ├── thumbnail_manager.py     ← NEW: hybrid path 썸네일 관리
│   ├── classifier.py            (MVP-B)
│   ├── tag_normalizer.py        (MVP-C)
│   └── worker.py
├── db/
│   ├── database.py
│   └── schema.sql               # 12개 테이블
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
└── .thumbcache/                 ← NEW: thumbnail_cache 실제 파일
    └── {prefix}/{file_id}.webp
```

---

*이 문서는 Aru Archive v2.3 최종 개발 착수용 설계안입니다.*  
*v2.2 대비 12개 항목이 수정·확정되었으며, 모든 세부 정책이 구현 착수 수준으로 확정되었습니다.*
