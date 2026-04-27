# Aru Archive — 개발 환경 이관 핸드오프

> 이 문서는 개발 PC를 변경할 때 새 Claude 인스턴스가 프로젝트를 즉시 파악하고
> 작업을 이어받을 수 있도록 작성한 핸드오프 문서입니다.

---

## 1. 프로젝트 개요

개인 아트워크 아카이브 관리 도구. Pixiv 등 소스에서 수집한 파일을 메타데이터 기반으로 분류·관리합니다.

| 항목 | 값 |
|------|----|
| 언어 | Python 3.12+ (현 환경: 3.14.4) |
| GUI | **PyQt6 전용** — PySide6 사용 절대 금지 |
| DB | SQLite (WAL 모드, FK 활성화) |
| 플랫폼 | Windows 11 |
| 버전 | v0.4.0 |
| 테스트 | pytest, 현재 **959개 통과** (952 passed + 7 skipped) |

### 핵심 의존성

```
PyQt6==6.11.0
Pillow==12.2.0
httpx==0.28.1
piexif==1.1.3
pytest==9.0.3
```

---

## 2. 개발 환경 세팅 절차

```bash
# 1. 저장소 클론 후 의존성 설치
pip install -r requirements.txt

# 2. config 설정
cp config.example.json config.json
# config.json의 data_dir, inbox_dir, db.path를 로컬 경로로 수정

# 3. 테스트 실행 (headless)
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q

# 4. 앱 실행
python main.py
```

### Windows에서 테스트 실행 시

