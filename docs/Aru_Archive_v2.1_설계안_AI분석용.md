# Aru Archive UX/구현 범위 재정리 설계안 v2.1 (AI 분석용)

## 메타데이터

- **문서 버전**: v2.1 (MVP 재분리 + 데이터 모델 재설계)
- **기준 문서**: Aru_Archive_UX설계안_AI분석용.md v2.0
- **작성일**: 2026-04-26
- **목적**: v2.0의 방향성 유지, 범위 줄이기 + 데이터 모델 명확화 + 초기 개발 가능성 강화

---

## 1. 개정 요약

### 1.1 v2.0에서 유지할 점

| 항목 | 이유 |
|------|------|
| 저장 진행 상태 표시 (브라우저 팝업) | 1초 이내 피드백 필수 |
| 다중 페이지 저장 진행률 | 부분 실패 인지의 핵심 |
| 분류 미리보기 (검토 후 분류 모드) | 잘못된 복사본 대량 생성 방지 |
| 복사 기반 예상 용량 표시 | 디스크 초과 충격 방지 |
| 작업 로그 / Recent Jobs | Undo의 기반 데이터 |
| Undo — 복사본 제거 | 복사 기반 분류의 필수 안전장치 |
| No Metadata 큐 | 누락 파일 방치 방지 |
| 분류 근거 보기 | 분류 결과 신뢰도의 핵심 |
| 초보자/고급 규칙 편집 | 진입 장벽 낮추기 |
| BMP/우고이라 작품 카드 단위 UX | 갤러리 혼란 방지 |
| Metadata Provenance | 파일 자립성 보장 |
| 첫 실행 설정 흐름 | Native Host 연결 실패율 감소 |

### 1.2 v2.0에서 수정할 점

| 항목 | 수정 내용 |
|------|-----------|
| MVP 범위 | 1차 MVP 10개 → MVP-A/B/C 3단계로 분리 |
| 첫 실행 마법사 | 10단계 → 5단계 경량화, MVP-C로 이동 |
| 데이터 모델 | artworks 확장 → artwork_groups + artwork_files 분리 |
| Undo 안전성 | 수정 감지 필드 3개 추가 (size + mtime + hash) |
| 로그 보존 정책 | Undo 기간 / 로그 보존 기간 명확히 분리 |
| 분류 미리보기 저장 | MVP-A/B: 메모리 기반, MVP-C: DB 저장 |
| Provenance raw_value | 파일 내부에서 제외, DB에만 저장 |
| 브라우저 팝업 역할 | 복잡한 UX 제거, 리모컨 역할로 축소 |
| classify_log | undo_entries + copy_records로 통합 (안 A 채택) |
| 개발 순서 | 최소 설정을 Sprint 0에 포함 |

### 1.3 v2.1의 핵심 목표

```
1. 개발 착수 가능한 수준으로 범위 줄이기
2. artwork_groups / artwork_files 로 파일 역할 명확화
3. Undo 안전성 강화 (수정 파일 감지)
4. Undo 기간과 로그 보존 기간 분리
5. 장기 확장성을 해치지 않는 최소 MVP 구조 확정
```

---

## 2. MVP 단계 재분리

### 2.1 MVP-A: 코어 검증 (Sprint 0~3, 약 8주)

**목표**: Pixiv 이미지를 저장하고 메타데이터를 기록하고 기본 분류까지 동작함을 검증.

**포함 기능:**

| 기능 | 설명 |
|------|------|
| 파일 저장 | Pixiv 단일/다중 페이지, 우고이라 |
| 메타데이터 읽기/쓰기 | JPEG/PNG/ZIP/WebP 형식 |
| 즉시 분류 | 기본 프리셋 규칙 (작가/시리즈/캐릭터) |
| 브라우저 팝업 진행률 | 저장 상태 표시 + 완료/실패 요약 |
| 저장 완료 후 폴더 열기 | "Inbox 열기", "분류 폴더 열기" |
| 최소 설정 화면 | Archive Root, 브라우저 연결 테스트 |
| save_jobs + job_pages 기록 | 기반 로그 (Undo는 아직 미구현) |
| PySide6 기본 갤러리 | 썸네일 그리드 + 기본 상세 패널 |

**제외 기능:**
- 분류 미리보기 (검토 후 분류 모드)
- Undo
- No Metadata 큐 화면 (DB 기록만)
- 분류 근거 보기
- 충돌 처리 다이얼로그 (설정값 자동 적용)
- 첫 실행 마법사 완성형
- Provenance 배지 UI

**완료 기준:**
```
✓ 브라우저에서 Pixiv 이미지 저장 → Inbox 파일 생성 + EXIF 메타데이터 삽입
✓ Classified 폴더에 규칙 기반 복사본 생성
✓ 갤러리에서 저장된 이미지 확인 가능
✓ 브라우저 팝업에서 진행률 확인 가능
```

---

### 2.2 MVP-B: 안전한 사용성 (Sprint 4~6, 약 6주)

**목표**: 실수를 되돌릴 수 있고, 분류 결과를 이해할 수 있다.

**포함 기능:**

| 기능 | 설명 |
|------|------|
| 분류 미리보기 | 메모리 기반, 검토 후 분류 모드 |
| 충돌 처리 다이얼로그 | 파일별 skip/overwrite/rename 선택 |
| undo_entries + copy_records | 분류 작업 로그 DB 기록 |
| Undo — 복사본 제거 | 파일 수정 감지 포함 |
| Recent Jobs 화면 | 작업 목록 + 복사본 제거 버튼 |
| No Metadata 큐 화면 | 목록 표시 + 수동 처리 |
| 분류 근거 보기 | 파일별 적용 규칙 표시 |
| 초보자 규칙 편집기 | 드롭다운 문장형 편집 |

**제외 기능:**
- classify_previews DB 저장 (메모리 기반으로 충분)
- Provenance 배지 UI (DB 기록은 하되 UI 미노출)
- 고급 규칙 편집기 (regex/JSON 직접)
- No Metadata 자동 복구 (Pixiv URL 자동 가져오기)
- 우고이라/BMP 카드 고도화
- 일괄 편집

