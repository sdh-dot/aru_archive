# Changelog

All notable changes to Aru Archive are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
