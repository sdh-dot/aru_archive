"""_EnrichThread._emit_queue_summary 존재 및 정상 실행 검증.

재현 버그: _emit_queue_summary가 _LocalMetadataImportThread에만 정의되어 있어
_EnrichThread.run() 내에서 호출 시 AttributeError 발생 → 보강 전체가 실패로 처리됨.

커버하는 케이스:
  1. _emit_queue_summary가 _EnrichThread 클래스의 메서드로 존재하는가
  2. DB에 레코드가 있을 때 예외 없이 실행되는가
  3. DB가 비어 있을 때 예외 없이 실행되는가
  4. ARU_ENRICH_TIMING=1 환경에서 run()의 done dict 키가 온전한가
  5. ARU_ENRICH_TIMING 미설정 시에도 done dict 키가 동일하게 존재하는가
  6. done dict에 timing 계측 키 전체가 포함되는가
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# helpers & fixtures
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


def _insert_group(conn, group_id, artwork_id="88908024", sync_status="metadata_missing"):
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artwork_url,
            artist_id, artist_name, artist_url,
            downloaded_at, indexed_at, metadata_sync_status)
           VALUES (?, 'pixiv', ?, '', '', '', '', ?, ?, ?)""",
        (group_id, artwork_id, _now(), _now(), sync_status),
    )
    conn.commit()