**완료 기준:**
```
✓ 분류 결과를 확인 후 실행 가능
✓ 잘못된 분류를 Recent Jobs에서 되돌릴 수 있음
✓ No Metadata 파일 목록 확인 + 수동 처리 가능
✓ 파일 클릭 시 "왜 이 폴더로 분류되었는지" 확인 가능
```

---

### 2.3 MVP-C: 완성도 UX (Sprint 7~8, 약 4주)

**목표**: 초보자 진입 장벽을 낮추고 전체 UX 흐름을 완성한다.

**포함 기능:**

| 기능 | 설명 |
|------|------|
| 첫 실행 마법사 (5단계) | Archive Root + 폴더 + 브라우저 + 규칙 + 완료 |
| Provenance 배지 UI | 🟢🟡🔵🔴 배지로 필드별 신뢰도 표시 |
| 고급 규칙 편집기 | regex, AND/OR, JSON 직접 편집 |
| 우고이라/BMP 카드 고도화 | 애니메이션 미리보기, 파일 구성 표시 |
| 일괄 메타데이터 편집 | 필터 후 선택 파일 태그 일괄 추가/변경 |
| classify_previews DB 저장 | 앱 재시작 후에도 미리보기 유지 |
| No Metadata 자동 복구 | Pixiv URL 직접 입력 자동 가져오기 |

**완료 기준:**
```
✓ 처음 설치한 사용자가 마법사를 통해 5단계 이내 사용 시작 가능
✓ 모든 필드에 출처 배지 표시
✓ regex/AND/OR 조건 직접 편집 가능
✓ 포터블 배포 완성
```

---

## 3. 첫 실행 / 초기 설정 전략

### 3.1 MVP-A용 최소 설정 화면

마법사 형식이 아닌 일반 설정 화면으로 제공. 앱 최초 실행 시 설정이 없으면 자동으로 이 화면을 열어준다.

```
┌───────────────────────────────────────────────────────────┐
│ Aru Archive 초기 설정                                      │
├───────────────────────────────────────────────────────────┤
│                                                           │
│ Archive 루트 폴더                                          │
│ [D:\AruArchive                              ] [찾아보기]  │
│                                                           │
│ 자동 생성:  ├── Inbox/   └── Classified/                  │
│ 현재 D: 드라이브 여유: 234 GB                             │
│                                                           │
│ 브라우저 연결 상태                                         │
│ 🟢 Chrome       연결됨   (v1.0.0)                         │
│ 🔴 Whale        연결 안 됨                                 │
│ 🟢 Native Host  등록 완료                                  │
│                                                           │
│ [Chrome 연결 설정]  [Whale 연결 설정]  [연결 테스트]       │
│                                                           │
│ 분류 모드                                                  │
│ ● 검토 후 분류 (권장)    ○ 즉시 자동 분류                  │
│                                                           │
├───────────────────────────────────────────────────────────┤
│                                          [설정 저장 시작]  │
└───────────────────────────────────────────────────────────┘
```

**MVP-A 설정 항목 (config.json에 저장):**
```json
{
  "version": "1.0",
  "archive_root": "D:/AruArchive",
  "inbox_dir": "D:/AruArchive/Inbox",
  "classified_dir": "D:/AruArchive/Classified",
  "classify_mode": "review",
  "setup_completed": true,
  "native_host": { "ipc_port": 18456 }
}
```

### 3.2 완성형 첫 실행 마법사 (MVP-C, 5단계)

| 단계 | 화면 내용 | 성공 조건 | 건너뛰기 |
|------|-----------|-----------|----------|
| 1/5 | Archive Root 폴더 선택 | 경로 쓰기 가능 | 불가 |
| 2/5 | Inbox / Classified 폴더 자동 생성 확인 | 폴더 생성 성공 | 불가 |
| 3/5 | 브라우저 연결 확인 (Chrome 필수, Whale 선택) | Chrome ping 응답 | Whale만 가능 |
| 4/5 | 기본 분류 규칙 선택 (프리셋 체크박스) | — | 가능 (나중에 설정) |
| 5/5 | 완료 요약 | — | — |

### 3.3 Pixiv 저장 테스트 — 선택 기능으로 분리

v2.0에서 9단계에 있던 저장 테스트는 완전히 선택 사항으로 분리.

- 완료 화면(5/5)에 "저장 테스트 해보기 (선택)" 버튼 제공
- 실패 시에도 마법사 완료 상태 유지 (테스트 실패가 설정 실패가 아님)
- 이유: 로그인 상태, 네트워크, 작품 접근 권한에 따라 실패 가능 → 첫 경험을 망치면 안 됨

### 3.4 브라우저 연결 확인 정책

| 브라우저 | 정책 |
|----------|------|
| Chrome | 3/5 단계에서 ping 테스트. 실패 시 마법사 진행 불가 (연결 설정 안내 제공) |
| Whale | 선택 사항. "건너뛰기" 버튼으로 패스 가능. 나중에 설정 화면에서 추가 |
| 공통 | Native Host 등록은 4/5 단계 이전에 자동 완료. 실패 시 install_host.bat 실행 안내 |

---

## 4. 데이터 모델 재설계

### 4.1 방식 비교

| 항목 | 기존 artworks 확장 | artwork_groups + artwork_files 분리 |
|------|-------------------|--------------------------------------|
| 초기 구현 복잡도 | 낮음 | 중간 |
| 다중 페이지 그룹핑 | parent_artwork_id로 취약하게 처리 | group_id로 명확히 처리 |
| 파일 역할 추적 | is_ugoira, has_webp 불리언 플래그 | file_role 열거형으로 명확 |
| 복사본 추적 | classified_paths JSON 배열 (비정규화) | artwork_files의 classified_copy 행으로 정규화 |
| 우고이라 ZIP + WebP | 별도 컬럼, 불명확 | 동일 group_id에 file_role로 구분 |
| sidecar 파일 | 미추적 | file_role='sidecar'로 추적 |
| BMP + PNG 관리본 | 미지원 | file_role='original'+'managed'로 표현 |
| 장기 마이그레이션 비용 | 높음 (파일 역할 추가 시 테이블 구조 변경) | 낮음 (file_role 값 추가만 필요) |

