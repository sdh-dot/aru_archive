"""
분류 실패 원인(series_uncategorized / author_fallback) 관련 테스트.

- batch preview에서 실패 원인 카운트 확인
- classification_failure 후보 생성 확인
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from db.database import initialize_database


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _insert_group(
    conn,
    gid: str,
    tmp_path: Path,
    *,
    series: list | None = None,
    char: list | None = None,
    tags: list | None = None,
    status: str = "full",
) -> str:
    src = tmp_path / f"{gid[:8]}.jpg"
    src.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO artwork_groups
           (group_id, artwork_id, artwork_title, artist_name,
            series_tags_json, character_tags_json, tags_json,
            metadata_sync_status, downloaded_at, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            gid, f"art-{gid[:8]}", f"title-{gid[:4]}", "artist_x",
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(char   or [], ensure_ascii=False),
            json.dumps(tags   or [], ensure_ascii=False),
            status, now, now,
        ),
    )
    conn.execute(
        """INSERT INTO artwork_files
           (file_id, group_id, file_path, file_format,
            file_role, file_status, file_size, created_at)
           VALUES (?, ?, ?, 'jpg', 'original', 'present', 512, ?)""",
        (str(uuid.uuid4()), gid, str(src), now),
    )
    conn.commit()
    return gid


_BASE_CONFIG = {
    "classified_dir": "",  # will be set per test
    "classification": {
        "folder_locale": "canonical",
        "on_conflict": "rename",
        "series_rule": "series_only",
        "character_rule": "series_character",
        "fallback_rule": "artist",
        "tag_rule": "none",
    },
}


def _config_with_dir(classified_dir: str) -> dict:
    cfg = dict(_BASE_CONFIG)
    cfg["classified_dir"] = classified_dir
    return cfg


# ---------------------------------------------------------------------------
# classification_info in build_classify_preview
# ---------------------------------------------------------------------------

class TestClassificationInfoInPreview:
    def test_series_uncategorized_reason(self, conn, tmp_path) -> None:
        """series 있고 character 없으면 series_detected_but_character_missing."""
        from core.classifier import build_classify_preview
        gid = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=[], tags=["マリー", "水着"],
        )
        p = build_classify_preview(conn, gid, _config_with_dir(str(tmp_path / "cls")))
        assert p is not None
        ci = p["classification_info"]
        assert ci is not None
        assert ci["classification_reason"] == "series_detected_but_character_missing"
        assert "character" in ci["missing_parts"]
        assert ci["series_context"] == "Blue Archive"
        assert "マリー" in ci["candidate_source_tags"]

    def test_author_fallback_reason(self, conn, tmp_path) -> None:
        """series도 character도 없으면 series_and_character_missing."""
        from core.classifier import build_classify_preview
        gid = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=[], char=[], tags=["未知のタグA", "未知のタグB"],
        )
        p = build_classify_preview(conn, gid, _config_with_dir(str(tmp_path / "cls")))
        assert p is not None
        ci = p["classification_info"]
        assert ci is not None
        assert ci["classification_reason"] == "series_and_character_missing"
        assert "series" in ci["missing_parts"]
        assert "character" in ci["missing_parts"]

    def test_no_classification_info_when_both_present(self, conn, tmp_path) -> None:
        """series도 character도 있으면 classification_info=None."""
        from core.classifier import build_classify_preview
        gid = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=["陸八魔アル"], tags=[],
        )
        p = build_classify_preview(conn, gid, _config_with_dir(str(tmp_path / "cls")))
        assert p is not None
        assert p["classification_info"] is None

    def test_blacklisted_tags_excluded_from_candidates(self, conn, tmp_path) -> None:
        """GENERAL_TAG_BLACKLIST 태그는 후보 소스에 포함되지 않는다."""
        from core.classifier import build_classify_preview
        gid = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=[],
            tags=["マリー", "1girl", "solo", "水着"],
        )
        p = build_classify_preview(conn, gid, _config_with_dir(str(tmp_path / "cls")))
        ci = p["classification_info"]
        assert "1girl" not in ci["candidate_source_tags"]
        assert "solo" not in ci["candidate_source_tags"]
        assert "マリー" in ci["candidate_source_tags"]


# ---------------------------------------------------------------------------
# generate_classification_failure_candidates
# ---------------------------------------------------------------------------

class TestClassificationFailureCandidates:
    def test_series_uncategorized_generates_character_candidates(
        self, conn, tmp_path
    ) -> None:
        from core.tag_candidate_generator import generate_classification_failure_candidates
        ci = {
            "classification_reason": "series_detected_but_character_missing",
            "candidate_source_tags": ["マリー", "アリス"],
            "series_context": "Blue Archive",
        }
        gid = str(uuid.uuid4())
        candidates = generate_classification_failure_candidates(conn, gid, ci)
        assert len(candidates) == 2
        for c in candidates:
            assert c["suggested_type"] == "character"
            assert c["suggested_parent_series"] == "Blue Archive"
            assert abs(c["confidence_score"] - 0.35) < 1e-9

    def test_author_fallback_generates_general_candidates(
        self, conn, tmp_path
    ) -> None:
        from core.tag_candidate_generator import generate_classification_failure_candidates
        ci = {
            "classification_reason": "series_and_character_missing",
            "candidate_source_tags": ["不明シリーズ"],
            "series_context": "",
        }
        gid = str(uuid.uuid4())
        candidates = generate_classification_failure_candidates(conn, gid, ci)
        assert len(candidates) == 1
        assert candidates[0]["suggested_type"] == "general"
        assert abs(candidates[0]["confidence_score"] - 0.20) < 1e-9

    def test_source_is_classification_failure(self, conn, tmp_path) -> None:
        from core.tag_candidate_generator import generate_classification_failure_candidates
        ci = {
            "classification_reason": "series_detected_but_character_missing",
            "candidate_source_tags": ["テストタグ"],
            "series_context": "Blue Archive",
        }
        candidates = generate_classification_failure_candidates(conn, str(uuid.uuid4()), ci)
        row = conn.execute(
            "SELECT source FROM tag_candidates WHERE raw_tag = 'テストタグ'"
        ).fetchone()
        assert row is not None
        assert row[0] == "classification_failure"

    def test_confirmed_aliases_skipped(self, conn) -> None:
        """tag_aliases에 있는 태그는 후보에서 제외된다."""
        from core.tag_candidate_generator import generate_classification_failure_candidates
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO tag_aliases
               (alias, canonical, tag_type, parent_series, source, enabled, created_at)
               VALUES ('確定済みタグ', '確定済みタグ', 'character', 'Blue Archive', 'test', 1, ?)""",
            (now,),
        )
        conn.commit()
        ci = {
            "classification_reason": "series_detected_but_character_missing",
            "candidate_source_tags": ["確定済みタグ", "新しいタグ"],
            "series_context": "Blue Archive",
        }
        candidates = generate_classification_failure_candidates(conn, str(uuid.uuid4()), ci)
        raw_tags = [c["raw_tag"] for c in candidates]
        assert "確定済みタグ" not in raw_tags
        assert "新しいタグ" in raw_tags

    def test_empty_candidate_source_returns_empty(self, conn) -> None:
        from core.tag_candidate_generator import generate_classification_failure_candidates
        ci = {
            "classification_reason": "series_and_character_missing",
            "candidate_source_tags": [],
            "series_context": "",
        }
        candidates = generate_classification_failure_candidates(conn, str(uuid.uuid4()), ci)
        assert candidates == []


