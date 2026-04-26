-- Aru Archive SQLite Schema v2.4
-- 12개 테이블
-- 참조: 최종 개발 착수용 설계안 v2.4

-- WAL 모드 및 기본 PRAGMA
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;


-- ============================================================
-- 1. artwork_groups: 작품 단위 그룹 (다중 페이지 묶음)
-- ============================================================
CREATE TABLE IF NOT EXISTS artwork_groups (
    group_id              TEXT PRIMARY KEY,          -- UUID v4
    source_site           TEXT NOT NULL DEFAULT 'pixiv',
    artwork_id            TEXT NOT NULL,
    artwork_url           TEXT,
    artwork_title         TEXT,
    artist_id             TEXT,
    artist_name           TEXT,
    artist_url            TEXT,
    artwork_kind          TEXT NOT NULL DEFAULT 'single_image',
                          -- single_image | multi_page | ugoira
    total_pages           INTEGER NOT NULL DEFAULT 1,
    cover_file_id         TEXT,                      -- artwork_files.file_id (lazy, FK 없음)
    tags_json             TEXT,                      -- JSON array
    character_tags_json   TEXT,
    series_tags_json      TEXT,
    downloaded_at         TEXT NOT NULL,             -- ISO 8601
    indexed_at            TEXT NOT NULL,
    updated_at            TEXT,
    status                TEXT NOT NULL DEFAULT 'inbox',
                          -- inbox | classified | partial | error
    metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
                          -- pending | full | json_only | out_of_sync |
                          -- file_write_failed | convert_failed | metadata_write_failed |
                          -- xmp_write_failed | db_update_failed |
                          -- needs_reindex | metadata_missing
                          --
                          -- [다중 페이지 집계 규칙]
                          -- 그룹 내 모든 파일의 metadata_sync_status 중
                          -- METADATA_STATUS_PRIORITY 기준 가장 심각한 값을 사용.
                          -- 예: p0=full, p1=metadata_write_failed, p2=full
                          --   → group = metadata_write_failed
                          -- aggregate_metadata_status() 함수(core/constants.py) 참조.
    schema_version        TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(artwork_id, source_site)
);

CREATE INDEX IF NOT EXISTS idx_artwork_groups_artist     ON artwork_groups(artist_id);
CREATE INDEX IF NOT EXISTS idx_artwork_groups_status     ON artwork_groups(status);
CREATE INDEX IF NOT EXISTS idx_artwork_groups_sync       ON artwork_groups(metadata_sync_status);
CREATE INDEX IF NOT EXISTS idx_artwork_groups_downloaded ON artwork_groups(downloaded_at);


-- ============================================================
-- 2. artwork_files: 개별 파일
--    file_role: original | managed | sidecar | classified_copy
-- ============================================================
CREATE TABLE IF NOT EXISTS artwork_files (
    file_id               TEXT PRIMARY KEY,          -- UUID v4
    group_id              TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    page_index            INTEGER NOT NULL DEFAULT 0,
    file_role             TEXT NOT NULL,
                          -- original         : Inbox 원본 파일 (BMP, GIF, ZIP 포함)
                          -- managed          : 원본에서 변환된 관리본 (PNG managed, WebP managed)
                          --                   BMP → PNG managed, animated GIF/ugoira → WebP managed
                          -- sidecar          : .aru.json 사이드카 (ZIP, static GIF)
                          -- classified_copy  : Classified 폴더에 복사된 파일 (MVP-B)
    file_path             TEXT NOT NULL UNIQUE,      -- 절대 경로
    file_format           TEXT NOT NULL,             -- jpg|png|webp|zip|gif|bmp|json
    file_hash             TEXT,                      -- SHA-256
    file_size             INTEGER,                   -- bytes
    metadata_embedded     INTEGER NOT NULL DEFAULT 0,
                          -- 0: AruArchive JSON 없음
                          -- 1: AruArchive JSON 임베딩 완료
    file_status           TEXT NOT NULL DEFAULT 'present',
                          -- present | missing | moved | orphan
    created_at            TEXT NOT NULL,
    modified_at           TEXT,
    last_seen_at          TEXT,
    source_file_id        TEXT REFERENCES artwork_files(file_id),
                          -- managed/sidecar의 경우 original file_id 참조
    classify_rule_id      TEXT,
    provenance_json       TEXT
);

CREATE INDEX IF NOT EXISTS idx_artwork_files_group  ON artwork_files(group_id);
CREATE INDEX IF NOT EXISTS idx_artwork_files_role   ON artwork_files(file_role);
CREATE INDEX IF NOT EXISTS idx_artwork_files_status ON artwork_files(file_status);
CREATE INDEX IF NOT EXISTS idx_artwork_files_hash   ON artwork_files(file_hash);