**결론: artwork_groups + artwork_files 방식 채택.** 초기 구현 비용이 약간 높지만, 다중 페이지/우고이라/BMP/복사본 추적을 처음부터 올바르게 모델링하면 이후 마이그레이션 비용이 없다.

---

### 4.2 최종 권장 테이블 정의

#### artwork_groups — 사용자가 보는 작품 단위

```sql
CREATE TABLE artwork_groups (
    group_id             TEXT PRIMARY KEY,  -- UUID v4
    source_site          TEXT NOT NULL DEFAULT 'pixiv',
    artwork_id           TEXT NOT NULL,
    artwork_url          TEXT,
    artwork_title        TEXT,
    artist_id            TEXT,
    artist_name          TEXT,
    artist_url           TEXT,
    artwork_kind         TEXT NOT NULL DEFAULT 'single_image',
    -- single_image | multi_page | ugoira
    total_pages          INTEGER NOT NULL DEFAULT 1,
    cover_file_id        TEXT,             -- FK → artwork_files.file_id (대표 썸네일)
    tags_json            TEXT,             -- JSON array: ["tag1", ...]
    character_tags_json  TEXT,             -- JSON array
    series_tags_json     TEXT,             -- JSON array
    downloaded_at        TEXT NOT NULL,    -- ISO8601
    indexed_at           TEXT NOT NULL,
    updated_at           TEXT,
    status               TEXT NOT NULL DEFAULT 'inbox',
    -- inbox | classified | unclassified | no_metadata | failed
    schema_version       TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(artwork_id, source_site)
);

CREATE INDEX idx_ag_artist_id   ON artwork_groups(artist_id);
CREATE INDEX idx_ag_status      ON artwork_groups(status);
CREATE INDEX idx_ag_downloaded  ON artwork_groups(downloaded_at);
CREATE INDEX idx_ag_site        ON artwork_groups(source_site);
```

#### artwork_files — 실제 파일 단위

```sql
CREATE TABLE artwork_files (
    file_id            TEXT PRIMARY KEY,  -- UUID v4
    group_id           TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    page_index         INTEGER NOT NULL DEFAULT 0,
    file_role          TEXT NOT NULL,
    -- original      : Pixiv에서 받은 원본 (JPEG/PNG/ZIP)
    -- managed       : 변환본 (WebP, PNG-from-BMP 등)
    -- sidecar       : 메타데이터 .aru.json
    -- classified_copy: Classified 폴더 복사본
    file_path          TEXT NOT NULL UNIQUE,
    file_format        TEXT NOT NULL,     -- jpeg | png | zip | webp | json | bmp
    file_hash          TEXT,              -- SHA-256
    file_size          INTEGER,           -- bytes
    metadata_embedded  INTEGER NOT NULL DEFAULT 0,  -- 1: 메타데이터 임베딩 완료
    created_at         TEXT NOT NULL,     -- ISO8601
    modified_at        TEXT,
    source_file_id     TEXT REFERENCES artwork_files(file_id),
    -- classified_copy의 원본 file_id
    classify_rule_id   TEXT,
    -- classified_copy가 어떤 규칙으로 생성됐는지
    provenance_json    TEXT
    -- _provenance 필드 (source, confidence, captured_at만, raw_value 제외)
);

CREATE INDEX idx_af_group_id   ON artwork_files(group_id);
CREATE INDEX idx_af_role       ON artwork_files(file_role);
CREATE INDEX idx_af_hash       ON artwork_files(file_hash);
```

---

### 4.3 파일 유형별 file_role 매핑

| 파일 | artwork_kind | file_role | file_format | page_index |
|------|-------------|-----------|-------------|------------|
| Pixiv 단일 JPEG | single_image | original | jpeg | 0 |
| Pixiv 다중 페이지 JPEG p0 | multi_page | original | jpeg | 0 |
| Pixiv 다중 페이지 JPEG p1 | multi_page | original | jpeg | 1 |
| 우고이라 원본 ZIP | ugoira | original | zip | 0 |
| 우고이라 WebP 변환본 | ugoira | managed | webp | 0 |
| 우고이라 sidecar .aru.json | ugoira | sidecar | json | 0 |
| BMP 원본 | single_image | original | bmp | 0 |
| BMP → PNG 변환본 | single_image | managed | png | 0 |
| Classified 복사본 (JPEG) | (원본과 동일) | classified_copy | jpeg | (원본과 동일) |

**그룹 표시 우선순위** (갤러리 카드의 대표 파일):
```
1. managed (WebP/PNG) 있으면 → managed 사용
2. original 사용
3. classified_copy는 갤러리 카드에 미사용 (상세 패널에서 별도 표시)
```

---

### 4.4 기타 보조 테이블

#### tags — 태그 인덱스 (검색 성능)

```sql
CREATE TABLE tags (
    group_id   TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    tag_type   TEXT NOT NULL DEFAULT 'general',  -- general | character | series
    PRIMARY KEY (group_id, tag, tag_type)
);
CREATE INDEX idx_tags_tag ON tags(tag);
```

#### save_jobs — 저장 작업 추적 (v2.0과 동일)

```sql
CREATE TABLE save_jobs (
    job_id        TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    source_site   TEXT NOT NULL,
    artwork_id    TEXT NOT NULL,
    artwork_title TEXT,
    total_pages   INTEGER DEFAULT 1,
    status        TEXT DEFAULT 'pending',
    -- pending|collecting|downloading|embedding|classifying|copying|done|partial_fail|failed
    pages_done    INTEGER DEFAULT 0,
    pages_failed  INTEGER DEFAULT 0,
    classify_mode TEXT DEFAULT 'review',
    completed_at  TEXT,
    error_message TEXT,
    group_id      TEXT REFERENCES artwork_groups(group_id)
);
```

