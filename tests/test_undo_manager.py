"""
core/undo_manager.py 테스트.

원칙 검증:
  - classified_copy만 삭제
  - original / managed / sidecar는 절대 삭제하지 않음
  - copy_records 행 자체는 삭제하지 않음
  - artwork_files.file_status → 'deleted'
  - undo_status: completed / partial / failed / expired
"""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from db.database import initialize_database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_group(conn, group_id: str | None = None) -> str:
    gid = group_id or str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, source_site, downloaded_at, indexed_at)
           VALUES (?, ?, 'pixiv', ?, ?)""",
        (gid, gid[:8], now, now),
    )
    conn.commit()
    return gid


def _make_file(conn, group_id: str, role: str, path: str) -> str:
    fid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, file_role, file_path, file_format,
            file_status, created_at)
           VALUES (?, ?, ?, ?, 'jpg', 'present', ?)""",
        (fid, group_id, role, path, now),
    )
    conn.commit()
    return fid


def _make_undo_entry(
    conn,
    entry_id: str | None = None,
    status: str = "pending",
    days_offset: int = 7,
) -> str:
    eid = entry_id or str(uuid.uuid4())
    now = _now()
    expires = (datetime.now(timezone.utc) + timedelta(days=days_offset)).isoformat()
    conn.execute(
        """INSERT INTO undo_entries
           (entry_id, operation_type, performed_at, undo_expires_at,
            undo_status, description)
           VALUES (?, 'classify', ?, ?, ?, 'test')""",
        (eid, now, expires, status),
    )
    conn.commit()
    return eid


def _make_copy_record(
    conn,
    entry_id: str,
    src_file_id: str,
    dest_file_id: str,
    dest_path: str,
    dest_size: int = 100,
    mtime_iso: str | None = None,
    hash_val: str | None = None,
) -> None:
    now = _now()
    conn.execute(
        """INSERT INTO copy_records
           (entry_id, src_file_id, dest_file_id, src_path, dest_path,
            rule_id, dest_file_size, dest_mtime_at_copy,
            dest_hash_at_copy, copied_at)
           VALUES (?, ?, ?, 'src.jpg', ?, 'author_fallback', ?, ?, ?, ?)""",
        (entry_id, src_file_id, dest_file_id, dest_path,
         dest_size, mtime_iso, hash_val, now),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# list_undo_entries
# ---------------------------------------------------------------------------

def test_list_undo_entries_newest_first(conn):
    """list_undo_entries는 최신순으로 반환한다."""
    from core.undo_manager import list_undo_entries

    import time
    e1 = _make_undo_entry(conn)
    time.sleep(0.01)
    e2 = _make_undo_entry(conn)

    entries = list_undo_entries(conn)
    ids = [e["entry_id"] for e in entries]
    assert ids.index(e2) < ids.index(e1)


def test_list_undo_entries_status_filter(conn):
    """status 필터가 동작한다."""
    from core.undo_manager import list_undo_entries

    e_pending  = _make_undo_entry(conn, status="pending")
    _make_undo_entry(conn, status="completed")

    pending_ids = {e["entry_id"] for e in list_undo_entries(conn, status="pending")}
    assert e_pending in pending_ids
    completed_ids = {e["entry_id"] for e in list_undo_entries(conn, status="completed")}
    assert e_pending not in completed_ids


# ---------------------------------------------------------------------------
# evaluate_undo_entry
# ---------------------------------------------------------------------------

def test_evaluate_deletable(conn, tmp_path):
    """dest_path가 존재하고 classified_copy이면 deletable."""
    from core.undo_manager import evaluate_undo_entry

    dest = tmp_path / "Classified" / "file.jpg"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"x" * 50)
    stat = dest.stat()
    mtime_iso = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original", str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(
        conn, eid, src_fid, dest_fid, str(dest),
        dest_size=50, mtime_iso=mtime_iso,
    )

    result = evaluate_undo_entry(conn, eid)
    assert result["can_undo"]
    assert result["summary"]["deletable"] == 1
    assert result["records"][0]["status"] == "deletable"


