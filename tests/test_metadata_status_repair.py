"""tests/test_metadata_status_repair.py

``core.metadata_status_repair`` 의 후보 선정과 dry-run/execute 동작 회귀 테스트.

핵심 invariant:
1. metadata_sync_status='metadata_missing' AND original 파일 metadata_embedded=1
   인 group 만 후보가 된다.
2. dry_run=True 면 DB 가 절대 변경되지 않는다.
3. dry_run=False 면 후보 group 만 'json_only' 로 바뀐다.
4. 정상 상태 (full / json_only / xmp_write_failed / pending / 기타 5종) 는
   어떤 경우에도 건드리지 않는다.
5. metadata_missing 이지만 metadata_embedded=0 (실제로 메타 없음) 는 후보 X.
6. classified_copy 보유 여부는 표시용 메타데이터일 뿐 후보 조건이 아니다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database

    conn = initialize_database(str(tmp_path / "repair.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: Optional[str] = None,
    source_site: str = "pixiv",
    artwork_id: Optional[str] = None,
    artwork_title: str = "테스트 작품",
    sync_status: str = "metadata_missing",
    tags: Optional[list[str]] = None,
    series: Optional[list[str]] = None,
    character: Optional[list[str]] = None,
) -> str:
    gid = group_id or str(uuid.uuid4())
    aid = artwork_id or gid[:12]
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, "
        " downloaded_at, indexed_at, metadata_sync_status, "
        " tags_json, series_tags_json, character_tags_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            gid, source_site, aid, artwork_title, now, now, sync_status,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
        ),
    )
    conn.commit()
    return gid


def _insert_file(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    file_role: str = "original",
    file_path: Optional[str] = None,
    metadata_embedded: int = 1,
    file_status: str = "present",
) -> str:
    fid = str(uuid.uuid4())
    fp = file_path or f"C:/fake/{fid}.jpg"
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, "
        " file_format, metadata_embedded, file_status, created_at) "
        "VALUES (?, ?, 0, ?, ?, 'jpg', ?, ?, ?)",
        (fid, group_id, file_role, fp, metadata_embedded, file_status, _now()),
    )
    conn.commit()
    return fid


def _status(conn: sqlite3.Connection, group_id: str) -> str:
    row = conn.execute(
        "SELECT metadata_sync_status FROM artwork_groups WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    return row["metadata_sync_status"] if row else ""


# ---------------------------------------------------------------------------
# 1. find_metadata_status_repair_candidates — 후보 선정 조건
# ---------------------------------------------------------------------------

class TestFindCandidates:
    """후보 선정 조건이 정확히 (metadata_missing AND embedded=1) 인지."""

    def test_eligible_group_is_listed(self, db):
        """metadata_missing + original metadata_embedded=1 → 후보."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        gid = _insert_group(db, sync_status="metadata_missing", series=["Blue Archive"])
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        cands = find_metadata_status_repair_candidates(db)
        assert len(cands) == 1
        assert cands[0]["group_id"] == gid
        assert cands[0]["metadata_sync_status"] == "metadata_missing"
        assert cands[0]["has_series"] is True

    def test_metadata_embedded_zero_is_not_candidate(self, db):
        """metadata_missing 이지만 embedded=0 → 후보 아님 (실제 메타 없음)."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        gid = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=0)

        cands = find_metadata_status_repair_candidates(db)
        assert cands == []

    def test_classifiable_status_never_candidate(self, db):
        """full / json_only / xmp_write_failed 는 절대 후보가 되지 않는다."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        for status in ("full", "json_only", "xmp_write_failed"):
            gid = _insert_group(db, sync_status=status)
            _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        cands = find_metadata_status_repair_candidates(db)
        assert cands == [], f"분류 가능 상태가 후보로 잡힘: {cands}"

    def test_other_non_missing_statuses_never_candidate(self, db):
        """pending / source_unavailable / metadata_write_failed 등도 후보 X."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        for status in (
            "pending", "source_unavailable", "metadata_write_failed",
            "out_of_sync", "needs_reindex", "convert_failed",
            "file_write_failed", "db_update_failed",
        ):
            gid = _insert_group(db, sync_status=status)
            _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        cands = find_metadata_status_repair_candidates(db)
        assert cands == [], f"비-missing 상태가 후보로 잡힘: {cands}"

    def test_group_without_original_file_is_not_candidate(self, db):
        """original 파일이 아예 없는 group 은 EXISTS 절에서 탈락."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        gid = _insert_group(db, sync_status="metadata_missing")
        # 파일 없음
        cands = find_metadata_status_repair_candidates(db)
        assert cands == []

    def test_only_managed_or_classified_copy_does_not_qualify(self, db):
        """managed/classified_copy 만 metadata_embedded=1 인 경우 — original 이
        조건을 충족해야 한다."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        gid = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid, file_role="original",        metadata_embedded=0)
        _insert_file(db, group_id=gid, file_role="managed",         metadata_embedded=1)
        _insert_file(db, group_id=gid, file_role="classified_copy", metadata_embedded=1)

        cands = find_metadata_status_repair_candidates(db)
        assert cands == []

    def test_candidate_metadata_flags_reflect_data(self, db):
        """has_tags / has_series / has_character / has_classified_copy 정확성."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        gid = _insert_group(
            db, sync_status="metadata_missing",
            tags=["일반태그"], series=["Trickcal Re:VIVE"], character=["티그"],
        )
        _insert_file(db, group_id=gid, file_role="original",        metadata_embedded=1)
        _insert_file(db, group_id=gid, file_role="classified_copy", metadata_embedded=1)

        cands = find_metadata_status_repair_candidates(db)
        assert len(cands) == 1
        c = cands[0]
        assert c["has_tags"]      is True
        assert c["has_series"]    is True
        assert c["has_character"] is True
        assert c["has_classified_copy"] is True

    def test_empty_json_arrays_are_treated_as_unpopulated(self, db):
        """tags_json='[]' 는 has_tags=False 로 본다."""
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        gid = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        c = find_metadata_status_repair_candidates(db)[0]
        assert c["has_tags"]      is False
        assert c["has_series"]    is False
        assert c["has_character"] is False
        assert c["has_classified_copy"] is False

    def test_limit_bounds_result_size(self, db):
        from core.metadata_status_repair import find_metadata_status_repair_candidates

        for _ in range(5):
            gid = _insert_group(db, sync_status="metadata_missing")
            _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        all_cands = find_metadata_status_repair_candidates(db)
        assert len(all_cands) == 5

        limited = find_metadata_status_repair_candidates(db, limit=2)
        assert len(limited) == 2