#### job_pages — 페이지별 상태 (v2.0과 동일)

```sql
CREATE TABLE job_pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES save_jobs(job_id) ON DELETE CASCADE,
    page_index  INTEGER NOT NULL,
    status      TEXT DEFAULT 'pending',
    file_id     TEXT REFERENCES artwork_files(file_id),
    error       TEXT,
    started_at  TEXT,
    done_at     TEXT
);
```

#### undo_entries — Undo 가능한 작업 로그

```sql
CREATE TABLE undo_entries (
    entry_id     TEXT PRIMARY KEY,
    job_id       TEXT REFERENCES save_jobs(job_id),
    action       TEXT NOT NULL,
    -- auto_classify | manual_classify | reindex_classify
    created_at   TEXT NOT NULL,
    undo_expires_at TEXT NOT NULL,   -- Undo 가능 만료일 (기본 30일)
    log_expires_at  TEXT NOT NULL,   -- 로그 보존 만료일 (기본 180일)
    artwork_id   TEXT,
    source_site  TEXT,
    group_id     TEXT REFERENCES artwork_groups(group_id),
    undo_status  TEXT NOT NULL DEFAULT 'available'
    -- available | expired | done | partial | unavailable
);
```

#### copy_records — 복사본 기록 (Undo 안전성 강화)

```sql
CREATE TABLE copy_records (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id              TEXT NOT NULL REFERENCES undo_entries(entry_id) ON DELETE CASCADE,
    src_file_id           TEXT REFERENCES artwork_files(file_id),
    dest_file_id          TEXT REFERENCES artwork_files(file_id),
    src_path              TEXT NOT NULL,
    dest_path             TEXT NOT NULL,
    rule_id               TEXT,
    -- Undo 안전성: 복사 시점 스냅샷
    dest_file_size        INTEGER NOT NULL,
    dest_mtime_at_copy    TEXT NOT NULL,    -- ISO8601
    dest_hash_at_copy     TEXT NOT NULL,    -- SHA-256
    manually_modified     INTEGER DEFAULT 0,
    copied_at             TEXT NOT NULL
);
```

#### no_metadata_queue — 메타데이터 없는 파일 큐

```sql
CREATE TABLE no_metadata_queue (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path             TEXT NOT NULL UNIQUE,
    discovered_at         TEXT NOT NULL,
    fail_reason           TEXT NOT NULL,
    -- no_exif | parse_fail | unsupported_format | missing_required_fields | pixiv_deleted
    extracted_artwork_id  TEXT,
    extracted_confidence  TEXT,             -- high | medium | low
    last_attempted        TEXT,
    attempt_count         INTEGER DEFAULT 0,
    status                TEXT DEFAULT 'pending'
    -- pending | retrying | resolved | excluded
);
```

#### metadata_provenance — 필드별 출처 DB 기록

```sql
CREATE TABLE metadata_provenance (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id       TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    field          TEXT NOT NULL,
    value_text     TEXT,           -- JSON 직렬화
    source         TEXT NOT NULL,
    -- pixiv_api | pixiv_dom | filename_parse | user_input | saucenao | missing
    confidence     TEXT NOT NULL,  -- high | medium | low | manual
    captured_at    TEXT NOT NULL,
    raw_value      TEXT            -- 파싱 전 원본 (DB에만 저장, 파일 내부 미포함)
);
CREATE INDEX idx_provenance_group ON metadata_provenance(group_id);
```

---

## 5. Undo 및 작업 로그 설계 보강

### 5.1 Undo 정책 명문화

| 항목 | 정책 |
|------|------|
| Inbox 원본 | **절대 삭제하지 않음** (file_role='original'/'managed') |
| Classified 복사본 | Undo 대상 (file_role='classified_copy') |
| 수정된 복사본 | 삭제 전 사용자 확인 다이얼로그 필수 |
| 이미 없어진 복사본 | 스킵하고 사용자에게 경고 (Undo 계속 진행) |
| 빈 폴더 자동 정리 | 설정 옵션 (기본: 정리함) |

### 5.2 파일 수정 감지 — 3중 비교

```python
from dataclasses import dataclass
from pathlib import Path
import hashlib, stat

@dataclass
class FileCheckResult:
    status: str  # 'safe' | 'modified' | 'missing'
    detail: str

def check_before_undo(record) -> FileCheckResult:
    path = Path(record.dest_path)

    if not path.exists():
        return FileCheckResult('missing', '파일이 이미 삭제되었거나 이동되었습니다.')

    stat_result = path.stat()
    current_size = stat_result.st_size
    current_mtime = stat_result.st_mtime_ns  # 나노초 정밀도

    # 1차: 크기 비교 (빠름)
    if current_size != record.dest_file_size:
        return FileCheckResult('modified', f'파일 크기가 변경됨 ({record.dest_file_size}B → {current_size}B)')

    # 2차: mtime 비교 (중간)
    copy_mtime_ns = int(record.dest_mtime_at_copy) if record.dest_mtime_at_copy else None
    if copy_mtime_ns and abs(current_mtime - copy_mtime_ns) > 1_000_000:  # 1ms 허용
        # 3차: 해시 비교 (정확, 느림 — mtime 차이 있을 때만)
        current_hash = sha256_file(path)
        if current_hash != record.dest_hash_at_copy:
            return FileCheckResult('modified', '파일 내용이 수정되었습니다.')

    return FileCheckResult('safe', '변경 없음')

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()
```

### 5.3 Undo 실행 흐름 (사용자 확인 포함)

