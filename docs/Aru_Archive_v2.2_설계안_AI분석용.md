# Aru Archive 최종 개발 착수용 설계안 v2.2

## 메타데이터

- **문서 버전**: 2.2 (최종 개발 착수용)
- **작성일**: 2026-04-26
- **기준 문서**: Aru Archive UX/구현 범위 재정리 설계안 v2.1
- **목적**: AI 코드 생성 및 분석 요청 시 참조 컨텍스트 (최종 확정판)
- **개발 언어**: Python 3.12 (백엔드/메인앱), JavaScript (브라우저 확장 MV3)
- **대상 플랫폼**: Windows 11, Chrome / Naver Whale

---

## 1. 개정 요약

### v2.1 → v2.2 변경 사항

| # | 항목 | v2.1 상태 | v2.2 결정 |
|---|------|-----------|-----------|
| 1 | classify_mode 기본값 | 미확정 | MVP-A 기본값 = `save_only` (분류 기능 MVP-B에서 활성화) |
| 2 | copy_records 보존 정책 | 옵션 검토 중 | **B-2 채택**: 만료 후 hash·mtime NULL, dest_file_size 보존 |
| 3 | 메타데이터 이중 저장 | AruArchive JSON만 | AruArchive JSON + XMP 표준 필드 병행 저장 |
| 4 | XMP 생성 도구 | 미결 | ExifTool 선택적 번들 (없으면 Python-only AruArchive JSON만) |
| 5 | 브라우저 지원 정책 | Chrome+Whale 동시 | Chrome **OR** Whale (≥1 필수); 양쪽 연결 시 기본 브라우저 선택 UI |
| 6 | 프로세스 구조 | 미결 | NativeHost → CoreWorker 서브프로세스 / MainApp HTTP IPC 분리 |
| 7 | SQLite 동시 접근 | 미결 | WAL + busy_timeout=5000 + operation_locks 테이블 |
| 8 | 메타데이터 동기화 추적 | 없음 | `artwork_groups.metadata_sync_status` 컬럼 추가 |
| 9 | 파일 상태 추적 | 없음 | `artwork_files.file_status` 컬럼 추가 (present/missing/moved) |
| 10 | 태그 별칭 정규화 | MVP-C 언급만 | `tag_aliases` 테이블 스키마 확정 (구현은 MVP-C) |
| 11 | 썸네일 캐시 | 미결 | `thumbnail_cache` 테이블 + 가상화 그리드 정책 확정 |
| 12 | No Metadata 큐 | MVP-A 기록만 | `no_metadata_queue` fail_reason enum 확정, MVP-A Sprint 1부터 기록 |

### 설계 핵심 원칙 (변경 없음)

| 원칙 | 설명 |
|------|------|
| 파일 우선 메타데이터 | 메타데이터 원본은 항상 파일 내부. DB는 검색 보조 인덱스 전용 |
| 복사 기반 분류 | 분류 시 원본을 이동하지 않고 복사. Inbox 파일은 항상 보존 |
| 2단계 저장 | Inbox 저장 → 메타데이터 임베딩 → (분류 폴더 복사) |
| 포터블 배포 | PyInstaller 단일 폴더 빌드, 설치 없이 실행 가능 |
| 확장 가능 구조 | Pixiv 우선 구현, X(트위터) 등 추후 어댑터 추가 방식 |

---

## 2. MVP 정책 최종 정리

### 2.1 MVP 단계별 범위

| 기능 | MVP-A | MVP-B | MVP-C |
|------|-------|-------|-------|
| 브라우저 확장 → Native Host 저장 | ✅ | ✅ | ✅ |
| Inbox 저장 + 메타데이터 임베딩 | ✅ | ✅ | ✅ |
| No Metadata Queue 기록 | ✅ | ✅ | ✅ |
| classify_mode = save_only | ✅ | - | - |
| PySide6 Inbox 뷰어 (기본 그리드) | ✅ | ✅ | ✅ |
| SQLite 보조 인덱스 | ✅ | ✅ | ✅ |
| 분류 규칙 엔진 (classify_mode = immediate/review) | ❌ | ✅ | ✅ |
| 분류 미리보기 UI | ❌ | ✅ | ✅ |
| Undo / 작업 로그 UI | ❌ | ✅ | ✅ |
| copy_records 보존 관리 | ❌ | ✅ | ✅ |
| thumbnail_cache 가상화 그리드 | ❌ | ✅ | ✅ |
| 태그 별칭 (tag_aliases) | ❌ | ❌ | ✅ |
| X(트위터) 어댑터 | ❌ | ❌ | ✅ |
| ExifTool XMP 생성 | ❌ | ✅ | ✅ |

### 2.2 classify_mode 정책

```
classify_mode: save_only   (MVP-A 기본, 분류 엔진 없음)
               immediate   (MVP-B, 저장 직후 자동 분류)
               review      (MVP-B, 분류 미리보기 후 사용자 확인)
```

- **MVP-A**: classify_mode는 config.json에 `"classify_mode": "save_only"` 고정
  - Classifier, copy_records, undo_entries 테이블은 생성하되 데이터 없음
- **MVP-B 활성화**: 설정 UI에서 immediate / review 선택 가능
- **classify_mode 변경 시**: 기존 inbox 파일에는 소급 적용 안 함 (변경 시점 이후 신규 저장분부터)