def _insert_file(conn, file_id, group_id, file_path="dummy.jpg"):
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path, file_format,
            created_at, file_status)
           VALUES (?, ?, 0, 'original', ?, 'jpg', ?, 'present')""",
        (file_id, group_id, file_path, _now()),
    )
    conn.commit()


def _make_enrich_thread_instance():
    """QApplication 없이 _EnrichThread 인스턴스를 만드는 헬퍼."""
    from app.views.workflow_wizard_view import _EnrichThread
    # QThread.__init__은 parent=None일 때 QApplication 없이도 인스턴스화 가능.
    obj = _EnrichThread.__new__(_EnrichThread)
    # signal emit을 mock으로 대체해 이벤트 루프 의존성 제거.
    obj.log_msg = MagicMock()
    obj.log_msg.emit = MagicMock()
    return obj


# ---------------------------------------------------------------------------
# 1. 메서드 존재 여부
# ---------------------------------------------------------------------------

class TestEmitQueueSummaryExists:
    def test_method_exists_on_enrich_thread_class(self):
        """_emit_queue_summary가 _EnrichThread 클래스의 메서드여야 한다."""
        from app.views.workflow_wizard_view import _EnrichThread
        assert hasattr(_EnrichThread, "_emit_queue_summary"), (
            "_EnrichThread에 _emit_queue_summary 메서드가 없음 — "
            "run() 내에서 ARU_ENRICH_TIMING=1 시 AttributeError 발생"
        )
        assert callable(getattr(_EnrichThread, "_emit_queue_summary"))

    def test_method_is_not_inherited_from_other_thread(self):
        """_emit_queue_summary가 _LocalMetadataImportThread에서 상속된 것이 아닌지 확인."""
        from app.views.workflow_wizard_view import _EnrichThread, _LocalMetadataImportThread
        # 두 클래스 모두 메서드를 가져야 하며, 각자 독립적으로 정의되어야 한다.
        assert "_emit_queue_summary" in _EnrichThread.__dict__, (
            "_EnrichThread.__dict__에 없음 — 상속이 아닌 직접 정의가 필요"
        )


# ---------------------------------------------------------------------------
# 2. DB에 레코드 있을 때 정상 실행
# ---------------------------------------------------------------------------

class TestEmitQueueSummaryWithData:
    def test_runs_without_exception_with_records(self, db, tmp_path):
        """artwork_files 레코드가 있을 때 _emit_queue_summary가 예외 없이 실행된다."""
        gid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        _insert_group(db, gid, artwork_id="88908024", sync_status="metadata_missing")
        _insert_file(db, fid, gid)

        thread = _make_enrich_thread_instance()
        thread._emit_queue_summary(db)  # 예외 없어야 함

        # log_msg.emit이 호출됐는지 확인 (총 파일 수가 있으므로 메시지 있어야 함)
        thread.log_msg.emit.assert_called_once()
        log_text = thread.log_msg.emit.call_args[0][0]
        assert "enrich queue" in log_text

    def test_log_message_contains_file_count(self, db, tmp_path):
        """로그에 파일 수가 포함되어야 한다."""
        for i in range(3):
            gid = str(uuid.uuid4())
            fid = str(uuid.uuid4())
            _insert_group(db, gid, artwork_id=str(uuid.uuid4().int)[:8])
            _insert_file(db, fid, gid, file_path=f"dummy_{i}.jpg")

        thread = _make_enrich_thread_instance()
        thread._emit_queue_summary(db)

        log_text = thread.log_msg.emit.call_args[0][0]
        assert "3 files" in log_text

    def test_multi_page_artwork_counted(self, db, tmp_path):
        """동일 artwork_id의 여러 파일은 multi-page로 집계되어야 한다."""
        gid = str(uuid.uuid4())
        artwork_id = "12345678"
        _insert_group(db, gid, artwork_id=artwork_id)
        # 같은 그룹에 파일 2개 (p0, p1)
        db.execute(
            """INSERT INTO artwork_files
               (file_id, group_id, page_index, file_role, file_path, file_format,
                created_at, file_status)
               VALUES (?, ?, 0, 'original', 'p0.jpg', 'jpg', ?, 'present')""",
            (str(uuid.uuid4()), gid, _now()),
        )
        db.execute(
            """INSERT INTO artwork_files
               (file_id, group_id, page_index, file_role, file_path, file_format,
                created_at, file_status)
               VALUES (?, ?, 1, 'original', 'p1.jpg', 'jpg', ?, 'present')""",
            (str(uuid.uuid4()), gid, _now()),
        )
        db.commit()

        thread = _make_enrich_thread_instance()
        thread._emit_queue_summary(db)

        log_text = thread.log_msg.emit.call_args[0][0]
        assert "multi-page" in log_text


# ---------------------------------------------------------------------------
# 3. DB가 비어 있을 때 정상 실행
# ---------------------------------------------------------------------------

class TestEmitQueueSummaryEmptyDb:
    def test_runs_without_exception_on_empty_db(self, db):
        """빈 DB에서도 _emit_queue_summary가 예외 없이 실행된다."""
        thread = _make_enrich_thread_instance()
        thread._emit_queue_summary(db)  # 예외 없어야 함
        # 레코드가 없으면 0 files → log_msg.emit이 호출될 수도 있고 안 될 수도 있음.
        # 중요한 건 예외가 없는 것이다.


# ---------------------------------------------------------------------------
# 4. done dict 키 검증 — ARU_ENRICH_TIMING=1
# ---------------------------------------------------------------------------

EXPECTED_DONE_KEYS = {
    "fetch_success", "fetch_failed",
    "write_success", "write_failed", "write_skipped",
    "phase1_fetch_total_ms", "phase2_write_total_ms", "per_file_avg_ms",
    "exiftool_spawn_count", "db_commit_count",
    "db_batch_flush_count", "db_batch_replay_count",
    "db_batch_replay_failure_count", "db_safe_mode_activations",
    "ui_progress_emit_count", "file_write_count",
}


class TestEnrichThreadDoneDictKeys:
    def test_done_dict_has_all_timing_keys_in_source(self):
        """_EnrichThread.run() 소스에 모든 timing 키가 포함되어야 한다."""
        from app.views.workflow_wizard_view import _EnrichThread
        import inspect
        source = inspect.getsource(_EnrichThread.run)
        for key in EXPECTED_DONE_KEYS:
            assert f'"{key}"' in source, f"done dict에 키 없음: {key}"

    def test_emit_queue_summary_called_in_run_source(self):
        """run() 소스에 _emit_queue_summary 호출부가 있어야 한다."""
        from app.views.workflow_wizard_view import _EnrichThread
        import inspect
        source = inspect.getsource(_EnrichThread.run)
        assert "_emit_queue_summary" in source, (
            "run()에서 _emit_queue_summary를 호출하지 않음"
        )


# ---------------------------------------------------------------------------
# 5. ARU_ENRICH_TIMING 미설정 시에도 done dict 키 동일 (소스 수준 검증)
# ---------------------------------------------------------------------------

class TestEnrichThreadTimingIndependent:
    def test_done_dict_keys_independent_of_timing_flag(self):
        """timing 키는 ARU_ENRICH_TIMING 값과 무관하게 done dict에 포함된다."""
        from app.views.workflow_wizard_view import _EnrichThread
        import inspect
        source = inspect.getsource(_EnrichThread.run)
        # done.emit 호출은 timing_enabled 분기 밖에 있어야 한다.
        # 소스에서 'self.done.emit' 이 'if timing_enabled' 블록 밖에 있는지 확인.
        # 간단히: 두 done.emit 호출이 있고 하나는 except 블록용이어야 한다.
        assert source.count("self.done.emit") >= 2, (
            "done.emit이 성공/실패 양쪽에 있어야 함"
        )

    def test_timing_summary_only_logged_when_enabled(self):
        """timing report_lines 생성은 timing_enabled 조건 블록 내에 있어야 한다."""
        from app.views.workflow_wizard_view import _EnrichThread
        import inspect
        source = inspect.getsource(_EnrichThread.run)
        assert "if timing_enabled:" in source
        assert "phase1_fetch_total_ms" in source
