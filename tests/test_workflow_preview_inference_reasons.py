"""Step 7 미리보기에 character→series inference reason 표시 회귀 테스트.

PR 1 의 ``core.classification_inference.infer_character_series_candidates`` 결과를
미리보기 ``사유·경고`` 컬럼에 표시하는 흐름을 lock 한다.

핵심 invariant:
- 분류 결과 / destination path / classification_info 는 절대 변경되지 않음
- DB write 가 발생하지 않음
- helper 가 raw_tags 가 없거나 후보가 없으면 빈 list 를 반환 (silent skip)
- top 3 후보만 표시 + "외 N건" 으로 요약
- ambiguous parent_series 가 있으면 "자동 적용 보류" 안내
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc).isoformat()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE tag_aliases (
            alias            TEXT NOT NULL,
            canonical        TEXT NOT NULL,
            tag_type         TEXT NOT NULL DEFAULT 'general',
            parent_series    TEXT NOT NULL DEFAULT '',
            media_type       TEXT,
            source           TEXT,
            confidence_score REAL,
            enabled          INTEGER NOT NULL DEFAULT 1,
            created_by       TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT,
            PRIMARY KEY (alias, tag_type, parent_series)
        );
        CREATE TABLE tag_localizations (
            localization_id TEXT PRIMARY KEY,
            canonical       TEXT NOT NULL,
            tag_type        TEXT NOT NULL,
            parent_series   TEXT NOT NULL DEFAULT '',
            locale          TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            sort_name       TEXT,
            source          TEXT,
            enabled         INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT,
            UNIQUE(canonical, tag_type, parent_series, locale)
        );
        CREATE TABLE artwork_groups (
            group_id   TEXT PRIMARY KEY,
            tags_json  TEXT
        );
        """
    )
    c.commit()
    yield c
    c.close()


def _add_alias(c, alias, canonical, parent_series, *,
               tag_type="character", source="built_in_pack:test"):
    c.execute(
        "INSERT INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        (alias, canonical, tag_type, parent_series, source, _NOW),
    )
    c.commit()


def _add_loc(c, canonical, display_name, locale, parent_series, *,
             tag_type="character", source="built_in_pack:test"):
    c.execute(
        "INSERT INTO tag_localizations "
        "(localization_id, canonical, tag_type, parent_series, locale, display_name, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (str(uuid.uuid4()), canonical, tag_type, parent_series, locale,
         display_name, source, _NOW),
    )
    c.commit()


def _add_group(c, group_id, raw_tags):
    c.execute(
        "INSERT INTO artwork_groups (group_id, tags_json) VALUES (?, ?)",
        (group_id, json.dumps(raw_tags, ensure_ascii=False)),
    )
    c.commit()


# ---------------------------------------------------------------------------
# _summarize_inference_for_preview
# ---------------------------------------------------------------------------

def _import_helpers():
    # Qt 가 없으면 import 자체가 실패하지 않도록 (helper 만 사용)
    pytest.importorskip("PyQt6", reason="PyQt6 필요")
    from app.views.workflow_wizard_view import (  # type: ignore
        _augment_previews_with_inference_reasons,
        _format_inference_reason,
        _summarize_inference_for_preview,
    )
    return (
        _summarize_inference_for_preview,
        _augment_previews_with_inference_reasons,
        _format_inference_reason,
    )


