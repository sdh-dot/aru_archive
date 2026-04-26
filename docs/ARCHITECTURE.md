# Aru Archive — Architecture

**Version:** 0.3.0 | **Protocol:** Native Messaging v2

---

## 1. 시스템 개요

```
┌─────────────────────────────────────────┐
│  Pixiv Web (pixiv.net)                  │
│  작품 페이지 / 이미지 서버              │
└─────────────────┬───────────────────────┘
                  │ 사용자 브라우저에서 열람
                  ▼
┌─────────────────────────────────────────┐
│  Browser Extension (MV3)                │
│  extension/popup/          — 저장 UI    │
│  extension/content_scripts/ — ID 추출   │
│  extension/background/      — SW 라우터 │
└─────────────────┬───────────────────────┘
                  │ Native Messaging (stdio)
                  │ 4-byte length + UTF-8 JSON
                  ▼
┌─────────────────────────────────────────┐
│  Native Host  (native_host/)            │
│  host.py     — 프로토콜 v2 메인 루프   │
│  handlers.py — 액션별 진입 처리        │
└─────────────────┬───────────────────────┘
                  │ Python 함수 호출
                  ▼
┌─────────────────────────────────────────┐
│  CoreWorker  (core/worker.py)           │
│  1. fetch_metadata (Pixiv AJAX)         │
│  2. fetch_pages (이미지 URL 목록)       │
│  3. download_pixiv_image                │
│  4. write_aru_metadata (JSON embed)     │
│  5. _register_file → DB                 │
│  6. _sync_tags                          │
│  7. tag_observations + candidates       │
│  8. _generate_cover_thumbnail           │
│  9. UPDATE save_jobs (completed/…)      │
└──────┬──────────────────────┬───────────┘
       │                      │
       ▼                      ▼
┌─────────────┐   ┌───────────────────────┐
│  SQLite DB  │   │  Archive Root (FS)    │
│  aru.db     │   │  Inbox/    ← 저장     │
│             │   │  Managed/  ← 변환본   │
│             │   │  Classified/ ← 분류   │
└─────────────┘   └───────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│  PyQt6 Main App  (app/)                 │
│  GalleryView     — 아트워크 브라우저   │
│  WorkLogView     — Undo / 작업 이력    │
│  TagCandidateView— 태그 정규화 UI      │
│  SaveJobsView    — 저장 작업 모니터    │
│  main_window.py  — 액션 조율           │
└─────────────────────────────────────────┘
```

---

## 2. 컴포넌트별 책임

### Browser Extension

| 파일 | 책임 |
|------|------|
| `extension/content_scripts/pixiv.js` | artwork_id 추출 (URL 파싱, DOM 독립) |
| `extension/background/service_worker.js` | Native 포트 관리, 메시지 라우팅, 컨텍스트 메뉴 |
| `extension/popup/popup.js` | 저장 버튼, 폴링(`pollJobStatus`), 상태 표시 |

### Native Host

| 파일 | 책임 |
|------|------|
| `native_host/host.py` | 프로토콜 v2 루프, 로깅 (`stderr`+파일, stdout 전용 NM) |
| `native_host/handlers.py` | `handle_save_pixiv_artwork()` — DB 열고 CoreWorker 호출 |

### CoreWorker

| 모듈 | 책임 |
|------|------|
| `core/worker.py` | 저장 파이프라인 오케스트레이션 |
| `core/pixiv_downloader.py` | httpx 스트리밍 다운로드, tmp→rename |
| `core/adapters/pixiv.py` | Pixiv AJAX API 래퍼, `AruMetadata` 변환 |
| `core/metadata_writer.py` | AruArchive JSON을 이미지 파일에 임베딩 |

### PyQt6 Main App

| 모듈 | 책임 |
|------|------|
| `app/main_window.py` | 툴바 액션, 뷰 전환, 백그라운드 스레드 조율 |
| `app/views/gallery_view.py` | 아트워크 그룹 썸네일 목록 |
| `app/views/work_log_view.py` | `copy_records` / `undo_entries` 테이블 + Undo 실행 |
| `app/views/tag_candidate_view.py` | 태그 후보 승인/거부 UI |
| `app/views/save_jobs_view.py` | 저장 작업 진행 상황 모니터 |

### 분류 / 태그

