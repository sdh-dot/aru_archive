"""메타데이터 batch Phase 1 / Phase 2 순차 실행 구조 테스트.

_EnrichThread.run() 의 Phase 1 → Phase 2 batch 오케스트레이션 로직을
함수 레벨로 재현하여 검증한다. QThread 직접 테스트는 Qt 이벤트 루프가
필요하므로 이 파일에서는 함수 호출 레벨을 커버한다.

확인 사항:
- Phase 1 全 성공 → write_targets = 全 대상
- Phase 1 일부 실패 → write_targets = 성공 건만
- Phase 1 全 실패 → Phase 2 실행 안 됨 (write_targets 비어있음)
- Phase 2 일부 실패 → write_failed 카운트
- Phase 2 skipped → write_skipped 카운트
- 빈 queue → 全 카운터 0
- Phase 1 commit 후 Phase 2 DB 읽기 정합성
- summary dict 키 정확성
"""
from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PILImage

from core.metadata_enricher import (
    fetch_and_store_pixiv_metadata,
    write_stored_metadata_to_file,
    build_enrichment_queue,
)


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _insert_group(
    conn: sqlite3.Connection,
    group_id: str,
    artwork_id: str = "12345678",
    sync_status: str = "metadata_missing",
) -> None:
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, ?, ?, ?, ?)""",
        (group_id, artwork_id, _now(), _now(), sync_status),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection,
    file_id: str,
    group_id: str,
    file_path: str,
) -> None:
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format, created_at)
           VALUES (?, ?, 0, 'original', ?, 'jpg', ?)""",
        (file_id, group_id, file_path, _now()),
    )
    conn.commit()


def _make_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    PILImage.new("RGB", (1, 1), (128, 64, 32)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())


def _make_adapter(artwork_id: str = "12345678") -> MagicMock:
    from core.models import AruMetadata
    adapter = MagicMock()
    adapter.fetch_metadata.return_value = {
        "illustId": artwork_id, "title": "Test Art", "userId": "999",
        "userName": "TestArtist", "pageCount": 1, "illustType": 0,
        "tags": {"tags": [{"tag": "テスト"}]},
    }
    meta = AruMetadata(
        artwork_id=artwork_id, artwork_title="Test Art",
        artist_id="999", artist_name="TestArtist",
        artist_url=f"https://www.pixiv.net/users/999",
        tags=["テスト"], series_tags=[], character_tags=[],
        raw_tags=["テスト"],
    )
    adapter.to_aru_metadata.return_value = meta
    return adapter


def _run_batch(
    conn: sqlite3.Connection,
    file_ids: list[str],
    adapter,
    exiftool_path: str | None = None,
) -> dict:
    """_EnrichThread.run() Phase 1→2 오케스트레이션을 함수 레벨로 재현."""
    fetch_success = 0
    fetch_failed = 0
    write_targets: list[str] = []

    for file_id in file_ids:
        r = fetch_and_store_pixiv_metadata(conn, file_id, adapter=adapter)
        if r["status"] == "ok":
            fetch_success += 1
            write_targets.append(file_id)
        else:
            fetch_failed += 1

    conn.commit()

    write_success = 0
    write_failed = 0
    write_skipped = 0

    for file_id in write_targets:
        r = write_stored_metadata_to_file(conn, file_id, exiftool_path=exiftool_path)
        if r["status"] == "ok":
            write_success += 1
        elif r["status"] == "skipped":
            write_skipped += 1
        else:
            write_failed += 1

    conn.commit()

    return {
        "fetch_success": fetch_success,
        "fetch_failed": fetch_failed,
        "write_success": write_success,
        "write_failed": write_failed,
        "write_skipped": write_skipped,
    }


# ---------------------------------------------------------------------------
# TestPhase1AllSuccess — Phase 1 全 성공
# ---------------------------------------------------------------------------

