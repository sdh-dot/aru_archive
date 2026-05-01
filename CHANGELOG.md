# Changelog

All notable changes to Aru Archive are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.5.1] — 2026-05-01

### Changed

**Visual Duplicate UX 개선 (PR #41, #43)**
- 파일 크기 표시를 byte에서 MB 단위로 변경.
- 자동 keep/delete 추천 근거(이유)를 카드별로 표시.
- 자동 추천 라벨과 수동 선택 라벨 분리 (`추천: 유지` / `✓ 유지` 등).
- keep/delete 영문·한글 혼재 표현을 한국어로 통일 (`삭제 후보` 표현으로 final-state와 명확히 구분).
- 삭제 미리보기 이동 버튼에 "실제 삭제 전 단계" tooltip 추가.

**UI 라벨·tooltip 정리 (PR #42, #44, #45, #46)**
- Manual Override dialog form labels 한국어화 (시리즈 이름 / 캐릭터 이름 / 폴더명 언어 / 원본 태그) + 입력 위젯 tooltip 추가.
- Integrity dialog: "missing으로 표시" → "누락으로 표시" + "실제 파일 삭제가 아니라 DB 상태 기록" tooltip 추가.
- Workflow Wizard Step 4/6/7/8/9 라벨·tooltip 정리:
  - "No Metadata만 보강" → "메타데이터 없는 항목만 보강"
  - "태그 재분류" → "태그 다시 분석"
  - "미리보기 생성" → "분류 미리보기 생성"
  - 컬럼 헤더 "분류사유·비고" → "사유·경고"
- Toolbar 정규화·분류 메뉴 항목 한국어화 + tooltip:
  - "태그 재분류" → "태그 다시 분석"
  - "후보 태그" → "태그 후보 검토"
  - "웹 사전" → "외부 사전 가져오기"
  - "Localized Tag Pack 가져오기" → "번역 태그팩 가져오기"
- Sidebar 카테고리 6건 한국어화 (`All Files` → `전체 파일` 등).
- BatchClassifyDialog / TagCandidateView / CanonicalMergeDialog의 영문·DB enum 노출 문구 한국어화.

### Fixed

**테스트·안정성 (PR #47, #48)**
- `tests/test_gui_smoke.py`의 toolbar button rename 사전 fail 2건 정리 (`_btn_*` → `_act_*` 매핑).
- MainWindow의 stale `_btn_scan` 미정의 참조를 현재 `_act_inbox_scan` 구조로 정정 — 스캔 시작·완료 핸들러에서 AttributeError 가능성 제거.

---

## [0.5.0] — 2026-05-01

### Changed

**Workflow 재구성 (PR #36, #37, #38)**
- Step 5: 사전 정규화 UI를 분류 기준 선택 UI로 교체 — 시리즈+캐릭터 / 시리즈만 / 개별태그(비활성) 세 가지 선택.
- Step 6: 태그 재분류 항목을 헤더에서 숨김 처리; Step 7 진입 시 자동 retag로 통합.
- Step 7 Preview 우클릭으로 수동 분류 지정 추가. 자동완성 라벨은 "캐릭터명 (시리즈명)" 형식이며 label/value 분리로 DB·metadata override에는 canonical value만 저장.
- Step 7 Preview 리스트 필터 추가 (전체 / 확인 필요 / 수동 보정됨), 상태 컬럼과 tooltip으로 검토 필요 항목 식별.

### Added

**Tag Pack / User Custom (PR #33, #39)**
- v3 mojibake repair helper 추가 (`tools/repair_mojibake_via_v2.py`) — v2 reference를 이용해 v3 raw export의 깨진 문자열을 복구.
- User Custom Alias API 추가: `add_user_alias` / `remove_user_alias` / `list_user_aliases`.
- `tag_aliases.source='user_confirmed'` 경로 사용 — DB schema 변경 없이 사용자 승인 alias 진입.
- user_confirmed series alias가 hardcoded SERIES_ALIASES보다 우선하는 정책 고정.

**Startup / Asset (PR #34, #35)**
- splash/icon source 자산을 `docs/`에서 `assets/`로 정리.
- Startup splash 추가 (`assets/splash/splash.png`).
- Startup notice dialog 추가 — 버전별 1회 표시, `ui.startup_notice_seen_version` config로 관리.

---

## [0.4.1] — 2026-05-01

### Added

- Gallery 우클릭 컨텍스트 메뉴에 "🔄 새로고침" 액션 추가.
- Metadata enrichment mode split:
  - "🔄 No Metadata만 보강" — `metadata_missing`만 처리 (기존 동작).
  - "🔁 Pixiv ID 있는 모든 항목 재시도" — `metadata_missing` / `metadata_write_failed` / `xmp_write_failed` / `json_only` 재처리.
- 파일 무결성 검사 (`🛡 파일 무결성 검사`):
  - 외부에서 삭제된 파일을 감지해 DB의 `file_status`를 `missing`으로 표시.
  - dry-run → confirm → apply 흐름.
  - 실제 파일 삭제는 수행하지 않음.

### Changed

- 사용자-facing "Inbox 스캔" 라벨을 "이미지 스캔"으로 통일 (toolbar / 로그 / 안내 문구 / Workflow Wizard Step 2).
- Gallery 목록과 sidebar 카운트가 `file_status='present'` 파일이 있는 group만 표시하도록 정리.
- 전체 보강 재시도 대상에서 `full` / `source_unavailable` / `pending`을 제외 (Pixiv 404 영구 마커 보존, 이미 완료된 항목 재처리 방지).

### Fixed

- 외부 Explorer 등에서 삭제된 파일이 Gallery에 계속 남는 문제를 missing 마킹 + present-only 표시 정책으로 완화.
- `missing` / `deleted` / `moved` / `orphan`만 남은 빈 group 카드가 Gallery 및 sidebar 카운트에 남던 stale 표시 문제 해결.

### Tests

- Gallery refresh action 회귀 테스트 추가.
- Metadata enrichment queue mode (missing_only / all_pixiv) 단위 테스트 추가.
- File integrity scanner 단위 테스트 + confirm dialog 회귀 테스트 추가.
- Gallery present-only SQL 필터 회귀 테스트 추가.

### Internal

- `core.metadata_enricher.build_enrichment_queue(conn, *, mode)` 신규 — 큐 SQL을 함수로 분리.
- `core.integrity_scanner` 모듈 신규 — `find_missing_files`, `mark_files_as_missing`, `run_integrity_scan`.
- Gallery SQL에 `_PRESENT_EXISTS_FRAGMENT` 모듈 상수 도입, `_GALLERY_BASE` / `_GALLERY_WHERE` / `_COUNT_SQL` / `_refresh_gallery_item` 일관 적용.

---

## [0.4.0] — 2026-05-01

### Added

**Visual Duplicate Auto Decision**
- `core/visual_duplicate_decision.py`: pure decision policy module that ranks candidates by resolution → format (webp first) → copy suffix → file size → filename, with safe fallback to `(0, 0)` dimensions when Pillow cannot read the file.
- `VisualDuplicateReviewDialog(initial_decisions=...)`: keyword-only argument that pre-populates user-facing keep/delete/exclude state; invalid keys/values silently dropped.
- `MainWindow._on_visual_duplicate_check`: calls `decide_visual_duplicate_groups`, flattens to `dict[file_id, decision]`, and passes as `initial_decisions` to the review dialog. INFO log notifies the user; `try/except` falls back to empty dict + WARN log on failure.

**Tag Pack v3 Raw Draft**
- `docs/tag_packs/drafts/` directory introduced as isolated holding area for raw exports that have not passed strict validation.
- `docs/tag_packs/drafts/README.md`: documents drafts policy (not active dataset, loader must not read it, 8-step v3 pipeline, sign-off required for active swap).
- `tests/test_tag_pack_v3_draft_isolation.py`: 5 regression tests verifying draft path, raw suffix, active v2 path preservation, and loader source isolation.

### Changed

**Workflow Wizard Step 3 Signal Delegation**
- `_Step3Meta._on_exact_dup` and `_on_visual_dup` no longer compute scope or call duplicate finders directly. They emit `exact_duplicate_scan_requested` / `visual_duplicate_scan_requested` signals; MainWindow handlers own scope selection (`inbox_managed`), confirm dialog, finder call, review dialog, and delete preview gate.

**Visual Duplicate Review Flow**
- The flow now includes an automatic candidate selection step before the review dialog opens. The user can change any decision before final confirmation. The multi-stage delete gate (`DeletePreviewDialog` → `execute_delete_preview`) is preserved unchanged.

### Tests

- `tests/test_duplicate_scope.py`: stale `inbox_managed` source-inspection assertions replaced with signal-delegation assertions (`signal_emit` present, `find_*duplicates` absent, dialogs not constructed in Step 3).
- `tests/test_tag_pack_failure_patch_v2_localizations.py`: localization regression aligned with `_review` / missing-locale policy.
- `tests/test_visual_duplicate_decision.py`, `tests/test_visual_duplicate_initial_decisions.py`, `tests/test_main_window_visual_duplicate_decision_integration.py`: new regression coverage for the auto-decision pipeline (pure function + dialog integration + MainWindow source-inspection).

### Internal

- Visual Duplicate auto selection is decoupled from UI: pure decision module → MainWindow flatten → dialog injection. The dialog itself does not import the decision module.
- v3 raw export is segregated under `docs/tag_packs/drafts/` so that the loader cannot accidentally treat it as active data; the active dataset remains `docs/tag_pack_export_localized_ko_ja_failure_patch_v2.json`.

---

## [0.3.0] — 2026-04-26

### Added

**GUI & Application**
- PyQt6 desktop application with dark wine/burgundy theme.
- Inbox scanning with file-status tracking and thumbnail generation.
- Gallery view with artwork group thumbnails and sidebar log panel.
- Archive Root persistence across sessions via `config.json`.
- `[🕘 작업 로그]` button → WorkLogView with per-operation Undo.
- `[🏷 태그 후보]` button → TagCandidateView for tag normalization.
- `[💾 저장 작업]` button → SaveJobsView with live job monitoring.

**Metadata & Classification**
- Pixiv metadata enrichment: title, artist, tags, series from AJAX API.
- BMP → PNG managed conversion; GIF → WebP conversion pipeline.
- Series → Character-based 4-tier classification engine:
  - Tier 1: `BySeries/{series}/{character}/`
  - Tier 2: `BySeries/{series}/_uncategorized/`
  - Tier 3: `ByCharacter/{character}/`
  - Tier 4: `ByAuthor/{artist}/` (fallback)
- Classification preview dialog and safe copy execution with conflict handling (`rename` / `skip` / `overwrite`).

**Tag Normalization Pipeline**
- `tag_observations`: per-artwork raw/translated tag occurrence log.
- `tag_candidate_generator`: auto-scores raw tags against known aliases.
- `tag_candidate_actions`: accept → promote to alias; reject → suppress.
- Tag aliases resolved at metadata enrichment and classification time.

**Undo System**
- `copy_records` and `undo_entries` tables for full copy audit trail.
- `undo_manager.evaluate_undo()`: verifies dest hash + mtime before deletion.
- `undo_manager.execute_undo()`: removes classified copy only; never touches originals or managed files.
- Configurable expiry (`undo_retention_days`, default 7 days).

**Browser Extension (Chrome / Naver Whale)**
- MV3 extension: popup + content script + service worker.
- One-click save from Pixiv artwork pages or right-click context menu.
- Popup shows live progress: "N/M 페이지" polling at 1 s interval (max 60 s).
- Korean error messages for all known failure modes.

**Native Messaging Host**
- Protocol v2: `{action, request_id, payload}` / `{success, request_id, data}`.
- 5 actions: `ping`, `save_pixiv_artwork`, `get_config_summary`, `open_main_app`, `get_job_status`.
- `_setup_logging()`: file + stderr only; stdout reserved for NM frames.
- Malformed JSON returns `protocol_error` without crashing the loop.
- `get_job_status` returns `progress{total/saved/failed}` + per-page `file_path`.

**CoreWorker Save Pipeline**
- `save_pixiv_artwork()` with distributed lock (120 s) via `locked_operation()`.
- Steps: fetch_metadata → fetch_pages → download → embed_metadata → register_file → sync_tags → tag_observations → thumbnail → finalize_job.
- Guarantees `save_jobs.status = failed` even on unexpected exceptions.

**Pixiv Downloader**
- `download_pixiv_image()`: httpx streaming, `Referer` header, tmp → rename.
- Cleans temp file on HTTP error; raises typed `PixivDownloadError`.

**Build & Install**
- `build/install_host.bat`: supports `chrome | whale | both <extension_id>`.
- `build/uninstall_host.bat`: removes registry keys and host directory.
- `build/gen_manifest.py`: generates `manifest.json` with real extension ID.
- `build/aru_archive.spec`: PyInstaller spec for standalone EXE packaging.

### Changed
- Native Messaging protocol upgraded from v1 to v2 (action/request_id/payload schema).
- Classification now prioritizes series/character paths over author-only fallback.
- WorkLogView fully rewritten with Undo evaluation and per-file confirmation dialog.
- `save_pixiv_artwork()` structured logging: `[INFO]` start/complete, `[WARN]` thumbnail, `[ERROR]` page.

### Fixed
- Native host stdout purity: all debug logging redirected to stderr + file.
- Malformed JSON from browser no longer crashes the native host loop.
- Undo expiry: `undo_entries.expires_at` correctly set to `now + retention_days`.
- BMP files handled via PNG managed conversion to avoid EXIF format incompatibility.
- Safe Undo prevents accidental deletion of original or managed source files.

### Database Schema (new tables)
| Table | Purpose |
|-------|---------|
| `save_jobs` | Per-artwork download job lifecycle |
| `job_pages` | Per-page download result with file FK |
| `tags` | Normalised tag storage |
| `tag_aliases` | Raw tag → canonical alias mapping |
| `tag_observations` | Per-artwork raw/translated tag log |
| `tag_candidates` | Auto-generated normalisation candidates |
| `undo_entries` | Safe-undo record for classified copies |

### Tests
- **309 tests passing** (`QT_QPA_PLATFORM=offscreen python -m pytest tests/`)
- Coverage: classifier, undo manager, tag observer/candidate, native protocol,
  native manifest, pixiv downloader, CoreWorker pipeline, job status handler, GUI smoke.

### Known Limitations
- Pixiv cookies are **not** auto-collected in this release.  
  R-18 / follower-only artworks will fail with HTTP 403 (planned for next milestone).
- Extension icons (`icons/icon16.png` etc.) use placeholder paths; actual PNG assets not yet generated.

---

## [0.1.0] — Initial Release

### Added
- PyQt6 archive browser skeleton.
- Inbox file scanning and Pixiv filename parsing (`{artwork_id}_p{n}.ext`).
- Series → Character classification engine (basic tier logic).
- Classification preview and copy execution.
- SQLite database with `artwork_groups`, `artwork_files`, `copy_records` tables.
- Initial test suite: classifier, filename parser, DB schema, inbox scan.
