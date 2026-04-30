"""
중복 검사 scope 정책 테스트.

- 기본 scope가 inbox_managed인지 확인
- inbox_managed에서 classified_copy / sidecar 제외
- inbox_managed에서 deleted / missing 제외
- inbox_only / managed_only / classified_only / all_archive 각각 동작 확인
- 시각적 중복도 동일 scope 정책 적용
- config duplicates.default_scope 기본값 확인
- all_archive 경고 핸들러 존재 확인
"""
from __future__ import annotations

import inspect
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.duplicate_finder import (
    _DEFAULT_SCOPE,
    _SCOPE_WHERE,
    find_exact_duplicates,
    select_duplicate_candidate_files,
)
from core.visual_duplicate_finder import find_visual_duplicates


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _insert_group(conn: sqlite3.Connection) -> str:
    gid = str(uuid.uuid4())
    aid = str(uuid.uuid4())[:8]
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, source_site, artwork_id, artist_name,
            series_tags_json, character_tags_json, tags_json,
            metadata_sync_status, status, indexed_at, updated_at, downloaded_at)
           VALUES (?, 'pixiv', ?, 'Artist', '[]', '[]', '[]',
                   'full', 'inbox', ?, ?, ?)""",
        (gid, aid, _now(), _now(), _now()),
    )
    conn.commit()
    return gid


def _insert_file(
    conn: sqlite3.Connection,
    group_id: str,
    file_path: str,
    file_role: str = "original",
    file_status: str = "present",
    file_hash: str = "hash_abc",
) -> str:
    fid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, page_index, file_role, file_path,
            file_format, file_hash, file_size, metadata_embedded,
            file_status, created_at)
           VALUES (?, ?, 0, ?, ?, 'jpg', ?, 1024, 1, ?, ?)""",
        (fid, group_id, file_role, file_path, file_hash, file_status, _now()),
    )
    conn.commit()
    return fid


# ---------------------------------------------------------------------------
# 1. 기본 scope 확인
# ---------------------------------------------------------------------------

class TestDefaultScope:
    def test_module_default_scope_constant(self):
        assert _DEFAULT_SCOPE == "inbox_managed"

    def test_find_exact_duplicates_default_param(self):
        sig = inspect.signature(find_exact_duplicates)
        assert sig.parameters["scope"].default == "inbox_managed"

    def test_find_visual_duplicates_default_param(self):
        sig = inspect.signature(find_visual_duplicates)
        assert sig.parameters["scope"].default == "inbox_managed"

    def test_select_helper_default_param(self):
        sig = inspect.signature(select_duplicate_candidate_files)
        assert sig.parameters["scope"].default == "inbox_managed"

    def test_scope_where_has_inbox_managed(self):
        assert "inbox_managed" in _SCOPE_WHERE
        assert "inbox_only" in _SCOPE_WHERE
        assert "managed_only" in _SCOPE_WHERE
        assert "classified_only" in _SCOPE_WHERE
        assert "all_archive" in _SCOPE_WHERE

    def test_config_default_scope(self):
        from core.config_manager import _DEFAULTS
        dup = _DEFAULTS.get("duplicates", {})
        assert dup.get("default_scope") == "inbox_managed"
        assert dup.get("allow_all_archive_scan") is False


# ---------------------------------------------------------------------------
# 2. inbox_managed — 기본 제외 확인
# ---------------------------------------------------------------------------

class TestInboxManagedScope:
    def test_original_included(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="original")
        rows = select_duplicate_candidate_files(db, scope="inbox_managed")
        assert len(rows) == 1

    def test_managed_included(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="managed")
        rows = select_duplicate_candidate_files(db, scope="inbox_managed")
        assert len(rows) == 1

    def test_classified_copy_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "copy.jpg"), file_role="classified_copy")
        rows = select_duplicate_candidate_files(db, scope="inbox_managed")
        assert rows == []

    def test_sidecar_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "meta.xmp"), file_role="sidecar")
        rows = select_duplicate_candidate_files(db, scope="inbox_managed")
        assert rows == []

    def test_deleted_status_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "del.jpg"),
                     file_role="original", file_status="deleted")
        rows = select_duplicate_candidate_files(db, scope="inbox_managed")
        assert rows == []

    def test_missing_status_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "missing.jpg"),
                     file_role="original", file_status="missing")
        rows = select_duplicate_candidate_files(db, scope="inbox_managed")
        assert rows == []

    def test_classified_copy_not_in_duplicate_group(self, db, tmp_path):
        """classified_copy는 기본 scope에서 중복 탐지 대상이 아님."""
        g1 = _insert_group(db)
        g2 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "orig.jpg"),
                     file_role="original", file_hash="same_hash")
        _insert_file(db, g2, str(tmp_path / "copy.jpg"),
                     file_role="classified_copy", file_hash="same_hash")

        # 기본 scope → 중복 없음 (classified_copy 제외)
        result = find_exact_duplicates(db)
        assert result == []

    def test_sidecar_not_in_duplicate_group(self, db, tmp_path):
        g1 = _insert_group(db)
        g2 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "orig.jpg"),
                     file_role="original", file_hash="same_hash")
        _insert_file(db, g2, str(tmp_path / "meta.xmp"),
                     file_role="sidecar", file_hash="same_hash")

        result = find_exact_duplicates(db)
        assert result == []