### 2.3 MVP-A 최소 완성 조건

1. 브라우저 확장에서 저장 버튼 → Inbox에 파일 저장 + 메타데이터 임베딩 완료
2. PySide6 갤러리 뷰에서 Inbox 파일 썸네일 표시 및 클릭 상세 보기
3. No Metadata 파일은 no_metadata_queue에 기록, UI에 카운터 표시
4. SQLite artworks DB 색인 완료
5. 포터블 exe 빌드 + install_host.bat 레지스트리 등록 동작

---

## 3. 메타데이터 저장 정책

### 3.1 이중 저장 구조

모든 파일에 두 가지 방식으로 메타데이터를 병행 저장한다.

```
┌─ AruArchive JSON (필수, MVP-A) ─────────────────────────────┐
│  · 완전한 스키마 (schema_version, provenance, ugoira 포함)    │
│  · 파일 형식별 저장 위치 (아래 표)                             │
└──────────────────────────────────────────────────────────────┘
┌─ XMP 표준 필드 (선택, MVP-B, ExifTool 필요) ─────────────────┐
│  · dc:title, dc:creator, dc:subject (tags), xmp:CreateDate   │
│  · AruArchive 전용 필드는 xmp:Label 또는 커스텀 NS 사용        │
│  · ExifTool 없으면 이 단계 skip (경고 로그만)                  │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 파일 형식별 저장 위치

| 파일 형식 | AruArchive JSON 저장 위치 | XMP 저장 위치 |
|-----------|--------------------------|--------------|
| JPEG | EXIF UserComment (`0x9286`, prefix `UNICODE\x00` + UTF-16LE) | EXIF XMP 세그먼트 (ExifTool) |
| PNG | iTXt chunk (keyword=`AruArchive`, text=JSON UTF-8) | iTXt chunk (keyword=`XML:com.adobe.xmp`) |
| WebP (변환본) | EXIF UserComment (JPEG와 동일 방식) | EXIF XMP 세그먼트 (ExifTool) |
| ZIP (우고이라 원본) | ZIP comment(식별자 256B) + `.aru.json` sidecar | 미적용 (sidecar only) |
| GIF | `.aru.json` sidecar | 미적용 |
| BMP | `.aru.json` sidecar | 미적용 |

> **sidecar 명명**: `{원본파일명}.aru.json`  
> **ZIP comment**: `aru:v1:{artwork_id}:{page_index}` (식별자 역할만)

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

### 3.4 XMP 표준 필드 매핑

| XMP 필드 | AruArchive 필드 | 비고 |
|----------|----------------|------|
| `dc:title` | `artwork_title` | |
| `dc:creator` | `artist_name` | |
| `dc:subject` | `tags` (배열) | |
| `dc:source` | `artwork_url` | |
| `xmp:CreateDate` | `downloaded_at` | |
| `xmp:Label` | `source_site` | |
| `Iptc4xmpExt:PersonInImage` | `character_tags` | |

### 3.5 ExifTool 통합 정책

- **번들 방식**: `exiftool.exe`를 PyInstaller 빌드 폴더에 포함 (optional)
- **실행 방식**: `subprocess.run(['exiftool', ...])` — 배치 플래그 활용
- **없을 때 동작**: AruArchive JSON만 저장, 경고 로그 기록, DB에 `metadata_sync_status='json_only'` 표시
- **있을 때 동작**: JSON 임베딩 후 ExifTool로 XMP 추가 → `metadata_sync_status='full'`
- **MVP-A**: ExifTool 없어도 정상 동작. MVP-B에서 ExifTool 번들 포함

### 3.6 메타데이터 재동기화

파일을 읽을 때 DB와 파일 내 메타데이터가 다르면:
1. 파일 내 메타데이터를 정본으로 취급
2. DB에 `metadata_sync_status='out_of_sync'` 표시
3. 메인앱 재색인(reindex) 실행 시 파일 → DB 방향으로 동기화

---

## 4. 데이터 모델 최종안

### 4.1 전체 테이블 목록

| 테이블 | 설명 | MVP |
|--------|------|-----|
| `artwork_groups` | 작품 단위 그룹 (다중 페이지 묶음) | A |
| `artwork_files` | 개별 파일 (원본/사이드카/분류복사본) | A |
| `tags` | 정규화 태그 인덱스 | A |
| `no_metadata_queue` | 메타데이터 없는 파일 보류 큐 | A |
| `undo_entries` | Undo 작업 로그 항목 | B |
| `copy_records` | Undo 항목별 개별 파일 복사 기록 | B |
| `classify_rules` | 분류 규칙 | B |
| `thumbnail_cache` | 썸네일 캐시 | B |
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
    metadata_sync_status  TEXT NOT NULL DEFAULT 'full',
                          -- full | json_only | out_of_sync | pending
    schema_version        TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(artwork_id, source_site)
);
```

**metadata_sync_status 값 정의**:

| 값 | 의미 |
|----|------|
| `full` | AruArchive JSON + XMP 모두 임베딩 완료 |
| `json_only` | AruArchive JSON만 임베딩 (ExifTool 없음) |
| `out_of_sync` | DB와 파일 메타데이터 불일치 감지 |
| `pending` | 임베딩 작업 진행 중 |

### 4.3 artwork_files 테이블

