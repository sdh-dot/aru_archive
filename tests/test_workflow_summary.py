"""
core/workflow_summary.build_workflow_file_status_summary 테스트.
"""
from __future__ import annotations

import pytest

from db.database import initialize_database
from core.workflow_summary import build_workflow_file_status_summary


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = initialize_database(str(db))
    yield c
    c.close()


def _insert_group(conn, group_id, artwork_id, status="inbox",
                  sync_status="metadata_missing", with_artwork_id=True):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    aid = artwork_id if with_artwork_id else ""
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, status, metadata_sync_status, "
        " downloaded_at, indexed_at, source_site) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pixiv')",
        (group_id, aid, status, sync_status, now, now),
    )


def _insert_file(conn, file_id, group_id, file_format="jpg"):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, file_path, file_format, file_role, "
        " file_status, created_at) "
        "VALUES (?, ?, ?, ?, 'original', 'present', ?)",
        (file_id, group_id, f"/inbox/{file_id}.{file_format}", file_format, now),
    )


class TestBuildWorkflowFileStatusSummary:
    def test_empty_db_returns_zero_totals(self, conn):
        s = build_workflow_file_status_summary(conn)
        assert s["total_groups"] == 0
        assert s["pixiv_id_extractable"] == 0
        assert s["pixiv_id_missing"] == 0
        assert s["classifiable"] == 0
        assert s["excluded"] == 0
        assert s["inbox_count"] == 0
        assert s["classified_count"] == 0

    def test_total_groups_count(self, conn):
        _insert_group(conn, "g1", "111", sync_status="metadata_missing")
        _insert_group(conn, "g2", "222", sync_status="full")
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        assert s["total_groups"] == 2

    def test_metadata_status_counts(self, conn):
        _insert_group(conn, "g1", "111", sync_status="metadata_missing")
        _insert_group(conn, "g2", "222", sync_status="full")
        _insert_group(conn, "g3", "333", sync_status="full")
        _insert_group(conn, "g4", "444", sync_status="json_only")
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        counts = s["metadata_status_counts"]
        assert counts["metadata_missing"] == 1
        assert counts["full"] == 2
        assert counts["json_only"] == 1

    def test_extension_counts(self, conn):
        _insert_group(conn, "g1", "111", sync_status="full")
        _insert_group(conn, "g2", "222", sync_status="full")
        _insert_file(conn, "f1", "g1", "jpg")
        _insert_file(conn, "f2", "g1", "jpg")
        _insert_file(conn, "f3", "g2", "png")
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        assert s["extension_counts"]["jpg"] == 2
        assert s["extension_counts"]["png"] == 1

    def test_pixiv_id_extractable(self, conn):
        _insert_group(conn, "g1", "111", with_artwork_id=True)
        _insert_group(conn, "g2", "222", with_artwork_id=True)
        _insert_group(conn, "g3", "000", with_artwork_id=False)
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        assert s["pixiv_id_extractable"] == 2
        assert s["pixiv_id_missing"] == 1

    def test_classifiable_counts_full_json_only_xmp_failed(self, conn):
        _insert_group(conn, "g1", "1", sync_status="full")
        _insert_group(conn, "g2", "2", sync_status="json_only")
        _insert_group(conn, "g3", "3", sync_status="xmp_write_failed")
        _insert_group(conn, "g4", "4", sync_status="metadata_missing")
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        assert s["classifiable"] == 3
        assert s["excluded"] == 1

    def test_xmp_capable_equals_classifiable(self, conn):
        _insert_group(conn, "g1", "1", sync_status="full")
        _insert_group(conn, "g2", "2", sync_status="json_only")
        _insert_group(conn, "g3", "3", sync_status="metadata_missing")
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        assert s["xmp_capable"] == s["classifiable"]

    def test_inbox_and_classified_counts(self, conn):
        _insert_group(conn, "g1", "1", status="inbox",      sync_status="full")
        _insert_group(conn, "g2", "2", status="inbox",      sync_status="full")
        _insert_group(conn, "g3", "3", status="classified",  sync_status="full")
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        assert s["inbox_count"] == 2
        assert s["classified_count"] == 1

    def test_excluded_is_total_minus_classifiable(self, conn):
        for i in range(5):
            _insert_group(conn, f"g{i}", str(i),
                          sync_status="metadata_missing" if i < 2 else "full")
        conn.commit()
        s = build_workflow_file_status_summary(conn)
        assert s["excluded"] == s["total_groups"] - s["classifiable"]
