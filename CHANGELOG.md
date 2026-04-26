# Changelog

All notable changes to Aru Archive are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

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
