# Changelog

All notable changes to Aru Archive are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.6.2] — 2026-05-02

### Added

**Missing-file restore UX 후속 — 누락 파일 보기 navigation (PR #56)**
- `IntegrityRestoreHoldDialog`에 "누락 파일 보기" 버튼 추가.
- 버튼 클릭 시 `navigate_to_missing_requested` signal 발신 → Sidebar "⚠ 누락 파일" 카테고리로 이동.
- hash mismatch 보류 항목 확인 후 누락 파일 목록으로 이어서 탐색 가능.
- read-only 유지 — DB update 없음.

**Mojibake DB 진단 도구 (PR #60)**
- `tools/diagnose_mojibake.py` — read-only DB 진단 스크립트 추가.
- `tag_aliases` / `tag_localizations` 테이블의 오염 범위를 정량 확인:
  - U+FFFD 대체 문자, `???` / underscore placeholder, locale mismatch, Latin-1 mojibake heuristic.
- `--json` 옵션으로 JSON report 출력.

**Mojibake DB 자동 정리 도구 (PR #61)**
- `tools/repair_mojibake_db.py` — 안전한 DB 정리 스크립트 추가.
- 기본 동작은 dry-run; `--apply` 실행 시 `--backup` 필수.
- 보호 source: `user_confirmed`, `built_in_pack:*`, `external:safebooru`, NULL/empty — 수정 대상에서 제외.
- action 분류: `update_localization` / `delete_alias` / `manual_review` / `protected_skip`.
- 트랜잭션 단위 rollback으로 부분 적용 방지.

**내장 Localization 보강 — 주요 시리즈 8종 (PR #62)**
- BA(블루 아카이브) 외 8종 built-in localization 추가:
  NIKKE, Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Arknights, Fate/Grand Order, Uma Musume Pretty Derby, Azur Lane.
- `core/tag_localizer.py` `_db_lookup` source priority tier 정비:
  - tier 0: `user_confirmed` (최우선)
  - tier 1: `built_in_pack:*`
  - tier 2: `imported_localized_pack` 등
- imported_localized_pack mojibake 값보다 built-in localization이 우선 적용되는 회귀 가드 추가.

### Changed

**Pixiv enrichment — DB tag_aliases 반영 (PR #57)**
- `classify_pixiv_tags()`에 DB connection 전달, enrichment 시점에 `tag_aliases` / user_confirmed alias를 character·series 정규화에 반영.
- 기준 태그가 있는데 `_uncategorized`로 분류되던 경로 완화.

**Windows Explorer 메타데이터 UX 개선 (PR #58)**
- `XPSubject` / `XPComment` / `ImageDescription` ExifTool 필드 보강.
- 태그·제목·설명이 Windows 탐색기 속성 창에서 올바르게 표시.
- JSON dump가 사용자-facing 설명 필드처럼 노출되던 문제 완화.

**json_only 메타데이터 경고 (PR #59)**
- ExifTool 미해결 등으로 `sync_status='json_only'`인 항목에 대해 Workflow Step 8 완료 메시지에 사용자 가시 경고 표시.

**Hitomi 추출 절차 문서화 및 .gitignore 강화 (PR #63)**
- `docs/data/hitomi_base_catalog/` 에 절차·스키마·추출 도구만 commit; sample data 제외.
- README에 commit 금지 대상 명시 (sample.json, catalog_summary, 사용자 DB, 원본 tags.txt 등).
- `.gitignore` 추가 항목:
  - `mojibake_report*.json`, `repair_plan*.json`
  - `docs/data/**/*.sample.json`, `docs/data/**/full/`, `docs/data/**/raw/`
  - `.research/`, `.scratch/`
  - `build/hitomi_catalog_check/`, `build/mojibake_*/`
- `extract_hitomi_catalog.py`에 adult/explicit 콘텐츠 denylist 적용 (로컬 추출 시 자동 필터).

### Notes

- DB schema 변경 없음.
- 사용자 DB 파일 commit 없음.
- Hitomi 원본 데이터 / sample data는 repository에 포함되지 않음.
- `resources/tag_packs/`에 외부 full export 미포함.
- duplicate awareness 미구현.
- `retag_before_batch_preview` default=True 미구현.
- `drafts/*` mojibake import 차단 lint 미구현.
- moved/renamed 복원, 강제 복원, hash 갱신, 새 파일 등록 미구현.
- Step 6 Observation 저장 미구현.

---

## [0.6.1] — 2026-05-02

### Added

**Hash mismatch 안전장치 — 복원 보류 정책 (PR #53)**
- Same-path missing → present 자동 복원 시 DB `file_hash`와 현재 파일 SHA-256이 다르면 복원을 보류.
- `run_integrity_scan()` 반환 dict에 additive key 추가:
  - `restore_skipped_hash_mismatch` — hash 불일치로 보류된 건수.
  - `hash_mismatch_files` — 보류된 파일 경로 목록.
  - `restore_skipped_hash_unavailable` — DB hash 없어 보류된 건수 (기존 same-path 복원 정책 유지).
- DB hash가 없는 파일은 종전 정책대로 복원 진행, hash 계산 실패 시 보수적으로 보류.
- MainWindow 무결성 검사 완료 메시지에 mismatch ≥1건일 때 `"해시 불일치로 복원 보류: Z건"` 문구 추가.

**Hash mismatch review UI (PR #54)**
- 복원 보류 항목을 read-only 상세 목록(`IntegrityRestoreHoldDialog`)에서 확인 가능.
- 표시 컬럼: 파일 경로 / 그룹 ID / 역할 / DB 해시(prefix) / 현재 해시(prefix).
- 사용자 액션은 닫기만 제공 — 강제 복원·DB update 없음.
- mismatch 0건일 때는 dialog 미표시.

### Notes

- DB schema 변경 없음.
- `core/inbox_scanner.py` 변경 없음.
- 실제 파일 삭제·복사·복원 로직 변경 없음.
- moved/renamed 파일 복원, 강제 복원, hash 갱신, 새 파일 등록 액션은 미구현.

---

## [0.6.0] — 2026-05-01

### Added

**누락 파일 확인 UX — Sidebar "⚠ 누락 파일" 카테고리 (PR #50)**
- Sidebar/Explorer에 "⚠ 누락 파일" 카테고리 추가 — `file_status='missing'` 항목만 필터링하는 전용 진입점.
- 카테고리 클릭 시 누락 파일 수(count)를 표시하며, 현재 경로에서 찾을 수 없는 파일임을 tooltip으로 안내 ("DB에는 기록되어 있지만 현재 경로에서 찾을 수 없는 파일").
- `_GALLERY_MISSING_SQL` 전용 조회 경로 추가 — 기존 `present`-only gallery query와 충돌 없이 독립 동작.

**누락 파일 자동 복원 — 파일 무결성 검사 복원 로직 (PR #51)**
- 파일 무결성 검사 실행 시, `file_status='missing'`으로 기록된 항목의 같은 경로에 파일이 다시 존재하면 `file_status='present'`로 자동 복원.
- `run_integrity_scan()` 반환 결과에 `restored_count` / `restored_files` / `restore_updated` 필드 추가.
- MainWindow 무결성 검사 완료 메시지에 "누락으로 표시: X건 / 다시 확인됨: Y건" 요약 표시.
- `last_seen_at` 갱신(기존 컬럼 UPDATE only) — DB schema 변경 없음.

### Notes

- 실제 파일 삭제·복사·이동 로직 변경 없음.
- InboxScanner 정책 변경 없음.
- 이름 변경(renamed/moved) 파일의 자동 복원은 미구현 — 후속 PR 예정.
- hash mismatch 경고·차단 정책은 미구현 — 후속 PR 예정.
- 수동 복원 UI는 미구현 — 후속 PR 예정.

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