# ---------------------------------------------------------------------------
# build_classify_batch_preview — 실패 카운트
# ---------------------------------------------------------------------------

class TestBatchPreviewFailureCounts:
    def test_series_uncategorized_count(self, conn, tmp_path) -> None:
        from core.batch_classifier import build_classify_batch_preview
        cls_dir = str(tmp_path / "cls")
        gid1 = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=[], tags=["マリー"],
        )
        gid2 = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=["陸八魔アル"], tags=[],
        )
        result = build_classify_batch_preview(
            conn, [gid1, gid2], _config_with_dir(cls_dir)
        )
        assert result["series_uncategorized_count"] == 1
        assert result["author_fallback_count"] == 0

    def test_author_fallback_count(self, conn, tmp_path) -> None:
        from core.batch_classifier import build_classify_batch_preview
        cls_dir = str(tmp_path / "cls")
        gid1 = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=[], char=[], tags=["謎タグ"],
        )
        result = build_classify_batch_preview(
            conn, [gid1], _config_with_dir(cls_dir)
        )
        assert result["author_fallback_count"] == 1
        assert result["series_uncategorized_count"] == 0

    def test_candidate_count_populated(self, conn, tmp_path) -> None:
        from core.batch_classifier import build_classify_batch_preview
        cls_dir = str(tmp_path / "cls")
        gid = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=[], tags=["アリス", "ミモリ"],
        )
        result = build_classify_batch_preview(
            conn, [gid], _config_with_dir(cls_dir)
        )
        assert result["candidate_count"] >= 1

    def test_warnings_include_failure_counts(self, conn, tmp_path) -> None:
        from core.batch_classifier import build_classify_batch_preview
        cls_dir = str(tmp_path / "cls")
        gid = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=[], tags=["アリス"],
        )
        result = build_classify_batch_preview(
            conn, [gid], _config_with_dir(cls_dir)
        )
        warnings_text = " ".join(result["warnings"])
        assert "series_uncategorized" in warnings_text

    def test_retag_option_runs_reclassifier(self, conn, tmp_path) -> None:
        """retag_before_batch_preview=True 이면 retag가 실행된다 (에러 없이)."""
        from core.batch_classifier import build_classify_batch_preview
        cls_dir = str(tmp_path / "cls")
        gid = _insert_group(
            conn, str(uuid.uuid4()), tmp_path,
            series=["Blue Archive"], char=[], tags=["テスト"],
        )
        cfg = _config_with_dir(cls_dir)
        cfg["classification"] = dict(cfg["classification"])
        cfg["classification"]["retag_before_batch_preview"] = True
        result = build_classify_batch_preview(conn, [gid], cfg)
        assert "classifiable_groups" in result
