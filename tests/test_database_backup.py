"""
tests/test_database_backup.py

backup_database helper 단위 테스트.
"""
from __future__ import annotations

import pytest


def test_backup_creates_file(tmp_path):
    """정상 경로에서 backup_database는 백업 파일을 생성하고 True를 반환해야 한다."""
    from db.database import backup_database

    src = tmp_path / "aru_archive.db"
    src.write_bytes(b"fake db data")
    dst = tmp_path / "aru_archive_before_reset_20250502_120000.db"

    result = backup_database(str(src), str(dst))

    assert result is True
    assert dst.exists()
    assert dst.read_bytes() == b"fake db data"


def test_backup_refuses_existing_target(tmp_path):
    """백업 대상 파일이 이미 존재하면 False를 반환하고 덮어쓰지 않아야 한다."""
    from db.database import backup_database

    src = tmp_path / "aru_archive.db"
    src.write_bytes(b"new data")
    dst = tmp_path / "backup.db"
    dst.write_bytes(b"existing backup")

    result = backup_database(str(src), str(dst))

    assert result is False
    assert dst.read_bytes() == b"existing backup", "existing backup must not be overwritten"


def test_backup_returns_false_when_src_missing(tmp_path):
    """소스 파일이 존재하지 않으면 False를 반환해야 한다."""
    from db.database import backup_database

    src = tmp_path / "nonexistent.db"
    dst = tmp_path / "backup.db"

    result = backup_database(str(src), str(dst))

    assert result is False
    assert not dst.exists()


def test_backup_returns_false_on_io_error(tmp_path, monkeypatch):
    """shutil.copy2가 OSError를 발생시키면 False를 반환해야 한다."""
    import shutil

    from db.database import backup_database

    src = tmp_path / "aru_archive.db"
    src.write_bytes(b"data")
    dst = tmp_path / "backup.db"

    def _raise(*a, **kw):
        raise OSError("simulated IO error")

    monkeypatch.setattr(shutil, "copy2", _raise)

    result = backup_database(str(src), str(dst))

    assert result is False


def test_backup_preserves_content_integrity(tmp_path):
    """백업 파일의 내용이 원본과 동일해야 한다."""
    from db.database import backup_database

    content = b"\x53\x51\x4c\x69\x74\x65\x20\x66\x6f\x72\x6d\x61\x74\x20\x33\x00"  # SQLite magic
    src = tmp_path / "real.db"
    src.write_bytes(content)
    dst = tmp_path / "real_backup.db"

    result = backup_database(str(src), str(dst))

    assert result is True
    assert dst.read_bytes() == content