def test_evaluate_missing(conn, tmp_path):
    """dest_path가 없으면 missing."""
    from core.undo_manager import evaluate_undo_entry

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(tmp_path / "gone.jpg"))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(tmp_path / "gone.jpg"))

    result = evaluate_undo_entry(conn, eid)
    assert result["summary"]["missing"] == 1
    assert result["records"][0]["status"] == "missing"


def test_evaluate_modified_size(conn, tmp_path):
    """파일 크기가 다르면 modified."""
    from core.undo_manager import evaluate_undo_entry

    dest = tmp_path / "file.jpg"
    dest.write_bytes(b"x" * 200)  # 실제 크기 200
    mtime_iso = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(
        conn, eid, src_fid, dest_fid, str(dest),
        dest_size=100, mtime_iso=mtime_iso,   # 기록된 크기 100 ≠ 실제 200
    )

    result = evaluate_undo_entry(conn, eid)
    assert result["records"][0]["status"] == "modified"
    assert result["requires_confirmation"]


def test_evaluate_unsafe_role(conn, tmp_path):
    """file_role이 original이면 unsafe_role."""
    from core.undo_manager import evaluate_undo_entry

    dest = tmp_path / "original.jpg"
    dest.write_bytes(b"x")

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original", str(tmp_path / "src.jpg"))
    # dest_file_id를 original 역할 파일로 지정
    dest_fid = _make_file(conn, gid, "original", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(dest), dest_size=1)

    result = evaluate_undo_entry(conn, eid)
    assert result["records"][0]["status"] == "unsafe_role"
    assert result["summary"]["unsafe"] == 1


# ---------------------------------------------------------------------------
# execute_undo_entry
# ---------------------------------------------------------------------------

def test_execute_deletes_classified_copy(conn, tmp_path):
    """execute_undo_entry는 classified_copy 파일을 삭제한다."""
    from core.undo_manager import execute_undo_entry

    dest = tmp_path / "Classified" / "file.jpg"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"x" * 50)
    stat = dest.stat()
    mtime_iso = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(dest),
                      dest_size=50, mtime_iso=mtime_iso)

    result = execute_undo_entry(conn, eid)

    assert result["undo_status"] == "completed"
    assert str(dest) in result["deleted"]
    assert not dest.exists()


def test_execute_does_not_delete_original(conn, tmp_path):
    """original 역할 파일은 삭제하지 않는다."""
    from core.undo_manager import execute_undo_entry

    orig = tmp_path / "Inbox" / "orig.jpg"
    orig.parent.mkdir(parents=True)
    orig.write_bytes(b"original content")

    gid = _make_group(conn)
    src_fid = _make_file(conn, gid, "original", str(orig))
    # dest_file_id를 original로 등록 → unsafe_role
    dest_fid = _make_file(conn, gid, "original", str(tmp_path / "fake.jpg"))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(orig), dest_size=16)

    result = execute_undo_entry(conn, eid)

    assert orig.exists(), "원본은 절대 삭제되지 않아야 한다"
    assert str(orig) not in result.get("deleted", [])


def test_execute_preserves_copy_records(conn, tmp_path):
    """copy_records 행은 삭제하지 않는다."""
    from core.undo_manager import execute_undo_entry

    dest = tmp_path / "file.jpg"
    dest.write_bytes(b"x")
    mtime_iso = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(dest),
                      dest_size=1, mtime_iso=mtime_iso)

    execute_undo_entry(conn, eid)

    count = conn.execute(
        "SELECT COUNT(*) FROM copy_records WHERE entry_id=?", (eid,)
    ).fetchone()[0]
    assert count == 1, "copy_records는 삭제되지 않아야 한다"


def test_execute_marks_file_status_deleted(conn, tmp_path):
    """삭제한 파일의 artwork_files.file_status → 'deleted'."""
    from core.undo_manager import execute_undo_entry

    dest = tmp_path / "file.jpg"
    dest.write_bytes(b"x" * 10)
    mtime_iso = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(dest),
                      dest_size=10, mtime_iso=mtime_iso)

    execute_undo_entry(conn, eid)

    row = conn.execute(
        "SELECT file_status FROM artwork_files WHERE file_id=?", (dest_fid,)
    ).fetchone()
    assert row["file_status"] == "deleted"