class TestSummarize:
    def test_empty_raw_tags_returns_empty(self, conn):
        summarize, _, _ = _import_helpers()
        assert summarize(conn, []) == []
        assert summarize(conn, None) == []

    def test_no_candidates_returns_empty(self, conn):
        summarize, _, _ = _import_helpers()
        assert summarize(conn, ["totally_unknown_tag_xyz"]) == []

    def test_high_confidence_character_to_series(self, conn):
        summarize, _, _ = _import_helpers()
        _add_alias(conn, "陸八魔アル", "陸八魔アル", "Blue Archive")
        reasons = summarize(conn, ["陸八魔アル"])
        assert len(reasons) >= 1
        first = reasons[0]
        assert first.startswith("[추론] 캐릭터 ")
        assert "陸八魔アル" in first
        assert "Blue Archive" in first
        assert "high" in first

    def test_localized_match_includes_locale(self, conn):
        summarize, _, _ = _import_helpers()
        _add_loc(conn, "陸八魔アル", "리쿠하치마 아루", "ko", "Blue Archive")
        reasons = summarize(conn, ["리쿠하치마 아루"])
        assert reasons
        joined = " | ".join(reasons)
        assert "ko localized" in joined

    def test_long_vowel_variant_marked_in_reason(self, conn):
        summarize, _, _ = _import_helpers()
        # alias 에는 ー 없는 형태, 입력은 끝에 ー 가 붙음
        _add_alias(conn, "ブル", "Blue Archive", "Blue Archive", tag_type="series")
        # series 후보는 표시 대상 아님 → character alias 도 추가
        _add_alias(conn, "ハチマ", "陸八魔アル", "Blue Archive")
        reasons = summarize(conn, ["ハチマー"])
        # trailing-long-vowel-removed variant 매칭이 character 후보에 들어가야 함
        assert reasons
        assert any("장음부호 variant" in r for r in reasons)

    def test_top_three_plus_extra_count(self, conn):
        summarize, _, _ = _import_helpers()
        # 4개 character 등록 → 모두 같은 시리즈
        for alias, canon in [
            ("CharA", "CanonA"),
            ("CharB", "CanonB"),
            ("CharC", "CanonC"),
            ("CharD", "CanonD"),
        ]:
            _add_alias(conn, alias, canon, "Blue Archive")
        reasons = summarize(conn, ["CharA", "CharB", "CharC", "CharD"])
        # 상위 3개 + 외 N건
        char_lines = [r for r in reasons if r.startswith("[추론] 캐릭터")]
        extra_lines = [r for r in reasons if r.startswith("[추론] 외 ")]
        assert len(char_lines) == 3
        assert len(extra_lines) == 1
        assert "외 1건" in extra_lines[0]

    def test_ambiguous_parent_series_warning(self, conn):
        summarize, _, _ = _import_helpers()
        _add_alias(conn, "Aru_in_X", "Aru", "Series X")
        _add_alias(conn, "Aru_in_Y", "Aru", "Series Y")
        reasons = summarize(conn, ["Aru_in_X", "Aru_in_Y"])
        assert reasons
        assert any("자동 적용 보류" in r for r in reasons)

    def test_character_without_parent_series_falls_back_to_notice(self, conn):
        summarize, _, _ = _import_helpers()
        # parent_series 가 빈 문자열인 character 후보만 있을 때.
        _add_alias(conn, "OrphanChar", "OrphanCanon", "")
        reasons = summarize(conn, ["OrphanChar"])
        # 보조 안내 라인이 있어야 한다.
        assert any("parent_series 없음" in r for r in reasons)

    def test_low_confidence_candidates_not_shown(self, conn):
        summarize, _, _ = _import_helpers()
        # source = unknown → low confidence
        _add_alias(conn, "OddTag", "陸八魔アル", "Blue Archive",
                   source="some_unknown_source")
        reasons = summarize(conn, ["OddTag"])
        # low 는 표시 대상에서 제외 (parent_series 가 있어도)
        char_lines = [r for r in reasons if r.startswith("[추론] 캐릭터")]
        assert char_lines == []

    def test_dedupe_same_raw_and_parent(self, conn):
        summarize, _, _ = _import_helpers()
        # 같은 (raw, parent_series) 가 alias + localization 양쪽으로 매칭돼도
        # reason 은 1번만 표시.
        _add_alias(conn, "陸八魔アル", "陸八魔アル", "Blue Archive")
        _add_loc(conn, "陸八魔アル", "陸八魔アル", "ja", "Blue Archive")
        reasons = summarize(conn, ["陸八魔アル"])
        char_lines = [r for r in reasons if "陸八魔アル → Blue Archive" in r]
        assert len(char_lines) == 1


# ---------------------------------------------------------------------------
# _augment_previews_with_inference_reasons — read-only invariants
# ---------------------------------------------------------------------------