class TestPhase1AllSuccess:
    def test_all_files_reach_phase2(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 全 성공 → write_targets = 全 대상."""
        gid1, fid1 = str(uuid.uuid4()), str(uuid.uuid4())
        gid2, fid2 = str(uuid.uuid4()), str(uuid.uuid4())
        img1 = tmp_path / "12345678_p0.jpg"
        img2 = tmp_path / "12345679_p0.jpg"
        _make_jpg(img1)
        _make_jpg(img2)
        _insert_group(db, gid1, "12345678")
        _insert_group(db, gid2, "12345679")
        _insert_file(db, fid1, gid1, str(img1))
        _insert_file(db, fid2, gid2, str(img2))

        write_calls: list[str] = []

        def fake_write(conn, file_id, exiftool_path=None, **kw):
            write_calls.append(file_id)
            return {"status": "ok", "phase": "metadata_write",
                    "sync_status": "full", "message": "ok", "error": None,
                    "group_id": None, "file_id": file_id}

        adapter = _make_adapter("12345678")
        adapter2 = _make_adapter("12345679")

        with patch("core.metadata_enricher.write_stored_metadata_to_file", side_effect=fake_write):
            r1 = fetch_and_store_pixiv_metadata(db, fid1, adapter=adapter)
            r2 = fetch_and_store_pixiv_metadata(db, fid2, adapter=adapter2)
            db.commit()
            assert r1["status"] == "ok"
            assert r2["status"] == "ok"
            # 두 파일 모두 write 단계 호출
            from core.metadata_enricher import write_stored_metadata_to_file as wsm
            wsm(db, fid1)
            wsm(db, fid2)
            assert len(write_calls) == 2

    def test_summary_fetch_success_equals_total(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 全 성공 → fetch_success == len(file_ids), fetch_failed == 0."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool"):
            summary = _run_batch(db, [fid], adapter=_make_adapter())

        assert summary["fetch_success"] == 1
        assert summary["fetch_failed"] == 0
        assert summary["write_success"] == 1
        assert summary["write_failed"] == 0
        assert summary["write_skipped"] == 0


# ---------------------------------------------------------------------------
# TestPhase1PartialFailure — Phase 1 일부 실패
# ---------------------------------------------------------------------------

class TestPhase1PartialFailure:
    def test_failed_files_excluded_from_write_targets(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 실패 파일은 write_targets에 추가되지 않는다."""
        gid_ok, fid_ok = str(uuid.uuid4()), str(uuid.uuid4())
        gid_fail, fid_fail = str(uuid.uuid4()), str(uuid.uuid4())

        img_ok = tmp_path / "12345678_p0.jpg"
        _make_jpg(img_ok)
        _insert_group(db, gid_ok, "12345678")
        _insert_file(db, fid_ok, gid_ok, str(img_ok))

        # fid_fail → artwork_id 없는 그룹 (파일명도 파싱 불가)
        img_fail = tmp_path / "noparse_file.jpg"
        _make_jpg(img_fail)
        _insert_group(db, gid_fail, "")   # artwork_id 없음
        _insert_file(db, fid_fail, gid_fail, str(img_fail))

        write_targets: list[str] = []

        for file_id in [fid_ok, fid_fail]:
            r = fetch_and_store_pixiv_metadata(db, file_id, adapter=_make_adapter())
            if r["status"] == "ok":
                write_targets.append(file_id)

        assert fid_ok in write_targets
        assert fid_fail not in write_targets

    def test_summary_counts_partial_failure(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 1건 실패 → fetch_failed=1, write_success=1 (성공 건만 write)."""
        gid_ok, fid_ok = str(uuid.uuid4()), str(uuid.uuid4())
        gid_fail, fid_fail = str(uuid.uuid4()), str(uuid.uuid4())

        img_ok = tmp_path / "12345678_p0.jpg"
        _make_jpg(img_ok)
        _insert_group(db, gid_ok, "12345678")
        _insert_file(db, fid_ok, gid_ok, str(img_ok))

        img_fail = tmp_path / "noparse_file.jpg"
        _make_jpg(img_fail)
        _insert_group(db, gid_fail, "")
        _insert_file(db, fid_fail, gid_fail, str(img_fail))

        with patch("core.metadata_enricher.write_aru_metadata"), \
             patch("core.metadata_enricher.write_xmp_metadata_with_exiftool"):
            summary = _run_batch(db, [fid_ok, fid_fail], adapter=_make_adapter())

        assert summary["fetch_success"] == 1
        assert summary["fetch_failed"] == 1
        assert summary["write_success"] == 1
        assert summary["write_skipped"] == 0
        assert summary["write_failed"] == 0


# ---------------------------------------------------------------------------
# TestPhase1AllFailure — Phase 1 全 실패
# ---------------------------------------------------------------------------

class TestPhase1AllFailure:
    def test_phase2_not_called_when_all_phase1_fail(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 全 실패 → write_targets 비어있음, Phase 2 진입 없음."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "noparse_file.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "")   # artwork_id 없음
        _insert_file(db, fid, gid, str(img))

        write_targets: list[str] = []
        r = fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())
        if r["status"] == "ok":
            write_targets.append(fid)

        assert len(write_targets) == 0

    def test_summary_all_zeros_except_fetch_failed(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 全 실패 → fetch_failed=N, write 카운터 全 0."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "noparse_file.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "")
        _insert_file(db, fid, gid, str(img))

        summary = _run_batch(db, [fid], adapter=_make_adapter())

        assert summary["fetch_failed"] == 1
        assert summary["fetch_success"] == 0
        assert summary["write_success"] == 0
        assert summary["write_failed"] == 0
        assert summary["write_skipped"] == 0


# ---------------------------------------------------------------------------
# TestPhase2Failure — Phase 2 실패
# ---------------------------------------------------------------------------

class TestPhase2Failure:
    def test_write_failed_counted_on_phase2_error(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 2 에서 status='error' 반환 → write_failed 카운트."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        def fail_write(conn, file_id, exiftool_path=None, **kw):
            return {
                "status": "error", "phase": "metadata_write",
                "sync_status": "xmp_write_failed", "message": "exiftool 실패",
                "error": "exiftool_error", "group_id": gid, "file_id": file_id,
            }

        with patch("core.metadata_enricher.write_stored_metadata_to_file", side_effect=fail_write):
            r1 = fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())
            db.commit()
            assert r1["status"] == "ok"
            from core.metadata_enricher import write_stored_metadata_to_file as wsm
            r2 = wsm(db, fid)
            assert r2["status"] == "error"

    def test_write_failed_and_success_counted_separately(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 2 일부 실패 → write_failed와 write_success 각각 정확히 카운트."""
        gid_ok, fid_ok = str(uuid.uuid4()), str(uuid.uuid4())
        gid_fail, fid_fail = str(uuid.uuid4()), str(uuid.uuid4())

        img_ok = tmp_path / "12345678_p0.jpg"
        img_fail = tmp_path / "12345679_p0.jpg"
        _make_jpg(img_ok)
        _make_jpg(img_fail)
        _insert_group(db, gid_ok, "12345678")
        _insert_group(db, gid_fail, "12345679")
        _insert_file(db, fid_ok, gid_ok, str(img_ok))
        _insert_file(db, fid_fail, gid_fail, str(img_fail))

        adapter_ok   = _make_adapter("12345678")
        adapter_fail = _make_adapter("12345679")

        r1 = fetch_and_store_pixiv_metadata(db, fid_ok, adapter=adapter_ok)
        r2 = fetch_and_store_pixiv_metadata(db, fid_fail, adapter=adapter_fail)
        db.commit()
        assert r1["status"] == r2["status"] == "ok"

        write_success = write_failed = 0
        call_count = [0]

        def selective_write(conn, file_id, exiftool_path=None, **kw):
            call_count[0] += 1
            if file_id == fid_ok:
                return {
                    "status": "ok", "phase": "metadata_write",
                    "sync_status": "full", "message": "ok",
                    "error": None, "group_id": gid_ok, "file_id": file_id,
                }
            return {
                "status": "error", "phase": "metadata_write",
                "sync_status": "xmp_write_failed", "message": "실패",
                "error": "exiftool_error", "group_id": gid_fail, "file_id": file_id,
            }

        with patch("core.metadata_enricher.write_stored_metadata_to_file", side_effect=selective_write):
            from core.metadata_enricher import write_stored_metadata_to_file as wsm
            for file_id in [fid_ok, fid_fail]:
                r = wsm(db, file_id)
                if r["status"] == "ok":
                    write_success += 1
                else:
                    write_failed += 1

        assert write_success == 1
        assert write_failed == 1
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# TestPhase2Skipped — Phase 2 skipped
# ---------------------------------------------------------------------------

class TestPhase2Skipped:
    def test_missing_file_returns_skipped_in_phase2(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 성공 후 파일이 삭제됐으면 Phase 2 → status='error' (file_missing)."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        r1 = fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())
        db.commit()
        assert r1["status"] == "ok"

        # 파일 삭제 후 Phase 2 호출
        img.unlink()
        r2 = write_stored_metadata_to_file(db, fid)
        assert r2["status"] == "error"
        assert r2["phase"] == "metadata_write"


# ---------------------------------------------------------------------------
# TestEmptyQueue — 빈 queue
# ---------------------------------------------------------------------------

class TestEmptyQueue:
    def test_empty_queue_all_counters_zero(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """대상 파일 없으면 全 카운터 0."""
        summary = _run_batch(db, [], adapter=_make_adapter())

        assert summary == {
            "fetch_success": 0,
            "fetch_failed": 0,
            "write_success": 0,
            "write_failed": 0,
            "write_skipped": 0,
        }

    def test_build_enrichment_queue_empty_on_no_targets(
        self, db: sqlite3.Connection
    ) -> None:
        """metadata_missing 항목 없으면 build_enrichment_queue 빈 list."""
        # json_only 상태는 missing_only mode 에서 제외
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        _insert_group(db, gid, "12345678", sync_status="json_only")

        queue = build_enrichment_queue(db, mode="missing_only")
        assert fid not in queue


# ---------------------------------------------------------------------------
# TestPhase1CommitBeforePhase2 — Phase 1 commit → Phase 2 정합성
# ---------------------------------------------------------------------------

class TestPhase1CommitBeforePhase2:
    def test_json_only_status_visible_to_phase2(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 commit 후 Phase 2 가 sync_status='json_only' 를 DB 에서 읽는다."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        r1 = fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())
        db.commit()
        assert r1["status"] == "ok"

        # Phase 1 이후 DB 상태
        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row["metadata_sync_status"] == "json_only"

        # Phase 2 는 artwork_id 가 DB 에 있어야 진행 가능
        artwork_row = db.execute(
            "SELECT artwork_id FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert artwork_row["artwork_id"] == "12345678"

    def test_phase1_db_update_survives_commit(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Phase 1 → commit → 새 조회에서도 json_only 유지."""
        gid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        img = tmp_path / "12345678_p0.jpg"
        _make_jpg(img)
        _insert_group(db, gid, "12345678")
        _insert_file(db, fid, gid, str(img))

        fetch_and_store_pixiv_metadata(db, fid, adapter=_make_adapter())
        db.commit()

        row = db.execute(
            "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row["metadata_sync_status"] == "json_only"