-- ============================================================
-- 3. tags: 정규화 태그 인덱스
--    컬럼명: group_id (artwork_id 아님)
--    artwork_groups.group_id FK와 일치
-- ============================================================
CREATE TABLE IF NOT EXISTS tags (
    group_id    TEXT NOT NULL REFERENCES artwork_groups(group_id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    tag_type    TEXT NOT NULL DEFAULT 'general',
                -- general | character | series
    canonical   TEXT,                               -- tag_aliases 정규화 후 값 (MVP-C)
    PRIMARY KEY (group_id, tag, tag_type)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag       ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_tags_canonical ON tags(canonical);


-- ============================================================
-- 4. save_jobs: 저장 작업 단위 (진행률 추적)
-- ============================================================
CREATE TABLE IF NOT EXISTS save_jobs (
    job_id          TEXT PRIMARY KEY,               -- UUID v4
    source_site     TEXT NOT NULL DEFAULT 'pixiv',
    artwork_id      TEXT NOT NULL,
    group_id        TEXT REFERENCES artwork_groups(group_id),
    status          TEXT NOT NULL DEFAULT 'pending',
                    -- pending | running | completed | failed | partial
    total_pages     INTEGER NOT NULL DEFAULT 1,
    saved_pages     INTEGER NOT NULL DEFAULT 0,
    failed_pages    INTEGER NOT NULL DEFAULT 0,
    classify_mode   TEXT,                           -- 작업 시작 당시 설정값 스냅샷
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_save_jobs_status  ON save_jobs(status);
CREATE INDEX IF NOT EXISTS idx_save_jobs_started ON save_jobs(started_at);


-- ============================================================
-- 5. job_pages: 저장 작업 내 개별 페이지 상태
--    status 전이: pending → downloading → embed_pending → saved
--                                       ↘ failed
-- ============================================================
CREATE TABLE IF NOT EXISTS job_pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL REFERENCES save_jobs(job_id) ON DELETE CASCADE,
    page_index      INTEGER NOT NULL,
    url             TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_id         TEXT REFERENCES artwork_files(file_id),
    status          TEXT NOT NULL DEFAULT 'pending',
                    -- pending | downloading | embed_pending | saved | failed
    error_message   TEXT,
    download_bytes  INTEGER,                        -- 실제 다운로드 바이트 수
    saved_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_pages_job_id ON job_pages(job_id);


-- ============================================================
-- 6. no_metadata_queue: 메타데이터 없는 파일 보류 큐
-- ============================================================
CREATE TABLE IF NOT EXISTS no_metadata_queue (
    queue_id      TEXT PRIMARY KEY,                 -- UUID v4
    file_path     TEXT NOT NULL,
    source_site   TEXT,
    job_id        TEXT REFERENCES save_jobs(job_id),
    detected_at   TEXT NOT NULL,
    fail_reason   TEXT NOT NULL,
                  -- no_dom_data              : content_script preload_data 찾지 못함
                  -- parse_error              : 메타데이터 파싱 중 예외
                  -- network_error            : httpx 다운로드 실패
                  -- unsupported_format       : 지원하지 않는 파일 형식
                  -- manual_add               : 사용자 수동 추가
                  -- embed_failed             : 기타 임베딩 오류 (범용 폴백)
                  --                           가능하면 아래 세부 reason을 우선 사용
                  -- partial_data             : 일부 필드 누락된 불완전 메타데이터
                  -- artwork_restricted       : R-18/프리미엄 접근 제한
                  -- api_error                : Pixiv AJAX API 4xx/5xx
                  -- bmp_convert_failed       : BMP → PNG managed 변환 실패
                  -- managed_file_create_failed: BMP 외 managed 파일 생성 실패
                  --                           (animated GIF→WebP, ugoira→WebP 등)
                  -- metadata_write_failed    : 파일 생성 후 AruArchive JSON 임베딩 실패
                  --
                  -- [중요] xmp_write_failed는 enum에는 존재하지만
                  --        기본적으로 no_metadata_queue에 INSERT하지 않는다.
                  --        AruArchive JSON이 정상 보존된 상태이므로
                  --        앱 내부 검색/분류/표시는 모두 정상 동작한다.
                  --        xmp_write_failed는 갤러리 카드 또는 상세 패널의
                  --        Warning 배지로 표시한다.
                  --        향후 warning queue 또는 XMP 재처리 큐를 만들 경우
                  --        이 enum 값을 재사용할 수 있다.
    raw_context   TEXT,                             -- 오류 당시 부분 데이터 JSON
    resolved      INTEGER NOT NULL DEFAULT 0,
    resolved_at   TEXT,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_no_metadata_resolved ON no_metadata_queue(resolved);
CREATE INDEX IF NOT EXISTS idx_no_metadata_job      ON no_metadata_queue(job_id);


-- ============================================================
-- 7. undo_entries: Undo 작업 로그 항목 (MVP-B)
-- ============================================================
CREATE TABLE IF NOT EXISTS undo_entries (
    entry_id        TEXT PRIMARY KEY,               -- UUID v4
    operation_type  TEXT NOT NULL,                  -- 'classify'
    performed_at    TEXT NOT NULL,
    undo_expires_at TEXT NOT NULL,                  -- performed_at + undo_retention_days
    undo_status     TEXT NOT NULL DEFAULT 'pending',
                    -- pending   : Undo 미실행, Undo 가능  (UI: "Undo 가능",  버튼 활성)
                    -- completed : Undo 완료됨             (UI: "Undo 완료",  버튼 비활성)
                    -- failed    : Undo 시도 실패          (UI: "Undo 실패",  버튼 비활성)
                    -- expired   : 보존 기간 만료          (UI: "Undo 만료",  버튼 비활성)
                    --
                    -- pending은 "Undo 작업이 아직 실행되지 않음"을 의미하며,
                    -- UI에서는 "Undo 가능"으로 표시한다. (DB값 ≠ UI 레이블)
    undone_at       TEXT,
    undo_error      TEXT,                           -- 실패 시 오류 메시지
    description     TEXT
);

CREATE INDEX IF NOT EXISTS idx_undo_entries_status  ON undo_entries(undo_status);
CREATE INDEX IF NOT EXISTS idx_undo_entries_expires ON undo_entries(undo_expires_at);


-- ============================================================
-- 8. copy_records: Undo 항목별 개별 파일 복사 기록 (B-2 정책, MVP-B)
--    만료 후: dest_mtime_at_copy, dest_hash_at_copy → NULL
--    만료 후에도 보존: dest_file_size (Recent Jobs 표시용)
-- ============================================================
CREATE TABLE IF NOT EXISTS copy_records (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id             TEXT NOT NULL REFERENCES undo_entries(entry_id) ON DELETE CASCADE,
    src_file_id          TEXT REFERENCES artwork_files(file_id),
    dest_file_id         TEXT REFERENCES artwork_files(file_id),
    src_path             TEXT NOT NULL,
    dest_path            TEXT NOT NULL,
    rule_id              TEXT,
    dest_file_size       INTEGER NOT NULL,           -- 만료 후에도 보존
    dest_mtime_at_copy   TEXT,                       -- 만료 후 NULL
    dest_hash_at_copy    TEXT,                       -- 만료 후 NULL
    manually_modified    INTEGER DEFAULT 0,
    copied_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_copy_records_entry ON copy_records(entry_id);


-- ============================================================
-- 9. classify_rules: 분류 규칙 (MVP-B)
-- ============================================================
CREATE TABLE IF NOT EXISTS classify_rules (
    rule_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    priority        INTEGER NOT NULL DEFAULT 100,   -- 낮을수록 높은 우선순위
    conditions_json TEXT NOT NULL,
    logic           TEXT NOT NULL DEFAULT 'AND',    -- AND | OR
    dest_template   TEXT NOT NULL,
    on_conflict     TEXT NOT NULL DEFAULT 'skip',   -- skip | overwrite | rename
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);


-- ============================================================
-- 10. thumbnail_cache: 썸네일 캐시 인덱스 (Hybrid path 방식)
--     실제 썸네일 파일: {data_dir}/.thumbcache/{file_id[0:2]}/{file_id}.webp
--     BLOB 컬럼 없음. DB는 경로 인덱스만 보관.
-- ============================================================
CREATE TABLE IF NOT EXISTS thumbnail_cache (
    file_id       TEXT PRIMARY KEY REFERENCES artwork_files(file_id) ON DELETE CASCADE,
    thumb_path    TEXT NOT NULL UNIQUE,             -- 절대 경로 (.thumbcache 내)
    thumb_size    TEXT NOT NULL DEFAULT '256x256',
    source_hash   TEXT NOT NULL,                    -- 원본 file_hash (갱신 판단용)
    file_size     INTEGER,                          -- 썸네일 파일 크기 (bytes)
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_thumbnail_source_hash ON thumbnail_cache(source_hash);


-- ============================================================
-- 11. tag_aliases: 태그 별칭 → 정규 태그 매핑 (MVP-C)
--     스키마는 MVP-A Sprint 1에 생성. 데이터는 Sprint 9(MVP-C).
-- ============================================================
CREATE TABLE IF NOT EXISTS tag_aliases (
    alias         TEXT PRIMARY KEY,
    canonical     TEXT NOT NULL,
    source_site   TEXT DEFAULT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tag_aliases_canonical ON tag_aliases(canonical);


-- ============================================================
-- 12. operation_locks: SQLite 동시 쓰기 잠금
--     키 패턴:
--       save:{source_site}:{artwork_id}  → 120초 (중복 저장 방지)
--       classify:{group_id}              → 60초
--       reindex                          → 600초
--       thumbnail:{file_id}              → 30초
--       undo:{entry_id}                  → 60초
--       db_maintenance                   → 120초
-- ============================================================
CREATE TABLE IF NOT EXISTS operation_locks (
    lock_name     TEXT PRIMARY KEY,
    locked_by     TEXT NOT NULL,                    -- 'native_host' | 'main_app' | 'reindex'
    locked_at     TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