```sql
CREATE TABLE artwork_files (
    file_id               TEXT PRIMARY KEY,          -- UUID v4
    group_id              TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    page_index            INTEGER NOT NULL DEFAULT 0,
    file_role             TEXT NOT NULL,
                          -- original | managed | sidecar | classified_copy
    file_path             TEXT NOT NULL UNIQUE,      -- 절대 경로
    file_format           TEXT NOT NULL,             -- jpg | png | webp | zip | gif | bmp | json
    file_hash             TEXT,                      -- SHA-256
    file_size             INTEGER,                   -- bytes
    metadata_embedded     INTEGER NOT NULL DEFAULT 0, -- 0 | 1
    file_status           TEXT NOT NULL DEFAULT 'present',
                          -- present | missing | moved | orphan
    created_at            TEXT NOT NULL,
    modified_at           TEXT,
    last_seen_at          TEXT,                      -- 헬스체크 마지막 확인 시각
    source_file_id        TEXT REFERENCES artwork_files(file_id),
                          -- classified_copy인 경우 원본 file_id
    classify_rule_id      TEXT,                      -- 적용된 규칙 ID
    provenance_json       TEXT                       -- _provenance 블록 JSON
);
```

**file_status 값 정의**:

| 값 | 의미 | 대응 |
|----|------|------|
| `present` | 경로에 파일 존재 확인 | 정상 |
| `missing` | 마지막 확인 시 파일 없음 | UI에 경고 배지 |
| `moved` | 다른 경로로 이동된 것으로 추정 | 재연결 UI 제공 |
| `orphan` | DB에 있으나 Inbox 밖 경로, 분류 기록도 없음 | 재색인 후 정리 |

**file_role 값 정의**:

| 값 | 의미 |
|----|------|
| `original` | Inbox에 저장된 최초 다운로드 파일 |
| `managed` | 변환된 관리 파일 (ugoira → WebP 변환본) |
| `sidecar` | `.aru.json` 사이드카 파일 |
| `classified_copy` | Classified 폴더로 복사된 파일 |

### 4.4 tags 테이블

```sql
CREATE TABLE tags (
    artwork_id  TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    tag_type    TEXT NOT NULL DEFAULT 'general',
                -- general | character | series
    canonical   TEXT,                               -- tag_aliases 정규화 후 값 (MVP-C)
    PRIMARY KEY (artwork_id, tag, tag_type)
);
CREATE INDEX idx_tags_tag ON tags(tag);
CREATE INDEX idx_tags_canonical ON tags(canonical);
```

### 4.5 no_metadata_queue 테이블

```sql
CREATE TABLE no_metadata_queue (
    queue_id      TEXT PRIMARY KEY,                 -- UUID v4
    file_path     TEXT NOT NULL,
    source_site   TEXT,
    detected_at   TEXT NOT NULL,
    fail_reason   TEXT NOT NULL,
                  -- no_dom_data | parse_error | network_error |
                  --  unsupported_format | manual_add
    raw_context   TEXT,                             -- 오류 당시 부분 데이터 JSON
    resolved      INTEGER NOT NULL DEFAULT 0,       -- 0 | 1
    resolved_at   TEXT,
    notes         TEXT
);
```

**fail_reason enum**:

| 값 | 발생 시점 |
|----|-----------|
| `no_dom_data` | content_script가 preload_data를 찾지 못함 |
| `parse_error` | 메타데이터 파싱 중 예외 발생 |
| `network_error` | 다운로드 실패 (httpx 오류) |
| `unsupported_format` | 지원하지 않는 파일 형식 |
| `manual_add` | 사용자가 수동으로 큐에 추가 |

### 4.6 undo_entries 테이블

```sql
CREATE TABLE undo_entries (
    entry_id        TEXT PRIMARY KEY,               -- UUID v4
    operation_type  TEXT NOT NULL,                  -- 'classify'
    performed_at    TEXT NOT NULL,
    undo_expires_at TEXT NOT NULL,                  -- performed_at + 보존 기간
    undone_at       TEXT,
    description     TEXT
);
```

