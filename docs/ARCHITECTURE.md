# Aru Archive Architecture

## 개요

Aru Archive는 브라우저 확장, Native Host, Python 코어, PyQt6 데스크톱 앱으로 구성됩니다.

- 브라우저 확장: Pixiv 페이지에서 저장 요청 생성
- Native Host: 브라우저와 로컬 Python 사이 프로토콜 처리
- Core: 다운로드, 메타데이터 기록, 스캔, 분류, 중복 점검
- PyQt6 App: 갤러리, 분류 미리보기, 작업 로그, 설정 UI 제공

## 주요 구성 요소

### Browser Extension

- `extension/content_scripts/pixiv.js`
- `extension/background/service_worker.js`
- `extension/popup/popup.js`

역할:

- `artwork_id` 추출
- Native Messaging 요청 전송
- 저장 상태 폴링 및 표시

### Native Host

- `native_host/host.py`
- `native_host/handlers.py`

역할:

- 프로토콜 v2 처리
- 요청 라우팅
- `core.worker` 진입

### Core

- `core/worker.py`
- `core/inbox_scanner.py`
- `core/classifier.py`
- `core/duplicate_finder.py`
- `core/visual_duplicate_finder.py`
- `core/metadata_writer.py`

역할:

- Pixiv 다운로드
- 메타데이터 기록
- Inbox 스캔
- 분류 미리보기 / 실행
- 중복 검사
- 썸네일 생성

### PyQt6 App

- `app/main_window.py`
- `app/views/workflow_wizard_view.py`
- `app/views/work_log_view.py`
- `app/views/tag_candidate_view.py`

역할:

- 작업 폴더 설정
- 갤러리 / 상세 보기
- 분류 실행 및 Undo
- 후보 태그 검토

## 데이터 흐름

### 저장

1. 사용자가 브라우저 확장에서 저장 요청
2. Native Host가 요청 수신
3. `core.worker.save_pixiv_artwork()` 실행
4. 원본 파일을 `inbox_dir`에 저장
5. 메타데이터를 기록하고 DB 반영
6. 필요 시 썸네일 생성

### 스캔

1. 사용자가 앱에서 Inbox 스캔 실행
2. `core.inbox_scanner.InboxScanner`가 `inbox_dir` 순회
3. 원본 파일 등록
4. BMP / animated GIF는 `managed_dir`에 관리본 생성
5. 그룹 / 파일 / 상태 정보를 DB에 반영

### 분류

1. 사용자가 분류 미리보기 생성
2. `core.classifier`가 대상 경로 계산
3. 사용자가 실행 확인
4. 결과 복사본을 `classified_dir`에 생성
5. Undo 이력 기록

## 경로 모델

현재 경로 모델은 “앱 내부 데이터”와 “사용자 작업 폴더”를 분리합니다.

### 앱 내부 데이터

- `data_dir`
- 기본값: `C:\Users\<user>\AruArchive`

저장 내용:

- `.runtime`
- `.thumbcache`
- `logs`
- SQLite DB
- IPC 토큰 등 런타임 파일

### 사용자 작업 폴더

- `inbox_dir`: 사용자가 고른 분류 대상 폴더
- `managed_dir`: BMP/GIF 변환 등 관리본 저장 폴더
- `classified_dir`: 분류 결과 복사본 저장 폴더

예:

```text
C:/Users/<user>/AruArchive/     <- data_dir
├── .runtime/
├── .thumbcache/
└── logs/

D:/PixivInbox/                  <- inbox_dir

D:/Managed/                     <- managed_dir

D:/Classified/                  <- classified_dir
```

첫 실행 시 사용자가 `D:\PixivInbox`를 선택하면:

- `inbox_dir = D:\PixivInbox`
- `managed_dir = D:\Managed`
- `classified_dir = D:\Classified`
- `data_dir = C:\Users\<user>\AruArchive`

## DB 요약

주요 테이블:

- `artwork_groups`
- `artwork_files`
- `tags`
- `tag_aliases`
- `tag_candidates`
- `save_jobs`
- `job_pages`
- `copy_records`
- `undo_entries`
- `delete_batches`
- `delete_records`

## 파일 역할

- `original`: Inbox의 원본 파일
- `managed`: Managed의 관리본 파일
- `classified_copy`: Classified의 분류 결과 복사본
- `sidecar`: 보조 메타데이터 파일

## 설계 포인트

- 원본은 이동하지 않고 보존
- 분류는 복사 기반
- Undo는 Classified 복사본만 대상으로 함
- 중복 검사의 기본 범위는 `Inbox / Managed`
- Classified 복사본은 기본적으로 중복 검사 제외