# ---------------------------------------------------------------------------
# 3. inbox_only scope
# ---------------------------------------------------------------------------

class TestInboxOnlyScope:
    def test_original_included(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="original")
        rows = select_duplicate_candidate_files(db, scope="inbox_only")
        assert len(rows) == 1

    def test_managed_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="managed")
        rows = select_duplicate_candidate_files(db, scope="inbox_only")
        assert rows == []

    def test_classified_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="classified_copy")
        rows = select_duplicate_candidate_files(db, scope="inbox_only")
        assert rows == []


# ---------------------------------------------------------------------------
# 4. managed_only scope
# ---------------------------------------------------------------------------

class TestManagedOnlyScope:
    def test_managed_included(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="managed")
        rows = select_duplicate_candidate_files(db, scope="managed_only")
        assert len(rows) == 1

    def test_original_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="original")
        rows = select_duplicate_candidate_files(db, scope="managed_only")
        assert rows == []

    def test_classified_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "a.jpg"), file_role="classified_copy")
        rows = select_duplicate_candidate_files(db, scope="managed_only")
        assert rows == []


# ---------------------------------------------------------------------------
# 5. classified_only scope
# ---------------------------------------------------------------------------

class TestClassifiedOnlyScope:
    def test_classified_copy_included(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "copy.jpg"), file_role="classified_copy")
        rows = select_duplicate_candidate_files(db, scope="classified_only")
        assert len(rows) == 1

    def test_original_excluded(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "orig.jpg"), file_role="original")
        rows = select_duplicate_candidate_files(db, scope="classified_only")
        assert rows == []


# ---------------------------------------------------------------------------
# 6. all_archive scope
# ---------------------------------------------------------------------------

class TestAllArchiveScope:
    def test_all_roles_included(self, db, tmp_path):
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "orig.jpg"), file_role="original")
        _insert_file(db, gid, str(tmp_path / "copy.jpg"), file_role="classified_copy")
        _insert_file(db, gid, str(tmp_path / "mgd.jpg"),  file_role="managed")
        rows = select_duplicate_candidate_files(db, scope="all_archive")
        assert len(rows) == 3

    def test_classified_in_duplicate_group(self, db, tmp_path):
        """all_archive에서는 classified_copy가 중복 탐지 대상에 포함된다."""
        g1 = _insert_group(db)
        g2 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "orig.jpg"),
                     file_role="original", file_hash="same_hash")
        _insert_file(db, g2, str(tmp_path / "copy.jpg"),
                     file_role="classified_copy", file_hash="same_hash")

        result = find_exact_duplicates(db, scope="all_archive")
        assert len(result) == 1
        assert len(result[0]["files"]) == 2

    def test_deleted_still_excluded(self, db, tmp_path):
        """all_archive도 file_status='present'만 포함."""
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "del.jpg"),
                     file_role="original", file_status="deleted")
        rows = select_duplicate_candidate_files(db, scope="all_archive")
        assert rows == []


# ---------------------------------------------------------------------------
# 7. group_ids 필터링
# ---------------------------------------------------------------------------

class TestGroupIdsFilter:
    def test_selected_scope_without_group_ids_returns_empty(self, db, tmp_path):
        g1 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "a.jpg"), file_role="original")

        rows = select_duplicate_candidate_files(db, scope="selected")
        assert rows == []

    def test_selected_scope_with_group_ids(self, db, tmp_path):
        g1 = _insert_group(db)
        g2 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "a.jpg"), file_role="original")
        _insert_file(db, g2, str(tmp_path / "b.jpg"), file_role="original")

        rows = select_duplicate_candidate_files(db, scope="selected", group_ids=[g1])
        assert len(rows) == 1
        assert rows[0]["group_id"] == g1

    def test_inbox_managed_with_group_ids(self, db, tmp_path):
        g1 = _insert_group(db)
        g2 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "a.jpg"), file_role="original",
                     file_hash="h1")
        _insert_file(db, g2, str(tmp_path / "b.jpg"), file_role="original",
                     file_hash="h1")

        # group_ids 필터로 g1만 대상 → 중복 없음 (파일 1개)
        result = find_exact_duplicates(db, scope="inbox_managed", group_ids=[g1])
        assert result == []

    def test_current_view_without_group_ids_returns_empty(self, db, tmp_path):
        g1 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "a.jpg"), file_role="original")

        rows = select_duplicate_candidate_files(db, scope="current_view")
        assert rows == []

    def test_current_view_with_group_ids_filters_to_visible_groups(self, db, tmp_path):
        g1 = _insert_group(db)
        g2 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "a.jpg"), file_role="original",
                     file_hash="same")
        _insert_file(db, g2, str(tmp_path / "b.jpg"), file_role="original",
                     file_hash="same")

        result = find_exact_duplicates(db, scope="current_view", group_ids=[g1])
        assert result == []

    def test_selected_scope_excludes_classified_copy(self, db, tmp_path):
        g1 = _insert_group(db)
        _insert_file(db, g1, str(tmp_path / "copy.jpg"), file_role="classified_copy")

        rows = select_duplicate_candidate_files(db, scope="selected", group_ids=[g1])
        assert rows == []