```powershell
# PowerShell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/ -q

# 또는 한 줄로
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

---

## 3. 프로젝트 디렉터리 구조

```
aru_archive/
├── main.py                        # GUI 진입점
├── config.json                    # 로컬 설정 (Git 제외)
├── config.example.json            # 설정 템플릿
├── requirements.txt
│
├── app/
│   ├── main_window.py             # 메인 윈도우, 툴바, 이벤트 핸들러
│   ├── views/
│   │   ├── gallery_view.py        # 갤러리 (다중 선택 포함)
│   │   ├── detail_view.py         # 상세 패널
│   │   ├── workflow_wizard_view.py # 9단계 작업 마법사
│   │   ├── dictionary_import_view.py # 사전 가져오기 (Danbooru/Safebooru/Localized)
│   │   ├── tag_candidate_view.py  # 태그 후보 검토
│   │   ├── delete_preview_dialog.py  # 삭제 미리보기 (HIGH risk: DELETE 입력)
│   │   ├── visual_duplicate_review_dialog.py  # 시각적 중복 리뷰
│   │   ├── canonical_merge_dialog.py
│   │   ├── batch_classify_dialog.py
│   │   └── classify_dialog.py
│   └── widgets/
│       ├── sidebar.py
│       └── log_panel.py
│
├── core/
│   ├── config_manager.py          # 설정 로드/저장, _DEFAULTS
│   ├── classifier.py              # 단일 파일 분류
│   ├── batch_classifier.py        # 일괄 분류 + 미리보기
│   ├── tag_classifier.py          # 태그 분류 엔진
│   ├── tag_reclassifier.py        # 전체 재분류
│   ├── tag_pack_loader.py         # Tag Pack seed/import (localized 포함)
│   ├── tag_pack_exporter.py       # Tag Pack export
│   ├── tag_merge.py               # alias 병합
│   ├── tag_variant.py             # variant suffix 분리
│   ├── tag_normalize.py           # 태그 정규화
│   ├── tag_localizer.py           # resolve_display_name
│   ├── tag_candidate_generator.py # 미분류 태그 후보 생성
│   ├── tag_candidate_actions.py   # 후보 승인/병합/거부
│   ├── external_dictionary.py     # 외부 사전 (Danbooru/Safebooru)
│   ├── duplicate_finder.py        # SHA-256 완전 중복 + scope 헬퍼
│   ├── visual_duplicate_finder.py # pHash 시각적 중복
│   ├── delete_manager.py          # 삭제 미리보기 + 실행 + 감사 기록
│   ├── inbox_scanner.py           # Inbox 스캔
│   ├── metadata_enricher.py       # Pixiv 메타데이터 보강
│   ├── metadata_writer.py         # AruArchive JSON + XMP 기록
│   ├── exiftool.py / exiftool_resolver.py  # ExifTool 연동
│   ├── xmp_retry.py               # XMP 재처리
│   ├── workflow_summary.py        # Wizard용 요약 함수들
│   └── dictionary_sources/
│       ├── danbooru_source.py
│       └── safebooru_source.py
│
├── db/
│   ├── database.py                # 초기화, migration 체인
│   └── schema.sql                 # 테이블 정의
│
├── tests/                         # pytest 테스트 스위트 (70개 파일, 959 테스트)
├── docs/                          # 설계 문서
├── resources/tag_packs/           # 내장 Tag Pack JSON
└── tools/                         # 유틸 스크립트
```

---

## 4. DB 테이블 목록

| 테이블 | 역할 |
|--------|------|
| `artwork_groups` | 작품 그룹 (source_site, artwork_id, 메타데이터) |
| `artwork_files` | 파일 레코드 (file_role, file_status, file_hash) |
| `tag_aliases` | canonical ↔ alias 매핑 (tag_type: series/character/general) |
| `tag_localizations` | canonical 다국어 표시명 (locale: ko/ja/en) |
| `tag_candidates` | 사용자 검토 대기 태그 후보 |
| `external_dictionary_entries` | Danbooru/Safebooru 스테이징 엔트리 |
| `thumbnail_cache` | 썸네일 경로 캐시 |
| `undo_entries` | 분류 실행 이력 (Undo용) |
| `delete_batches` | 삭제 배치 감사 기록 |
| `delete_records` | 파일별 삭제 결과 기록 |

### artwork_files.file_role 값

| role | 위치 |
|------|------|
| `original` | Inbox (원본) |
| `managed` | Managed |
| `classified_copy` | Classified (분류 결과 복사본) |
| `sidecar` | 메타데이터 사이드카 |

### artwork_files.file_status 값

`present` / `deleted` / `missing` / `xmp_write_failed` / 기타

---

## 5. 주요 정책 / 불변 규칙

### GUI
- **PyQt6만 사용.** `from PySide6` / `import PySide6` 절대 금지
- 검증 명령: `Select-String -Path .\* -Pattern "PySide6" -Recurse` → 0건이어야 함 (주석 제외)

### 삭제 정책
- 모든 삭제는 영구 삭제 (휴지통 없음, `Path.unlink()`)
- 삭제 전 반드시 `build_delete_preview → execute_delete_preview(confirmed=True)` 흐름
- HIGH risk (original 포함 또는 그룹이 비워짐): `DeletePreviewDialog`에서 `"DELETE"` 직접 입력 필요
- 감사 기록: `delete_batches` + `delete_records`

### 중복 검사 scope
- 기본값: `inbox_managed` (Inbox/Managed의 original/managed만)
- **Classified 복사본은 기본 제외** — 원본-복사본 오탐 방지
- `all_archive`는 고급 옵션. `config.duplicates.allow_all_archive_scan = true` + 경고 다이얼로그 확인 필요

### 태그 분류
- `_review.merge_candidate` / `variant_tag` / `possibly_general_or_group_tag` → 자동 병합 금지, report만
- external_dictionary_entries는 항상 staged → 사용자 승인 후 tag_aliases 승격
- classify 가능 상태: `full` | `json_only` | `xmp_write_failed`

---

## 6. 최근 완료 작업 (직전 세션)

### 세션 1 — Permanent Delete / Duplicate / Localized Tag Pack

| 기능 | 핵심 파일 |
|------|----------|
| 삭제 시스템 (미리보기·실행·감사) | `core/delete_manager.py`, `app/views/delete_preview_dialog.py` |
| 완전 중복 검사 (SHA-256) | `core/duplicate_finder.py` |
| 시각적 중복 검사 (pHash/Pillow) | `core/visual_duplicate_finder.py` |
| 시각적 중복 리뷰 UI | `app/views/visual_duplicate_review_dialog.py` |
| Localized Tag Pack Import | `core/tag_pack_loader.py` (`validate_localized_tag_pack`, `import_localized_tag_pack`) |
| DB migration | `db/database.py` (`delete_batches`, `delete_records`) |
| 툴바 버튼 3개 추가 | `app/main_window.py` (🗑 선택 삭제, 🧬 완전 중복, 👁 시각적 중복) |
| Wizard Step 3 중복 검사 | `app/views/workflow_wizard_view.py` |
| DictionaryImportView | `app/views/dictionary_import_view.py` (📦 Localized Tag Pack 가져오기) |
| 테스트 6개 파일 신규 | `tests/test_delete_manager.py` 외 5개 |
| 문서 신규/업데이트 | `docs/file-deletion.md`, `docs/duplicate-management.md` |

### 세션 2 — Duplicate Scope 기본값 개선

| 항목 | 내용 |
|------|------|
| `core/duplicate_finder.py` | `select_duplicate_candidate_files()` 공유 helper 추가; 7개 scope 상수; 기본값 `"archive"` → `"inbox_managed"` |
| `core/visual_duplicate_finder.py` | 공유 helper 재사용; 기본값 `"archive"` → `"inbox_managed"` |
| `core/config_manager.py` | `_DEFAULTS["duplicates"]` 섹션 추가 (`default_scope`, `allow_all_archive_scan` 등) |
| `app/main_window.py` | `_get_dup_scope()` 추가; all_archive 경고 다이얼로그 |
| `app/views/workflow_wizard_view.py` | `scope="inbox_managed"` 명시; 결과 레이블에 범위 표시 |
| `tests/test_duplicate_scope.py` | 신규 34개 테스트 |
| 문서 업데이트 | `docs/duplicate-management.md`, `docs/workflow-wizard.md`, `README.md` |

---

## 7. 현재 테스트 상태

```
959 테스트 (952 passed, 7 skipped)
PySide6 실제 import: 0건
```

실행 방법:
```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