def test_execute_undo_status_completed(conn, tmp_path):
    """모든 대상 삭제 성공 → undo_status='completed'."""
    from core.undo_manager import execute_undo_entry

    dest = tmp_path / "f.jpg"
    dest.write_bytes(b"y")
    mtime_iso = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(dest),
                      dest_size=1, mtime_iso=mtime_iso)

    result = execute_undo_entry(conn, eid)
    assert result["undo_status"] == "completed"

    row = conn.execute(
        "SELECT undo_status FROM undo_entries WHERE entry_id=?", (eid,)
    ).fetchone()
    assert row["undo_status"] == "completed"


def test_execute_partial_when_some_fail(conn, tmp_path):
    """일부 성공, 일부 missing → undo_status='completed' (missing은 건너뜀)."""
    from core.undo_manager import execute_undo_entry

    # 실제로 존재하는 파일
    dest1 = tmp_path / "f1.jpg"
    dest1.write_bytes(b"a")
    mtime1 = datetime.fromtimestamp(dest1.stat().st_mtime, tz=timezone.utc).isoformat()
    # 존재하지 않는 파일
    dest2 = tmp_path / "gone.jpg"

    gid = _make_group(conn)
    src_fid   = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid1 = _make_file(conn, gid, "classified_copy", str(dest1))
    dest_fid2 = _make_file(conn, gid, "classified_copy", str(dest2))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid1, str(dest1),
                      dest_size=1, mtime_iso=mtime1)
    _make_copy_record(conn, eid, src_fid, dest_fid2, str(dest2), dest_size=1)

    result = execute_undo_entry(conn, eid)
    # 1개 삭제 성공, 1개 missing(건너뜀) → completed
    assert result["undo_status"] == "completed"
    assert str(dest1) in result["deleted"]
    assert str(dest2) in result["skipped_missing"]


def test_execute_force_modified(conn, tmp_path):
    """force_modified=True면 수정된 파일도 삭제한다."""
    from core.undo_manager import execute_undo_entry

    dest = tmp_path / "modified.jpg"
    dest.write_bytes(b"x" * 200)
    mtime_iso = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(dest),
                      dest_size=50,        # 실제 200 ≠ 기록 50 → modified
                      mtime_iso=mtime_iso)

    result = execute_undo_entry(conn, eid, force_modified=True)
    assert str(dest) in result["deleted"]
    assert not dest.exists()


def test_execute_aborts_on_modified_without_force(conn, tmp_path):
    """force_modified=False이고 modified 파일이 있으면 실행 중단."""
    from core.undo_manager import execute_undo_entry

    dest = tmp_path / "modified.jpg"
    dest.write_bytes(b"x" * 200)
    mtime_iso = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc).isoformat()

    gid = _make_group(conn)
    src_fid  = _make_file(conn, gid, "original",        str(tmp_path / "src.jpg"))
    dest_fid = _make_file(conn, gid, "classified_copy", str(dest))
    eid = _make_undo_entry(conn)
    _make_copy_record(conn, eid, src_fid, dest_fid, str(dest),
                      dest_size=50, mtime_iso=mtime_iso)

    result = execute_undo_entry(conn, eid, force_modified=False)
    assert result.get("aborted")
    assert dest.exists(), "중단 시 파일은 삭제되지 않아야 한다"

    # undo_status는 여전히 pending
    row = conn.execute(
        "SELECT undo_status FROM undo_entries WHERE entry_id=?", (eid,)
    ).fetchone()
    assert row["undo_status"] == "pending"


def test_execute_raises_if_not_pending(conn, tmp_path):
    """pending이 아닌 항목은 ValueError."""
    from core.undo_manager import execute_undo_entry

    eid = _make_undo_entry(conn, status="completed")
    with pytest.raises(ValueError, match="pending만 실행 가능"):
        execute_undo_entry(conn, eid)


