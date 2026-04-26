# Aru Archive

개인 아트워크 아카이브 관리 도구.
Pixiv 등 소스에서 수집한 파일을 메타데이터 기반으로 분류·관리합니다.

**플랫폼:** Windows 11 · Python 3.12+ · PyQt6 · SQLite

---

## 아이콘

| 항목 | 내용 |
|------|------|
| 원본 파일 | `docs/icon.png` |
| 배포용 ICO | `app/resources/icons/aru_archive_icon.ico` (16·32·48·64·128·256 px 멀티사이즈) |
| 변환 도구 | Pillow (`PIL.Image.resize + Image.save(format="ICO")`) |
| 적용 범위 | QApplication 전역 아이콘, QMainWindow 타이틀바·태스크바, PyInstaller EXE 아이콘 |

---

## 프로젝트 구조

| 경로 | 역할 |
|------|------|
| `main.py` | GUI/헤드리스 실행 진입점, 설정 로드, 로깅 초기화 |
| `app/` | PyQt6 데스크톱 UI, 갤러리·상세·분류 미리보기 화면 |
| `core/` | 파일 스캔, 메타데이터 읽기/쓰기, Pixiv 보강, 태그/경로 분류 엔진 |
| `db/` | SQLite 초기화 코드와 스키마 |
| `extension/` | 브라우저 확장 MVP 코드 |
| `native_host/` | 브라우저 확장과 로컬 앱 사이의 Native Messaging 진입점 |
| `tests/` | 핵심 정책과 GUI smoke 테스트 |
| `docs/` | 설계안, 정책 패치, 아키텍처 메모 |

더 자세한 내부 흐름은 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고하세요.

---

## 설치

```bash
pip install -r requirements.txt
```

---

## 실행

```bash
# GUI 모드 (기본)
python main.py

# 설정 파일 지정
python main.py --config path/to/config.json

# 헤드리스 서버 모드
python main.py --headless
```

---

## 테스트

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

---

## 수동 테스트 절차

### Pixiv 메타데이터 보강 수동 테스트

1. `python main.py` 실행
2. 상단 툴바 [📁 Archive Root 선택] 클릭 → 아카이브 루트 폴더 선택
3. [🔍 Inbox 스캔] 클릭 → Pixiv 파일명 형식(`{artwork_id}_p{n}.ext`)의 파일 스캔
4. 갤러리에서 `⏳ Pending` 또는 `❓ NoMeta` 상태 파일 선택
5. 우측 상세 패널 → [🌐 Pixiv 메타데이터 가져오기] 클릭
6. 로그 패널에서 fetch 진행 상황 확인
7. 완료 후 상세 패널 Status가 `🟡 JSON Only`로 변경되었는지 확인
8. 제목·작가·태그가 상세 패널에 표시되는지 확인

---

### 분류 엔진 수동 테스트

1. `python main.py` 실행
2. 상단 툴바 [📁 Archive Root 선택] 클릭 → 아카이브 루트 폴더 선택
3. [🔍 Inbox 스캔] 클릭
4. Pixiv 메타데이터 가져오기로 파일 Status를 `json_only` 상태로 만들기
5. 갤러리에서 `🟡 JSON Only` 상태 파일 선택
6. 상단 툴바 [📋 분류 미리보기] 클릭
7. 다이얼로그에서 복사 예정 경로 확인:
   - `Classified/BySeries/{series}/{character}/filename` (시리즈+캐릭터 태그가 있는 경우)
   - `Classified/BySeries/{series}/_uncategorized/filename` (시리즈 태그만 있는 경우)
   - `Classified/ByCharacter/{character}/filename` (캐릭터 태그만 있는 경우)
   - `Classified/ByAuthor/{artist}/filename` (시리즈/캐릭터 태그가 없는 경우)
8. [실행] 클릭
9. 로그 패널에서 복사 결과 확인:
   ```
   [INFO] Copied: ...ByAuthor/작가명/file.jpg
   [INFO] Classification completed: N copied, 0 skipped
   ```
10. 파일 시스템에서 `Classified/` 폴더에 파일이 복사되었는지 확인
11. 갤러리 카드 상태가 `classified`로 변경되었는지 확인
12. 좌측 카테고리 카운터가 갱신되었는지 확인

#### DB 확인 (선택)

SQLite 브라우저 또는 sqlite3 CLI로 확인:

