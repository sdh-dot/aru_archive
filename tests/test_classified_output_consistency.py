"""tests/test_classified_output_consistency.py

read-only 진단 도구 회귀 테스트.

검증 contract:
- 함수는 SELECT 만 수행. 어떤 path 조합에서도 DB 가 변경되지 않는다.
- expected destination 계산은 build_classify_preview 결과를 그대로 재활용.
- path 비교는 normalization (resolve + casefold) 기반.
- legacy_extra / missing_expected / consistent / legacy_and_missing /
  unverifiable 5종 status 가 올바르게 판정된다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "consistency.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    artwork_id: str | None = None,
    title: str = "샘플",
    series: list[str] | None = None,
    character: list[str] | None = None,
    sync_status: str = "json_only",
) -> None:
    # group_id 기반 unique artwork_id 로 폴백 — 같은 conn 안에서 여러 group
    # 을 INSERT 해도 UNIQUE(artwork_id, source_site) 충돌이 생기지 않게 한다.
    if artwork_id is None:
        artwork_id = group_id[:12]
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, "
        " downloaded_at, indexed_at, metadata_sync_status, "
        " tags_json, series_tags_json, character_tags_json, artist_name) "
        "VALUES (?, 'pixiv', ?, ?, ?, ?, ?, '[]', ?, ?, '작가')",
        (
            group_id, artwork_id, title, now, now, sync_status,
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    file_path: str,
    file_role: str = "original",
    file_status: str = "present",
    metadata_embedded: int = 1,
) -> str:
    fid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, "
        " file_format, file_size, metadata_embedded, file_status, created_at) "
        "VALUES (?, ?, 0, ?, ?, 'jpg', 1024, ?, ?, ?)",
        (fid, group_id, file_role, file_path, metadata_embedded, file_status, _now()),
    )
    conn.commit()
    return fid


def _make_real_jpg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0")  # minimal JPEG header bytes


def _config(tmp_path: Path) -> dict:
    classified = tmp_path / "Classified"
    classified.mkdir(exist_ok=True)
    return {
        "classified_dir": str(classified),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": True,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
            "folder_locale":                   "canonical",
        },
    }


# ---------------------------------------------------------------------------
# A. consistent
# ---------------------------------------------------------------------------

class TestConsistent:
    def test_expected_equals_existing(self, db, tmp_path):
        from core.classifier import build_classify_preview
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["伊落マリー"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))

        cfg = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        # expected dest 와 동일한 파일을 classified_copy 로 등록
        for d in preview["destinations"]:
            _insert_file(
                db, group_id=gid, file_path=d["dest_path"],
                file_role="classified_copy", metadata_embedded=1,
            )

        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified", include_consistent=True,
        )
        assert report.summary.groups_scanned >= 1
        assert report.summary.groups_consistent >= 1
        consistent_items = [it for it in report.items if it.status == "consistent"]
        assert any(it.group_id == gid for it in consistent_items)


# ---------------------------------------------------------------------------
# B. legacy_extra
# ---------------------------------------------------------------------------

class TestLegacyExtra:
    def test_existing_has_extra_path_not_in_expected(self, db, tmp_path):
        from core.classifier import build_classify_preview
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["伊落マリー"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))

        cfg = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        # expected 그대로 등록
        for d in preview["destinations"]:
            _insert_file(
                db, group_id=gid, file_path=d["dest_path"],
                file_role="classified_copy",
            )
        # 추가 legacy path (현재 규칙으로는 안 만들어지는 폴더)
        legacy_path = str(tmp_path / "Classified" / "BySeries" / "옛이름" / "마리" / "p0.jpg")
        _insert_file(
            db, group_id=gid, file_path=legacy_path,
            file_role="classified_copy",
        )

        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified",
        )
        items = [it for it in report.items if it.group_id == gid]
        assert items and items[0].status == "legacy_extra"
        assert legacy_path in items[0].legacy_extra_paths
        assert items[0].missing_expected_paths == ()
        assert report.summary.groups_with_legacy_extra >= 1
        assert report.summary.legacy_file_count >= 1


# ---------------------------------------------------------------------------
# C. missing_expected
# ---------------------------------------------------------------------------

class TestMissingExpected:
    def test_expected_path_not_in_existing(self, db, tmp_path):
        from core.classifier import build_classify_preview
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["伊落マリー"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))

        cfg = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        # expected dest 등록을 의도적으로 생략. 단, 그룹이 scope='all_classified'
        # 에 잡히도록 무관한 classified_copy 1건만 등록.
        unrelated = str(tmp_path / "Classified" / "그외" / "x.jpg")
        _insert_file(
            db, group_id=gid, file_path=unrelated,
            file_role="classified_copy",
        )

        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified",
        )
        items = [it for it in report.items if it.group_id == gid]
        assert items
        # legacy(unrelated 1건) + missing(expected 누락) 모두 있으므로
        # status 는 legacy_and_missing 이 된다 — D 케이스에서 정확히 검증.
        # 본 케이스는 missing_expected_paths 가 비어 있지 않은지만 확인.
        assert items[0].missing_expected_paths
        assert report.summary.groups_with_missing_expected >= 1


# ---------------------------------------------------------------------------
# D. legacy_and_missing
# ---------------------------------------------------------------------------

class TestLegacyAndMissing:
    def test_both_legacy_and_missing(self, db, tmp_path):
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["伊落マリー"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))

        legacy_path = str(tmp_path / "Classified" / "옛" / "p0.jpg")
        _insert_file(
            db, group_id=gid, file_path=legacy_path,
            file_role="classified_copy",
        )

        cfg = _config(tmp_path)
        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified",
        )
        items = [it for it in report.items if it.group_id == gid]
        assert items and items[0].status == "legacy_and_missing"
        assert legacy_path in items[0].legacy_extra_paths
        assert items[0].missing_expected_paths


# ---------------------------------------------------------------------------
# E. unverifiable
# ---------------------------------------------------------------------------

class TestUnverifiable:
    def test_no_source_file_marks_unverifiable(self, db, tmp_path):
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        # original 파일 없이 group + classified_copy 만 둔다 → preview 가 None.
        _insert_group(db, group_id=gid, series=["Blue Archive"])
        _insert_file(
            db, group_id=gid,
            file_path=str(tmp_path / "Classified" / "Foo" / "p0.jpg"),
            file_role="classified_copy",
        )

        cfg = _config(tmp_path)
        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified",
        )
        items = [it for it in report.items if it.group_id == gid]
        assert items and items[0].status == "unverifiable"
        assert items[0].current_destinations == ()
        assert report.summary.groups_unverifiable >= 1

    def test_classified_dir_unset_marks_unverifiable(self, db, tmp_path):
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))
        _insert_file(
            db, group_id=gid,
            file_path=str(tmp_path / "Classified" / "Foo" / "p0.jpg"),
            file_role="classified_copy",
        )

        cfg = _config(tmp_path)
        cfg["classified_dir"] = ""  # build_classify_preview → None
        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified",
        )
        items = [it for it in report.items if it.group_id == gid]
        assert items and items[0].status == "unverifiable"


# ---------------------------------------------------------------------------
# F. multi-destination
# ---------------------------------------------------------------------------

class TestMultiDestination:
    def test_set_comparison_with_multiple_destinations(self, db, tmp_path):
        from core.classifier import build_classify_preview
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid, series=["Blue Archive"],
            character=["伊落マリー", "陸八魔アル"],
        )
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))

        cfg = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        assert len(preview["destinations"]) >= 2

        # 모든 expected dest 등록
        for d in preview["destinations"]:
            _insert_file(
                db, group_id=gid, file_path=d["dest_path"],
                file_role="classified_copy",
            )

        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified", include_consistent=True,
        )
        items = [it for it in report.items if it.group_id == gid]
        assert items and items[0].status == "consistent"
        assert len(items[0].current_destinations) == len(preview["destinations"])


# ---------------------------------------------------------------------------
# G. path normalization
# ---------------------------------------------------------------------------

class TestPathNormalization:
    def test_case_difference_treated_as_same(self, db, tmp_path):
        from core.classifier import build_classify_preview
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["伊落マリー"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))

        cfg = _config(tmp_path)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        # expected dest 와 case 만 다른 path 등록 (Windows 동의어).
        for d in preview["destinations"]:
            altered = d["dest_path"].swapcase()
            _insert_file(
                db, group_id=gid, file_path=altered,
                file_role="classified_copy",
            )

        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified", include_consistent=True,
        )
        items = [it for it in report.items if it.group_id == gid]
        assert items
        # casefold 정규화로 같은 path 로 인식 → consistent.
        assert items[0].status == "consistent", (
            f"case-only diff should be consistent, got {items[0].status}"
        )

    def test_helper_normalize(self):
        from core.classified_output_consistency import _normalize_path_for_compare
        a = _normalize_path_for_compare("C:\\Users\\X\\Foo.jpg")
        b = _normalize_path_for_compare("c:/users/x/FOO.JPG")
        # 두 표현은 같은 절대 경로를 의미해야 한다 (Windows 환경 기준).
        assert a == b
        # 빈 문자열은 그대로.
        assert _normalize_path_for_compare("") == ""


# ---------------------------------------------------------------------------
# H. read-only invariant
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_report_does_not_modify_db(self, db, tmp_path):
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["伊落マリー"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))
        legacy = str(tmp_path / "Classified" / "옛" / "p0.jpg")
        _insert_file(db, group_id=gid, file_path=legacy, file_role="classified_copy")

        before = {
            "groups": db.execute("SELECT COUNT(*) FROM artwork_groups").fetchone()[0],
            "files":  db.execute("SELECT COUNT(*) FROM artwork_files").fetchone()[0],
            "tags":   db.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
            "aliases": db.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0],
            "undo":   db.execute("SELECT COUNT(*) FROM undo_entries").fetchone()[0],
            "copy":   db.execute("SELECT COUNT(*) FROM copy_records").fetchone()[0],
        }

        cfg = _config(tmp_path)
        build_classified_output_consistency_report(db, config=cfg)

        after = {
            "groups": db.execute("SELECT COUNT(*) FROM artwork_groups").fetchone()[0],
            "files":  db.execute("SELECT COUNT(*) FROM artwork_files").fetchone()[0],
            "tags":   db.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
            "aliases": db.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0],
            "undo":   db.execute("SELECT COUNT(*) FROM undo_entries").fetchone()[0],
            "copy":   db.execute("SELECT COUNT(*) FROM copy_records").fetchone()[0],
        }
        assert before == after, f"DB row counts changed: {before} → {after}"

    def test_no_filesystem_mutation(self, db, tmp_path):
        """report 호출 후 inbox / Classified 폴더의 파일 목록이 변하지 않는다."""
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["伊落マリー"])
        orig = tmp_path / "inbox" / "p0.jpg"
        _make_real_jpg(orig)
        _insert_file(db, group_id=gid, file_path=str(orig))
        legacy_dir = tmp_path / "Classified" / "옛"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_dir / "p0.jpg"
        legacy_file.write_bytes(b"x")
        _insert_file(
            db, group_id=gid, file_path=str(legacy_file),
            file_role="classified_copy",
        )

        before_files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
        cfg = _config(tmp_path)
        build_classified_output_consistency_report(db, config=cfg)
        after_files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
        assert before_files == after_files


# ---------------------------------------------------------------------------
# scope / param plumbing
# ---------------------------------------------------------------------------

class TestScopeAndParams:
    def test_explicit_group_ids_override_scope(self, db, tmp_path):
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gids = []
        for _ in range(3):
            gid = str(uuid.uuid4())
            _insert_group(db, group_id=gid, series=["Blue Archive"])
            _insert_file(
                db, group_id=gid,
                file_path=str(tmp_path / f"{gid[:6]}.jpg"),
                file_role="classified_copy",
            )
            gids.append(gid)

        cfg = _config(tmp_path)
        # only 1 explicit group
        report = build_classified_output_consistency_report(
            db, config=cfg, group_ids=[gids[0]],
        )
        # scope 무관, group_ids 가 우선.
        assert report.summary.groups_scanned == 1
        assert all(it.group_id == gids[0] for it in report.items)

    def test_limit_caps_all_classified_scope(self, db, tmp_path):
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        for _ in range(5):
            gid = str(uuid.uuid4())
            _insert_group(db, group_id=gid, series=["Blue Archive"])
            _insert_file(
                db, group_id=gid,
                file_path=str(tmp_path / f"{gid[:6]}.jpg"),
                file_role="classified_copy",
            )

        cfg = _config(tmp_path)
        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified", limit=2,
        )
        assert report.summary.groups_scanned == 2

    def test_classified_copy_with_status_other_than_present_excluded(self, db, tmp_path):
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
        )

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"])
        # missing 인 classified_copy 만 → scope='all_classified' 에 안 잡힘.
        _insert_file(
            db, group_id=gid,
            file_path=str(tmp_path / "deleted.jpg"),
            file_role="classified_copy",
            file_status="missing",
        )

        cfg = _config(tmp_path)
        report = build_classified_output_consistency_report(
            db, config=cfg, scope="all_classified",
        )
        assert all(it.group_id != gid for it in report.items)
        assert report.summary.groups_scanned == 0
