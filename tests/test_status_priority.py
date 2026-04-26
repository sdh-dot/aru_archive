"""
aggregate_metadata_status() 단위 테스트.
다중 페이지 artwork_groups 상태 집계 규칙 검증.
"""
import pytest
from core.constants import aggregate_metadata_status, METADATA_STATUS_PRIORITY


class TestAggregateMetadataStatus:
    def test_all_full(self):
        assert aggregate_metadata_status(["full", "full"]) == "full"

    def test_full_and_json_only(self):
        assert aggregate_metadata_status(["full", "json_only"]) == "json_only"

    def test_full_and_xmp_write_failed(self):
        assert aggregate_metadata_status(["full", "xmp_write_failed"]) == "xmp_write_failed"

    def test_full_and_metadata_write_failed(self):
        assert aggregate_metadata_status(["full", "metadata_write_failed"]) == "metadata_write_failed"

    def test_convert_failed_beats_metadata_write_failed(self):
        assert aggregate_metadata_status(["convert_failed", "metadata_write_failed"]) == "convert_failed"

    def test_empty_list_returns_pending(self):
        assert aggregate_metadata_status([]) == "pending"

    def test_file_write_failed_is_highest(self):
        """file_write_failed는 가장 심각한 상태여야 한다."""
        all_statuses = list(METADATA_STATUS_PRIORITY.keys())
        assert aggregate_metadata_status(all_statuses) == "file_write_failed"

    def test_single_pending(self):
        assert aggregate_metadata_status(["pending"]) == "pending"

    def test_single_full(self):
        assert aggregate_metadata_status(["full"]) == "full"

    def test_three_pages_one_failed(self):
        """p0=full, p1=metadata_write_failed, p2=full → metadata_write_failed"""
        assert aggregate_metadata_status(["full", "metadata_write_failed", "full"]) == "metadata_write_failed"

    def test_priority_order(self):
        """우선순위 순서 확인: file_write_failed > convert_failed > metadata_write_failed"""
        assert (
            METADATA_STATUS_PRIORITY["file_write_failed"]
            > METADATA_STATUS_PRIORITY["convert_failed"]
            > METADATA_STATUS_PRIORITY["metadata_write_failed"]
            > METADATA_STATUS_PRIORITY["metadata_missing"]
            > METADATA_STATUS_PRIORITY["xmp_write_failed"]
            > METADATA_STATUS_PRIORITY["json_only"]
            > METADATA_STATUS_PRIORITY["full"]
        )

    def test_xmp_write_failed_beats_json_only(self):
        assert aggregate_metadata_status(["json_only", "xmp_write_failed"]) == "xmp_write_failed"

    def test_needs_reindex_beats_out_of_sync(self):
        assert aggregate_metadata_status(["out_of_sync", "needs_reindex"]) == "needs_reindex"
