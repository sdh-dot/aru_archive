"""series-only mode resolver 회귀 테스트 (PR #120).

resolve_series_only_destination 의 6개 분기와 build_classify_preview 통합
경로를 검증한다. metadata pipeline / DB schema / classified_copy 정책은
변경되지 않으며, preview 단계의 destination 결정과 needs_review 분류만
확인한다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.classifier import (
    SERIES_ONLY_REASON_MULTI_REQ_CONFIRM,
    SERIES_ONLY_REASON_PARENT_CONFLICT,
    SERIES_ONLY_REASON_UNIDENTIFIED,
    SERIES_ONLY_RULE_MULTIPLE_PARENT_SERIES,
    SERIES_ONLY_RULE_PARENT_SERIES,
    SERIES_ONLY_RULE_SERIES_TAG,
    build_classify_preview,
    is_series_only_mode,
    resolve_series_only_destination,
)


# ---------------------------------------------------------------------------
# Pure resolver tests — 7개 분기
# ---------------------------------------------------------------------------

class TestResolveSeriesOnlyDestination:
    """resolve_series_only_destination 의 분기를 검증한다."""

    def test_1_explicit_series_only_uses_series_tag(self) -> None:
        """명시 시리즈 태그만 있을 때 → ready, rule=series_tag."""
        result = resolve_series_only_destination(
            explicit_series=["fate_grand_order"],
            parent_series_map={},
        )
        assert result["status"] == "ready"
        assert result["rule"] == SERIES_ONLY_RULE_SERIES_TAG
        assert result["series"] == ["fate_grand_order"]

    def test_2_character_only_infers_parent_series(self) -> None:
        """캐릭터 단독 (parent_series 1개) → ready, rule=parent_series."""
        result = resolve_series_only_destination(
            explicit_series=[],
            parent_series_map={"羽川ハスミ": "blue_archive"},
        )
        assert result["status"] == "ready"
        assert result["rule"] == SERIES_ONLY_RULE_PARENT_SERIES
        assert result["series"] == ["blue_archive"]

    def test_3_multiple_characters_same_parent_collapse_to_one(self) -> None:
        """캐릭터 여러명, 같은 parent_series → 단일 destination."""
        result = resolve_series_only_destination(
            explicit_series=[],
            parent_series_map={
                "羽川ハスミ": "blue_archive",
                "伊落マリー": "blue_archive",
            },
        )
        assert result["status"] == "ready"
        assert result["rule"] == SERIES_ONLY_RULE_PARENT_SERIES
        assert result["series"] == ["blue_archive"]

    def test_4_multi_parent_series_with_allow_multi_emits_all(self) -> None:
        """parent_series 다수 + allow_multi=True → ready, rule=multiple_parent_series."""
        result = resolve_series_only_destination(
            explicit_series=[],
            parent_series_map={
                "羽川ハスミ":  "blue_archive",
                "マシュ・キリエライト": "fate_grand_order",
            },
            allow_multi_destination=True,
        )
        assert result["status"] == "ready"
        assert result["rule"] == SERIES_ONLY_RULE_MULTIPLE_PARENT_SERIES
        assert "blue_archive" in result["series"]
        assert "fate_grand_order" in result["series"]
        assert len(result["series"]) == 2

    def test_5_multi_parent_series_no_allow_multi_needs_review(self) -> None:
        """parent_series 다수 + allow_multi=False → needs_review."""
        result = resolve_series_only_destination(
            explicit_series=[],
            parent_series_map={
                "羽川ハスミ":  "blue_archive",
                "マシュ・キリエライト": "fate_grand_order",
            },
            allow_multi_destination=False,
        )
        assert result["status"] == "needs_review"
        assert result["reason"] == SERIES_ONLY_REASON_MULTI_REQ_CONFIRM
        assert "blue_archive" in result["parent_series"]
        assert "fate_grand_order" in result["parent_series"]

    def test_6_explicit_series_conflicts_with_parent_no_destination(self) -> None:
        """명시 시리즈 + 충돌하는 parent_series → needs_review, no destination."""
        result = resolve_series_only_destination(
            explicit_series=["fate_grand_order"],
            parent_series_map={"羽川ハスミ": "blue_archive"},
        )
        assert result["status"] == "needs_review"
        assert result["reason"] == SERIES_ONLY_REASON_PARENT_CONFLICT
        assert "fate_grand_order" in result["series"]
        assert "blue_archive" in result["parent_series"]

    def test_7_no_series_no_character_unidentified(self) -> None:
        """series / character 모두 없음 → needs_review, reason=series_unidentified."""
        result = resolve_series_only_destination(
            explicit_series=[],
            parent_series_map={},
        )
        assert result["status"] == "needs_review"
        assert result["reason"] == SERIES_ONLY_REASON_UNIDENTIFIED
        assert result["series"] == []
        assert result["parent_series"] == []

    # 추가 보강 — explicit series 가 parent_series 와 일치하면 conflict 가
    # 아니라 ready 로 분류된다.
    def test_explicit_matches_parent_no_conflict(self) -> None:
        result = resolve_series_only_destination(
            explicit_series=["blue_archive"],
            parent_series_map={"羽川ハスミ": "blue_archive"},
        )
        assert result["status"] == "ready"
        assert result["rule"] == SERIES_ONLY_RULE_SERIES_TAG
        assert result["series"] == ["blue_archive"]


# ---------------------------------------------------------------------------
# is_series_only_mode signature detection
# ---------------------------------------------------------------------------

class TestIsSeriesOnlyMode:
    def test_signature_match(self) -> None:
        cfg = {
            "enable_series_character":         False,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": False,
        }
        assert is_series_only_mode(cfg) is True

    def test_default_series_character_signature_does_not_match(self) -> None:
        cfg = {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": True,
        }
        assert is_series_only_mode(cfg) is False

    def test_partial_signature_does_not_match(self) -> None:
        # series_uncategorized 만 켜져 있고 series_character 가 켜져 있으면
        # 시리즈+캐릭터 모드 — series-only 가 아님.
        cfg = {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": False,
        }
        assert is_series_only_mode(cfg) is False


# ---------------------------------------------------------------------------
# Integration tests — build_classify_preview + series-only mode + DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "series_only.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    artwork_id: str | None = None,
    tags: list[str] | None = None,
    series: list[str] | None = None,
    character: list[str] | None = None,
    sync_status: str = "json_only",
    artist: str = "test_artist",
) -> None:
    if artwork_id is None:
        artwork_id = group_id[:12]
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, artist_name, "
        " downloaded_at, indexed_at, metadata_sync_status, "
        " tags_json, series_tags_json, character_tags_json) "
        "VALUES (?, 'pixiv', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            group_id, artwork_id, "test", artist, now, now, sync_status,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection, group_id: str, path: Path
) -> str:
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


def _series_only_config(classified_dir: Path) -> dict:
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


class TestSeriesOnlyIntegration:
    """build_classify_preview + series-only cfg 통합 동작."""

    def test_character_only_uses_inferred_parent_series(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """character 만 있고 parent_series 가 등록돼 있으면 destination 생성."""
        _seed_alias(db, "羽川ハスミ", "羽川ハスミ", "character", "Blue Archive")

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            tags=["羽川ハスミ"],
            series=[],
            character=["羽川ハスミ"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_config(classified))

        assert preview is not None
        dests = preview["destinations"]
        assert len(dests) >= 1
        assert any("Blue Archive" in d["dest_path"] for d in dests)
        assert any(d.get("series_only_rule") == SERIES_ONLY_RULE_PARENT_SERIES
                   for d in dests)

    def test_explicit_vs_parent_conflict_produces_no_destination(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """명시 series 가 character.parent_series 와 다르면 destination 없음."""
        _seed_alias(db, "Fate/Grand Order", "Fate/Grand Order", "series", "")
        _seed_alias(db, "羽川ハスミ", "羽川ハスミ", "character", "Blue Archive")

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            tags=["Fate/Grand Order", "羽川ハスミ"],
            series=["Fate/Grand Order"],
            character=["羽川ハスミ"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_config(classified))

        assert preview is not None
        # destinations 는 비거나, author_fallback 없이 시리즈/캐릭터 dest 도 없어야 한다.
        non_author = [
            d for d in preview["destinations"]
            if d.get("rule_type") not in ("author_fallback",)
        ]
        assert non_author == []
        ci = preview.get("classification_info") or {}
        assert ci.get("classification_reason") == SERIES_ONLY_REASON_PARENT_CONFLICT

    def test_no_series_no_character_marks_unidentified(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series / character 모두 없으면 series_unidentified 로 표시."""
        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(db, group_id=gid, tags=["foo"], series=[], character=[])
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_config(classified))

        assert preview is not None
        ci = preview.get("classification_info") or {}
        assert ci.get("classification_reason") == SERIES_ONLY_REASON_UNIDENTIFIED