```sql
-- 분류 기록 확인
SELECT * FROM copy_records ORDER BY copied_at DESC LIMIT 10;

-- classified_copy 파일 확인
SELECT file_path, file_role, created_at
FROM   artwork_files
WHERE  file_role = 'classified_copy'
ORDER  BY created_at DESC LIMIT 10;

-- undo 항목 확인
SELECT entry_id, operation_type, undo_status, performed_at
FROM   undo_entries
ORDER  BY performed_at DESC LIMIT 5;
```

---

## config.json 예시

```json
{
  "data_dir": "F:/AruArchive",
  "inbox_dir": "F:/AruArchive/Inbox",
  "classified_dir": "F:/AruArchive/Classified",
  "undo_retention_days": 7,
  "db": {
    "path": "F:/AruArchive/.runtime/aru.db"
  },
  "classification": {
    "primary_strategy": "series_character",
    "enable_series_character": true,
    "enable_series_uncategorized": true,
    "enable_character_without_series": true,
    "fallback_by_author": true,
    "enable_by_author": false,
    "enable_by_tag": false,
    "on_conflict": "rename"
  }
}
```

---

## 분류 정책

| 조건 | 동작 |
|------|------|
| `full` / `json_only` / `xmp_write_failed` | 분류 가능 |
| `metadata_missing` / `pending` / 실패 계열 | 분류 제외 |
| BMP original | 직접 분류 금지 (PNG managed 생성 후 재시도) |
| managed 파일 존재 | managed 우선 복사 |
| 시리즈 + 캐릭터 태그 존재 | `Classified/BySeries/{series}/{character}/filename` |
| 시리즈만 존재 | `Classified/BySeries/{series}/_uncategorized/filename` |
| 캐릭터만 존재 | `Classified/ByCharacter/{character}/filename` |
| 시리즈/캐릭터 없음 | `Classified/ByAuthor/{artist}/filename` fallback |
| `on_conflict=rename` | `filename_1.ext`, `filename_2.ext` … |
| `on_conflict=skip` | 기존 파일 유지, 복사 생략 |

### 분류 우선순위 (4-tier)

| 우선순위 | 조건 | 목적지 경로 | rule_type |
|--------|------|------------|-----------|
| 1 | series_tags + character_tags 모두 있음 | `BySeries/{series}/{char}/` | `series_character` |
| 2 | series_tags만 있음 | `BySeries/{series}/_uncategorized/` | `series_uncategorized` |
| 3 | character_tags만 있음 | `ByCharacter/{char}/` | `character` |
| 4 | series/char 모두 없음 + `fallback_by_author=true` | `ByAuthor/{artist}/` | `author_fallback` |
| 추가 | `enable_by_author=true` (항상 추가) | `ByAuthor/{artist}/` | `author` |
| 추가 | `enable_by_tag=true` | `ByTag/{tag}/` | `by_tag` |

### 태그 자동 분류 (core/tag_classifier.py)

Pixiv 태그를 3가지로 분류:
- **series_tags**: `SERIES_ALIASES` 매칭 → canonical 시리즈명 (예: ブルアカ → "Blue Archive")
- **character_tags**: `CHARACTER_ALIASES` 매칭 → canonical 캐릭터명 + 연관 시리즈 자동 추가
- **tags**: 분류되지 않은 일반 태그

`[🏷 태그 재분류]` 툴바 버튼으로 기존 태그를 재분류할 수 있습니다.

---

## 태그 정규화 시스템

**원칙: 자동 확정 금지. 자동 후보 생성만 수행. 최종 확정은 사용자 승인 기반.**

### 흐름 (5단계)

| 단계 | 동작 | 관련 모듈 |
|------|------|-----------|
| 1 | Pixiv 메타데이터 보강 시 raw 태그를 `tag_observations`에 기록 | `core/tag_observer.py` |
| 2 | 관측 데이터를 분석하여 신뢰도 점수가 있는 후보를 `tag_candidates`에 생성 | `core/tag_candidate_generator.py` |
| 3 | `[🏷 후보 태그]` 버튼으로 후보 검토 다이얼로그 열기 | `app/views/tag_candidate_view.py` |
| 4 | 사용자가 [✅ 승인] / [❌ 거부] / [⏭ 무시] 선택 | `core/tag_candidate_actions.py` |
| 5 | 승인된 항목이 `tag_aliases`에 등록되고 다음 `[🏷 태그 재분류]`부터 적용 | `core/tag_classifier.py` |

### 신뢰도 점수 계산

