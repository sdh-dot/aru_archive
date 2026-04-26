"""
Aru Archive 핵심 상수 및 enum 정의.
v2.4 설계안 기준.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# metadata_sync_status 최종 11개 값
# artwork_groups.metadata_sync_status 컬럼에서 사용
# ---------------------------------------------------------------------------
METADATA_SYNC_STATUSES = [
    "pending",               # 기본값. 파이프라인 진입 전/진행 중
    "full",                  # AruArchive JSON + XMP 모두 완료
    "json_only",             # JSON만 완료 (ExifTool 없음 / static GIF sidecar 성공)
    "out_of_sync",           # DB와 파일 메타데이터 불일치
    "file_write_failed",     # 원본 파일 저장 자체 실패 (1단계 실패)
    "convert_failed",        # 원본 저장 성공, managed 변환 실패 (2단계 실패)
    "metadata_write_failed", # managed 생성 성공, JSON 임베딩 실패 (3단계 실패)
    "xmp_write_failed",      # JSON 성공, XMP만 실패 (4단계 실패)
    "db_update_failed",      # 파일 처리 성공, DB 업데이트 실패
    "needs_reindex",         # 재색인 필요 (db_update_failed 이후)
    "metadata_missing",      # 파일 내 AruArchive JSON 없음 (외부 편집 의심)
]

# ---------------------------------------------------------------------------
# 그룹 상태 집계 우선순위: 숫자가 높을수록 더 심각한 상태
#
# 다중 페이지 작품에서 페이지별 metadata_sync_status가 다를 수 있으므로,
# aggregate_metadata_status()를 통해 그룹 상태를 집계한다.
# 가장 심각한 상태가 group 상태로 승격된다.
# ---------------------------------------------------------------------------
METADATA_STATUS_PRIORITY: dict[str, int] = {
    "file_write_failed": 100,
    "convert_failed": 90,
    "metadata_write_failed": 80,
    "metadata_missing": 70,
    "db_update_failed": 60,
    "needs_reindex": 50,
    "out_of_sync": 40,
    "xmp_write_failed": 30,
    "json_only": 20,
    "pending": 10,
    "full": 0,
}


def aggregate_metadata_status(statuses: list[str]) -> str:
    """
    파일별 metadata_sync_status 목록을 받아 group-level 상태를 결정한다.

    다중 페이지 작품에서 페이지별 상태가 다를 수 있으므로,
    그룹 내 가장 심각도가 높은 상태를 반환한다.

    집계 규칙:
    - 빈 목록이면 'pending' 반환
    - 모든 파일이 'full'이면 'full' 반환
    - 실패 상태가 하나라도 있으면 가장 심각한 상태 반환
    - 우선순위는 METADATA_STATUS_PRIORITY 기준

    예시:
        ["full", "full"]                  → "full"
        ["full", "json_only"]             → "json_only"
        ["full", "metadata_write_failed"] → "metadata_write_failed"
        ["convert_failed", "full"]        → "convert_failed"
        []                                → "pending"
    """
    if not statuses:
        return "pending"
    return max(statuses, key=lambda s: METADATA_STATUS_PRIORITY.get(s, 0))


# ---------------------------------------------------------------------------
# no_metadata_queue.fail_reason 최종 13개 값
# ---------------------------------------------------------------------------
NO_METADATA_FAIL_REASONS = [
    "no_dom_data",                 # content_script preload_data 찾지 못함
    "parse_error",                 # 메타데이터 파싱 중 예외
    "network_error",               # httpx 다운로드 실패
    "unsupported_format",          # 지원하지 않는 파일 형식
    "manual_add",                  # 사용자 수동 추가
    "embed_failed",                # 기타 임베딩 오류의 범용 폴백
                                   # 세부 reason이 있으면 그것을 우선 사용:
                                   #   bmp_convert_failed, managed_file_create_failed,
                                   #   metadata_write_failed 등
    "partial_data",                # 일부 필드 누락된 불완전 메타데이터
    "artwork_restricted",          # R-18 / 프리미엄 접근 제한
    "api_error",                   # Pixiv AJAX API 4xx/5xx
    "bmp_convert_failed",          # BMP → PNG managed 변환 실패
    "managed_file_create_failed",  # BMP 외 managed 파일 생성 실패 (GIF→WebP, ugoira→WebP 등)
    "metadata_write_failed",       # 파일 생성 후 AruArchive JSON 임베딩 실패
    # xmp_write_failed는 enum에는 존재하지만 기본적으로 no_metadata_queue에 INSERT하지 않는다.
    # AruArchive JSON이 정상 보존된 상태이므로 UI Warning 배지로 처리한다.
    # 향후 warning queue 또는 XMP 재처리 큐를 만들 경우 이 enum 값을 재사용할 수 있다.
    "xmp_write_failed",
]

# xmp_write_failed를 no_metadata_queue에 INSERT하지 않는 정책.
# 이 플래그를 확인하여 큐 삽입 여부를 결정하는 코드에서 참조한다.
XMP_WRITE_FAILED_SKIP_QUEUE = True

# ---------------------------------------------------------------------------
# file_role enum
# ---------------------------------------------------------------------------
FILE_ROLES = ["original", "managed", "sidecar", "classified_copy"]

# ---------------------------------------------------------------------------
# artwork_kind enum
# ---------------------------------------------------------------------------
ARTWORK_KINDS = ["single_image", "multi_page", "ugoira"]

# ---------------------------------------------------------------------------
# artwork status enum
# ---------------------------------------------------------------------------
ARTWORK_STATUSES = ["inbox", "classified", "partial", "error"]

# ---------------------------------------------------------------------------
# classify_mode enum
# MVP-A 기본값: save_only
# ---------------------------------------------------------------------------
CLASSIFY_MODES = ["save_only", "immediate", "review"]
CLASSIFY_MODE_DEFAULT = "save_only"

# ---------------------------------------------------------------------------
# undo_status enum
# UI 표시 매핑:
#   pending   → "Undo 가능"   (Undo 버튼 활성화)
#   completed → "Undo 완료"   (비활성화)
#   failed    → "Undo 실패"   (비활성화)
#   expired   → "Undo 만료"   (비활성화)
# ---------------------------------------------------------------------------
UNDO_STATUSES = ["pending", "completed", "failed", "expired"]

UNDO_STATUS_UI_LABEL: dict[str, str] = {
    "pending": "Undo 가능",
    "completed": "Undo 완료",
    "failed": "Undo 실패",
    "expired": "Undo 만료",
}

# ---------------------------------------------------------------------------
# job status enum
# ---------------------------------------------------------------------------
JOB_STATUSES = ["pending", "running", "completed", "failed", "partial"]

# ---------------------------------------------------------------------------
# job_pages status enum
# ---------------------------------------------------------------------------
JOB_PAGE_STATUSES = ["pending", "downloading", "embed_pending", "saved", "failed"]

# ---------------------------------------------------------------------------
# file_status enum
# ---------------------------------------------------------------------------
FILE_STATUSES = ["present", "missing", "moved", "orphan"]

# ---------------------------------------------------------------------------
# tag_type enum
# ---------------------------------------------------------------------------
TAG_TYPES = ["general", "character", "series"]

# ---------------------------------------------------------------------------
# operation_locks 키 패턴
# ---------------------------------------------------------------------------
def make_save_lock_key(source_site: str, artwork_id: str) -> str:
    """save:{source_site}:{artwork_id}  — 중복 저장 방지 (120초)"""
    return f"save:{source_site}:{artwork_id}"


def make_classify_lock_key(group_id: str) -> str:
    """classify:{group_id}  — 분류 실행 (60초)"""
    return f"classify:{group_id}"


def make_thumbnail_lock_key(file_id: str) -> str:
    """thumbnail:{file_id}  — 썸네일 생성 (30초)"""
    return f"thumbnail:{file_id}"


def make_undo_lock_key(entry_id: str) -> str:
    """undo:{entry_id}  — Undo 실행 (60초)"""
    return f"undo:{entry_id}"


LOCK_REINDEX = "reindex"
LOCK_DB_MAINTENANCE = "db_maintenance"

# ---------------------------------------------------------------------------
# 지원 파일 형식
# ---------------------------------------------------------------------------
SUPPORTED_FORMATS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "zip"}

# BMP는 반드시 PNG managed로 변환. WebP managed가 아님.
# WebP managed는 ugoira / animated GIF 전용.
BMP_MANAGED_FORMAT = "png"
UGOIRA_MANAGED_FORMAT = "webp"
ANIMATED_GIF_MANAGED_FORMAT = "webp"

# ---------------------------------------------------------------------------
# thumbnail 설정
# ---------------------------------------------------------------------------
THUMBNAIL_SIZE_DEFAULT: tuple[int, int] = (256, 256)
THUMBNAIL_SIZE_SMALL: tuple[int, int] = (128, 128)
THUMBNAIL_QUALITY = 85
THUMBCACHE_DIR = ".thumbcache"

# ---------------------------------------------------------------------------
# IPC 설정
# ---------------------------------------------------------------------------
DEFAULT_HTTP_PORT = 18456
IPC_TOKEN_FILENAME = "ipc_token"
RUNTIME_DIR = ".runtime"