### 4.7 copy_records 테이블 (B-2 정책 반영)

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
    dest_mtime_at_copy   TEXT,                       -- 만료 후 NULL로 업데이트
    dest_hash_at_copy    TEXT,                       -- 만료 후 NULL로 업데이트
    manually_modified    INTEGER DEFAULT 0,
    copied_at            TEXT NOT NULL
);
```

**B-2 만료 처리 로직**:

```python
# undo_expires_at 경과 시 실행 (백그라운드 주기 작업)
db.execute("""
    UPDATE copy_records
    SET dest_mtime_at_copy = NULL,
        dest_hash_at_copy = NULL
    WHERE entry_id IN (
        SELECT entry_id FROM undo_entries
        WHERE undo_expires_at < datetime('now')
          AND undone_at IS NULL
    )
""")
```

- `dest_file_size`: 만료 후에도 보존 → Recent Jobs 패널 파일 크기 표시에 사용
- `dest_mtime_at_copy`, `dest_hash_at_copy`: 만료 후 NULL → Undo 안전성 체크 불가 → Undo 버튼 비활성화

### 4.8 classify_rules 테이블

```sql
CREATE TABLE classify_rules (
    rule_id       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    priority      INTEGER NOT NULL DEFAULT 100,
    conditions_json TEXT NOT NULL,                  -- Condition[] JSON
    logic         TEXT NOT NULL DEFAULT 'AND',      -- AND | OR
    dest_template TEXT NOT NULL,
    on_conflict   TEXT NOT NULL DEFAULT 'skip',     -- skip | overwrite | rename
    created_at    TEXT NOT NULL,
    updated_at    TEXT
);
```

### 4.9 thumbnail_cache 테이블

```sql
CREATE TABLE thumbnail_cache (
    file_id       TEXT PRIMARY KEY REFERENCES artwork_files(file_id) ON DELETE CASCADE,
    thumb_data    BLOB NOT NULL,                    -- WebP 바이너리 (128x128 또는 256x256)
    thumb_size    TEXT NOT NULL DEFAULT '256x256',
    source_hash   TEXT NOT NULL,                    -- 원본 file_hash (갱신 판단용)
    created_at    TEXT NOT NULL
);
```

### 4.10 tag_aliases 테이블 (MVP-C)

```sql
CREATE TABLE tag_aliases (
    alias         TEXT PRIMARY KEY,                 -- 별칭 태그 (소문자 정규화)
    canonical     TEXT NOT NULL,                    -- 정규 태그
    source_site   TEXT DEFAULT NULL,               -- NULL = 전 사이트 공통
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_tag_aliases_canonical ON tag_aliases(canonical);
```

### 4.11 operation_locks 테이블

```sql
CREATE TABLE operation_locks (
    lock_name     TEXT PRIMARY KEY,
    locked_by     TEXT NOT NULL,                    -- 'native_host' | 'main_app' | 'reindex'
    locked_at     TEXT NOT NULL,
    expires_at    TEXT NOT NULL                     -- locked_at + 타임아웃 (보통 30초)
);
```

---

## 5. Undo / copy_records 보존 정책

### 5.1 B-2 정책 요약

- **채택 이유**: Undo 안전성(hash 체크)과 저장 공간 절약을 균형 있게 달성
- **보존 기간**: config.json의 `undo_retention_days` (기본값: 7일)
- **만료 시 처리**: `dest_hash_at_copy`, `dest_mtime_at_copy` → NULL (UPDATE)
- **보존 항목**: `dest_file_size` — Recent Jobs 패널에서 복사 크기 정보 표시에 필요
- **만료 후 Undo 버튼**: 비활성화 + "보존 기간 만료 (7일)" 툴팁 표시

### 5.2 Undo 실행 흐름

```
사용자: Undo 버튼 클릭
  │
  ▼ [안전성 체크 — 3-field]
  for each copy_record:
      current_size  = os.path.getsize(dest_path)
      current_mtime = os.path.getmtime(dest_path)
      ① dest_file_size == current_size?
      ② dest_mtime_at_copy == current_mtime?  (NULL이면 체크 불가 → 만료 상태)
      ③ dest_hash_at_copy == sha256(dest_path)?  (NULL이면 체크 불가)
  
  모두 통과 → 삭제 진행
  불일치 감지 → "파일이 수정된 것으로 보입니다. 그래도 삭제하시겠습니까?" 확인 다이얼로그
  NULL (만료) → Undo 비활성 (버튼 자체 disabled)
```

### 5.3 Undo 만료 정리 스케줄

- 메인앱 시작 시 1회 실행
- 이후 24시간마다 백그라운드 실행 (QTimer)
- 정리 대상: `undo_expires_at < now()` AND `undone_at IS NULL`

---

## 6. 브라우저 연결 정책

### 6.1 지원 브라우저

| 브라우저 | 지원 여부 | 비고 |
|---------|----------|------|
| Google Chrome (Stable) | ✅ 필수 지원 | HKCU NativeMessaging 등록 |
| Naver Whale | ✅ 필수 지원 | HKCU NativeMessaging 등록 |
| Chrome Beta/Dev/Canary | ❌ 미지원 | 레지스트리 경로 상이 |
| Edge | ❌ 미지원 | 향후 검토 |

### 6.2 동시 연결 정책

- **Chrome OR Whale 중 ≥1 연결 필수**: 둘 다 없으면 메인앱 초기화 경고
- **양쪽 동시 연결 시**: 첫 실행 시 "기본 브라우저 선택" UI 표시 (이후 config.json 저장)
- **각 브라우저 독립 등록**: `install_host.bat` 실행 시 Chrome + Whale 레지스트리 동시 등록

### 6.3 레지스트리 등록 경로

```
Chrome:
HKCU\Software\Google\Chrome\NativeMessagingHosts\net.aru_archive.host
  → {install_dir}\native_host\manifest_chrome.json

Whale:
HKCU\Software\Naver\Whale\NativeMessagingHosts\net.aru_archive.host
  → {install_dir}\native_host\manifest_whale.json
```

### 6.4 확장 프로그램 배포 정책

- **Chrome**: Chrome Web Store (심사 필요) 또는 개발자 모드 로드 (MVP-A)
- **Whale**: Whale Store 또는 개발자 모드 로드 (MVP-A)
- **Extension ID**: 브라우저별로 다름 → manifest.json의 `externally_connectable` 미사용, Native Messaging으로만 통신

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
        ├──── MainApp 실행 중? ──── YES ──▶ HTTP POST localhost:18456
        │                                    MainApp이 CoreWorker 작업 큐에 추가
        │
        └──── MainApp 없음? ──────── NO ──▶ CoreWorker 서브프로세스 직접 spawn
                                            완료 후 결과를 Extension에 반환

[Core Worker]                    core/worker.py
  · 실제 파일 다운로드 (httpx)
  · 메타데이터 임베딩
  · SQLite 업데이트
  · (MVP-B) Classifier 실행

[Main App]                       app/main_window.py (PySide6)
  · HTTP 서버 localhost:18456 (QThread)
  · UI 갱신 (갤러리, 진행률)
  · 설정, 규칙 편집
```

### 7.2 IPC 프로토콜 (NativeHost ↔ MainApp)

**Base URL**: `http://127.0.0.1:18456/api`

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/api/ping` | GET | MainApp 실행 여부 확인 |
| `/api/jobs` | POST | 저장 작업 큐에 추가 |
| `/api/jobs/{job_id}` | GET | 작업 상태 폴링 |
| `/api/notify` | POST | MainApp UI 갱신 알림 |

### 7.3 CoreWorker 서브프로세스 모드

NativeHost가 MainApp 없이 단독 실행 시:

```python
# native_host/host.py
import subprocess

def spawn_core_worker(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, '-m', 'core.worker', '--json-stdin'],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=120
    )
    return json.loads(proc.stdout)