| 조건 | 점수 변화 |
|------|-----------|
| 기본 | +0.20 |
| 기지 시리즈와 함께 등장 | +0.30 |
| 관측 횟수 ≥ 3 | +0.20 |
| 번역 태그 존재 | +0.20 |
| 여러 시리즈에 걸쳐 등장 | -0.30 |
| `GENERAL_TAG_BLACKLIST` 포함 | -0.50 |

### DB 테이블

| 테이블 | 역할 |
|--------|------|
| `tag_observations` | artwork당 raw_tag별 관측 기록 (UNIQUE per artwork+tag) |
| `tag_candidates` | 후보 목록 (pending → accepted / rejected / ignored) |
| `tag_aliases` | 확정된 alias (복합 PK: alias + tag_type + parent_series) |

---

## 작업 로그와 Undo

분류 실행 시 Aru Archive는 `copy_records`와 `undo_entries`를 생성합니다.  
`[🕘 작업 로그]` 툴바 버튼으로 최근 분류 작업을 확인하고 Undo할 수 있습니다.

### Undo 원칙

**Undo 기능은 Classified 폴더에 생성된 복사본만 삭제합니다.**

삭제하지 않는 항목:
- Inbox 원본 (`original` 역할)
- managed 파일 (`managed` 역할)
- sidecar 파일 (`sidecar` 역할)
- copy_records 이력 (삭제 후에도 보존)

수정된 복사본은 삭제 전 경고 다이얼로그를 표시합니다.

### Undo 상태

| undo_status | 의미 | UI 표시 |
|-------------|------|---------|
| `pending`   | Undo 가능 | "Undo 가능" |
| `completed` | 모든 복사본 삭제 완료 | "Undo 완료" |
| `partial`   | 일부만 삭제 완료 | "일부 완료" |
| `failed`    | Undo 실패 | "Undo 실패" |
| `expired`   | 보존 기간 만료 | "Undo 만료" |

기본 Undo 보존 기간: **7일** (`undo_retention_days` 설정)

만료 후 B-2 정책: `dest_hash_at_copy` / `dest_mtime_at_copy` → NULL (이력은 보존)

### 수동 테스트 절차

1. `python main.py` 실행
2. Archive Root 선택 → Inbox 스캔
3. Pixiv 메타데이터 보강 (Status → `json_only`)
4. [📋 분류 미리보기] → [▶ 분류 실행]
5. `Classified/` 폴더에 복사본 생성 확인
6. `[🕘 작업 로그]` 클릭
7. 방금 작업 선택 → [⏪ Undo] 클릭
8. 확인 다이얼로그에서 삭제 대상 확인 → [Yes]
9. 복사본이 삭제되었는지 확인
10. Inbox 원본은 그대로인지 확인
11. DB에서 copy_records 이력이 남아 있는지 확인:
    ```sql
    SELECT * FROM copy_records ORDER BY copied_at DESC LIMIT 10;
    SELECT undo_status FROM undo_entries ORDER BY performed_at DESC LIMIT 5;
    ```

---

## Browser Extension + Native Messaging (MVP-C)

Pixiv 브라우저 페이지에서 바로 Aru Archive로 저장하는 확장 프로그램입니다.

### 구성 요소

| 경로 | 역할 |
|------|------|
| `extension/` | Chrome / Naver Whale MV3 확장 (popup + content_script + service_worker) |
| `native_host/host.py` | Native Messaging Host 메인 루프 |
| `native_host/handlers.py` | 액션 핸들러 — CoreWorker 호출 |
| `core/worker.py` | Pixiv 저장 파이프라인 (다운로드 → DB 기록 → 태그 → 썸네일) |
| `core/pixiv_downloader.py` | httpx 기반 이미지 다운로더 (임시 파일 → rename) |
| `build/install_host.bat` | Windows HKCU 레지스트리 등록 스크립트 |

### 프로토콜 v2

```
요청: {"action": "...", "request_id": "...", "payload": {...}}
응답: {"success": bool, "request_id": "...", "data": {...}}
      {"success": false, "request_id": "...", "error": "..."}
```

| 액션 | 설명 |
|------|------|
| `ping` | 연결 확인 |
| `save_pixiv_artwork` | artwork_id + cookies + preload_data로 저장 |
| `get_config_summary` | data_dir / inbox_dir / db_path 반환 |
| `open_main_app` | Aru Archive GUI 실행 |
| `get_job_status` | save_jobs 상태 조회 |

### 설치

