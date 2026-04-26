"""
core/worker.py save_pixiv_artwork 파이프라인 테스트.
Pixiv API와 다운로더를 mock하여 DB 기록을 검증한다.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    c = initialize_database(str(tmp_path / "worker_test.db"))
    yield c
    c.close()


@pytest.fixture
def config(tmp_path):
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    return {
        "data_dir":  str(tmp_path / "AruArchive"),
        "inbox_dir": str(inbox),
        "db":        {"path": str(tmp_path / "worker_test.db")},
        "classify_mode": "save_only",
    }


def _raw_meta(artwork_id="12345678", n=1):
    return {
        "illustId":   artwork_id,
        "title":      "Test Artwork",
        "userId":     "9999",
        "userName":   "TestArtist",
        "pageCount":  n,
        "illustType": 0,
        "xRestrict":  0,
        "tags": {
            "tags": [
                {"tag": "テスト"},
                {"tag": "original", "translation": {"en": "original"}},
            ]
        },
    }


def _pages_raw(artwork_id="12345678", n=1):
    return [
        {
            "urls": {"original": f"https://i.pximg.net/{artwork_id}_p{i}.jpg"},
            "width": 1200,
            "height": 1600,
        }
        for i in range(n)
    ]


def _fake_download(url, dest_path, *, referer, cookies=None, timeout=60):
    Path(dest_path).write_bytes(b"FAKE_JPEG")
    return 9


def _std_ctx(artwork_id="12345678", n=1, download_side_effect=_fake_download):
    """표준 mock 컨텍스트 스택을 반환한다.

    download_pixiv_image / write_aru_metadata는 worker 내부에서 local import되므로
    원본 모듈에서 패치해야 한다.
    """
    from core.adapters.pixiv import PixivAdapter
    stack = contextlib.ExitStack()
    stack.enter_context(patch.object(PixivAdapter, "fetch_metadata",
                                     return_value=_raw_meta(artwork_id, n)))
    stack.enter_context(patch("core.worker._fetch_pages",
                              return_value=_pages_raw(artwork_id, n)))
    stack.enter_context(patch("core.pixiv_downloader.download_pixiv_image",
                              side_effect=download_side_effect))
    stack.enter_context(patch("core.metadata_writer.write_aru_metadata"))
    stack.enter_context(patch("core.worker._generate_cover_thumbnail"))
    return stack


# ---------------------------------------------------------------------------

def test_single_page_saved(conn, config):
    """단일 페이지 아트워크가 저장되고 DB 레코드가 생성된다."""
    from core.worker import save_pixiv_artwork

    with _std_ctx():
        result = save_pixiv_artwork(conn, config, "12345678")

    assert result["saved"] == 1
    assert result["total"] == 1
    assert result["failed"] == 0
    assert "job_id" in result

    job = conn.execute(
        "SELECT status, saved_pages FROM save_jobs WHERE job_id=?", (result["job_id"],)
    ).fetchone()
    assert job["status"] == "completed"
    assert job["saved_pages"] == 1

    group = conn.execute(
        "SELECT artwork_title FROM artwork_groups WHERE artwork_id='12345678'"
    ).fetchone()
    assert group["artwork_title"] == "Test Artwork"


def test_multi_page_all_saved(conn, config):
    """3페이지 작품: 모두 저장되고 job_pages 레코드 3개가 생성된다."""
    from core.worker import save_pixiv_artwork

    with _std_ctx(n=3):
        result = save_pixiv_artwork(conn, config, "12345678")

    assert result["saved"] == 3
    assert result["failed"] == 0

    n_files = conn.execute(
        "SELECT count(*) as n FROM artwork_files WHERE file_role='original'"
    ).fetchone()["n"]
    assert n_files == 3

    n_pages = conn.execute(
        "SELECT count(*) as n FROM job_pages WHERE status='saved'"
    ).fetchone()["n"]
    assert n_pages == 3


def test_partial_failure(conn, config):
    """2페이지 중 1페이지 실패 → job status=partial."""
    from core.pixiv_downloader import PixivDownloadError
    from core.worker import save_pixiv_artwork

    call_count = [0]

    def sometimes_fail(url, dest_path, *, referer, cookies=None, timeout=60):
        call_count[0] += 1
        if call_count[0] == 2:
            raise PixivDownloadError("HTTP 404")
        return _fake_download(url, dest_path, referer=referer)

    from core.adapters.pixiv import PixivAdapter
    with (
        patch.object(PixivAdapter, "fetch_metadata", return_value=_raw_meta(n=2)),
        patch("core.worker._fetch_pages", return_value=_pages_raw(n=2)),
        patch("core.pixiv_downloader.download_pixiv_image", side_effect=sometimes_fail),
        patch("core.metadata_writer.write_aru_metadata"),
        patch("core.worker._generate_cover_thumbnail"),
    ):
        result = save_pixiv_artwork(conn, config, "12345678")

    assert result["saved"] == 1
    assert result["failed"] == 1

    job = conn.execute(
        "SELECT status FROM save_jobs WHERE job_id=?", (result["job_id"],)
    ).fetchone()
    assert job["status"] == "partial"


def test_all_failed(conn, config):
    """전체 다운로드 실패 → job status=failed."""
    from core.pixiv_downloader import PixivDownloadError
    from core.worker import save_pixiv_artwork

    def always_fail(*a, **kw):
        raise PixivDownloadError("HTTP 403")

    from core.adapters.pixiv import PixivAdapter
    with (
        patch.object(PixivAdapter, "fetch_metadata", return_value=_raw_meta()),
        patch("core.worker._fetch_pages", return_value=_pages_raw()),
        patch("core.pixiv_downloader.download_pixiv_image", side_effect=always_fail),
        patch("core.metadata_writer.write_aru_metadata"),
        patch("core.worker._generate_cover_thumbnail"),
    ):
        result = save_pixiv_artwork(conn, config, "12345678")

    assert result["saved"] == 0
    job = conn.execute(
        "SELECT status FROM save_jobs WHERE job_id=?", (result["job_id"],)
    ).fetchone()
    assert job["status"] == "failed"


def test_tags_recorded(conn, config):
    """저장 후 tags 테이블에 태그가 기록된다."""
    from core.worker import save_pixiv_artwork

    with _std_ctx():
        save_pixiv_artwork(conn, config, "12345678")

    tags = [r["tag"] for r in conn.execute("SELECT tag FROM tags").fetchall()]
    assert "テスト" in tags


def test_artwork_group_idempotent(conn, config):
    """동일 artwork_id로 두 번 저장해도 artwork_groups는 하나만 생성된다."""
    from core.worker import save_pixiv_artwork

    with _std_ctx():
        save_pixiv_artwork(conn, config, "12345678")
    with _std_ctx():
        save_pixiv_artwork(conn, config, "12345678")

    count = conn.execute(
        "SELECT count(*) as n FROM artwork_groups WHERE artwork_id='12345678'"
    ).fetchone()["n"]
    assert count == 1


def test_lock_prevents_duplicate(conn, config):
    """동일 artwork_id에 잠금이 걸려 있으면 LockAcquisitionError가 발생한다."""
    from core.constants import make_save_lock_key
    from core.locks import LockAcquisitionError, acquire_lock
    from core.worker import save_pixiv_artwork

    lock_key = make_save_lock_key("pixiv", "99999")
    acquire_lock(conn, lock_key, "test", 60)

    with pytest.raises(LockAcquisitionError):
        save_pixiv_artwork(conn, config, "99999")


def test_job_pages_saved_status(conn, config):
    """저장된 페이지의 job_pages.status가 'saved'이다."""
    from core.worker import save_pixiv_artwork

    with _std_ctx(n=2):
        result = save_pixiv_artwork(conn, config, "12345678")

    statuses = [
        r["status"]
        for r in conn.execute(
            "SELECT status FROM job_pages WHERE job_id=?", (result["job_id"],)
        ).fetchall()
    ]
    assert all(s == "saved" for s in statuses)
