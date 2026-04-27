"""
classification_failure_exporter 테스트.

개발자 전용 분류 실패 태그 export 기능의 활성화 조건, 수집 로직,
텍스트 포매터, 파일 저장, 경로 보안을 검증한다.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    from db.database import initialize_database
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _insert_group(
    conn,
    tags: list[str],
    title: str = "",
    artist: str = "",
    series_tags: list[str] | None = None,
    character_tags: list[str] | None = None,
) -> str:
    group_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, artwork_id, artwork_title, artist_name, "
        "tags_json, series_tags_json, character_tags_json, "
        "downloaded_at, indexed_at, metadata_sync_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'full')",
        (
            group_id,
            f"art_{group_id[:8]}",
            title,
            artist,
            json.dumps(tags, ensure_ascii=False),
            json.dumps(series_tags or [], ensure_ascii=False),
            json.dumps(character_tags or [], ensure_ascii=False),
            now, now,
        ),
    )
    conn.commit()
    return group_id


def _make_author_fallback_preview(group_id: str, source_path: str, raw_tags: list[str]) -> dict:
    return {
        "group_id": group_id,
        "source_path": source_path,
        "destinations": [
            {"rule_type": "author_fallback", "dest_path": "/out/author/file.jpg", "will_copy": True}
        ],
        "classification_info": {
            "classification_reason": "series_and_character_missing",
            "missing_parts": ["series", "character"],
            "series_context": "",
            "candidate_source_tags": raw_tags[:5],
            "suggested_action": "series/character alias 후보를 확인하세요.",
        },
        "fallback_tags": [],
        "inferred_series_evidence": [],
    }


def _make_series_uncategorized_preview(group_id: str, source_path: str) -> dict:
    return {
        "group_id": group_id,
        "source_path": source_path,
        "destinations": [
            {"rule_type": "series_uncategorized", "dest_path": "/out/series/file.jpg", "will_copy": True}
        ],
        "classification_info": {
            "classification_reason": "series_detected_but_character_missing",
            "missing_parts": ["character"],
            "series_context": "Blue Archive",
            "candidate_source_tags": ["未知キャラ"],
            "suggested_action": "태그 재분류를 실행하세요.",
        },
        "fallback_tags": [],
        "inferred_series_evidence": [],
    }


def _make_series_character_preview(group_id: str, source_path: str) -> dict:
    return {
        "group_id": group_id,
        "source_path": source_path,
        "destinations": [
            {"rule_type": "series_character", "dest_path": "/out/series/char/file.jpg", "will_copy": True}
        ],
        "classification_info": None,
        "fallback_tags": [],
        "inferred_series_evidence": [],
    }


# ---------------------------------------------------------------------------
# 1. is_failure_export_enabled — 기본값 OFF
# ---------------------------------------------------------------------------

class TestIsFailureExportEnabled:
    def test_default_config_returns_false(self):
        from core.classification_failure_exporter import is_failure_export_enabled
        cfg = {"developer": {"enabled": False, "export_classification_failures": False}}
        assert is_failure_export_enabled(cfg) is False

    def test_empty_config_returns_false(self):
        from core.classification_failure_exporter import is_failure_export_enabled
        assert is_failure_export_enabled({}) is False

    def test_none_config_returns_false(self):
        from core.classification_failure_exporter import is_failure_export_enabled
        assert is_failure_export_enabled(None) is False

    def test_developer_enabled_and_export_true_returns_true(self):
        from core.classification_failure_exporter import is_failure_export_enabled
        cfg = {
            "developer": {
                "enabled": True,
                "export_classification_failures": True,
            }
        }
        assert is_failure_export_enabled(cfg) is True

    def test_developer_enabled_only_returns_false(self):
        """enabled=True だが export_classification_failures=False → False"""
        from core.classification_failure_exporter import is_failure_export_enabled
        cfg = {"developer": {"enabled": True, "export_classification_failures": False}}
        assert is_failure_export_enabled(cfg) is False

    def test_export_flag_only_no_enabled_returns_false(self):
        """export_classification_failures=True だが enabled=False → False"""
        from core.classification_failure_exporter import is_failure_export_enabled
        cfg = {"developer": {"enabled": False, "export_classification_failures": True}}
        assert is_failure_export_enabled(cfg) is False

    def test_env_export_flag_returns_true(self, monkeypatch):
        from core.classification_failure_exporter import is_failure_export_enabled
        monkeypatch.setenv("ARU_EXPORT_CLASSIFICATION_FAILURES", "1")
        assert is_failure_export_enabled({}) is True

    def test_env_dev_mode_returns_true(self, monkeypatch):
        from core.classification_failure_exporter import is_failure_export_enabled
        monkeypatch.setenv("ARU_ARCHIVE_DEV_MODE", "1")
        assert is_failure_export_enabled({}) is True

    def test_env_truthy_values(self, monkeypatch):
        from core.classification_failure_exporter import is_failure_export_enabled
        for val in ("true", "yes", "on", "TRUE"):
            monkeypatch.setenv("ARU_EXPORT_CLASSIFICATION_FAILURES", val)
            assert is_failure_export_enabled(None) is True

    def test_env_absent_does_not_force_off_config(self, monkeypatch):
        """env 변수 미설정은 config=True를 강제로 끄지 않는다."""
        from core.classification_failure_exporter import is_failure_export_enabled
        monkeypatch.delenv("ARU_EXPORT_CLASSIFICATION_FAILURES", raising=False)
        monkeypatch.delenv("ARU_ARCHIVE_DEV_MODE", raising=False)
        cfg = {"developer": {"enabled": True, "export_classification_failures": True}}
        assert is_failure_export_enabled(cfg) is True


# ---------------------------------------------------------------------------
# 4 & 5. collect_classification_failures — author_fallback / series_uncategorized
# ---------------------------------------------------------------------------

class TestCollectClassificationFailures:
    def test_author_fallback_item_included(self, conn):
        tags = ["陸八魔アル(正月)", "晴れ着"]
        group_id = _insert_group(conn, tags, title="アル社長", artist="eko")
        preview = _make_author_fallback_preview(group_id, f"/path/{group_id}.jpg", tags)
        from core.classification_failure_exporter import collect_classification_failures
        report = collect_classification_failures(conn, preview)
        assert report["summary"]["failed_groups"] == 1
        item = report["failed_items"][0]
        assert item["rule_type"] == "author_fallback"
        assert item["title"] == "アル社長"
        assert item["artist"] == "eko"

    def test_series_uncategorized_item_included(self, conn):
        tags = ["Blue Archive", "未知キャラ"]
        group_id = _insert_group(conn, tags, series_tags=["Blue Archive"])
        preview = _make_series_uncategorized_preview(group_id, f"/path/{group_id}.jpg")
        from core.classification_failure_exporter import collect_classification_failures
        report = collect_classification_failures(conn, preview)
        assert report["summary"]["failed_groups"] == 1
        assert report["failed_items"][0]["rule_type"] == "series_uncategorized"

    def test_series_character_item_excluded(self, conn):
        """정상 series_character 항목은 report에 포함되지 않는다."""
        group_id = _insert_group(conn, ["アロナ", "ブルーアーカイブ"],
                                 series_tags=["Blue Archive"], character_tags=["アロナ"])
        preview = _make_series_character_preview(group_id, f"/path/{group_id}.jpg")
        from core.classification_failure_exporter import collect_classification_failures
        report = collect_classification_failures(conn, preview)
        assert report["summary"]["failed_groups"] == 0
        assert report["failed_items"] == []

    def test_batch_preview_format(self, conn):
        """build_classify_batch_preview 형식("previews" 키)을 처리할 수 있다."""
        tags = ["陸八魔アル(正月)", "晴れ着"]
        g1 = _insert_group(conn, tags)
        g2 = _insert_group(conn, ["アロナ"], series_tags=["Blue Archive"], character_tags=["アロナ"])
        p1 = _make_author_fallback_preview(g1, f"/p/{g1}.jpg", tags)
        p2 = _make_series_character_preview(g2, f"/p/{g2}.jpg")
        from core.classification_failure_exporter import collect_classification_failures
        batch_preview = {"previews": [p1, p2]}
        report = collect_classification_failures(conn, batch_preview)
        assert report["summary"]["failed_groups"] == 1

    def test_raw_tags_frequency_correct(self, conn):
        """동일 태그가 여러 그룹에 나타나면 count가 올바르게 집계된다."""
        shared_tag = "晴れ着"
        g1 = _insert_group(conn, [shared_tag, "アルタグ"])
        g2 = _insert_group(conn, [shared_tag, "別タグ"])
        p1 = _make_author_fallback_preview(g1, "/p/g1.jpg", [shared_tag, "アルタグ"])
        p2 = _make_author_fallback_preview(g2, "/p/g2.jpg", [shared_tag, "別タグ"])
        from core.classification_failure_exporter import collect_classification_failures
        report = collect_classification_failures(conn, {"previews": [p1, p2]})
        freq = {e["tag"]: e["count"] for e in report["tag_frequency"]}
        assert freq.get(shared_tag) == 2
        assert freq.get("アルタグ") == 1

    def test_absolute_path_excluded_by_default(self, conn):
        """기본 설정에서는 file_path(절대 경로)가 report item에 없다."""
        tags = ["test_tag"]
        group_id = _insert_group(conn, tags)
        preview = _make_author_fallback_preview(group_id, "/absolute/path/file.jpg", tags)
        from core.classification_failure_exporter import collect_classification_failures
        report = collect_classification_failures(conn, preview)
        item = report["failed_items"][0]
        assert "file_path" not in item

    def test_absolute_path_included_when_requested(self, conn):
        """include_absolute_paths=True 時は file_path が含まれる。"""
        tags = ["test_tag"]
        group_id = _insert_group(conn, tags)
        source = "/absolute/path/file.jpg"
        preview = _make_author_fallback_preview(group_id, source, tags)
        from core.classification_failure_exporter import collect_classification_failures
        report = collect_classification_failures(conn, preview, include_absolute_paths=True)
        item = report["failed_items"][0]
        assert item.get("file_path") == source

    def test_file_name_always_included(self, conn):
        """file_path が除外されても file_name は常に含まれる。"""
        tags = ["test_tag"]
        group_id = _insert_group(conn, tags)
        preview = _make_author_fallback_preview(group_id, "/some/path/my_file.jpg", tags)
        from core.classification_failure_exporter import collect_classification_failures
        report = collect_classification_failures(conn, preview)
        assert report["failed_items"][0]["file_name"] == "my_file.jpg"


# ---------------------------------------------------------------------------
# 8. format_classification_failures_text
# ---------------------------------------------------------------------------

class TestFormatClassificationFailuresText:
    def _make_report(self, tags: list[str], file_name: str = "test.jpg") -> dict:
        return {
            "summary": {"failed_groups": 1, "unique_raw_tags": len(tags), "generated_at": "2026-04-27T00:00:00Z"},
            "failed_items": [{
                "group_id": "g1", "artwork_id": "a1",
                "title": "テスト", "artist": "test_artist",
                "file_name": file_name,
                "rule_type": "author_fallback",
                "status": "full",
                "raw_tags": tags,
                "series_tags_json": [], "character_tags_json": [],
                "known_series_candidates": [], "known_character_candidates": [],
                "warnings": [], "suggested_debug_notes": [],
            }],
            "tag_frequency": [{"tag": t, "count": 1, "sample_titles": ["テスト"]} for t in tags],
        }

    def test_contains_file_name(self):
        from core.classification_failure_exporter import format_classification_failures_text
        report = self._make_report(["tag1"], "my_artwork.jpg")
        text = format_classification_failures_text(report)
        assert "my_artwork.jpg" in text

    def test_contains_raw_tags(self):
        from core.classification_failure_exporter import format_classification_failures_text
        report = self._make_report(["陸八魔アル(正月)", "晴れ着"])
        text = format_classification_failures_text(report)
        assert "陸八魔アル(正月)" in text
        assert "晴れ着" in text

    def test_contains_summary_header(self):
        from core.classification_failure_exporter import format_classification_failures_text
        report = self._make_report(["t1"])
        text = format_classification_failures_text(report)
        assert "## Summary" in text
        assert "failed groups: 1" in text

    def test_contains_frequent_tags_section(self):
        from core.classification_failure_exporter import format_classification_failures_text
        report = self._make_report(["多頻度タグ"])
        text = format_classification_failures_text(report)
        assert "Frequent Unknown Tags" in text
        assert "多頻度タグ" in text


# ---------------------------------------------------------------------------
# 9. save_classification_failure_report — json/txt 파일 생성
# ---------------------------------------------------------------------------

class TestSaveClassificationFailureReport:
    def _minimal_report(self) -> dict:
        return {
            "summary": {"failed_groups": 1, "unique_raw_tags": 2, "generated_at": "2026-04-27T00:00:00Z"},
            "failed_items": [],
            "tag_frequency": [],
        }

    def test_json_file_created(self, tmp_path):
        from core.classification_failure_exporter import save_classification_failure_report
        paths = save_classification_failure_report(self._minimal_report(), tmp_path, write_json=True, write_text=False)
        assert paths["json"] is not None
        assert Path(paths["json"]).exists()

    def test_text_file_created(self, tmp_path):
        from core.classification_failure_exporter import save_classification_failure_report
        paths = save_classification_failure_report(self._minimal_report(), tmp_path, write_json=False, write_text=True)
        assert paths["text"] is not None
        assert Path(paths["text"]).exists()

    def test_both_files_created(self, tmp_path):
        from core.classification_failure_exporter import save_classification_failure_report
        paths = save_classification_failure_report(self._minimal_report(), tmp_path)
        assert Path(paths["json"]).exists()
        assert Path(paths["text"]).exists()

    def test_json_content_valid(self, tmp_path):
        from core.classification_failure_exporter import save_classification_failure_report
        report = self._minimal_report()
        paths = save_classification_failure_report(report, tmp_path, write_json=True, write_text=False)
        loaded = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        assert loaded["summary"]["failed_groups"] == 1

    def test_creates_output_dir(self, tmp_path):
        from core.classification_failure_exporter import save_classification_failure_report
        nested = tmp_path / "a" / "b" / "c"
        save_classification_failure_report(self._minimal_report(), nested)
        assert nested.exists()

    def test_no_files_when_both_false(self, tmp_path):
        from core.classification_failure_exporter import save_classification_failure_report
        paths = save_classification_failure_report(
            self._minimal_report(), tmp_path, write_json=False, write_text=False
        )
        assert paths["json"] is None
        assert paths["text"] is None