# ---------------------------------------------------------------------------
# 2. repair_metadata_sync_status — dry_run vs execute
# ---------------------------------------------------------------------------

class TestRepairExecution:
    """dry_run=True 는 read-only, dry_run=False 는 정확한 row 만 갱신."""

    def test_dry_run_does_not_modify_db(self, db):
        from core.metadata_status_repair import repair_metadata_sync_status

        gid = _insert_group(db, sync_status="metadata_missing", series=["Blue Archive"])
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        result = repair_metadata_sync_status(db, dry_run=True)
        assert result["dry_run"] is True
        assert result["candidate_count"] == 1
        assert result["updated_count"] == 0
        assert _status(db, gid) == "metadata_missing", "dry_run 인데 status 변경됨"

    def test_execute_updates_only_eligible_rows(self, db):
        from core.metadata_status_repair import repair_metadata_sync_status

        # 후보 (eligible)
        gid_eligible = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid_eligible, file_role="original", metadata_embedded=1)

        # 비후보 1: missing + embedded=0
        gid_missing_zero = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid_missing_zero, file_role="original", metadata_embedded=0)

        # 비후보 2: full + embedded=1
        gid_full = _insert_group(db, sync_status="full")
        _insert_file(db, group_id=gid_full, file_role="original", metadata_embedded=1)

        # 비후보 3: pending
        gid_pending = _insert_group(db, sync_status="pending")
        _insert_file(db, group_id=gid_pending, file_role="original", metadata_embedded=1)

        result = repair_metadata_sync_status(db, dry_run=False)
        assert result["dry_run"] is False
        assert result["candidate_count"] == 1
        assert result["updated_count"]   == 1

        assert _status(db, gid_eligible)     == "json_only"
        assert _status(db, gid_missing_zero) == "metadata_missing"
        assert _status(db, gid_full)         == "full"
        assert _status(db, gid_pending)      == "pending"

    def test_execute_with_no_candidates_is_noop(self, db):
        from core.metadata_status_repair import repair_metadata_sync_status

        gid = _insert_group(db, sync_status="full")
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        result = repair_metadata_sync_status(db, dry_run=False)
        assert result["candidate_count"] == 0
        assert result["updated_count"]   == 0
        assert _status(db, gid) == "full"

    def test_execute_repairs_to_json_only_not_full(self, db):
        """복구 결과는 보수적으로 json_only 여야 한다 (full 금지).

        XMP write 성공 여부를 확인하지 않으므로 full 은 과한 추정이다.
        """
        from core.metadata_status_repair import repair_metadata_sync_status

        gid = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        repair_metadata_sync_status(db, dry_run=False)
        assert _status(db, gid) == "json_only"

    def test_execute_updates_updated_at(self, db):
        from core.metadata_status_repair import repair_metadata_sync_status

        gid = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)
        # 초기엔 updated_at 비어 있는 게 보통.
        before = db.execute(
            "SELECT updated_at FROM artwork_groups WHERE group_id=?", (gid,)
        ).fetchone()["updated_at"]

        repair_metadata_sync_status(db, dry_run=False)

        after = db.execute(
            "SELECT updated_at FROM artwork_groups WHERE group_id=?", (gid,)
        ).fetchone()["updated_at"]
        assert after, "updated_at 가 갱신되지 않음"
        assert after != before, "updated_at 가 같음 (변경 안 됨)"

    def test_execute_does_not_touch_classifiable_statuses(self, db):
        """이번 PR 의 가장 중요한 invariant — 정상 상태는 절대 건드리지 않는다."""
        from core.metadata_status_repair import repair_metadata_sync_status

        protected = []
        for status in ("full", "json_only", "xmp_write_failed"):
            gid = _insert_group(db, sync_status=status)
            _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)
            protected.append((gid, status))

        result = repair_metadata_sync_status(db, dry_run=False)
        assert result["candidate_count"] == 0
        assert result["updated_count"]   == 0
        for gid, original in protected:
            assert _status(db, gid) == original

    def test_execute_idempotent(self, db):
        """두 번 실행해도 두 번째 실행에선 후보가 없어야 한다."""
        from core.metadata_status_repair import repair_metadata_sync_status

        gid = _insert_group(db, sync_status="metadata_missing")
        _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        first = repair_metadata_sync_status(db, dry_run=False)
        assert first["updated_count"] == 1

        second = repair_metadata_sync_status(db, dry_run=False)
        assert second["candidate_count"] == 0
        assert second["updated_count"]   == 0

    def test_execute_respects_limit(self, db):
        from core.metadata_status_repair import repair_metadata_sync_status

        for _ in range(4):
            gid = _insert_group(db, sync_status="metadata_missing")
            _insert_file(db, group_id=gid, file_role="original", metadata_embedded=1)

        result = repair_metadata_sync_status(db, dry_run=False, limit=2)
        assert result["candidate_count"] == 2
        assert result["updated_count"]   == 2

        remaining = db.execute(
            "SELECT COUNT(*) c FROM artwork_groups WHERE metadata_sync_status='metadata_missing'"
        ).fetchone()["c"]
        assert remaining == 2


# ---------------------------------------------------------------------------
# 3. CLASSIFIABLE_STATUSES 연동 — repair 결과는 분류 가능 상태로 진입
# ---------------------------------------------------------------------------

class TestRepairOutputIsClassifiable:
    def test_repaired_status_is_in_classifiable_statuses(self):
        """REPAIRED_STATUS 는 반드시 CLASSIFIABLE_STATUSES 의 한 원소여야 한다.

        한쪽이 바뀌면 repair 가 무의미해진다.
        """
        from core.classifier import CLASSIFIABLE_STATUSES
        from core.metadata_status_repair import REPAIRED_STATUS

        assert REPAIRED_STATUS in CLASSIFIABLE_STATUSES, (
            f"repair output {REPAIRED_STATUS!r} 가 CLASSIFIABLE_STATUSES 에 없음"
        )

    def test_target_status_is_not_classifiable(self):
        from core.classifier import CLASSIFIABLE_STATUSES
        from core.metadata_status_repair import REPAIR_TARGET_STATUS

        assert REPAIR_TARGET_STATUS not in CLASSIFIABLE_STATUSES, (
            "repair target 이 이미 분류 가능 상태로 표시되어 있음 — repair 의미 없음"
        )
