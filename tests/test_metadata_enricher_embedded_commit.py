"""``_set_file_embedded`` 의 명시적 commit 회귀 테스트.

배경:
``core.metadata_enricher._set_file_embedded`` 는 이전에 commit 을 호출하지
않아, ``enrich_file_from_pixiv`` 의 embed_failed 경로가 호출자 측 trailing
commit (예: ``_EnrichThread.run()`` 루프 끝의 ``conn.commit()``) 에 의존했다.

이 테스트는:
- helper 가 자체 commit 을 수행해 connection close 후에도 ``metadata_embedded=0``
  가 보존되는지
- 기존 success 경로 ``metadata_embedded=1`` 도 동일하게 보존되는지
를 lock 한다.
"""
from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.metadata_enricher import _set_file_embedded, enrich_file_from_pixiv


# ---------------------------------------------------------------------------
# Fixtures (test_metadata_enricher.py 와 같은 패턴)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    from db.database import initialize_database
    p = str(tmp_path / "embedded_commit.db")
    conn = initialize_database(p)
    conn.close()
    return p


@pytest.fixture()
def db(db_path: str) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _insert_group(conn: sqlite3.Connection, group_id: str, artwork_id: str) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, ?, ?, ?, 'metadata_missing')""",
        (group_id, artwork_id, now, now),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection, file_id: str, group_id: str,
    file_path: str, file_format: str = "jpg", page_index: int = 0,
) -> None:
    now = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at)
           VALUES (?, ?, ?, 'original', ?, ?, ?)""",
        (file_id, group_id, page_index, file_path, file_format, now),
    )
    conn.commit()


def _make_jpeg(path: Path) -> Path:
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (1, 1), (128, 64, 32)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())
    return path


def _make_adapter_success(body: dict) -> MagicMock:
    """fetch + to_aru_metadata 둘 다 성공하는 adapter."""
    from datetime import datetime, timezone

    from core.models import AruMetadata
    adapter = MagicMock()
    adapter.fetch_metadata.return_value = body
    meta = AruMetadata(
        artwork_id=body.get("illustId", "123"),
        artwork_title=body.get("title", "Test"),
        artist_id="999",
        artist_name="Artist",
        artist_url="https://www.pixiv.net/users/999",
        tags=["tag1"],
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        _provenance={
            "source":      "pixiv_ajax_api",
            "confidence":  "high",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    adapter.to_aru_metadata.return_value = meta
    return adapter


def _read_embedded(db_path: str, file_id: str) -> int | None:
    """DB 를 새 connection 으로 열어 metadata_embedded 를 조회한다.

    None 반환 = row 없음.  int 반환 = 저장된 flag 값.
    별도 connection 으로 읽어야 commit 여부를 정확히 검증할 수 있다.
    """
    from db.database import initialize_database
    conn = initialize_database(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT metadata_embedded FROM artwork_files WHERE file_id = ?",
            (file_id,),
        ).fetchone()
        if row is None:
            return None
        return int(row["metadata_embedded"])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helper 단위 테스트 — 명시적 commit
# ---------------------------------------------------------------------------

class TestSetFileEmbeddedCommit:
    def test_helper_commits_immediately(self, db: sqlite3.Connection, db_path: str):
        """_set_file_embedded 호출 직후 다른 connection 에서도 변경이 보여야 한다."""
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "11111")
        _insert_file(db, fid, gid, "/dummy/path.jpg")
        # 초기값 = 0 (schema default)
        assert _read_embedded(db_path, fid) == 0

        _set_file_embedded(db, fid, 1)

        # commit 됐다면 별도 connection 에서 1 로 보임
        assert _read_embedded(db_path, fid) == 1

    def test_helper_zero_value_committed(self, db: sqlite3.Connection, db_path: str):
        """embed_failed 경로의 핵심 — embedded=0 도 명시적으로 commit 되어야 한다."""
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "22222")
        _insert_file(db, fid, gid, "/dummy/path2.jpg")

        # 우선 1 로 set 후 commit
        _set_file_embedded(db, fid, 1)
        assert _read_embedded(db_path, fid) == 1

        # 0 으로 다시 set — 이게 commit 안 되면 다른 connection 은 여전히 1 을 봄
        _set_file_embedded(db, fid, 0)
        assert _read_embedded(db_path, fid) == 0


# ---------------------------------------------------------------------------
# 통합 테스트 — embed_failed 경로의 metadata_embedded=0 보존
# ---------------------------------------------------------------------------

class TestEmbedFailedPersistsAcrossClose:
    def test_embed_failed_persists_metadata_embedded_zero(
        self, db: sqlite3.Connection, db_path: str, tmp_path: Path,
    ):
        """write_aru_metadata 실패 → embed_failed 종료 → conn close 후에도
        metadata_embedded=0 이 유지되어야 한다.

        helper 가 trailing commit 에 의존하면 close 시 SQLite 가 implicit
        deferred transaction 을 rollback 하여 이 값이 사라진다.
        """
        img = _make_jpeg(tmp_path / "12345678_p0.jpg")
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img), "jpg")
        # 초기 schema default 는 0 — 미리 1 로 만들어두고 fail 후 0 으로 떨어지는지 본다.
        _set_file_embedded(db, fid, 1)
        assert _read_embedded(db_path, fid) == 1

        body = {
            "illustId": "12345678", "title": "Embed Fail Test", "userId": "999",
            "userName": "Artist", "pageCount": 1, "illustType": 0,
            "tags": {"tags": [{"tag": "tag1"}]},
        }
        adapter = _make_adapter_success(body)

        # write_aru_metadata 가 raise → enrich_file_from_pixiv 의 embed_failed 경로 진입
        with patch(
            "core.metadata_enricher.write_aru_metadata",
            side_effect=OSError("simulated write failure"),
        ):
            result = enrich_file_from_pixiv(db, fid, adapter=adapter)

        assert result["status"] == "embed_failed"
        assert result["sync_status"] == "metadata_write_failed"

        # 실제 close — _EnrichThread 의 finally close 와 동일한 시점
        db.close()

        # 새 connection 으로 metadata_embedded=0 확인
        assert _read_embedded(db_path, fid) == 0


# ---------------------------------------------------------------------------
# Success path 회귀 — embedded=1 도 commit 되어야 함
# ---------------------------------------------------------------------------

class TestSuccessPathRegression:
    def test_success_path_persists_metadata_embedded_one(
        self, db: sqlite3.Connection, db_path: str, tmp_path: Path,
    ):
        img = _make_jpeg(tmp_path / "87654321_p0.jpg")
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, "87654321")
        _insert_file(db, fid, gid, str(img), "jpg")
        assert _read_embedded(db_path, fid) == 0

        body = {
            "illustId": "87654321", "title": "Success Test", "userId": "999",
            "userName": "Artist", "pageCount": 1, "illustType": 0,
            "tags": {"tags": [{"tag": "tag1"}]},
        }
        adapter = _make_adapter_success(body)

        result = enrich_file_from_pixiv(db, fid, adapter=adapter)
        assert result["status"] == "success"

        db.close()
        assert _read_embedded(db_path, fid) == 1