```
[복사본 제거] 클릭
│
▼ 각 copy_record에 대해 check_before_undo() 실행
│
├─ missing  → 이미 없음, 스킵 (카운트 집계)
├─ modified → "수정된 파일" 목록에 추가
└─ safe     → 삭제 대기 목록에 추가
│
▼ 수정된 파일이 있는 경우:
┌─────────────────────────────────────────────────────┐
│ ⚠ 수정된 복사본이 발견되었습니다.                   │
│                                                     │
│ 다음 파일은 복사 이후 수정된 것으로 보입니다:        │
│ - Classified/시리즈/Blue Archive/141100516_p0.jpg   │
│   (파일 내용이 수정되었습니다)                       │
│                                                     │
│ 이 파일들을 어떻게 처리할까요?                       │
│ [삭제]  [보존 (Undo 제외)]  [파일 열기]             │
└─────────────────────────────────────────────────────┘
│
▼ 확인 후 삭제 실행
  - 삭제된 복사본 수
  - 스킵된 복사본 수 (이미 없음)
  - 보존된 복사본 수 (사용자 선택)
│
▼ undo_entries.undo_status 업데이트
  - 전체 삭제: 'done'
  - 일부 보존: 'partial'
│
▼ artwork_files에서 classified_copy 행 삭제
▼ 빈 폴더 자동 정리 (설정 옵션)
▼ 완료 알림 + [새 규칙으로 다시 분류] 버튼
```

### 5.4 Undo 가능 기간과 로그 보존 기간 분리

| 구분 | 기본값 | 설정 옵션 | 만료 시 동작 |
|------|--------|-----------|-------------|
| Undo 가능 기간 | 30일 | 7일 / 30일 / 90일 / 무제한 | undo_status → 'expired', copy_records 삭제 가능 |
| 작업 로그 보존 기간 | 180일 | 30일 / 90일 / 180일 / 무제한 | undo_entries + copy_records 전체 삭제 |

**undo_status 상태 전이:**

```
available ─── Undo 실행 ──→ done
    │                        (전체 성공)
    │
    ├── Undo 실행 (일부 보존) ──→ partial
    │
    ├── undo_expires_at 경과 ──→ expired
    │                            (로그는 log_expires_at까지 유지)
    │
    └── 외부 변경으로 전체 불가 ──→ unavailable
```

**만료 처리 스케줄 (앱 시작 시 또는 주기적으로 실행):**

```python
def process_expiration(db, now: datetime):
    # 1. Undo 기간 만료 처리
    db.execute("""
        UPDATE undo_entries
        SET undo_status = 'expired'
        WHERE undo_expires_at < ?
          AND undo_status = 'available'
    """, (now.isoformat(),))

    # 2. Undo 만료된 항목의 copy_records 삭제 (공간 절약)
    db.execute("""
        DELETE FROM copy_records
        WHERE entry_id IN (
            SELECT entry_id FROM undo_entries
            WHERE undo_status = 'expired'
              AND undo_expires_at < ?
        )
    """, (now.isoformat(),))

    # 3. 로그 보존 기간 초과 시 undo_entries 전체 삭제
    db.execute("""
        DELETE FROM undo_entries
        WHERE log_expires_at < ?
          AND undo_status != 'available'
    """, (now.isoformat(),))
```

---

## 6. 분류 미리보기 저장 정책

### 6.1 방식 비교

| 항목 | 방식 A: 메모리 기반 | 방식 B: DB 저장형 |
|------|-------------------|-----------------|
| 구현 복잡도 | 낮음 | 높음 |
| 앱 종료 후 유지 | 미유지 (재생성 필요) | 유지됨 |
| 미리보기 크기 | 제한 없음 | preview_json 크기 주의 |
| 재생성 비용 | 낮음 (빠른 계산) | 불필요 |
| 적합한 MVP | MVP-A/B | MVP-C |

**결론**: MVP-A/B에서는 메모리 기반 채택. 앱 재시작 시 미리보기 자동 무효화 + "분류 미리보기를 다시 생성해주세요" 안내만 표시. MVP-C에서 DB 저장 방식 추가.

### 6.2 메모리 기반 미리보기 (MVP-A/B)

```python
# app/state/classify_preview_store.py
from threading import Lock

class ClassifyPreviewStore:
    """앱 전역 단일 인스턴스. 앱 종료 시 사라짐."""
    def __init__(self):
        self._preview: ClassifyPreview | None = None
        self._lock = Lock()

    def set(self, preview: ClassifyPreview):
        with self._lock:
            self._preview = preview

    def get(self) -> ClassifyPreview | None:
        with self._lock:
            return self._preview

    def clear(self):
        with self._lock:
            self._preview = None

    def is_valid(self) -> bool:
        """미리보기가 존재하고 만료되지 않았는지 확인 (1시간 유효)"""
        with self._lock:
            if not self._preview:
                return False
            age = datetime.now() - datetime.fromisoformat(self._preview.generated_at)
            return age.total_seconds() < 3600
```

### 6.3 DB 저장형 미리보기 (MVP-C)

```sql
CREATE TABLE classify_previews (
    preview_id    TEXT PRIMARY KEY,
    job_id        TEXT REFERENCES save_jobs(job_id),
    generated_at  TEXT NOT NULL,
    expires_at    TEXT NOT NULL,  -- generated_at + 24시간
    status        TEXT NOT NULL DEFAULT 'pending',
    -- pending | executed | cancelled | expired
    preview_json  TEXT NOT NULL   -- ClassifyPreview JSON (경량: 파일 경로 + 규칙 ID만)
);
```

**preview_json 경량화 원칙**: 상세 계산(예상 용량 등)은 재조회, JSON에는 group_id + matched_rule_id + dest_path 목록만 저장.

---

## 7. Metadata Provenance 저장 정책

### 7.1 파일 내부 저장 vs DB 저장 분리

| 저장 위치 | 저장 내용 | 이유 |
|-----------|-----------|------|
| 파일 내부 (_provenance JSON) | source, confidence, captured_at | 파일 자립성 보장. DB 없이도 출처 파악 가능 |
| DB (metadata_provenance 테이블) | + raw_value (파싱 전 원본) | 디버깅용. 파일 크기 증가 없이 상세 정보 보존 |