# ---------------------------------------------------------------------------
# 8. 시각적 중복도 동일 scope 정책 적용
# ---------------------------------------------------------------------------

class TestVisualDuplicateScope:
    def test_classified_excluded_by_default(self, db, tmp_path):
        """시각적 중복 기본 scope도 classified_copy를 제외한다."""
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "copy.jpg"), file_role="classified_copy")

        # Pillow 없어도 rows가 0이면 groups도 0
        groups = find_visual_duplicates(db, scope="inbox_managed")
        assert groups == []

    def test_classified_included_in_all_archive(self, db, tmp_path):
        """all_archive scope에서는 classified_copy가 대상에 포함된다 (Pillow 없이 확인)."""
        gid = _insert_group(db)
        _insert_file(db, gid, str(tmp_path / "copy.jpg"), file_role="classified_copy")

        # 파일이 실제로 존재하지 않으면 pHash 계산 실패 → groups=[]
        # 하지만 select 자체가 rows를 반환하는지 확인
        from core.duplicate_finder import select_duplicate_candidate_files
        rows = select_duplicate_candidate_files(db, scope="all_archive")
        assert len(rows) == 1
        assert rows[0]["file_role"] == "classified_copy"


# ---------------------------------------------------------------------------
# 9. UI / config 확인
# ---------------------------------------------------------------------------

class TestConfigAndHandlers:
    def test_config_allow_all_archive_default_false(self):
        from core.config_manager import _default_config
        cfg = _default_config()
        assert cfg["duplicates"]["allow_all_archive_scan"] is False

    def test_config_default_scope_inbox_managed(self):
        from core.config_manager import _default_config
        cfg = _default_config()
        assert cfg["duplicates"]["default_scope"] == "inbox_managed"

    def test_main_window_has_get_dup_scope_method(self):
        """MainWindow에 _get_dup_scope 핸들러가 존재하는지 확인."""
        from app.main_window import MainWindow
        assert hasattr(MainWindow, "_get_dup_scope")

    def test_main_window_has_duplicate_scope_request_builder(self):
        from app.main_window import MainWindow
        assert hasattr(MainWindow, "_build_duplicate_scope_request")

    def test_main_window_duplicate_checks_pass_group_ids(self):
        import inspect
        from app.main_window import MainWindow

        exact_src = inspect.getsource(MainWindow._on_exact_duplicate_check)
        visual_src = inspect.getsource(MainWindow._on_visual_duplicate_check)
        assert "group_ids=group_ids" in exact_src
        assert "group_ids=group_ids" in visual_src

    def test_workflow_wizard_exact_dup_emits_signal_only(self):
        """PR #20 이후 Workflow Step 3는 scope를 직접 결정하지 않고
        MainWindow handler에 signal delegation한다.
        scope/inbox_managed 결정은 MainWindow 책임이다.
        """
        import inspect
        from app.views.workflow_wizard_view import _Step3Meta
        src = inspect.getsource(_Step3Meta._on_exact_dup)
        # signal delegation이 있어야 한다
        assert "exact_duplicate_scan_requested" in src
        # Step 3가 직접 finder를 호출하거나 scope를 결정하면 안 된다
        assert "find_exact_duplicates" not in src
        assert "inbox_managed" not in src

    def test_workflow_wizard_visual_dup_emits_signal_only(self):
        """PR #20 이후 Workflow Step 3는 scope를 직접 결정하지 않고
        MainWindow handler에 signal delegation한다.
        scope/inbox_managed 결정은 MainWindow 책임이다.
        """
        import inspect
        from app.views.workflow_wizard_view import _Step3Meta
        src = inspect.getsource(_Step3Meta._on_visual_dup)
        # signal delegation이 있어야 한다
        assert "visual_duplicate_scan_requested" in src
        # Step 3가 직접 finder를 호출하거나 dialog/scope를 결정하면 안 된다
        assert "find_visual_duplicates" not in src
        assert "VisualDuplicateReviewDialog" not in src
        assert "DeletePreviewDialog" not in src
        assert "inbox_managed" not in src
