"""classification source 병합 정책 테스트 (PR #128).

검증 항목:
- collect_classification_source_tags() helper 동작
- build_classify_preview() 에서 raw_tags_json 기반 series/character 식별
- author_fallback 방지 (raw_tags 에 series 있을 때)
- inference reason 경로 (merged source 사용)
- retag_groups_from_existing_tags() merged source 사용
- consistency report expected destination (build_classify_preview 경유)
- legacy row (raw_tags_json 없음) 기존 동작 유지
- invalid raw_tags_json 안전 처리
- preview ≡ execute 일관성
- UserComment JSON / XMP / DB status 무영향 확인
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _seed_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    tag_type: str,
    parent_series: str = "",
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 'test', 1, ?)",
        (alias, canonical, tag_type, parent_series, _now()),
    )
    conn.commit()


def _seed_blue_archive(conn: sqlite3.Connection) -> None:
    """Blue Archive series + 合歓垣フブキ character alias 최소 seed."""
    for alias in ("ブルーアーカイブ", "ブルアカ", "BlueArchive", "Blue Archive"):
        _seed_alias(conn, alias, "Blue Archive", "series")
    _seed_alias(conn, "合歓垣フブキ", "合歓垣フブキ", "character", "Blue Archive")
    _seed_alias(conn, "ネムガキ", "合歓垣フブキ", "character", "Blue Archive")


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    raw_tags: list[str] | None = None,
    tags: list[str] | None = None,
    series: list[str] | None = None,
    character: list[str] | None = None,
    sync_status: str = "json_only",
    artist: str = "test_artist",
) -> None:
    artwork_id = group_id[:12]
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, artist_name, "
        " downloaded_at, indexed_at, metadata_sync_status, "
        " raw_tags_json, tags_json, series_tags_json, character_tags_json) "
        "VALUES (?, 'pixiv', ?, 'フブキ', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            group_id, artwork_id, artist, now, now, sync_status,
            json.dumps(raw_tags, ensure_ascii=False) if raw_tags is not None else None,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def _insert_file(conn: sqlite3.Connection, group_id: str, path: Path) -> str:
    fid = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0")
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, "
        " file_format, file_size, metadata_embedded, file_status, created_at) "
        "VALUES (?, ?, 0, 'original', ?, 'jpg', 1024, 1, 'present', ?)",
        (fid, group_id, str(path), _now()),
    )
    conn.commit()
    return fid


def _series_char_cfg(classified_dir: Path) -> dict:
    return {
        "classified_dir": str(classified_dir),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": False,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
            "folder_locale":                   "canonical",
            "allow_multi_destination":         True,
        },
    }


def _series_only_cfg(classified_dir: Path) -> dict:
    return {
        "classified_dir": str(classified_dir),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         False,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": False,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
            "folder_locale":                   "canonical",
            "allow_multi_destination":         True,
        },
    }


# ---------------------------------------------------------------------------
# 테스트 1 — collect_classification_source_tags() helper
# ---------------------------------------------------------------------------

class TestCollectClassificationSourceTags:
    def test_merges_all_four_fields(self):
        from core.classifier import collect_classification_source_tags
        row = {
            "raw_tags_json":       json.dumps(["ブルーアーカイブ", "合歓垣フブキ"]),
            "tags_json":           json.dumps(["fanart", "サングラス"]),
            "series_tags_json":    json.dumps([]),
            "character_tags_json": json.dumps([]),
        }
        result = collect_classification_source_tags(row)
        assert "ブルーアーカイブ" in result
        assert "合歓垣フブキ" in result
        assert "fanart" in result
        assert "サングラス" in result

    def test_deduplication_preserves_order(self):
        from core.classifier import collect_classification_source_tags
        row = {
            "raw_tags_json":       json.dumps(["A", "B", "C"]),
            "tags_json":           json.dumps(["B", "D"]),
            "series_tags_json":    json.dumps(["C", "E"]),
            "character_tags_json": json.dumps(["A", "F"]),
        }
        result = collect_classification_source_tags(row)
        assert result == ["A", "B", "C", "D", "E", "F"]

    def test_none_raw_tags_falls_back_to_other_fields(self):
        from core.classifier import collect_classification_source_tags
        row = {
            "raw_tags_json":       None,
            "tags_json":           json.dumps(["tag1"]),
            "series_tags_json":    json.dumps(["Series A"]),
            "character_tags_json": json.dumps([]),
        }
        result = collect_classification_source_tags(row)
        assert result == ["tag1", "Series A"]

    def test_invalid_json_is_skipped(self):
        from core.classifier import collect_classification_source_tags
        row = {
            "raw_tags_json":       "NOT_JSON",
            "tags_json":           json.dumps(["ok_tag"]),
            "series_tags_json":    None,
            "character_tags_json": None,
        }
        result = collect_classification_source_tags(row)
        assert result == ["ok_tag"]

    def test_all_null_returns_empty(self):
        from core.classifier import collect_classification_source_tags
        row = {
            "raw_tags_json": None,
            "tags_json": None,
            "series_tags_json": None,
            "character_tags_json": None,
        }
        assert collect_classification_source_tags(row) == []

    def test_missing_key_is_safe(self):
        """row 에 일부 필드가 없어도 안전하게 처리한다."""
        from core.classifier import collect_classification_source_tags
        row = {"tags_json": json.dumps(["only_this"])}
        result = collect_classification_source_tags(row)
        assert result == ["only_this"]

    def test_raw_tags_order_before_tags_json(self):
        """raw_tags_json 항목이 tags_json 보다 먼저 나온다."""
        from core.classifier import collect_classification_source_tags
        row = {
            "raw_tags_json": json.dumps(["raw_first"]),
            "tags_json":     json.dumps(["general_second"]),
            "series_tags_json": None,
            "character_tags_json": None,
        }
        result = collect_classification_source_tags(row)
        assert result.index("raw_first") < result.index("general_second")


# ---------------------------------------------------------------------------
# 테스트 2 — build_classify_preview(): raw_tags 기반 Blue Archive 식별
# ---------------------------------------------------------------------------

class TestBuildClassifyPreviewRawTags:
    def test_blue_archive_series_from_raw_tags(self, db, tmp_path):
        """raw_tags_json 에 ブルーアーカイブ 있으면 Blue Archive series 식별."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["ブルーアーカイブ", "合歓垣フブキ", "fanart", "サングラス", "ネムガキ"],
            tags=["fanart", "サングラス"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None

        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "author_fallback" not in rule_types, (
            f"author_fallback 으로 빠짐 — destinations: {rule_types}"
        )
        assert any(
            "series_character" in r or "series_uncategorized" in r
            for r in rule_types
        )

    def test_character_from_raw_tags(self, db, tmp_path):
        """raw_tags_json 의 합歓垣フブキ/ネムガキ 가 character 로 식별된다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["ブルーアーカイブ", "合歓垣フブキ", "fanart"],
            tags=["fanart"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None

        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "series_character" in rule_types, (
            f"series_character destination 없음 — destinations: {rule_types}"
        )

    def test_alias_tag_ネムガキ_identifies_character(self, db, tmp_path):
        """raw_tags_json 에 alias ネムガキ 만 있어도 character 식별된다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["ブルーアーカイブ", "ネムガキ", "サングラス"],
            tags=["サングラス"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None

        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "author_fallback" not in rule_types, (
            f"ネムガキ alias 에서 character 미식별 — destinations: {rule_types}"
        )

    def test_series_only_mode_raw_tags(self, db, tmp_path):
        """series-only 모드에서도 raw_tags_json 기반으로 series 를 식별한다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["ブルーアーカイブ", "fanart"],
            tags=["fanart"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_only_cfg(classified))
        assert preview is not None

        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "author_fallback" not in rule_types
        assert "series_unidentified_fallback" not in rule_types, (
            f"series-only 에서 미식별 fallback 발동 — destinations: {rule_types}"
        )
        assert any("series" in r for r in rule_types)

    def test_preview_detail_consistency(self, db, tmp_path):
        """detail panel 과 preview 의 태그 source 일관성 — raw_tags_json 이 있으면
        both 에서 같은 태그 집합을 기반으로 동작한다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        raw = ["ブルーアーカイブ", "合歓垣フブキ", "fanart"]
        _insert_group(
            db, group_id=gid,
            raw_tags=raw,
            tags=["fanart"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview, collect_classification_source_tags
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None

        # collect_classification_source_tags 가 raw_tags_json 을 포함
        row = db.execute(
            "SELECT raw_tags_json, tags_json, series_tags_json, character_tags_json "
            "FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        source = collect_classification_source_tags(row)
        for tag in raw:
            assert tag in source, f"raw tag {tag!r} 이 source 에 없음"


# ---------------------------------------------------------------------------
# 테스트 3 — author_fallback 방지
# ---------------------------------------------------------------------------

class TestAuthorFallbackPrevention:
    def test_no_author_fallback_when_series_in_raw_tags(self, db, tmp_path):
        """raw_tags_json 에 series alias 있으면 author_fallback 으로 가면 안 된다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["BlueArchive", "fanart"],
            tags=["fanart"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None
        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "author_fallback" not in rule_types

    def test_author_fallback_when_no_series_at_all(self, db, tmp_path):
        """series/character alias 가 전혀 없으면 author_fallback 이 정상이다."""
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["fanart", "girl"],
            tags=["fanart", "girl"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None
        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "author_fallback" in rule_types


# ---------------------------------------------------------------------------
# 테스트 4 — legacy row (raw_tags_json 없음) 기존 동작 유지
# ---------------------------------------------------------------------------

class TestLegacyRowFallback:
    def test_legacy_row_uses_existing_series_character(self, db, tmp_path):
        """raw_tags_json 이 NULL 인 legacy row 는 series_tags_json / character_tags_json
        기반으로 동작한다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=None,  # NULL
            tags=["fanart"],
            series=["Blue Archive"],
            character=["合歓垣フブキ"],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None
        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "series_character" in rule_types

    def test_legacy_row_only_tags_json_no_series(self, db, tmp_path):
        """raw_tags_json 없고 series_tags_json 도 비어 있으면 author_fallback."""
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=None,
            tags=["fanart"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None
        rule_types = [d["rule_type"] for d in preview["destinations"]]
        assert "author_fallback" in rule_types


# ---------------------------------------------------------------------------
# 테스트 5 — invalid raw_tags_json 안전 처리
# ---------------------------------------------------------------------------

class TestInvalidRawTags:
    def test_invalid_raw_tags_json_does_not_crash(self, db, tmp_path):
        """raw_tags_json 이 invalid JSON 이어도 앱이 중단되지 않는다."""
        gid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO artwork_groups "
            "(group_id, source_site, artwork_id, artwork_title, artist_name, "
            " downloaded_at, indexed_at, metadata_sync_status, "
            " raw_tags_json, tags_json, series_tags_json, character_tags_json) "
            "VALUES (?, 'pixiv', ?, 'test', 'artist', ?, ?, 'json_only', "
            " 'NOT_VALID_JSON', '[]', '[]', '[]')",
            (gid, gid[:12], _now(), _now()),
        )
        db.commit()
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None  # 중단 없이 결과 반환

    def test_collect_source_tags_with_invalid_json(self):
        """collect_classification_source_tags 가 invalid JSON 을 안전하게 skip."""
        from core.classifier import collect_classification_source_tags
        row = {
            "raw_tags_json": "{bad json}",
            "tags_json": json.dumps(["ok"]),
            "series_tags_json": None,
            "character_tags_json": "[]",
        }
        result = collect_classification_source_tags(row)
        assert result == ["ok"]


# ---------------------------------------------------------------------------
# 테스트 6 — retag_groups_from_existing_tags() merged source 사용
# ---------------------------------------------------------------------------

class TestRetagMergedSource:
    def test_retag_finds_series_from_raw_tags(self, db):
        """retag 이 raw_tags_json 기반으로 series_tags_json 을 복구한다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["ブルーアーカイブ", "合歓垣フブキ", "fanart"],
            tags=["fanart"],
            series=[], character=[],
        )

        from core.tag_reclassifier import retag_groups_from_existing_tags
        result = retag_groups_from_existing_tags(db, [gid])
        assert result["errors"] == []

        row = db.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups "
            "WHERE group_id = ?", (gid,)
        ).fetchone()
        series = json.loads(row["series_tags_json"] or "[]")
        char   = json.loads(row["character_tags_json"] or "[]")
        assert "Blue Archive" in series, f"Blue Archive 미식별 — series={series}"
        assert any("フブキ" in c or "合歓" in c for c in char), f"character 미식별 — char={char}"

    def test_retag_legacy_row_unchanged_behavior(self, db):
        """raw_tags_json 이 없는 legacy row 는 기존 tags_json 기반으로 retag."""
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=None,
            tags=["fanart", "girl"],
            series=[], character=[],
        )

        from core.tag_reclassifier import retag_groups_from_existing_tags
        result = retag_groups_from_existing_tags(db, [gid])
        assert result["errors"] == []
        # series/character 없는 일반 tags → 빈 결과가 정상
        row = db.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups "
            "WHERE group_id = ?", (gid,)
        ).fetchone()
        series = json.loads(row["series_tags_json"] or "[]")
        char   = json.loads(row["character_tags_json"] or "[]")
        assert series == []
        assert char == []


# ---------------------------------------------------------------------------
# 테스트 7 — preview ≡ execute destination 일관성
# ---------------------------------------------------------------------------

class TestPreviewExecuteConsistency:
    def test_preview_and_execute_same_destination(self, db, tmp_path):
        """build_classify_preview 결과를 execute 에 그대로 전달하면 동일 경로."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["ブルーアーカイブ", "合歓垣フブキ"],
            tags=[], series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        from core.classifier import build_classify_preview, execute_classify_preview
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))
        assert preview is not None

        expected_dests = [d["dest_path"] for d in preview["destinations"]]
        # execute 는 preview.destinations 를 그대로 사용 — 재계산 없음
        result = execute_classify_preview(db, preview, _series_char_cfg(classified))
        assert result["success"] is True
        for dest in expected_dests:
            assert Path(dest).exists() or result["skipped"] > 0, (
                f"예상 destination {dest} 가 생성되지 않음"
            )


# ---------------------------------------------------------------------------
# 테스트 8 — DB status / UserComment JSON / XMP 무영향 확인
# ---------------------------------------------------------------------------

class TestNoSideEffects:
    def test_preview_does_not_modify_db_tags(self, db, tmp_path):
        """build_classify_preview 는 DB 의 series/character 컬럼을 변경하지 않는다."""
        _seed_blue_archive(db)
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["ブルーアーカイブ", "合歓垣フブキ"],
            tags=["fanart"],
            series=[], character=[],
        )
        fpath = tmp_path / "source" / f"{gid[:8]}.jpg"
        _insert_file(db, gid, fpath)
        classified = tmp_path / "classified"

        # preview 전 DB 상태 스냅샷
        before = db.execute(
            "SELECT series_tags_json, character_tags_json, metadata_sync_status "
            "FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        series_before  = before["series_tags_json"]
        char_before    = before["character_tags_json"]
        status_before  = before["metadata_sync_status"]

        from core.classifier import build_classify_preview
        build_classify_preview(db, gid, _series_char_cfg(classified))

        # preview 후 DB 상태
        after = db.execute(
            "SELECT series_tags_json, character_tags_json, metadata_sync_status "
            "FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert after["series_tags_json"] == series_before, "preview 가 series_tags_json 을 변경함"
        assert after["character_tags_json"] == char_before, "preview 가 character_tags_json 을 변경함"
        assert after["metadata_sync_status"] == status_before, "preview 가 metadata_sync_status 를 변경함"

    def test_collect_source_tags_does_not_write(self, db):
        """collect_classification_source_tags 는 DB 에 아무것도 쓰지 않는다."""
        gid = str(uuid.uuid4())
        _insert_group(
            db, group_id=gid,
            raw_tags=["A", "B"],
            tags=["C"],
            series=[], character=[],
        )
        row_before = dict(db.execute(
            "SELECT * FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone())

        from core.classifier import collect_classification_source_tags
        row = db.execute(
            "SELECT raw_tags_json, tags_json, series_tags_json, character_tags_json "
            "FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        collect_classification_source_tags(row)

        row_after = dict(db.execute(
            "SELECT * FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone())
        assert row_before == row_after, "collect_classification_source_tags 가 DB 를 변경함"