**파일 내부 _provenance 예시 (경량):**
```json
{
  "schema_version": "1.0",
  "artwork_title": "タイトル",
  "artist_name": "作家名",
  "_provenance": {
    "artwork_title":  { "source": "pixiv_api",      "confidence": "high",   "captured_at": "2026-04-26T15:30:00+09:00" },
    "artist_name":    { "source": "pixiv_api",      "confidence": "high",   "captured_at": "2026-04-26T15:30:00+09:00" },
    "artwork_id":     { "source": "filename_parse", "confidence": "medium", "captured_at": "2026-04-26T15:30:00+09:00" },
    "character_tags": { "source": "user_input",     "confidence": "manual", "captured_at": "2026-04-26T16:00:00+09:00" }
  }
}
```

**DB에만 저장되는 raw_value 예시:**
```json
{
  "artwork_id": {
    "raw_value": "illust_141100516_20260426.jpg",
    "parsed_pattern": "^illust_(\\d+)_"
  }
}
```

### 7.2 파일 ↔ DB 동기화 정책

| 이벤트 | 동작 |
|--------|------|
| 최초 저장 시 | 파일 내 _provenance 기록 + DB metadata_provenance INSERT |
| 사용자 수동 편집 시 | 파일 내 _provenance 업데이트 + DB UPDATE (source=user_input) |
| DB 재색인 시 | 파일에서 _provenance 읽어 DB UPSERT (파일이 원본) |
| 파일 ↔ DB 불일치 발견 시 | 파일 내 값을 신뢰하고 DB를 파일 기준으로 덮어씀 |

**원칙**: 파일이 원본, DB는 검색용 캐시. DB 손실 시 파일에서 완전 복구 가능.

### 7.3 Provenance 배지 연결 (MVP-C UI)

```python
PROVENANCE_BADGE = {
    'pixiv_api':      {'label': 'Pixiv API', 'color': '#37864E', 'emoji': '🟢'},
    'pixiv_dom':      {'label': 'Pixiv 페이지', 'color': '#37864E', 'emoji': '🟢'},
    'filename_parse': {'label': '파일명 추정', 'color': '#B8860B', 'emoji': '🟡'},
    'user_input':     {'label': '수동 입력', 'color': '#1F497D', 'emoji': '🔵'},
    'saucenao':       {'label': 'SauceNao', 'color': '#6A0DAD', 'emoji': '🟣'},
    'missing':        {'label': '누락', 'color': '#C00000', 'emoji': '🔴'},
}
# MVP-A/B에서는 배지 없이 텍스트(출처: Pixiv API)로만 표시
# MVP-C에서 색상 배지 위젯 추가
```

---

## 8. 브라우저 팝업과 메인 앱 역할 분리

### 8.1 역할 원칙

```
브라우저 팝업 = 리모컨
  - 저장 트리거
  - 진행률 표시
  - 성공/실패 요약
  - 간단한 재시도 (단일 페이지)
  - "Aru Archive에서 열기" 딥링크

메인 앱 = 관제실
  - 분류 미리보기 + 실행
  - 충돌 처리
  - 규칙 편집
  - Undo
  - 상세 로그
  - No Metadata 처리
  - 일괄 편집
```

### 8.2 팝업 UI 기능 목록 (MVP별)

| 기능 | MVP-A | MVP-B | MVP-C |
|------|-------|-------|-------|
| 저장 진행률 표시 | ✓ | ✓ | ✓ |
| 성공/실패/부분실패 요약 | ✓ | ✓ | ✓ |
| Inbox 열기 버튼 | ✓ | ✓ | ✓ |
| 분류 폴더 열기 버튼 | ✓ | ✓ | ✓ |
| Aru Archive에서 열기 | ✓ | ✓ | ✓ |
| 단일 페이지 재시도 | ✓ | ✓ | ✓ |
| "분류 미리보기 대기 중" 뱃지 | — | ✓ | ✓ |
| No Metadata 경고 뱃지 | — | ✓ | ✓ |
| 연결 상태 아이콘 | ✓ | ✓ | ✓ |

**팝업에서 제거한 기능 (메인 앱으로 이동):**
- 분류 미리보기 전체 화면
- 충돌 파일 선택 다이얼로그
- 로그 상세 보기
- 규칙 수정
- Undo 실행

### 8.3 Native Messaging 프로토콜 재정리

| action | 호출 주체 | 설명 | MVP |
|--------|-----------|------|-----|
| `ping` | Extension | 연결 및 버전 확인 | A |
| `save_artwork` | Extension | 작품 저장 (다중 페이지 포함) | A |
| `get_job_status` | Extension | 저장 진행률 폴링 (팝업용) | A |
| `open_main_app` | Extension | 메인 앱 실행 + 특정 뷰 포커스 | A |
| `retry_page` | Extension | 단일 페이지 재시도 | A |
| `get_classify_preview` | App | 분류 미리보기 생성 | B |
| `execute_classify` | App | 분류 실행 (미리보기 승인 후) | B |
| `undo_classify` | App | Undo (복사본 제거) | B |
| `get_no_metadata_queue` | App | No Metadata 큐 조회 | B |
| `resolve_no_metadata` | App | No Metadata 항목 처리 | B |
| `reindex_dir` | App | 디렉토리 재색인 | A |

**팝업 → 메인 앱 딥링크 방식:**
```
open_main_app 메시지:
{
  "action": "open_main_app",
  "focus": "recent_jobs",  // gallery | recent_jobs | no_metadata | classify_preview
  "job_id": "550e8400-..."
}
→ 메인 앱이 실행 중이면 해당 뷰 포커스
→ 실행 중이 아니면 앱 시작 후 해당 뷰 열기
```

---

## 9. classify_log / copy_records 최종 정책

### 9.1 방안 비교

**안 A: classify_log 제거, undo_entries + copy_records로 통합**

장점:
- 중복 테이블 없음 (단일 소스)
- 분류 이력 = Undo 로그로 일원화
- 테이블 수 감소

단점:
- Undo 만료 후 copy_records 삭제 시 상세 이력 손실
- undo_entries에 Undo 관심사 + 이력 관심사 혼합