---

## 8. config.json 스키마 요약

```json
{
  "schema_version": "1.0",
  "data_dir": "<Archive Root 절대경로>",
  "inbox_dir": "<data_dir>/Inbox",
  "classified_dir": "<data_dir>/Classified",
  "exiftool_path": null,
  "db": { "path": "<data_dir>/.runtime/aru.db" },
  "duplicates": {
    "default_scope": "inbox_managed",
    "max_exact_files_per_run": 1000,
    "max_visual_files_per_run": 300,
    "allow_all_archive_scan": false
  },
  "classification": {
    "folder_locale": "ko",
    "fallback_locale": "canonical",
    "enable_localized_folder_names": true,
    "fallback_by_author": true,
    "on_conflict": "rename"
  }
}
```

---

## 9. 남은 TODO / 로드맵

### 단기 (다음 세션에서 처리 가능)

| 우선순위 | 항목 |
|---------|------|
| 중 | `visual_duplicate_finder.py:50` — Pillow `getdata()` → `get_flattened_data()` deprecation 교체 (Pillow 14 이전까지 동작) |
| 중 | `current_view` scope MVP 구현 — 현재 inbox_managed fallback, 실제 갤러리 필터 연동 필요 |
| 중 | `selected` scope UI 연동 — 갤러리 다중 선택 항목으로 중복 검사 실행 |
| 낮 | 중복 검사 진행 표시 (config의 `show_progress_every` 활용) |

### 장기

| 항목 |
|------|
| Pixiv 쿠키 자동 수집 (R-18 저장 지원) |
| EXE 독립 배포 빌드 (PyInstaller) |
| CHARACTER_ALIASES / SERIES_ALIASES 추가 확장 |

---

## 10. 주요 문서 목록

| 문서 | 내용 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 전체 시스템 아키텍처, 데이터 흐름, DB 스키마 |
| [classification-policy.md](classification-policy.md) | 4-tier 분류 정책, 충돌 처리 |
| [tag-normalization.md](tag-normalization.md) | 태그 정규화 파이프라인, Localized Tag Pack Import |
| [workflow-wizard.md](workflow-wizard.md) | 9단계 작업 마법사 설명, 중복 검사 기본 범위 |
| [duplicate-management.md](duplicate-management.md) | 완전/시각적 중복 정책, scope 정의 |
| [file-deletion.md](file-deletion.md) | 영구 삭제 정책, 위험도 기준, 감사 기록 |
| [metadata-policy.md](metadata-policy.md) | 메타데이터 sync_status 값 |

---

## 11. 새 Claude 인스턴스에게 전달할 핵심 컨텍스트

새 세션 시작 시 아래 내용을 전달하면 즉시 작업 가능합니다.

```
프로젝트: Aru Archive — Python 3.12+, PyQt6, SQLite, Windows 11
버전: v0.4.0, 테스트 959개 통과

필수 규칙:
1. PyQt6만 사용. PySide6 import 절대 금지.
2. 테스트는 QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
3. 작업 후 PySide6 검색: Select-String -Path .\* -Pattern "PySide6" -Recurse → 0건

최근 완료:
- Permanent Delete (delete_manager.py, delete_preview_dialog.py)
- Exact/Visual Duplicate Cleanup (duplicate_finder.py, visual_duplicate_finder.py)
- Localized Tag Pack Import (tag_pack_loader.py: validate/import_localized_tag_pack)
- Duplicate Scope 기본값 inbox_managed 변경 (Classified 제외)
- 관련 테스트 및 docs 업데이트

현재 잔여 TODO:
- Pillow getdata() → get_flattened_data() deprecation 교체
- current_view scope 실제 구현 (현재 inbox_managed fallback)
- selected scope UI 연동 (갤러리 다중 선택 → 중복 검사)

docs/handoff.md 파일에 전체 이관 정보 있음.
```