```

### 7.4 MainApp HTTP 서버 (QThread)

```python
# app/http_server.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

class AppHttpServer(threading.Thread):
    PORT = 18456
    
    def run(self):
        server = HTTPServer(('127.0.0.1', self.PORT), RequestHandler)
        server.serve_forever()
```

- MainApp 종료 시 서버도 함께 종료
- 포트 충돌 시: 18457, 18458 순차 시도 후 config.json에 실제 포트 기록

---

## 8. SQLite 동시 접근 정책

### 8.1 기본 설정

```python
# db/database.py
import sqlite3

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5.0)  # busy_timeout=5000ms
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn
```

### 8.2 접근 패턴 정책

| 접근자 | 읽기 | 쓰기 | 비고 |
|--------|------|------|------|
| NativeHost / CoreWorker | ✅ | ✅ | 저장 작업 시 쓰기 |
| MainApp (UI Thread) | ✅ | ❌ | UI는 읽기 전용 |
| MainApp (Worker Thread) | ✅ | ✅ | 재색인, Undo 실행 시 |
| Reindex Job | ✅ | ✅ | 단독 실행 |

### 8.3 operation_locks 사용

```python
# 쓰기 작업 전 잠금 획득
def acquire_lock(conn, lock_name: str, locked_by: str, timeout_sec: int = 30) -> bool:
    expires_at = (datetime.now() + timedelta(seconds=timeout_sec)).isoformat()
    try:
        conn.execute("""
            INSERT INTO operation_locks (lock_name, locked_by, locked_at, expires_at)
            VALUES (?, ?, datetime('now'), ?)
        """, (lock_name, locked_by, expires_at))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # 이미 잠금 있음 — 만료 여부 확인
        row = conn.execute(
            "SELECT expires_at FROM operation_locks WHERE lock_name=?", (lock_name,)
        ).fetchone()
        if row and row['expires_at'] < datetime.now().isoformat():
            # 만료된 잠금 강제 해제
            conn.execute("DELETE FROM operation_locks WHERE lock_name=?", (lock_name,))
            conn.commit()
            return acquire_lock(conn, lock_name, locked_by, timeout_sec)
        return False

def release_lock(conn, lock_name: str):
    conn.execute("DELETE FROM operation_locks WHERE lock_name=?", (lock_name,))
    conn.commit()
```

### 8.4 WAL 체크포인트 정책

- 자동 체크포인트 (SQLite 기본값 1000페이지) 유지
- MainApp 종료 시 `PRAGMA wal_checkpoint(TRUNCATE)` 실행

---

## 9. 파일 경로 변경 / Missing 파일 대응

### 9.1 file_status 갱신 정책

| 트리거 | 동작 |
|--------|------|
| 갤러리 뷰 파일 로드 | 해당 파일 `file_status` 확인 → missing이면 배지 표시 |
| 재색인(reindex) 실행 | 전체 artwork_files 경로 존재 여부 순차 확인 후 갱신 |
| 메인앱 시작 | Inbox 폴더 quick scan (파일명만 비교, hash 없이) |

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

### 9.3 Inbox 파일 이동 감지

- Inbox 폴더는 사용자가 임의로 수정하지 않는 것을 권장 (first-run wizard에서 안내)
- Inbox 경로 변경(설정에서)이 감지되면: 전체 재색인 트리거
- `last_seen_at` 컬럼으로 마지막 확인 시각 기록 → 오래된 파일 우선 재확인

---

## 10. 태그 정규화 / 별칭 (tag_aliases)

### 10.1 정책 (MVP-C 구현, 스키마는 MVP-A 생성)

- **목적**: Pixiv 다국어 태그 (일본어/영어/중국어) 및 오탈자를 단일 정규 태그로 통합
- **방향**: 별칭(alias) → 정규(canonical) 단방향 매핑
- **적용 시점**: 파일 저장 시가 아닌 검색/필터 시 동적 적용 (원본 태그는 보존)

### 10.2 tag_aliases 운용

```python
# core/tag_normalizer.py (MVP-C)