class TestAugmentInPlace:
    def test_adds_inference_reasons_field(self, conn):
        _, augment, _ = _import_helpers()
        gid = "g1"
        _add_alias(conn, "陸八魔アル", "陸八魔アル", "Blue Archive")
        _add_group(conn, gid, ["陸八魔アル"])
        previews = [{"group_id": gid, "destinations": []}]
        augment(conn, previews)
        assert "inference_reasons" in previews[0]
        assert previews[0]["inference_reasons"]

    def test_does_not_modify_destinations(self, conn):
        _, augment, _ = _import_helpers()
        gid = "g1"
        _add_alias(conn, "陸八魔アル", "陸八魔アル", "Blue Archive")
        _add_group(conn, gid, ["陸八魔アル"])
        original_dest = {
            "rule_type": "series_character",
            "dest_path": "/x/y/z.jpg",
            "will_copy": True,
            "conflict": None,
            "used_fallback": False,
        }
        previews = [{
            "group_id": gid,
            "source_path": "/inbox/a.jpg",
            "destinations": [dict(original_dest)],
            "classification_info": None,
        }]
        augment(conn, previews)
        # destination 객체는 그대로
        assert previews[0]["destinations"][0] == original_dest
        assert previews[0]["classification_info"] is None

    def test_no_db_writes(self, conn):
        _, augment, _ = _import_helpers()
        gid = "g1"
        _add_alias(conn, "陸八魔アル", "陸八魔アル", "Blue Archive")
        _add_group(conn, gid, ["陸八魔アル"])
        before_aliases = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        before_groups = conn.execute("SELECT COUNT(*) FROM artwork_groups").fetchone()[0]
        augment(conn, [{"group_id": gid, "destinations": []}])
        after_aliases = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
        after_groups = conn.execute("SELECT COUNT(*) FROM artwork_groups").fetchone()[0]
        assert before_aliases == after_aliases
        assert before_groups == after_groups

    def test_empty_previews_safe(self, conn):
        _, augment, _ = _import_helpers()
        # 예외 없이 통과
        augment(conn, [])
        augment(conn, None)

    def test_missing_group_row_is_silent(self, conn):
        _, augment, _ = _import_helpers()
        previews = [{"group_id": "no-such-id", "destinations": []}]
        augment(conn, previews)
        assert previews[0]["inference_reasons"] == []

    def test_existing_field_not_overwritten(self, conn):
        _, augment, _ = _import_helpers()
        gid = "g1"
        _add_alias(conn, "陸八魔アル", "陸八魔アル", "Blue Archive")
        _add_group(conn, gid, ["陸八魔アル"])
        previews = [{
            "group_id": gid,
            "destinations": [],
            "inference_reasons": ["pre-existing"],
        }]
        augment(conn, previews)
        assert previews[0]["inference_reasons"] == ["pre-existing"]


# ---------------------------------------------------------------------------
# Step 7 UI integration — warn column 4 contains reason
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6", reason="PyQt6 필요")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_step7(tmp_path):
    from app.views.workflow_wizard_view import _Step7Preview
    from db.database import initialize_database

    db_path = str(tmp_path / "aru.db")
    init = initialize_database(db_path)
    init.close()

    config = {
        "classified_dir": str(tmp_path / "Classified"),
        "classification": {"folder_locale": "ko"},
    }

    class _MockWizard:
        _config = config

        def _conn_factory(self):
            return initialize_database(db_path)

        def _db_path(self):
            return db_path

    return _Step7Preview(_MockWizard())


def _preview_with_inference(reasons):
    return {
        "group_id": "gx",
        "source_path": "/inbox/art.jpg",
        "artwork_title": "Test",
        "fallback_tags": [],
        "classification_info": None,
        "inference_reasons": list(reasons),
        "destinations": [
            {
                "will_copy": True,
                "rule_type": "series_character",
                "dest_path": "/classified/Blue Archive/Aru/art.jpg",
                "conflict": None,
                "used_fallback": False,
            }
        ],
    }


class TestStep7WarnColumnIncludesInference:
    def test_warn_column_appends_inference_reason(self, qapp, tmp_path):
        step = _make_step7(tmp_path)
        step.show()
        reason = "[추론] 캐릭터 陸八魔アル → Blue Archive 후보 (high, built_in_pack:test)"
        step._populate_preview_table([_preview_with_inference([reason])])
        assert step._preview_table.item(0, 4).text() == reason

    def test_warn_column_combines_existing_and_inference(self, qapp, tmp_path):
        step = _make_step7(tmp_path)
        step.show()
        preview = _preview_with_inference(["[추론] 외 2건"])
        preview["destinations"][0]["used_fallback"] = True
        step._populate_preview_table([preview])
        text = step._preview_table.item(0, 4).text()
        assert "fallback" in text
        assert "[추론] 외 2건" in text

    def test_no_inference_reasons_field_still_works(self, qapp, tmp_path):
        # backward-compat: 필드 부재 시 기존 동작 유지.
        step = _make_step7(tmp_path)
        step.show()
        preview = _preview_with_inference([])
        del preview["inference_reasons"]
        step._populate_preview_table([preview])
        assert step._preview_table.item(0, 4) is not None
        # 기존 warn 정보가 없으면 빈 문자열.
        assert step._preview_table.item(0, 4).text() == ""

    def test_destination_path_column_unchanged_by_inference(self, qapp, tmp_path):
        step = _make_step7(tmp_path)
        step.show()
        dest = "/classified/Blue Archive/Aru/art.jpg"
        preview = _preview_with_inference(["[추론] anything"])
        preview["destinations"][0]["dest_path"] = dest
        step._populate_preview_table([preview])
        assert step._preview_table.item(0, 5).text() == dest

    def test_will_copy_unchanged_by_inference(self, qapp, tmp_path):
        step = _make_step7(tmp_path)
        step.show()
        preview = _preview_with_inference(["[추론] anything"])
        preview["destinations"][0]["will_copy"] = False
        step._populate_preview_table([preview])
        # 추론 reason 유무와 무관하게 will_copy=False → "제외"
        assert step._preview_table.item(0, 2).text() == "제외"