1. Chrome / Whale에 확장 로드
   - Chrome: `chrome://extensions` → 개발자 모드 ON → `extension/` 폴더 로드 → **확장 ID 복사**
   - Whale: `whale://extensions` → 개발자 모드 ON → `extension/` 폴더 로드 → **확장 ID 복사**
2. Native Host 설치 (관리자 권한 불필요):
   ```bat
   :: Chrome 전용 (확장 ID 포함 — 권장)
   build\install_host.bat chrome <extension_id>

   :: Whale 전용
   build\install_host.bat whale <extension_id>

   :: Chrome + Whale 동시
   build\install_host.bat both <extension_id>

   :: 확장 ID 없이 우선 설치 (allowed_origins에 PLACEHOLDER가 남아 연결 불가)
   build\install_host.bat
   ```
3. 브라우저를 재시작하면 확장이 Native Host를 인식합니다.

> **확장 ID가 바뀐 경우:** 확장을 삭제 후 재설치하면 ID가 변경됩니다.  
> `install_host.bat chrome <new_id>` 를 다시 실행하세요.

### 저장 흐름

1. Pixiv 작품 페이지에서 팝업 → **저장** 클릭 (또는 우클릭 → "Aru Archive에 저장")
2. content_script가 artwork_id + preload_data 수집
3. service_worker → native host → CoreWorker 파이프라인 실행
4. Pixiv AJAX API로 메타데이터 + 이미지 URL 취득
5. 이미지를 Inbox에 다운로드, AruArchive JSON 임베딩
6. `artwork_groups` / `artwork_files` / `tags` / `tag_observations` DB 기록
7. 썸네일 생성
8. 팝업에 job_id 표시 — GUI `[💾 저장 작업]` 버튼으로 진행 상황 확인

### 쿠키 제한 사항

MVP-C에서는 **브라우저 쿠키를 자동으로 수집하지 않습니다.**  
`PHPSESSID` 세션 쿠키가 없으면 R-18 작품 또는 팔로워 전용 작품은 `HTTP 403` 오류로 저장 실패합니다.

| 상황 | 결과 |
|------|------|
| 공개 작품 | 쿠키 없이 저장 가능 |
| R-18 / 팔로워 전용 작품 | 쿠키 전달 구현 전까지 저장 불가 (향후 개선 예정) |

---

### 수동 테스트 체크리스트

#### 준비

- [ ] `python main.py` 실행 → GUI 정상 표시
- [ ] `build/install_host.bat chrome <extension_id>` 실행 → "Chrome 등록 완료" 메시지 확인
- [ ] 브라우저에서 확장 아이콘이 표시되는지 확인

#### 연결 테스트

- [ ] Pixiv 작품 페이지 (`https://www.pixiv.net/artworks/...`) 접속
- [ ] 팝업 → **연결 테스트** 클릭 → "연결 성공 ✓" 표시 확인
- [ ] **연결 테스트** (앱 미실행 상태) → "Aru Archive 앱이 실행 중인지 확인하세요" 오류 표시 확인

#### 저장 테스트

- [ ] Pixiv 공개 작품 페이지에서 팝업 → **저장** 클릭
- [ ] 팝업 상태가 "저장 중… N/M 페이지"로 업데이트되는지 확인
- [ ] 완료 후 "저장 완료 (N페이지)" 표시 확인
- [ ] GUI `[💾 저장 작업]` → 해당 job이 "완료" 상태인지 확인
- [ ] `[📂 폴더 열기]` → Inbox 폴더에 이미지가 저장되었는지 확인
- [ ] `[🌐 작품 페이지]` → 브라우저에서 Pixiv 작품 페이지가 열리는지 확인
- [ ] 우클릭 컨텍스트 메뉴 "Aru Archive에 저장"으로도 동일하게 저장되는지 확인

#### 실패 테스트

- [ ] 존재하지 않는 artwork_id URL에서 저장 시도 → "저장 실패" 표시 확인
- [ ] GUI `[💾 저장 작업]` → 해당 job이 "실패" 상태인지 확인
- [ ] `[📋 실패 로그 복사]` → 클립보드에 오류 내용이 복사되는지 확인

---

### save_jobs 확인

```sql
SELECT job_id, artwork_id, status, saved_pages, total_pages, started_at
FROM   save_jobs
ORDER  BY started_at DESC LIMIT 10;

SELECT page_index, filename, status, download_bytes
FROM   job_pages
WHERE  job_id = '<job_id>'
ORDER  BY page_index;
```