def get_canonical(tag: str, site: str = None) -> str:
    """alias → canonical 변환. alias 없으면 원본 반환."""
    tag_lower = tag.lower().strip()
    row = db.execute(
        "SELECT canonical FROM tag_aliases WHERE alias=? AND (source_site=? OR source_site IS NULL)",
        (tag_lower, site)
    ).fetchone()
    return row['canonical'] if row else tag
```

### 10.3 초기 alias 데이터

MVP-C 출시 시 번들 포함 예정 (별도 `tag_aliases_default.json`):
```json
[
  {"alias": "オリジナル",     "canonical": "original",      "source_site": "pixiv"},
  {"alias": "original",      "canonical": "original",      "source_site": null},
  {"alias": "r-18",          "canonical": "R-18",          "source_site": "pixiv"},
  {"alias": "女の子",         "canonical": "girl",          "source_site": "pixiv"}
]
```

---

## 11. 썸네일 캐시 / 성능

### 11.1 썸네일 생성 정책

| 항목 | 값 |
|------|-----|
| 크기 | 256×256 px (표준), 128×128 (소형 그리드) |
| 형식 | WebP (품질 85) |
| 저장 위치 | SQLite `thumbnail_cache.thumb_data` BLOB |
| 갱신 조건 | `source_hash != artwork_files.file_hash` |
| 생성 시점 | 파일 저장 완료 직후 (CoreWorker 내) |

### 11.2 가상화 그리드 정책

- **적용 기준**: 표시 항목 500개 초과 시 QListView 가상화 모드 활성화
- **구현**: `QAbstractItemModel` + `QListView.setUniformItemSizes(True)`
- **썸네일 로드**: 뷰포트 내 카드만 thumb_data 요청 (lazy load)
- **스크롤 성능 목표**: 10,000개 항목에서 60fps 스크롤

### 11.3 썸네일 캐시 무효화

```python
# 파일 hash 변경 감지 시
def invalidate_thumbnail(file_id: str):
    db.execute("DELETE FROM thumbnail_cache WHERE file_id=?", (file_id,))
    db.commit()
    # 다음 뷰포트 진입 시 재생성
```

### 11.4 썸네일 없는 경우 플레이스홀더

| 상황 | 플레이스홀더 |
|------|------------|
| 생성 중 | 회전 스피너 오버레이 |
| ZIP/ugoira (WebP 없음) | 필름 아이콘 |
| file_status=missing | `?` 아이콘 + 흐린 처리 |
| GIF/BMP (사이드카 only) | 파일 형식 아이콘 |

---

## 12. No Metadata 큐 정책

### 12.1 기록 시점 (MVP-A Sprint 1부터)

- NativeHost가 메타데이터 없는 저장 요청을 받는 모든 경우
- content_script가 DOM 파싱에 실패한 경우 (partial data와 함께 큐에 기록)
- 파일 다운로드 성공했으나 메타데이터 임베딩 실패한 경우

### 12.2 큐 처리 흐름

```
[Extension] content_script 파싱 실패
  │
  ▼ {action: 'save_no_metadata', file_url, fail_reason, partial_data}
  │
[NativeHost] → 파일 다운로드 (메타데이터 없이)
  │           → Inbox에 파일 저장
  │           → no_metadata_queue INSERT
  │
[MainApp] UI 상단 배너: "메타데이터 없는 파일 3개"
  → No Metadata 패널 열기
  → 각 항목: 썸네일, 파일명, fail_reason, "수동 입력" / "무시" 버튼
```

### 12.3 fail_reason별 UI 안내 메시지

| fail_reason | 표시 메시지 | 권장 액션 |
|-------------|-----------|----------|
| `no_dom_data` | "페이지 데이터를 찾을 수 없습니다" | 페이지 새로고침 후 재시도 |
| `parse_error` | "데이터 파싱 오류" | 개발자에게 신고 |
| `network_error` | "네트워크 오류로 일부 정보 누락" | 재다운로드 시도 |
| `unsupported_format` | "지원하지 않는 파일 형식" | 수동 메타데이터 입력 |
| `manual_add` | "수동 추가된 파일" | 메타데이터 직접 입력 |

### 12.4 수동 메타데이터 입력 UI (MVP-B)

- No Metadata 패널에서 항목 클릭 → 메타데이터 입력 다이얼로그
- 필수 필드: artwork_url (Pixiv URL 붙여넣기로 자동 파싱 시도)
- 선택 필드: artist_name, tags, custom_notes
- 저장 시: 파일에 메타데이터 임베딩 + no_metadata_queue.resolved = 1

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
  ▼ [background/service_worker.js → Native Messaging]
  5. {action: 'save_artwork' | 'save_no_metadata', metadata, pages: [...]} 전송
  │
  ▼ [NativeHost → CoreWorker]
  6. save_no_metadata → no_metadata_queue INSERT, 파일만 저장 후 종료
  7. save_artwork → CoreWorker 실행
  │
  ▼ [CoreWorker]
  8.  artwork_groups INSERT (group_id = UUID)
  9.  operation_locks 획득 (lock_name='write_{group_id}')
  10. 각 페이지:
      a. PixivAdapter.get_http_headers() → Referer 포함
      b. httpx.get(page_url) → bytes
      c. Inbox/{source_site}/{filename} 저장
      d. artwork_files INSERT (file_role='original', file_status='present')
      e. 메타데이터 임베딩:
           JPEG/WebP → piexif EXIF UserComment (AruArchive JSON)
           PNG → iTXt chunk (AruArchive JSON)
           ZIP → ZIP comment + .aru.json sidecar
           GIF/BMP → .aru.json sidecar
      f. (ExifTool 있음) XMP 표준 필드 추가
      g. metadata_sync_status 업데이트
      h. thumbnail_cache 생성
  11. (우고이라) animated WebP 변환:
      a. PIL.Image 프레임 로드
      b. save(format='WEBP', save_all=True, duration=delays, loop=0)
      c. WebP에 piexif EXIF UserComment 삽입
      d. artwork_files INSERT (file_role='managed', file_format='webp')
  12. classify_mode == 'save_only' → 분류 skip
  13. tags INSERT
  14. operation_locks 해제
  15. MainApp HTTP 알림 (실행 중인 경우)
  16. 완료 응답 → Extension
```