| 모듈 | 책임 |
|------|------|
| `core/classifier.py` | 4-tier 경로 결정, 복사 실행, `copy_records` 기록 |
| `core/tag_classifier.py` | 태그를 `general` / `series` / `character`로 분류 |
| `core/tag_observer.py` | 작품별 태그 등장 기록 (`tag_observations`) |
| `core/tag_candidate_generator.py` | 정규화 후보 자동 생성 (`tag_candidates`) |
| `core/tag_candidate_actions.py` | 후보 승인 → `tag_aliases` / 거부 → suppressed |
| `core/undo_manager.py` | 안전 Undo 평가·실행 (원본·managed 파일 보호) |

---

## 3. 데이터 흐름

### 저장 (브라우저 → Inbox)

```
사용자 클릭
  → Extension popup.js: save_request 메시지
    → service_worker.js: sendNative("save_pixiv_artwork", payload)
      → native_host/host.py: 수신 → handle_save_pixiv_artwork(payload)
        → core/worker.py: save_pixiv_artwork()
          → Pixiv AJAX API: fetch metadata + page URLs
          → core/pixiv_downloader.py: 이미지 다운로드 → Inbox/
          → core/metadata_writer.py: AruArchive JSON embed
          → db: artwork_groups, artwork_files, save_jobs, tags 기록
          → core/thumbnail_manager.py: 커버 썸네일
        → 응답: {job_id, saved, total, failed}
      → service_worker.js: resolve(data)
    → popup.js: pollJobStatus() 1초 폴링 → 완료 표시
```

### 분류 (Inbox → Classified)

```
PyQt6: [분류 미리보기]
  → core/classifier.py: generate_preview()
    → DB 조회: artwork_groups.series/character/artist
    → 4-tier 경로 결정
  → 사용자 확인 → [실행]
    → classifier.py: copy_to_classified()
      → 파일 복사
      → DB: copy_records INSERT
      → DB: undo_entries INSERT (해시·mtime 기록)
```

### Undo

```
WorkLogView: [Undo] 클릭
  → core/undo_manager.py: evaluate_undo()
    → dest 파일 해시 + mtime 검증
    → 원본/managed 파일 삭제 여부 검사 (보호)
  → 사용자 확인
    → execute_undo(): Classified 복사본만 삭제
    → DB: undo_entries.undo_status = completed
```

---

## 4. DB 테이블 구조 요약

| 테이블 | 역할 |
|--------|------|
| `artwork_groups` | 작품 단위 메타데이터 (제목·작가·태그·분류 상태) |
| `artwork_files` | 파일 단위 레코드 (경로·해시·크기·sync_status) |
| `tags` | 정규화된 태그 저장 |
| `tag_aliases` | raw tag → canonical alias 매핑 |
| `tag_observations` | 작품별 태그 등장 이력 |
| `tag_candidates` | 정규화 후보 큐 (confidence_score 포함) |
| `save_jobs` | 저장 작업 생명주기 |
| `job_pages` | 페이지별 다운로드 결과 |
| `copy_records` | 분류 복사 이력 |
| `undo_entries` | 안전 Undo 레코드 (해시·mtime·만료일) |
| `locks` | 분산 잠금 (동일 artwork_id 중복 저장 방지) |

---

## 5. 파일 시스템 구조 (Archive Root)

```
Archive Root/
├── Inbox/                 ← CoreWorker가 저장하는 위치
│   ├── 103192368_p0.jpg
│   └── 103192368_p1.jpg
├── Managed/               ← BMP→PNG, GIF→WebP 변환본
│   └── 103192368_p0_managed.png
├── Classified/            ← 분류 복사본
│   └── BySeries/
│       └── {시리즈}/
│           └── {캐릭터}/
│               └── 103192368_p0.jpg
├── Thumbnails/            ← 썸네일 캐시
│   └── {group_id}.webp
└── .runtime/
    └── aru.db             ← SQLite DB
```

---

## 6. 버전 상수

`core/version.py` 참고:

| 상수 | 현재 값 |
|------|---------|
| `APP_VERSION` | 0.3.0 |
| `EXTENSION_VERSION` | 0.3.0 |
| `NATIVE_PROTOCOL_VERSION` | 2 |
| `DB_SCHEMA_VERSION` | 1 |
| `ARU_METADATA_SCHEMA_VERSION` | 1.0 |