# ---------------------------------------------------------------------------
# expire_old_undo_entries
# ---------------------------------------------------------------------------

def test_expire_changes_pending_to_expired(conn):
    """만료 기간이 지난 pending 항목을 expired로 변경한다."""
    from core.undo_manager import expire_old_undo_entries

    # 이미 만료된 항목 (undo_expires_at을 과거로)
    eid = str(uuid.uuid4())
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn.execute(
        """INSERT INTO undo_entries
           (entry_id, operation_type, performed_at, undo_expires_at,
            undo_status, description)
           VALUES (?, 'classify', ?, ?, 'pending', 'expired_test')""",
        (eid, _now(), past),
    )
    conn.commit()

    count = expire_old_undo_entries(conn)
    assert count >= 1

    row = conn.execute(
        "SELECT undo_status FROM undo_entries WHERE entry_id=?", (eid,)
    ).fetchone()
    assert row["undo_status"] == "expired"


def test_expire_nullifies_b2_columns(conn):
    """만료 후 dest_hash_at_copy / dest_mtime_at_copy가 NULL 처리된다."""
    from core.undo_manager import expire_old_undo_entries

    eid = str(uuid.uuid4())
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn.execute(
        """INSERT INTO undo_entries
           (entry_id, operation_type, performed_at, undo_expires_at,
            undo_status, description)
           VALUES (?, 'classify', ?, ?, 'pending', 'b2_test')""",
        (eid, _now(), past),
    )
    # copy_records 행 추가
    conn.execute(
        """INSERT INTO copy_records
           (entry_id, src_path, dest_path, dest_file_size,
            dest_mtime_at_copy, dest_hash_at_copy, copied_at)
           VALUES (?, 'src.jpg', 'dst.jpg', 100, '2025-01-01T00:00:00', 'abc123', ?)""",
        (eid, _now()),
    )
    conn.commit()

    expire_old_undo_entries(conn)

    row = conn.execute(
        "SELECT dest_hash_at_copy, dest_mtime_at_copy FROM copy_records WHERE entry_id=?",
        (eid,),
    ).fetchone()
    assert row["dest_hash_at_copy"] is None
    assert row["dest_mtime_at_copy"] is None


def test_expire_does_not_affect_completed(conn):
    """completed 항목은 expire 대상이 아니다."""
    from core.undo_manager import expire_old_undo_entries

    eid = _make_undo_entry(conn, status="completed", days_offset=-5)
    expire_old_undo_entries(conn)

    row = conn.execute(
        "SELECT undo_status FROM undo_entries WHERE entry_id=?", (eid,)
    ).fetchone()
    assert row["undo_status"] == "completed"


# ---------------------------------------------------------------------------
# cleanup_empty_dirs
# ---------------------------------------------------------------------------

def test_cleanup_empty_dirs(tmp_path):
    """빈 폴더를 stop_at까지 삭제한다."""
    from core.undo_manager import cleanup_empty_dirs

    classified = tmp_path / "Classified"
    leaf = classified / "BySeries" / "BlueArchive" / "Char"
    leaf.mkdir(parents=True)
    deleted_file = leaf / "img.jpg"
    deleted_file.touch()
    deleted_file.unlink()  # 파일 삭제 후 폴더만 남음

    removed = cleanup_empty_dirs(deleted_file, stop_at=classified)
    assert removed > 0
    assert not leaf.exists()
    assert classified.exists(), "stop_at 자체는 삭제되지 않아야 한다"


def test_cleanup_does_not_remove_nonempty(tmp_path):
    """내용이 있는 폴더는 삭제하지 않는다."""
    from core.undo_manager import cleanup_empty_dirs

    classified = tmp_path / "Classified"
    leaf = classified / "BySeries" / "BlueArchive"
    leaf.mkdir(parents=True)
    (leaf / "other.jpg").touch()  # 다른 파일 존재

    deleted_file = leaf / "img.jpg"
    deleted_file.touch()
    deleted_file.unlink()

    removed = cleanup_empty_dirs(deleted_file, stop_at=classified)
    assert removed == 0
    assert leaf.exists()