### 13.2 분류 플로우 (MVP-B, classify_mode=immediate)

```
[CoreWorker] (저장 완료 후 이어서)
  1. Classifier.evaluate(group) → 매칭 규칙 목록
  2. 규칙 없음 → status='inbox' 유지, 종료
  3. 규칙 있음:
     a. undo_entries INSERT (operation_type='classify', expires_at = now+7d)
     b. for each (file, rule):
          dest_path = render_template(rule.dest_template, metadata)
          shutil.copy2(src_path, dest_path)
          file_hash = sha256(dest_path)
          copy_records INSERT (dest_file_size, dest_mtime_at_copy, dest_hash_at_copy)
          artwork_files INSERT (file_role='classified_copy', source_file_id=original.file_id)
     c. artwork_groups UPDATE status='classified'
  4. MainApp HTTP 알림
```

### 13.3 Undo 플로우 (MVP-B)

```
[MainApp UI] 작업 로그 패널 → Undo 버튼 클릭
  │
  ▼ [MainApp WorkerThread]
  1. copy_records 조회 (entry_id 기준)
  2. undo_expires_at < now → 버튼 비활성 (이 경로 도달 불가)
  3. 각 copy_record:
     a. dest_mtime_at_copy IS NULL → 안전성 체크 불가 → 이미 비활성 (방어 코드)
     b. 3-field 체크:
          current_size == dest_file_size?
          current_mtime == dest_mtime_at_copy?
          sha256(dest) == dest_hash_at_copy?
     c. 불일치 → 확인 다이얼로그
     d. 통과 → os.remove(dest_path)
     e. artwork_files UPDATE file_status='missing' (classified_copy)
  4. undo_entries UPDATE undone_at = now()
  5. artwork_groups UPDATE status='inbox'
  6. UI 갱신
```

### 13.4 재색인 플로우

```
[MainApp] 재색인 메뉴 선택
  │
  ▼ [MainApp WorkerThread]
  1. operation_locks 획득 (lock_name='reindex')
  2. Inbox 폴더 전체 순회
  3. 각 파일:
     a. 파일 읽기 → AruArchive JSON 추출
     b. artwork_groups UPSERT (artwork_id+source_site 기준)
     c. artwork_files UPSERT
     d. tags 재구성
     e. thumbnail_cache 갱신 (hash 변경 시)
  4. artwork_files 중 파일이 없는 항목 → file_status='missing'
  5. operation_locks 해제
  6. metadata_sync_status 갱신
```

### 13.5 No Metadata 수동 처리 플로우 (MVP-B)

```
[MainApp UI] No Metadata 패널 → 항목 클릭
  │
  ▼ 메타데이터 입력 다이얼로그
  1. artwork_url 입력 → PixivAdapter.fetch_by_url() 시도
  2. 자동 파싱 성공 → 필드 자동 채움
  3. 자동 파싱 실패 → 수동 입력
  4. 저장 클릭:
     a. metadata_writer.write(file_path, metadata)
     b. artwork_groups INSERT or UPDATE
     c. no_metadata_queue UPDATE resolved=1
  5. 갤러리 뷰 갱신
```

---

## 14. Sprint 반영 사항

### Sprint 계획 (MVP-A: Sprint 1~4, MVP-B: Sprint 5~8, MVP-C: Sprint 9)

| Sprint | 목표 | 핵심 산출물 | MVP |
|--------|------|-----------|-----|
| S1 | DB 스키마 + 메타데이터 읽기/쓰기 | `db/database.py`, `core/metadata_writer.py`, `core/metadata_reader.py` | A |
| S2 | 우고이라 변환 + Native Host 기반 | `core/ugoira_converter.py`, `native_host/host.py` | A |
| S3 | 브라우저 확장 + Pixiv 어댑터 | `extension/`, `core/adapters/pixiv.py` | A |
| S4 | PySide6 기본 앱 + 포터블 빌드 | `app/`, `build/`, `install_host.bat` | A |
| S5 | 분류 엔진 + Undo 기반 | `core/classifier.py`, Undo DB 로직 | B |
| S6 | 분류 미리보기 UI + 작업 로그 | `app/views/classify_preview.py`, `app/views/work_log.py` | B |
| S7 | 썸네일 캐시 + 가상화 그리드 | `thumbnail_cache` 테이블, 가상화 QListView | B |
| S8 | ExifTool 통합 + No Metadata 수동 처리 | ExifTool subprocess wrapper, No Metadata UI | B |
| S9 | 태그 별칭 + X 어댑터 + 패키징 최종화 | `tag_aliases`, `core/adapters/x.py`, installer | C |

