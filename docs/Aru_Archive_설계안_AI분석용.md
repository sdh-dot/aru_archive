# Aru Archive — 프로젝트 설계안 (AI 분석용)

## 메타데이터

- **문서 버전**: 1.0
- **작성일**: 2026-04-26
- **목적**: AI 코드 생성 및 분석 요청 시 참조 컨텍스트
- **개발 언어**: Python (백엔드/메인앱), JavaScript (브라우저 확장)
- **대상 플랫폼**: Windows 11, Chrome / Naver Whale

---

## 1. 프로젝트 개요

Aru Archive는 Pixiv 이미지 및 우고이라를 브라우저에서 저장할 때, 파일 내부에 작가 정보·작품 URL·태그 등의 메타데이터를 직접 기록하고, 이후 해당 메타데이터를 기준으로 자동 분류하는 **Windows용 로컬 관리 프로그램**이다.

### 핵심 원칙

| 원칙 | 설명 |
|------|------|
| 파일 우선 메타데이터 | 메타데이터 원본은 항상 파일 내부. DB는 검색 보조 인덱스 전용 |
| 복사 기반 분류 | 분류 시 원본을 이동하지 않고 복사. Inbox 파일은 항상 보존 |
| 2단계 저장 | Inbox 저장 → 메타데이터 임베딩 → 분류 폴더 복사 |
| 포터블 배포 | PyInstaller 단일 폴더 빌드, 설치 없이 실행 가능 |
| 확장 가능 구조 | Pixiv 우선 구현, X(트위터) 등 추후 어댑터 추가 방식 |

---

## 2. 시스템 구성 요소

### 2.1 구성 요소 목록

```
Browser Extension (Chrome/Whale MV3)
  └─ content_scripts/pixiv.js     : Pixiv DOM 파싱, 페이지 URL 수집
  └─ background/service_worker.js : Native Messaging 통신 허브

Native Messaging Host (Python)
  └─ native_host/host.py          : stdin/stdout 메시지 루프
  └─ native_host/handlers.py      : 액션 처리, httpx 다운로드

Core Library (Python)
  └─ core/adapters/base.py        : 소스 사이트 추상 인터페이스
  └─ core/adapters/pixiv.py       : Pixiv 어댑터 구현
  └─ core/metadata_writer.py      : 파일별 메타데이터 읽기/쓰기
  └─ core/ugoira_converter.py     : ZIP → animated WebP 변환
  └─ core/classifier.py           : 규칙 기반 분류 엔진
  └─ db/database.py               : SQLite CRUD 래퍼

Main App (Python + PySide6)
  └─ app/main_window.py
  └─ app/views/gallery_view.py    : 썸네일 그리드
  └─ app/views/detail_view.py     : 이미지 + 메타데이터 패널
  └─ app/views/rules_view.py      : 분류 규칙 편집 UI
  └─ app/widgets/ugoira_player.py : 프레임 단위 우고이라 재생
```

### 2.2 컴포넌트 간 통신

```
Browser Extension
  ──[Native Messaging: JSON over stdin/stdout]──▶ Native Messaging Host
                                                         │
                                          ┌──────────────┴──────────────┐
                                          ▼                             ▼
                                   Core Library                   SQLite DB
                                   (파일 처리)                  (보조 인덱스)
                                          │
                                   Main App (PySide6)
                                   (UI, 규칙 편집, 뷰어)
```

---

## 3. 저장 플로우 (확정)

```
사용자 클릭
  │
  ▼ [content_scripts/pixiv.js]
  1. preload_data JSON 파싱 → 메타데이터 수집
  2. GET /ajax/illust/{id}/pages → 전체 페이지 URL 수집
  3. (우고이라) GET /ajax/illust/{id}/ugoira_meta → 프레임/딜레이 수집
  │
  ▼ [background/service_worker.js → Native Messaging]
  4. {action: 'save_artwork', metadata, pages: [...]} 전송
  │
  ▼ [native_host/handlers.py]
  5. PixivAdapter.get_http_headers() → Referer: https://www.pixiv.net
  6. 각 페이지 httpx.get(url) → bytes
  7. Inbox/{source_site}/{filename} 저장
  8. 파일 형식별 메타데이터 임베딩:
       JPEG → EXIF UserComment (piexif)
       PNG  → iTXt chunk (직접 조작)
       ZIP  → ZIP comment(식별자) + .aru.json sidecar
  9. (ZIP) animated WebP 변환 → EXIF UserComment 삽입
 10. SQLite INSERT (status='inbox')
 11. Classifier 실행 → Classified/ 복사
 12. SQLite UPDATE (status='classified')
 13. 완료 응답 반환
```

