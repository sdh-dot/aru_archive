"""
InboxScanner 통합 테스트.

커버:
  - JPEG 메타 없음 → metadata_missing, no_metadata_queue 등록
  - 동일 파일 재스캔 → skipped
  - BMP → PNG managed 생성, DB 등록
  - static GIF → .aru.json sidecar 생성, json_only
  - xmp_write_failed → no_metadata_queue 미삽입 (v2.4 정책)
  - 빈 Inbox, 존재하지 않는 Inbox
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.inbox_scanner import InboxScanner, ScanResult, compute_file_hash
from db.database import initialize_database


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def archive(tmp_path):
    """임시 아카이브 루트 + 초기화된 DB 연결."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = str(data_dir / "aru_archive.db")
    conn = initialize_database(db_path)
    yield {"data_dir": str(data_dir), "db_path": db_path, "conn": conn}
    conn.close()


# ---------------------------------------------------------------------------
# 이미지 파일 생성 헬퍼 (Pillow 사용)
# ---------------------------------------------------------------------------

def _make_jpeg(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (4, 4), color=(200, 100, 50)).save(str(path), format="JPEG")


def _make_png(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (4, 4), color=(50, 100, 200)).save(str(path), format="PNG")


def _make_bmp(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (4, 4), color=(100, 200, 100)).save(str(path), format="BMP")


def _make_static_gif(path: Path) -> None:
    from PIL import Image
    img = Image.new("P", (4, 4))
    img.putpalette([255, 0, 0] * 256)
    img.save(str(path), format="GIF")


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_jpeg_no_metadata(archive, tmp_path):
    """메타데이터 없는 JPEG → metadata_missing, no_metadata_queue 등록."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _make_jpeg(inbox / "test.jpg")

    sc = InboxScanner(archive["conn"], archive["data_dir"])
    result = sc.scan(str(inbox))

    assert result.scanned == 1
    assert result.new == 1
    assert result.failed == 0

    row = archive["conn"].execute(
        "SELECT metadata_sync_status FROM artwork_groups"
    ).fetchone()
    assert row["metadata_sync_status"] == "metadata_missing"

    q = archive["conn"].execute(
        "SELECT fail_reason FROM no_metadata_queue"
    ).fetchone()
    assert q is not None
    assert q["fail_reason"] == "manual_add"


def test_duplicate_path_skip(archive, tmp_path):
    """같은 파일 두 번 스캔 → 두 번째는 skipped (경로 중복)."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _make_jpeg(inbox / "dup.jpg")

    sc = InboxScanner(archive["conn"], archive["data_dir"])
    r1 = sc.scan(str(inbox))
    r2 = sc.scan(str(inbox))

    assert r1.new == 1
    assert r2.skipped == 1
    assert r2.new == 0

    count = archive["conn"].execute(
        "SELECT COUNT(*) FROM artwork_groups"
    ).fetchone()[0]
    assert count == 1


def test_duplicate_hash_skip(archive, tmp_path):
    """같은 내용의 다른 이름 파일 → 해시 중복으로 skipped."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _make_jpeg(inbox / "a.jpg")

    inbox2 = tmp_path / "inbox2"
    inbox2.mkdir()
    # 완전히 동일한 내용으로 생성 (같은 픽셀·quality)
    import shutil
    shutil.copy(inbox / "a.jpg", inbox2 / "b.jpg")

    sc = InboxScanner(archive["conn"], archive["data_dir"])
    sc.scan(str(inbox))
    r2 = sc.scan(str(inbox2))

    assert r2.skipped == 1


def test_bmp_convert(archive, tmp_path):
    """BMP → PNG managed 생성, artwork_files에 managed 행 등록."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _make_bmp(inbox / "test.bmp")

    sc = InboxScanner(archive["conn"], archive["data_dir"])
    result = sc.scan(str(inbox))

    assert result.new == 1
    assert result.failed == 0

    roles = {r["file_role"] for r in archive["conn"].execute(
        "SELECT file_role FROM artwork_files"
    ).fetchall()}
    assert "original" in roles
    assert "managed" in roles

    managed_fmt = archive["conn"].execute(
        "SELECT file_format FROM artwork_files WHERE file_role = 'managed'"
    ).fetchone()
    assert managed_fmt["file_format"] == "png"

    group = archive["conn"].execute(
        "SELECT metadata_sync_status FROM artwork_groups"
    ).fetchone()
    assert group["metadata_sync_status"] == "metadata_missing"


def test_static_gif_sidecar(archive, tmp_path):
    """static GIF → .aru.json sidecar 생성, status=json_only."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _make_static_gif(inbox / "static.gif")

    sc = InboxScanner(archive["conn"], archive["data_dir"])
    result = sc.scan(str(inbox))

    assert result.new == 1

    group = archive["conn"].execute(
        "SELECT metadata_sync_status FROM artwork_groups"
    ).fetchone()
    assert group["metadata_sync_status"] == "json_only"

    sidecar = inbox / "static.gif.aru.json"
    assert sidecar.exists()

    roles = {r["file_role"] for r in archive["conn"].execute(
        "SELECT file_role FROM artwork_files"
    ).fetchall()}
    assert "sidecar" in roles


def test_xmp_write_failed_not_queued(archive, tmp_path):
    """xmp_write_failed는 no_metadata_queue에 INSERT하지 않는다 (v2.4 정책)."""
    from core.constants import XMP_WRITE_FAILED_SKIP_QUEUE
    assert XMP_WRITE_FAILED_SKIP_QUEUE is True

    sc = InboxScanner(archive["conn"], archive["data_dir"])
    sc._enqueue_no_metadata(
        tmp_path / "fake.jpg",
        "test-group-id",
        "xmp_write_failed",
        "2025-01-01T00:00:00+00:00",
    )

    count = archive["conn"].execute(
        "SELECT COUNT(*) FROM no_metadata_queue"
    ).fetchone()[0]
    assert count == 0


def test_regular_fail_reason_queued(archive, tmp_path):
    """일반 fail_reason은 no_metadata_queue에 정상 삽입된다."""
    sc = InboxScanner(archive["conn"], archive["data_dir"])
    sc._enqueue_no_metadata(
        tmp_path / "fake.jpg",
        None,
        "manual_add",
        "2025-01-01T00:00:00+00:00",
    )

    count = archive["conn"].execute(
        "SELECT COUNT(*) FROM no_metadata_queue"
    ).fetchone()[0]
    assert count == 1


def test_empty_inbox(archive, tmp_path):
    """빈 Inbox → 파일 0건, 오류 없음."""
    inbox = tmp_path / "empty"
    inbox.mkdir()

    sc = InboxScanner(archive["conn"], archive["data_dir"])
    result = sc.scan(str(inbox))

    assert result.scanned == 0
    assert result.new == 0
    assert result.failed == 0


def test_nonexistent_inbox(archive, tmp_path):
    """존재하지 않는 Inbox → 오류 없이 빈 ScanResult 반환."""
    sc = InboxScanner(archive["conn"], archive["data_dir"])
    result = sc.scan(str(tmp_path / "no_such_dir"))

    assert result.scanned == 0
    assert result.new == 0


def test_compute_file_hash(tmp_path):
    """compute_file_hash — 같은 내용은 같은 해시, 다른 내용은 다른 해시."""
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f3 = tmp_path / "c.bin"

    f1.write_bytes(b"hello")
    f2.write_bytes(b"hello")
    f3.write_bytes(b"world")

    assert compute_file_hash(f1) == compute_file_hash(f2)
    assert compute_file_hash(f1) != compute_file_hash(f3)