**안 B: classify_log = 작업 요약, copy_records = 파일별 상세**

장점:
- 관심사 분리
- Undo 만료 후에도 classify_log로 요약 이력 확인 가능

단점:
- 테이블 하나 더
- classify_log와 undo_entries 사이 중복 정보

### 9.2 최종 결정: 안 A 채택 (단, log_expires_at으로 이력 보존)

undo_entries를 **분류 이력 + Undo 로그**로 통합 운용.
Undo 만료(`undo_expires_at`) 후에도 `log_expires_at`까지 undo_entries 행 자체는 유지.
copy_records는 Undo 만료 시 삭제 (공간 절약), undo_entries는 로그로 남음.

```
undo_entries:
  entry_id, action, artwork_id, created_at, undo_expires_at, log_expires_at, undo_status
  → Undo 기간: undo_expires_at 기준
  → 이력 조회: log_expires_at 기준 (Recent Jobs 화면에서 표시)

copy_records:
  entry_id, src_path, dest_path, rule_id, dest_file_size, dest_mtime, dest_hash, ...
  → Undo 실행의 실제 데이터
  → Undo 만료 후 삭제 (undo_expires_at 기준)
```

### 9.3 분류 근거 표시 방식

**"왜 이 폴더로 분류되었는지" 표시 쿼리:**
```sql
-- 특정 파일의 분류 근거 조회
SELECT
    af.dest_path,
    af.classify_rule_id,
    cr.rule_id,
    ue.created_at AS classified_at,
    ue.action
FROM artwork_files af
JOIN copy_records cr ON cr.dest_file_id = af.file_id
JOIN undo_entries ue ON ue.entry_id = cr.entry_id
WHERE af.group_id = ?
  AND af.file_role = 'classified_copy';
```

**표시 정보 구성:**
- classify_rule_id → rules 테이블에서 rule_name + conditions 조회
- classified_at → 분류 일시
- action → 'auto_classify' / 'manual_classify'

### 9.4 Recent Jobs 구성 방식

```sql
-- Recent Jobs 화면용 쿼리
SELECT
    ue.entry_id,
    ue.action,
    ue.created_at,
    ue.undo_status,
    ue.undo_expires_at,
    ag.artwork_title,
    ag.artist_name,
    ag.artwork_id,
    COUNT(cr.id) AS copy_count,
    SUM(cr.dest_file_size) AS total_size
FROM undo_entries ue
JOIN artwork_groups ag ON ag.group_id = ue.group_id
LEFT JOIN copy_records cr ON cr.entry_id = ue.entry_id
WHERE ue.log_expires_at > datetime('now')
GROUP BY ue.entry_id
ORDER BY ue.created_at DESC;
```

---

## 10. 수정된 Sprint 계획

### Sprint 0 — 기반 + 최소 설정 (2주) [MVP-A 시작]

```
산출물:
  - DB 스키마 전체 확정 (artwork_groups + artwork_files + 5개 보조 테이블)
  - config.json 스키마 확정
  - 최소 설정 화면 (PySide6): Archive Root 지정 + 브라우저 연결 테스트
  - install_host.bat + 레지스트리 등록 자동화
  - 어댑터 인터페이스 정의 (base.py)
  - 테스트 픽스처 및 샘플 데이터

완료 기준: 설정 완료 후 config.json 생성, Native Host 등록 확인 가능
```

### Sprint 1 — 저장 코어 (2주) [MVP-A]

```
산출물:
  - core/metadata_writer.py (JPEG/PNG/ZIP/WebP EXIF/iTXt/sidecar)
  - core/ugoira_converter.py (ZIP → animated WebP)
  - core/adapters/pixiv.py (preload_data + AJAX API 파싱)
  - native_host/host.py + handlers.py (save_artwork)
  - artwork_groups + artwork_files DB INSERT
  - save_jobs + job_pages DB INSERT

완료 기준: CLI로 Pixiv URL 입력 시 Inbox 저장 + 메타데이터 임베딩 확인
```

### Sprint 2 — 브라우저 확장 + 저장 UX (2주) [MVP-A]

```
산출물:
  - extension/ (manifest.json + content_scripts/pixiv.js + popup)
  - 팝업 진행률 표시 (get_job_status 폴링)
  - 완료/실패/부분실패 팝업 UI
  - "Aru Archive에서 열기" (open_main_app) 기능
  - 단일 페이지 재시도 (retry_page)
  - 기본 규칙 프리셋 적용 (즉시 분류 모드)

완료 기준: 브라우저에서 저장 버튼 클릭 → 팝업 진행률 → 완료 알림
```

### Sprint 3 — PySide6 기본 앱 (2주) [MVP-A 완료]

```
산출물:
  - app/main_window.py (3패널 레이아웃)
  - app/views/gallery_view.py (artwork_groups 기반 그리드)
  - app/views/detail_view.py (기본 메타데이터 탭)
  - app/widgets/progress_banner.py (하단 상태 배너)
  - 우고이라 WebP 재생 (QMovie)
  - 다중 페이지 카드 (페이지 수 배지)

완료 기준: 저장된 이미지를 갤러리에서 확인 가능. MVP-A 완료.
```

### Sprint 4 — 분류 미리보기 + Undo 기반 (2주) [MVP-B 시작]

```
산출물:
  - 분류 미리보기 생성 (get_classify_preview, 메모리 기반)
  - app/views/classify_preview_view.py
  - 충돌 처리 다이얼로그 (conflict_dialog.py)
  - 검토 후 분류 모드 실행 (execute_classify)
  - undo_entries + copy_records DB 기록
  - 복사 용량 예상 표시

완료 기준: 미리보기 확인 후 분류 실행, undo_entries DB에 기록됨
```

### Sprint 5 — Undo + No Metadata + 분류 근거 (2주) [MVP-B]

