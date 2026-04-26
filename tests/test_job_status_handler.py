"""
native_host.host._handle_get_job_status 단위 테스트.

save_jobs / job_pages / artwork_files 테이블을 직접 구성하여
progress, pages, file_path JOIN, 오류 케이스를 검증한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    c = initialize_database(str(tmp_path / "jsh_test.db"))
    yield c
    c.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_job(conn, *, status="running", total=2, saved=0, failed=0, error=None):
    job_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO save_jobs
            (job_id, source_site, artwork_id, status, total_pages,
             saved_pages, failed_pages, started_at, error_message)
           VALUES (?, 'pixiv', '12345678', ?, ?, ?, ?, ?, ?)""",
        (job_id, status, total, saved, failed, _now(), error),
    )
    conn.commit()
    return job_id


def _insert_page(conn, job_id, *, page_index=0, status="saved", file_id=None, error=None):
    conn.execute(
        """INSERT INTO job_pages
            (job_id, page_index, url, filename, status, file_id, error_message)
           VALUES (?, ?, 'http://x', 'p0.jpg', ?, ?, ?)""",
        (job_id, page_index, status, file_id, error),
    )
    conn.commit()


def _insert_file(conn, *, file_path="/Inbox/p0.jpg", page_index=0):
    file_id = str(uuid.uuid4())
    group_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_groups
            (group_id, source_site, artwork_id, artwork_kind, total_pages,
             downloaded_at, indexed_at, status, metadata_sync_status)
           VALUES (?, 'pixiv', '12345678', 'single_image', 1, ?, ?, 'inbox', 'pending')""",
        (group_id, _now(), _now()),
    )
    conn.execute(
        """INSERT INTO artwork_files
            (file_id, group_id, page_index, file_role, file_path,
             file_format, file_size, metadata_embedded, file_status, created_at)
           VALUES (?, ?, ?, 'original', ?, 'jpg', 9, 1, 'present', ?)""",
        (file_id, group_id, page_index, file_path, _now()),
    )
    conn.commit()
    return file_id


# ---------------------------------------------------------------------------

def test_job_not_found(conn):
    """`_handle_get_job_status`가 존재하지 않는 job_id에 `_error` 반환."""
    from native_host.host import _handle_get_job_status
    result = _handle_get_job_status(conn, "nonexistent-job-id")
    assert result.get("_error") == "job_not_found"


def test_running_status(conn):
    """실행 중인 job: status=running, progress 반환."""
    from native_host.host import _handle_get_job_status
    job_id = _insert_job(conn, status="running", total=3, saved=1)
    _insert_page(conn, job_id, page_index=0, status="saved")

    result = _handle_get_job_status(conn, job_id)
    assert result["status"] == "running"
    assert result["progress"]["total_pages"] == 3
    assert result["progress"]["saved_pages"] == 1


def test_completed_status(conn):
    """완료된 job: status=completed, pages 목록 포함."""
    from native_host.host import _handle_get_job_status
    job_id = _insert_job(conn, status="completed", total=2, saved=2, failed=0)
    _insert_page(conn, job_id, page_index=0, status="saved")
    _insert_page(conn, job_id, page_index=1, status="saved")

    result = _handle_get_job_status(conn, job_id)
    assert result["status"] == "completed"
    assert len(result["pages"]) == 2
    assert result["pages"][0]["status"] == "saved"


def test_partial_status_with_failed_page(conn):
    """부분 완료: failed 페이지의 error_message가 포함된다."""
    from native_host.host import _handle_get_job_status
    job_id = _insert_job(conn, status="partial", total=2, saved=1, failed=1)
    _insert_page(conn, job_id, page_index=0, status="saved")
    _insert_page(conn, job_id, page_index=1, status="failed", error="HTTP 404")

    result = _handle_get_job_status(conn, job_id)
    assert result["status"] == "partial"
    assert result["progress"]["failed_pages"] == 1

    failed_page = next(p for p in result["pages"] if p["page_index"] == 1)
    assert failed_page["error_message"] == "HTTP 404"
    assert "file_path" not in failed_page


def test_file_path_via_join(conn):
    """저장된 페이지의 file_path가 artwork_files JOIN으로 반환된다."""
    from native_host.host import _handle_get_job_status

    file_id = _insert_file(conn, file_path="/Inbox/art_p0.jpg", page_index=0)
    job_id  = _insert_job(conn, status="completed", total=1, saved=1)
    _insert_page(conn, job_id, page_index=0, status="saved", file_id=file_id)

    result = _handle_get_job_status(conn, job_id)
    page = result["pages"][0]
    assert page["file_path"] == "/Inbox/art_p0.jpg"


def test_progress_zeros_when_null(conn):
    """saved_pages / failed_pages が NULL の場合に 0 で返される。"""
    from native_host.host import _handle_get_job_status
    job_id = str(uuid.uuid4())
    # total_pages=0 を明示。saved_pages/failed_pages は省略して NULL にする
    conn.execute(
        "INSERT INTO save_jobs"
        " (job_id, source_site, artwork_id, status, total_pages, started_at)"
        " VALUES (?, 'pixiv', '99', 'running', 0, ?)",
        (job_id, _now()),
    )
    conn.commit()

    result = _handle_get_job_status(conn, job_id)
    assert result["progress"]["total_pages"]  == 0
    assert result["progress"]["saved_pages"]  == 0
    assert result["progress"]["failed_pages"] == 0


def test_no_pages_returns_empty_list(conn):
    """job_pages가 없는 job은 pages=[] 반환."""
    from native_host.host import _handle_get_job_status
    job_id = _insert_job(conn, status="running", total=1)

    result = _handle_get_job_status(conn, job_id)
    assert result["pages"] == []