---

## 4. 메타데이터 스키마 (JSON)

모든 파일에 동일한 스키마로 저장. 파일 형식에 따라 저장 위치만 다름.

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
  "custom_notes": ""
}
```

### 파일 형식별 저장 위치

| 파일 형식 | 저장 방식 | 상세 |
|-----------|-----------|------|
| JPEG | EXIF UserComment | `0x9286`, prefix `UNICODE\x00` + UTF-16LE JSON |
| PNG | iTXt chunk | keyword=`AruArchive`, text=JSON UTF-8 |
| ZIP (우고이라) | ZIP comment + sidecar | comment=`aru:v1:{id}:{page}`, 전체 데이터는 `.aru.json` |
| WebP (변환본) | EXIF UserComment | JPEG와 동일 방식 |

---

## 5. 소스 사이트 어댑터 인터페이스

```python
class SourceSiteAdapter(ABC):
    site_name: str  # 'pixiv' | 'x' | ...

    def can_handle(self, url: str) -> bool: ...
    def parse_page_data(self, raw_data: dict) -> ArtworkMetadata: ...
    def build_download_targets(self, metadata, page_data) -> list[DownloadTarget]: ...
    def get_http_headers(self) -> dict: ...
```

**현재 구현**: `PixivAdapter`
**예정**: `XAdapter` (X/트위터, Pixiv 완성 후 추가)

어댑터 등록: `core/adapters/__init__.py`의 `_ADAPTERS` 리스트에 추가만 하면 됨.

---

## 6. 분류 규칙 모델

```python
@dataclass
class Condition:
    field: str   # 'artist_id'|'artist_name'|'tags'|'character_tags'|'series_tags'|...
    op: str      # 'eq'|'contains'|'in'|'startswith'|'regex'
    value: str | list[str]

@dataclass
class ClassifyRule:
    rule_id: str
    name: str
    enabled: bool
    priority: int        # 낮을수록 높은 우선순위
    conditions: list[Condition]
    logic: str           # 'AND' | 'OR'
    dest_template: str   # '{classified_dir}/작가/{artist_name}'
    on_conflict: str     # 'skip' | 'overwrite' | 'rename'
```

**dest_template 변수**: `{classified_dir}`, `{artist_name}`, `{artist_id}`,
`{character_tags[0]}`, `{series_tags[0]}`, `{source_site}`, `{artwork_id}`

---

## 7. SQLite 스키마

```sql
CREATE TABLE artworks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site       TEXT NOT NULL DEFAULT 'pixiv',
    artwork_id        TEXT NOT NULL,
    page_index        INTEGER NOT NULL DEFAULT 0,
    artwork_url       TEXT,
    artwork_title     TEXT,
    artist_id         TEXT,
    artist_name       TEXT,
    is_ugoira         INTEGER DEFAULT 0,
    has_webp          INTEGER DEFAULT 0,
    total_pages       INTEGER DEFAULT 1,
    downloaded_at     TEXT,
    indexed_at        TEXT NOT NULL,
    status            TEXT DEFAULT 'inbox',
    inbox_path        TEXT NOT NULL UNIQUE,
    classified_paths  TEXT,
    file_hash         TEXT,
    schema_version    TEXT DEFAULT '1.0',
    UNIQUE(artwork_id, page_index, source_site)
);