### Sprint 1 필수 구현 항목 (v2.2 기준 변경)

- [x] 전체 SQLite 스키마 생성 (10개 테이블)
- [x] `no_metadata_queue` 포함 (MVP-A from Sprint 1)
- [x] `operation_locks` 포함
- [x] `artwork_groups.metadata_sync_status` 컬럼 포함
- [x] `artwork_files.file_status` 컬럼 포함
- [x] `thumbnail_cache`, `tag_aliases` 테이블 생성 (데이터는 이후 Sprint)

### Sprint 4 필수 구현 항목

- [ ] install_host.bat: Chrome + Whale 레지스트리 동시 등록
- [ ] config.json: `classify_mode: "save_only"` 기본값
- [ ] config.json: `undo_retention_days: 7` 기본값
- [ ] config.json: `exiftool_path: null` (자동 탐지)
- [ ] First-run wizard: 브라우저 선택 화면 포함 (Chrome/Whale/양쪽)
- [ ] MainApp HTTP 서버 (포트 18456)

---

## 15. 최종 권장안

### 15.1 개발 착수 순서 권장

```
1순위 (Sprint 1): DB 스키마 확정 → metadata_writer + metadata_reader 단위 테스트
2순위 (Sprint 2): ugoira_converter → JPEG/PNG/WebP/ZIP 메타데이터 임베딩 검증
3순위 (Sprint 3): 브라우저 확장 기본 동작 → NativeHost → CoreWorker 파이프라인
4순위 (Sprint 4): PySide6 갤러리 뷰 + 포터블 빌드
(이 시점에 MVP-A 기능 완성, 실사용 테스트 가능)
```

### 15.2 주요 리스크 및 대응

| 리스크 | 가능성 | 대응 |
|--------|--------|------|
| Pixiv preload_data JSON 구조 변경 | 중 | 파싱 실패 → no_metadata_queue 자동 기록, 어댑터 업데이트로 대응 |
| ExifTool 번들 크기 (약 5MB) | 낮 | MVP-B에서 선택적 포함, 없어도 동작 보장 |
| SQLite WAL 동시 쓰기 충돌 | 낮 | operation_locks + busy_timeout=5000 으로 충분 |
| Windows 방화벽 localhost:18456 차단 | 낮 | loopback은 방화벽 예외. 차단 시 named pipe fallback 검토 |
| 대용량 Inbox (10,000+) UI 렉 | 중 | thumbnail_cache + 가상화 그리드 (Sprint 7에서 해결) |

### 15.3 파일 구조 (최종)

```
aru_archive/
├── extension/
│   ├── manifest.json
│   ├── content_scripts/
│   │   └── pixiv.js
│   ├── background/
│   │   └── service_worker.js
│   └── popup/
│       ├── popup.html
│       └── popup.js
├── native_host/
│   ├── host.py                  # stdin/stdout 메시지 루프
│   ├── handlers.py              # 액션 라우팅
│   ├── manifest_chrome.json     # Chrome NM 매니페스트
│   └── manifest_whale.json      # Whale NM 매니페스트
├── core/
│   ├── adapters/
│   │   ├── __init__.py          # _ADAPTERS 등록
│   │   ├── base.py              # SourceSiteAdapter ABC
│   │   └── pixiv.py             # PixivAdapter
│   ├── metadata_writer.py       # 파일별 메타데이터 임베딩
│   ├── metadata_reader.py       # 파일별 메타데이터 추출
│   ├── ugoira_converter.py      # ZIP → animated WebP
│   ├── classifier.py            # 규칙 기반 분류 엔진 (MVP-B)
│   ├── tag_normalizer.py        # tag_aliases 정규화 (MVP-C)
│   └── worker.py                # CoreWorker 진입점
├── db/
│   ├── database.py              # SQLite CRUD 래퍼
│   └── schema.sql               # 전체 스키마 SQL
├── app/
│   ├── main_window.py
│   ├── http_server.py           # localhost:18456
│   ├── views/
│   │   ├── gallery_view.py      # 썸네일 그리드 (가상화)
│   │   ├── detail_view.py       # 이미지 + 메타데이터 패널
│   │   ├── rules_view.py        # 분류 규칙 편집 UI (MVP-B)
│   │   ├── work_log_view.py     # 작업 로그 + Undo UI (MVP-B)
│   │   └── no_metadata_view.py  # No Metadata 큐 패널
│   └── widgets/
│       ├── ugoira_player.py     # 프레임 단위 우고이라 재생
│       └── provenance_badge.py  # 출처 신뢰도 배지
├── build/
│   ├── install_host.bat         # 레지스트리 등록 (Chrome + Whale)
│   ├── uninstall_host.bat
│   └── aru_archive.spec         # PyInstaller 스펙
├── config.json                  # 사용자 설정 (런타임 생성)
└── aru_archive.db               # SQLite DB (런타임 생성)
```

### 15.4 config.json 기본 구조

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

### 15.5 기술 스택 최종 확정

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

---

*이 문서는 Aru Archive v2.2 최종 개발 착수용 설계안입니다.*  
*v2.1 대비 11개 항목이 확정 결정되었으며, MVP-A 착수에 필요한 모든 사항이 포함되어 있습니다.*