```
산출물:
  - Undo 실행 핸들러 (undo_classify)
  - 파일 수정 감지 (check_before_undo: size + mtime + hash)
  - undo_confirm_dialog.py
  - app/views/recent_jobs_view.py
  - app/views/no_metadata_view.py
  - 수동 메타데이터 입력 다이얼로그
  - app/views/classify_reason_panel.py

완료 기준: Recent Jobs에서 복사본 제거 가능. No Metadata 파일 목록 확인 + 처리 가능.
```

### Sprint 6 — 규칙 편집 UI (2주) [MVP-B 완료]

```
산출물:
  - app/views/rules_view.py (초보자 모드)
  - 드롭다운 문장형 규칙 편집기
  - 규칙 목록 관리 (활성/비활성, 순서 변경)
  - 규칙 → 적용 미리보기 연동

완료 기준: 초보자 모드로 새 규칙 생성 + 미리보기 확인 가능. MVP-B 완료.
```

### Sprint 7 — 완성도 UX (2주) [MVP-C 시작]

```
산출물:
  - app/views/wizard_view.py (5단계 첫 실행 마법사)
  - Provenance 배지 위젯 (app/widgets/provenance_badge.py)
  - 우고이라 카드 고도화 (애니메이션 미리보기, 파일 구성 표시)
  - BMP 카드 (원본 + PNG 관리본 표시)
  - 고급 규칙 편집기 (regex/JSON 직접)

완료 기준: 처음 실행한 사용자가 마법사 5단계 이내 완료 가능
```

### Sprint 8 — 일괄 편집 + DB 미리보기 + 패키징 (2주) [MVP-C 완료]

```
산출물:
  - 일괄 메타데이터 편집 화면
  - classify_previews 테이블 + DB 저장 미리보기 전환
  - PyInstaller 패키징 (메인 앱 + Native Host 분리 빌드)
  - 클린 Windows 환경 포터블 실행 테스트
  - E2E 시나리오 테스트 전체
  - 성능 테스트 (1,000개+ 썸네일)

완료 기준: 포터블 배포본 완성. 모든 MVP-C 기능 동작 확인.
```

---

## 11. 최종 권장안

### 11.1 지금 당장 구현할 것 (Sprint 0~1에서 결정해야 함)

| 항목 | 이유 |
|------|------|
| **artwork_groups + artwork_files 스키마** | 나중에 artworks에서 마이그레이션하면 데이터 손실 위험 + 고비용 |
| **undo_entries + copy_records 기본 구조** | Undo 없이 복사 기반 분류를 사용하면 위험 (MVP-B 기다리더라도 DB는 준비) |
| **file_role 열거형 설계** | original/managed/sidecar/classified_copy는 나중에 추가하기 어려움 |
| **_provenance 파일 임베딩** | 파일 자립성의 근간, 나중에 추가하면 기존 파일 재임베딩 필요 |
| **최소 설정 화면 (Archive Root)** | 없으면 개발 테스트도 불가 |

### 11.2 미뤄도 되는 것

| 항목 | 미룰 수 있는 근거 | 미뤄야 할 Sprint |
|------|-----------------|-----------------|
| 첫 실행 마법사 완성형 | 최소 설정 화면으로 대체 가능 | Sprint 7 |
| Provenance 배지 UI | DB 기록은 하되 텍스트로 대체 | Sprint 7 |
| classify_previews DB 저장 | 메모리 기반으로 충분 | Sprint 8 |
| 고급 규칙 편집기 | 초보자 모드 먼저 검증 | Sprint 7 |
| No Metadata 자동 복구 | 수동 입력으로 우선 대체 | Sprint 7+ |
| 일괄 메타데이터 편집 | 단일 편집이 먼저 | Sprint 8 |
| X(트위터) 어댑터 | Pixiv 완성 후 | MVP-C 이후 |

### 11.3 장기적으로 반드시 남겨야 하는 구조적 결정

| 구조적 결정 | 변경 시 비용 | 이유 |
|-------------|-------------|------|
| artwork_groups + artwork_files 분리 | 극히 높음 | 파일 역할 추적의 근간 |
| file_role 열거형 (original/managed/sidecar/classified_copy) | 높음 | 갤러리 그룹핑 + Undo + 카드 UX의 기반 |
| _provenance 파일 임베딩 (source + confidence + captured_at) | 높음 | 파일 자립성 (DB 없이 동작 가능) |
| undo_entries + copy_records (dest_hash_at_copy 포함) | 중간 | 안전한 Undo의 유일한 방법 |
| undo_expires_at / log_expires_at 분리 | 낮음 | 정책 변경 용이 |
| 소스 사이트 어댑터 패턴 | 높음 | X 등 타 사이트 추가의 근간 |
| Native Messaging 프로토콜 (팝업=리모컨, 앱=관제실) | 중간 | 팝업 복잡도 억제 |

---

## 부록: 전체 테이블 목록 (v2.1 확정)

| 테이블 | 역할 | 도입 Sprint |
|--------|------|-------------|
| artwork_groups | 작품 단위 (갤러리 카드) | Sprint 0 |
| artwork_files | 파일 단위 (original/managed/sidecar/classified_copy) | Sprint 0 |
| tags | 태그 검색 인덱스 | Sprint 0 |
| save_jobs | 저장 작업 추적 | Sprint 1 |
| job_pages | 페이지별 저장 상태 | Sprint 1 |
| undo_entries | 분류 이력 + Undo 로그 | Sprint 4 |
| copy_records | 복사본 경로 + 수정 감지 스냅샷 | Sprint 4 |
| no_metadata_queue | 메타데이터 없는 파일 큐 | Sprint 5 |
| metadata_provenance | 필드별 출처 + raw_value (DB 전용) | Sprint 1 (기록), Sprint 7 (UI) |
| classify_previews | 미리보기 DB 저장 (선택) | Sprint 8 |

---

*이 문서는 v2.0 설계안을 기반으로 MVP 범위 재분리, 데이터 모델 재설계, Undo 안전성 강화, 초기 개발 순서를 재정리한 v2.1 확정안입니다.*
*기술 구현 상세는 Aru_Archive_설계안_AI분석용.md (v1.0)을 병행 참조하세요.*
