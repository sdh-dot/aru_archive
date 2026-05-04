"""
PR #126 — Pixiv raw tag 보존 테스트.

검증 항목:
  1. PixivAdapter.to_aru_metadata() — raw_tags에 원본 태그 목록 보존
  2. raw_tags에는 분류된(series/character) 태그도 포함
  3. AruMetadata.to_dict() — raw_tags 미포함 (UserComment JSON 불변)
  4. AruMetadata.from_dict() — raw_tags 없는 dict에서도 정상 복원
  5. _update_group_from_meta() — raw_tags_json을 DB에 저장
  6. _update_group_from_meta() — raw_tags가 빈 리스트이면 NULL 저장
  7. DB round-trip — raw_tags_json 쓰고 읽기
  8. detail_view._update_tags_section() — raw_tags_json 우선 표시
  9. detail_view._update_tags_section() — raw_tags_json 없으면 classified tags fallback
  10. raw_tags는 classify_pixiv_tags 결과에 의존하지 않음 (분류 실패해도 보존)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.adapters.pixiv import PixivAdapter
from core.models import AruMetadata


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _pixiv_raw(
    tags: list[str],
    illust_id: str = "12345678",
    title: str = "テスト",
    user_id: str = "99",
    user_name: str = "Artist",
) -> dict:
    return {
        "illustId": illust_id,
        "title": title,
        "userId": user_id,
        "userName": user_name,
        "pageCount": 1,
        "illustType": 0,
        "tags": {"tags": [{"tag": t} for t in tags]},
        "xRestrict": 0,
    }


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS artwork_groups (
    group_id              TEXT PRIMARY KEY,
    source_site           TEXT NOT NULL DEFAULT 'pixiv',
    artwork_id            TEXT NOT NULL,
    artwork_url           TEXT,
    artwork_title         TEXT,
    artist_id             TEXT,
    artist_name           TEXT,
    artist_url            TEXT,
    artwork_kind          TEXT NOT NULL DEFAULT 'single_image',
    total_pages           INTEGER NOT NULL DEFAULT 1,
    cover_file_id         TEXT,
    tags_json             TEXT,
    character_tags_json   TEXT,
    series_tags_json      TEXT,
    raw_tags_json         TEXT,
    downloaded_at         TEXT NOT NULL DEFAULT '',
    indexed_at            TEXT NOT NULL DEFAULT '',
    updated_at            TEXT,
    status                TEXT NOT NULL DEFAULT 'inbox',
    metadata_sync_status  TEXT NOT NULL DEFAULT 'pending',
    schema_version        TEXT NOT NULL DEFAULT '1.0',
    UNIQUE(artwork_id, source_site)
);
CREATE TABLE IF NOT EXISTS tags (
    group_id TEXT NOT NULL,
    tag      TEXT NOT NULL,
    tag_type TEXT NOT NULL DEFAULT 'general',
    canonical TEXT,
    PRIMARY KEY (group_id, tag, tag_type)
);
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLES)
    conn.commit()
    return conn


def _insert_group(conn: sqlite3.Connection, group_id: str, artwork_id: str = "12345678") -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO artwork_groups (group_id, artwork_id, downloaded_at, indexed_at) VALUES (?, ?, ?, ?)",
        (group_id, artwork_id, now, now),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Test 1: to_aru_metadata() preserves raw_tags
# ---------------------------------------------------------------------------

class TestToAruMetadataRawTags:
    def test_1_raw_tags_preserved_in_meta(self) -> None:
        """to_aru_metadata() 반환 AruMetadata에 원본 Pixiv 태그가 raw_tags에 저장된다."""
        input_tags = ["ブルーアーカイブ", "アリス(ブルーアーカイブ)", "일반태그", "R-18"]
        raw = _pixiv_raw(input_tags)
        adapter = PixivAdapter()
        meta = adapter.to_aru_metadata(raw)

        assert meta.raw_tags == input_tags

    def test_2_raw_tags_includes_classified_tags(self) -> None:
        """분류된 series/character 태그도 raw_tags에 남는다 (흡수 없음)."""
        input_tags = ["ブルーアーカイブ", "アリス(ブルーアーカイブ)", "일반태그"]
        raw = _pixiv_raw(input_tags)
        adapter = PixivAdapter()
        meta = adapter.to_aru_metadata(raw)

        # raw_tags는 모든 입력 태그를 포함해야 함
        assert set(meta.raw_tags) == set(input_tags)

    def test_3_to_dict_excludes_raw_tags(self) -> None:
        """to_dict()에는 raw_tags가 없어야 한다 — UserComment JSON 불변 정책."""
        meta = AruMetadata(
            tags=["일반"],
            series_tags=["시리즈"],
            character_tags=["캐릭터"],
            raw_tags=["시리즈", "캐릭터", "일반", "원본추가태그"],
        )
        d = meta.to_dict()
        assert "raw_tags" not in d

    def test_4_from_dict_no_raw_tags_field(self) -> None:
        """raw_tags 키가 없는 dict에서 from_dict()가 정상 복원된다 (하위 호환)."""
        d = {
            "schema_version": "1.0",
            "source_site": "pixiv",
            "artwork_id": "111",
            "tags": ["tag1"],
            "series_tags": [],
            "character_tags": [],
        }
        meta = AruMetadata.from_dict(d)
        assert meta.raw_tags == []
        assert meta.tags == ["tag1"]

    def test_10_raw_tags_independent_of_classification(self) -> None:
        """classify_pixiv_tags가 모두 general로 분류해도 raw_tags는 원본 보존."""
        input_tags = ["알수없는태그A", "알수없는태그B", "알수없는태그C"]
        raw = _pixiv_raw(input_tags)
        adapter = PixivAdapter()
        meta = adapter.to_aru_metadata(raw)

        # 분류 결과와 무관하게 raw_tags는 원본 유지
        assert meta.raw_tags == input_tags


# ---------------------------------------------------------------------------
# Test 5-7: DB 저장/로드
# ---------------------------------------------------------------------------

class TestRawTagsDBStorage:
    def test_5_update_group_stores_raw_tags_json(self) -> None:
        """_update_group_from_meta()가 raw_tags_json을 DB에 저장한다."""
        from core.metadata_enricher import _update_group_from_meta

        conn = _make_conn()
        gid = "aaaabbbb-0001-0001-0001-000000000001"
        _insert_group(conn, gid)

        meta = AruMetadata(
            artwork_title="테스트",
            artist_id="99",
            artist_name="Artist",
            artist_url="https://www.pixiv.net/users/99",
            tags=["일반"],
            series_tags=[],
            character_tags=[],
            raw_tags=["시리즈원본", "일반", "캐릭터원본"],
        )
        now = datetime.now(timezone.utc).isoformat()
        _update_group_from_meta(conn, gid, meta, "json_only", now)

        row = conn.execute(
            "SELECT raw_tags_json FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row is not None
        stored = json.loads(row["raw_tags_json"])
        assert stored == ["시리즈원본", "일반", "캐릭터원본"]

    def test_6_empty_raw_tags_stored_as_null(self) -> None:
        """raw_tags가 빈 리스트이면 raw_tags_json은 NULL로 저장된다."""
        from core.metadata_enricher import _update_group_from_meta

        conn = _make_conn()
        gid = "aaaabbbb-0001-0001-0001-000000000002"
        _insert_group(conn, gid)

        meta = AruMetadata(
            artwork_title="테스트",
            artist_id="99",
            artist_name="Artist",
            artist_url="https://www.pixiv.net/users/99",
            tags=["일반"],
            series_tags=[],
            character_tags=[],
            raw_tags=[],
        )
        now = datetime.now(timezone.utc).isoformat()
        _update_group_from_meta(conn, gid, meta, "json_only", now)

        row = conn.execute(
            "SELECT raw_tags_json FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        assert row["raw_tags_json"] is None

    def test_7_raw_tags_db_round_trip(self) -> None:
        """raw_tags_json 쓰고 읽기 — JSON 직렬화/역직렬화 무결성."""
        from core.metadata_enricher import _update_group_from_meta

        conn = _make_conn()
        gid = "aaaabbbb-0001-0001-0001-000000000003"
        _insert_group(conn, gid)

        original_tags = ["ブルーアーカイブ", "アリス(ブルーアーカイブ)", "R-18", "일반태그"]
        meta = AruMetadata(
            artwork_title="라운드트립 테스트",
            artist_id="1",
            artist_name="Tester",
            artist_url="https://www.pixiv.net/users/1",
            tags=["일반태그"],
            series_tags=[],
            character_tags=[],
            raw_tags=original_tags,
        )
        now = datetime.now(timezone.utc).isoformat()
        _update_group_from_meta(conn, gid, meta, "json_only", now)

        row = conn.execute(
            "SELECT raw_tags_json FROM artwork_groups WHERE group_id = ?", (gid,)
        ).fetchone()
        loaded = json.loads(row["raw_tags_json"])
        assert loaded == original_tags


# ---------------------------------------------------------------------------
# Test 8-9: detail_view._update_tags_section()
# ---------------------------------------------------------------------------

class TestDetailViewTagsSection:
    def _make_view(self):
        """_update_tags_section에 필요한 최소 mock DetailView."""
        from unittest.mock import MagicMock

        view = MagicMock()
        # 실제 메서드를 바인딩
        from app.views.detail_view import DetailView
        view._tags_edit = MagicMock()
        # 언바운드 메서드를 직접 호출
        view._update_tags_section = lambda group: DetailView._update_tags_section(view, group)
        return view

    def test_8_raw_tags_json_shown_when_present(self) -> None:
        """raw_tags_json이 있으면 classified tags 대신 원본 태그를 표시한다."""
        view = self._make_view()
        raw_original = ["ブルーアーカイブ", "アリス(ブルーアーカイブ)", "일반태그"]
        group = {
            "raw_tags_json": json.dumps(raw_original),
            "tags_json": json.dumps(["일반태그"]),
            "character_tags_json": json.dumps(["아리스"]),
            "series_tags_json": json.dumps(["블루 아카이브"]),
        }
        view._update_tags_section(group)
        call_args = view._tags_edit.setPlainText.call_args[0][0]
        # raw_tags_json의 원본 태그들이 표시되어야 함
        assert "ブルーアーカイブ" in call_args
        assert "アリス(ブルーアーカイブ)" in call_args

    def test_9_fallback_to_classified_when_no_raw_tags_json(self) -> None:
        """raw_tags_json이 없으면 tags_json / character_tags_json / series_tags_json으로 fallback."""
        view = self._make_view()
        group = {
            "raw_tags_json": None,
            "tags_json": json.dumps(["일반태그"]),
            "character_tags_json": json.dumps(["아리스"]),
            "series_tags_json": json.dumps(["블루 아카이브"]),
        }
        view._update_tags_section(group)
        call_args = view._tags_edit.setPlainText.call_args[0][0]
        assert "일반태그" in call_args
        assert "아리스" in call_args
        assert "블루 아카이브" in call_args


# ---------------------------------------------------------------------------
# Test 11-18: Pixiv 메타데이터 가져오기 선택 정책
# ---------------------------------------------------------------------------

def _make_main_window_mock(selected_ids: list, current_group_id=None):
    """_on_pixiv_meta_selected / _on_pixiv_meta_from_detail 테스트용 minimal mock."""
    from unittest.mock import MagicMock, patch
    from app.main_window import MainWindow

    mw = MagicMock(spec=MainWindow)
    mw._gallery = MagicMock()
    mw._gallery.get_selected_group_ids.return_value = list(selected_ids)
    mw._gallery.get_selected_group_id.return_value = selected_ids[0] if selected_ids else None
    mw._detail = MagicMock()
    mw._detail._current_group_id = current_group_id
    mw._log = MagicMock()
    mw._on_pixiv_meta = MagicMock()
    mw._refresh_pixiv_for_groups = MagicMock()
    return mw


class TestPixivMetaSelectionPolicy:
    """_on_pixiv_meta_selected / _on_pixiv_meta_from_detail 선택 정책 검증."""

    # ---- Top 메뉴 (_on_pixiv_meta_selected) ----

    def test_11_top_menu_multi_select_calls_batch(self) -> None:
        """Top 메뉴: gallery에 2개 이상 선택 → _refresh_pixiv_for_groups() 호출."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock(["gid-A", "gid-B", "gid-C"])
        MainWindow._on_pixiv_meta_selected(mw)
        mw._refresh_pixiv_for_groups.assert_called_once_with(["gid-A", "gid-B", "gid-C"])
        mw._on_pixiv_meta.assert_not_called()

    def test_12_top_menu_single_select_calls_single(self) -> None:
        """Top 메뉴: gallery에 1개 선택 → _on_pixiv_meta() 단건 호출."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock(["gid-A"])
        MainWindow._on_pixiv_meta_selected(mw)
        mw._on_pixiv_meta.assert_called_once_with("gid-A")
        mw._refresh_pixiv_for_groups.assert_not_called()

    def test_13_top_menu_no_select_falls_back_to_current(self) -> None:
        """Top 메뉴: gallery 선택 없음 + current group 있음 → current로 단건 호출."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock([], current_group_id="current-gid")
        MainWindow._on_pixiv_meta_selected(mw)
        mw._on_pixiv_meta.assert_called_once_with("current-gid")
        mw._refresh_pixiv_for_groups.assert_not_called()

    def test_14_top_menu_no_select_no_current_warns(self) -> None:
        """Top 메뉴: gallery 선택 없음 + current 없음 → 경고 로그, 처리 없음."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock([], current_group_id=None)
        MainWindow._on_pixiv_meta_selected(mw)
        mw._on_pixiv_meta.assert_not_called()
        mw._refresh_pixiv_for_groups.assert_not_called()
        mw._log.append.assert_called()

    # ---- Detail panel (_on_pixiv_meta_from_detail) ----

    def test_15_detail_panel_multi_select_calls_batch(self) -> None:
        """Detail panel: gallery에 2개 이상 선택 → _refresh_pixiv_for_groups() 호출."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock(["gid-A", "gid-B"])
        MainWindow._on_pixiv_meta_from_detail(mw, "current-gid")
        mw._refresh_pixiv_for_groups.assert_called_once_with(["gid-A", "gid-B"])
        mw._on_pixiv_meta.assert_not_called()

    def test_16_detail_panel_single_select_calls_single(self) -> None:
        """Detail panel: gallery 1개 선택 → _on_pixiv_meta() 단건 호출 (current 무시)."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock(["gid-A"])
        MainWindow._on_pixiv_meta_from_detail(mw, "current-gid")
        mw._on_pixiv_meta.assert_called_once_with("gid-A")
        mw._refresh_pixiv_for_groups.assert_not_called()

    def test_17_detail_panel_no_select_uses_fallback(self) -> None:
        """Detail panel: gallery 선택 없음 → fallback_group_id(current)로 단건 호출."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock([], current_group_id=None)
        MainWindow._on_pixiv_meta_from_detail(mw, "current-gid")
        mw._on_pixiv_meta.assert_called_once_with("current-gid")
        mw._refresh_pixiv_for_groups.assert_not_called()

    def test_18_detail_panel_no_select_no_fallback_warns(self) -> None:
        """Detail panel: gallery 선택 없음 + fallback 없음 → 경고 로그, 처리 없음."""
        from app.main_window import MainWindow
        mw = _make_main_window_mock([], current_group_id=None)
        MainWindow._on_pixiv_meta_from_detail(mw, "")
        mw._on_pixiv_meta.assert_not_called()
        mw._refresh_pixiv_for_groups.assert_not_called()
        mw._log.append.assert_called()
