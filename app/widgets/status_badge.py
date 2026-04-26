"""
상태 배지 위젯.
xmp_write_failed Warning 배지, metadata_sync_status 표시 등에 사용.
MVP-A: 골격만 정의.
"""
from __future__ import annotations

from core.constants import UNDO_STATUS_UI_LABEL

# metadata_sync_status → 배지 텍스트 / 색상 매핑
SYNC_STATUS_BADGE: dict[str, tuple[str, str]] = {
    "full": ("✓", "#4CAF50"),              # 녹색
    "json_only": ("J", "#2196F3"),          # 파란색
    "out_of_sync": ("!", "#FF9800"),        # 주황색
    "file_write_failed": ("✗", "#F44336"), # 빨간색
    "convert_failed": ("✗", "#F44336"),
    "metadata_write_failed": ("✗", "#F44336"),
    "xmp_write_failed": ("⚠", "#FF9800"),  # 주황색 경고 (no_metadata_queue 미기록)
    "db_update_failed": ("!", "#FF9800"),
    "needs_reindex": ("↺", "#9E9E9E"),     # 회색
    "metadata_missing": ("?", "#9C27B0"),  # 보라색
    "pending": ("…", "#9E9E9E"),           # 회색
}


def get_badge_info(metadata_sync_status: str) -> tuple[str, str]:
    """
    metadata_sync_status에 대응하는 (배지 텍스트, 색상) 반환.
    xmp_write_failed는 Warning 배지 (⚠)로 표시하며 no_metadata_queue에 기록하지 않는다.
    """
    return SYNC_STATUS_BADGE.get(metadata_sync_status, ("?", "#9E9E9E"))