CREATE TABLE tags (
    artwork_id  INTEGER NOT NULL REFERENCES artworks(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    tag_type    TEXT NOT NULL DEFAULT 'general',
    PRIMARY KEY (artwork_id, tag, tag_type)
);

CREATE TABLE classify_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    artwork_id    INTEGER NOT NULL REFERENCES artworks(id),
    rule_id       TEXT,
    dest_path     TEXT,
    classified_at TEXT
);
```

---

## 8. Native Messaging 프로토콜

### 메시지 형식

```
[4 bytes little-endian length][JSON UTF-8 bytes]
```

### 액션 목록

| action | 방향 | 설명 |
|--------|------|------|
| `ping` | Extension → Host | 연결 확인 |
| `save_artwork` | Extension → Host | 작품 저장 (다중 페이지 포함) |
| `save_ugoira` | Extension → Host | 우고이라 저장 |
| `get_job_status` | Extension → Host | 저장 진행률 폴링 |
| `reindex_dir` | App → Host | 디렉토리 재색인 |

### save_artwork 요청 구조

```json
{
  "action": "save_artwork",
  "metadata": { /* ArtworkMetadata 필드 */ },
  "pages": [
    {
      "page_index": 0,
      "url": "https://i.pximg.net/.../141100516_p0.jpg",
      "filename": "141100516_p0.jpg",
      "width": 2400,
      "height": 3200
    }
  ]
}
```

### 응답 구조

```json
{
  "success": true,
  "data": {
    "job_id": "abc123",
    "saved": 3,
    "results": [
      {
        "page_index": 0,
        "inbox_path": "D:/AruArchive/Inbox/pixiv/141100516_p0.jpg",
        "classified_path": "D:/AruArchive/Classified/작가/作家名/141100516_p0.jpg"
      }
    ]
  }
}
```

---

## 9. 우고이라 처리 상세

```
입력: ugoira.zip (프레임 JPEG 묶음) + metadata
      metadata.ugoira_frames: ["000000.jpg", "000001.jpg", ...]
      metadata.ugoira_delays: [80, 80, 120, ...]  (ms)

출력:
  Inbox/pixiv/
  ├── {artwork_id}_ugoira.zip          원본 보존
  ├── {artwork_id}_ugoira.zip.aru.json 메타데이터 sidecar
  └── {artwork_id}_ugoira.webp         animated WebP (Pillow 생성)
```

WebP 생성: `PIL.Image` → `save(format='WEBP', save_all=True, append_images=..., duration=delays, loop=0)`
WebP 메타데이터: piexif로 EXIF UserComment 삽입 (JPEG와 동일)

뷰어 우선순위: `.webp` 존재 시 QMovie 재생 → 없으면 ZIP 직접 프레임 재생

---

## 10. 폴더 구조 (런타임)

```
D:/AruArchive/
├── Inbox/
│   └── pixiv/
│       ├── 141100516_p0.jpg
│       ├── 141100516_p1.jpg
│       ├── 141100517_ugoira.zip
│       ├── 141100517_ugoira.zip.aru.json
│       └── 141100517_ugoira.webp
├── Classified/
│   ├── 작가/
│   │   └── 作家名/
│   │       ├── 141100516_p0.jpg
│   │       └── 141100516_p1.jpg
│   └── 캐릭터/
│       └── キャラ名/
│           └── 141100516_p0.jpg
├── aru_archive.db
└── config.json
```

---

## 11. 기술 스택

| 영역 | 기술 | 버전 |
|------|------|------|
| 메인 앱 UI | PySide6 | 6.x |
| HTTP 클라이언트 | httpx | 0.27+ |
| JPEG EXIF | piexif | 1.1.x |
| 이미지 처리 | Pillow | 10.x |
| DB | SQLite3 | 내장 |
| 패키징 | PyInstaller | 6.x |
| 브라우저 확장 | Manifest V3 | Chrome/Whale |

---

## 12. 개발 Phase

| Phase | 작업 | 핵심 파일 |
|-------|------|-----------|
| 1 | 메타데이터 읽기/쓰기 모듈 | `core/metadata_writer.py` |
| 2 | 우고이라 변환기 | `core/ugoira_converter.py` |
| 3 | Native Host + Pixiv 어댑터 | `native_host/`, `core/adapters/pixiv.py` |
| 4 | 브라우저 확장 | `extension/` |
| 5 | 분류 엔진 + SQLite | `core/classifier.py`, `db/` |
| 6 | PySide6 메인 앱 | `app/` |
| 7 | 패키징 + 설치 스크립트 | `build/`, `install_host.bat` |

---

## 13. 미결 사항 (추후 결정 필요)

- 저장 완료 후 Inbox 파일의 자동 정리 정책 (보존 vs 기간 후 삭제)
- 동일 작품 재다운로드 시 중복 처리 방식 (file_hash 비교 기반)
- 분류 규칙 충돌 시 다중 분류 폴더 지원 여부
- X(트위터) 어댑터 추가 시점 및 우선순위

---

*이 문서는 AI 코드 생성 요청 시 컨텍스트로 첨부하기 위한 설계 요약입니다.*
