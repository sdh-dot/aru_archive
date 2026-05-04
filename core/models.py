"""
Aru Archive 데이터 모델.
AruArchive JSON 스키마 v1.0 및 DB 테이블 대응 dataclass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# AruMetadata: AruArchive JSON 스키마 v1.0
# ---------------------------------------------------------------------------
@dataclass
class AruMetadata:
    """
    파일 내부에 저장되는 AruArchive JSON 스키마.

    저장 위치:
    - JPEG/WebP: EXIF UserComment (0x9286, UTF-16LE)
    - PNG: iTXt chunk (keyword=AruArchive)
    - ZIP (ugoira): .aru.json sidecar + ZIP comment
    - GIF (static): .aru.json sidecar (파일 우선 원칙의 예외)
    - BMP: 직접 저장 안 함 → PNG managed에 저장

    주의: BMP original에는 메타데이터를 삽입하지 않는다.
    BMP는 반드시 PNG managed를 생성하고, PNG managed에 기록한다.
    """
    schema_version: str = "1.0"
    source_site: str = "pixiv"
    artwork_id: str = ""
    artwork_url: str = ""
    artwork_title: str = ""
    page_index: int = 0
    total_pages: int = 1
    original_filename: str = ""
    artist_id: str = ""
    artist_name: str = ""
    artist_url: str = ""
    tags: list[str] = field(default_factory=list)
    character_tags: list[str] = field(default_factory=list)
    series_tags: list[str] = field(default_factory=list)
    raw_tags: list[str] = field(default_factory=list)  # original Pixiv tags before classification; DB-only, not in UserComment JSON
    downloaded_at: str = ""
    is_ugoira: bool = False
    ugoira_frames: Optional[list[str]] = None
    ugoira_delays: Optional[list[int]] = None
    ugoira_frame_count: Optional[int] = None
    ugoira_total_duration_ms: Optional[int] = None
    ugoira_webp_path: Optional[str] = None
    rating: Optional[str] = None
    custom_notes: str = ""
    _provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_site": self.source_site,
            "artwork_id": self.artwork_id,
            "artwork_url": self.artwork_url,
            "artwork_title": self.artwork_title,
            "page_index": self.page_index,
            "total_pages": self.total_pages,
            "original_filename": self.original_filename,
            "artist_id": self.artist_id,
            "artist_name": self.artist_name,
            "artist_url": self.artist_url,
            "tags": self.tags,
            "character_tags": self.character_tags,
            "series_tags": self.series_tags,
            "downloaded_at": self.downloaded_at,
            "is_ugoira": self.is_ugoira,
            "ugoira_frames": self.ugoira_frames,
            "ugoira_delays": self.ugoira_delays,
            "ugoira_frame_count": self.ugoira_frame_count,
            "ugoira_total_duration_ms": self.ugoira_total_duration_ms,
            "ugoira_webp_path": self.ugoira_webp_path,
            "rating": self.rating,
            "custom_notes": self.custom_notes,
            "_provenance": self._provenance,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "AruMetadata":
        obj = cls()
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        return obj

    @classmethod
    def from_json(cls, json_str: str) -> "AruMetadata":
        return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# ArtworkGroup: artwork_groups 테이블 대응
# ---------------------------------------------------------------------------
@dataclass
class ArtworkGroup:
    group_id: str = ""
    source_site: str = "pixiv"
    artwork_id: str = ""
    artwork_url: str = ""
    artwork_title: str = ""
    artist_id: str = ""
    artist_name: str = ""
    artist_url: str = ""
    artwork_kind: str = "single_image"          # single_image | multi_page | ugoira
    total_pages: int = 1
    cover_file_id: Optional[str] = None
    tags_json: Optional[str] = None
    character_tags_json: Optional[str] = None
    series_tags_json: Optional[str] = None
    downloaded_at: str = ""
    indexed_at: str = ""
    updated_at: Optional[str] = None
    status: str = "inbox"                        # inbox | classified | partial | error
    metadata_sync_status: str = "pending"        # 11개 값 (constants.py 참조)
    schema_version: str = "1.0"


# ---------------------------------------------------------------------------
# ArtworkFile: artwork_files 테이블 대응
# ---------------------------------------------------------------------------
@dataclass
class ArtworkFile:
    file_id: str = ""
    group_id: str = ""
    page_index: int = 0
    file_role: str = "original"                  # original | managed | sidecar | classified_copy
    file_path: str = ""
    file_format: str = ""                        # jpg|png|webp|zip|gif|bmp|json
    file_hash: Optional[str] = None
    file_size: Optional[int] = None
    metadata_embedded: int = 0                   # 0=없음, 1=완료
    file_status: str = "present"                 # present | missing | moved | orphan
    created_at: str = ""
    modified_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    source_file_id: Optional[str] = None         # original file_id (managed/sidecar용)
    classify_rule_id: Optional[str] = None
    provenance_json: Optional[str] = None


# ---------------------------------------------------------------------------
# SaveJob: save_jobs 테이블 대응
# ---------------------------------------------------------------------------
@dataclass
class SaveJob:
    job_id: str = ""
    source_site: str = "pixiv"
    artwork_id: str = ""
    group_id: Optional[str] = None
    status: str = "pending"                      # pending | running | completed | failed | partial
    total_pages: int = 1
    saved_pages: int = 0
    failed_pages: int = 0
    classify_mode: Optional[str] = None          # 작업 시작 당시 설정값 스냅샷
    started_at: str = ""
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# JobPage: job_pages 테이블 대응
# ---------------------------------------------------------------------------
@dataclass
class JobPage:
    id: Optional[int] = None
    job_id: str = ""
    page_index: int = 0
    url: str = ""
    filename: str = ""
    file_id: Optional[str] = None
    status: str = "pending"                      # pending | downloading | embed_pending | saved | failed
    error_message: Optional[str] = None
    download_bytes: Optional[int] = None
    saved_at: Optional[str] = None


# ---------------------------------------------------------------------------
# NoMetadataQueueItem: no_metadata_queue 테이블 대응
# ---------------------------------------------------------------------------
@dataclass
class NoMetadataQueueItem:
    queue_id: str = ""
    file_path: str = ""
    source_site: Optional[str] = None
    job_id: Optional[str] = None
    detected_at: str = ""
    fail_reason: str = "embed_failed"            # 13개 값 (constants.py 참조)
    raw_context: Optional[str] = None
    resolved: int = 0
    resolved_at: Optional[str] = None
    notes: Optional[str] = None
