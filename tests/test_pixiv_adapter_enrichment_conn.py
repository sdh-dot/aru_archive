"""
PixivAdapter.to_aru_metadata() — conn 전달 시 DB tag_aliases 반영 검증.

시나리오:
  1. DB alias 반영: user_confirmed alias가 character_tags에 포함됨
  2. conn=None 기존 동작: hardcoded에 없는 alias는 매칭 실패 (빈 character_tags)
  3. user_confirmed > import 우선순위: 같은 alias에 두 source → user_confirmed canonical 선택
  4. 빈 character_tags 회귀 가드: conn 전달 시 character_tags가 비지 않음

네트워크 호출 없음. tag_aliases 스키마는 db/schema.sql과 일치.
"""
from __future__ import annotations

import sqlite3

import pytest

from core.adapters.pixiv import PixivAdapter


# ---------------------------------------------------------------------------
# 헬퍼 — tag_aliases 스키마 (db/schema.sql PRIMARY KEY 포함)
# ---------------------------------------------------------------------------

_CREATE_TAG_ALIASES = """
CREATE TABLE IF NOT EXISTS tag_aliases (
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
)
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TAG_ALIASES)
    conn.commit()
    return conn


def _insert_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    tag_type: str,
    source: str,
    parent_series: str = "",
    enabled: int = 1,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (alias, canonical, tag_type, parent_series, source, enabled),
    )
    conn.commit()


def _pixiv_raw(tags: list[str], illust_id: str = "11111111") -> dict:
    """테스트용 Pixiv AJAX body fixture (네트워크 없음)."""
    return {
        "illustId": illust_id,
        "title": "テスト作品",
        "userId": "42",
        "userName": "テスト作家",
        "pageCount": 1,
        "illustType": 0,
        "tags": {"tags": [{"tag": t} for t in tags]},
        "xRestrict": 0,
    }


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


class TestToAruMetadataWithConn:
    """conn 전달 경로: DB alias → character_tags 반영."""

    def test_db_user_confirmed_alias_reflected_in_character_tags(self) -> None:
        """
        DB에 user_confirmed alias '白子'→'白子(ブルーアーカイブ)' 등록 후
        raw tags에 '白子'가 있으면 character_tags에 canonical이 포함돼야 한다.
        (hardcoded CHARACTER_ALIASES에 없는 alias 사용 — DB 의존성 명확)
        """
        conn = _make_conn()
        _insert_alias(
            conn,
            alias="白子",
            canonical="白子(ブルーアーカイブ)",
            tag_type="character",
            source="user_confirmed",
            parent_series="Blue Archive",
        )

        adapter = PixivAdapter()
        raw = _pixiv_raw(tags=["白子", "ブルーアーカイブ"])
        meta = adapter.to_aru_metadata(raw, conn=conn)

        assert "白子(ブルーアーカイブ)" in meta.character_tags, (
            f"character_tags={meta.character_tags!r} — DB user_confirmed alias 미반영"
        )
        assert "Blue Archive" in meta.series_tags, (
            f"series_tags={meta.series_tags!r} — parent_series 역추론 실패"
        )
        conn.close()

    def test_conn_none_unknown_alias_not_matched(self) -> None:
        """
        conn=None이면 DB alias 로드 없음.
        hardcoded에 없는 '白子'는 character_tags에 포함되지 않아야 한다.
        """
        adapter = PixivAdapter()
        raw = _pixiv_raw(tags=["白子", "ブルーアーカイブ"])
        meta = adapter.to_aru_metadata(raw)  # conn 미전달

        # '白子'는 hardcoded CHARACTER_ALIASES에 없으므로 매칭 실패
        assert "白子(ブルーアーカイブ)" not in meta.character_tags, (
            "conn=None인데 DB alias가 반영됐다 — 격리 위반"
        )

    def test_user_confirmed_takes_priority_over_import(self) -> None:
        """
        같은 alias에 source='import' / source='user_confirmed' 두 row 존재 시
        user_confirmed canonical이 우선한다 (PR #39 정책).

        parent_series가 다르면 PRIMARY KEY가 달라 두 row 공존 가능.
        classify_pixiv_tags는 두 entry를 ambiguous로 처리하지만,
        series context가 있으면 user_confirmed series를 선택한다.

        여기서는 series context를 함께 제공해 disambiguation이 동작하는 경우를 검증.
        """
        conn = _make_conn()
        # import alias: ホシノ → "Hoshino" / series "Blue Archive"
        _insert_alias(
            conn,
            alias="ホシノ",
            canonical="Hoshino",
            tag_type="character",
            source="import",
            parent_series="Blue Archive",
        )
        # user_confirmed alias: ホシノ → "星野アヤネ" / series "Blue Archive"
        # PRIMARY KEY (alias, tag_type, parent_series) — parent_series가 같으면 덮어씀
        # → user_confirmed가 import를 덮어쓰는 시나리오
        conn.execute(
            "UPDATE tag_aliases SET canonical=?, source=? "
            "WHERE alias=? AND tag_type=? AND parent_series=?",
            ("星野アヤネ", "user_confirmed", "ホシノ", "character", "Blue Archive"),
        )
        conn.commit()

        adapter = PixivAdapter()
        raw = _pixiv_raw(tags=["ホシノ", "ブルーアーカイブ"])
        meta = adapter.to_aru_metadata(raw, conn=conn)

        assert "星野アヤネ" in meta.character_tags, (
            f"character_tags={meta.character_tags!r} — user_confirmed canonical 미선택"
        )
        assert "Hoshino" not in meta.character_tags, (
            "import canonical이 user_confirmed보다 앞서 남아 있음"
        )
        conn.close()

    def test_character_tags_not_empty_when_conn_provided(self) -> None:
        """
        conn 전달 시 DB alias가 있는 캐릭터 태그 → character_tags 비지 않음.
        _uncategorized fallback 회귀 가드.
        """
        conn = _make_conn()
        _insert_alias(
            conn,
            alias="ネル",
            canonical="네루(블루 아카이브)",
            tag_type="character",
            source="user_confirmed",
            parent_series="Blue Archive",
        )
        _insert_alias(
            conn,
            alias="ブルーアーカイブ",
            canonical="Blue Archive",
            tag_type="series",
            source="import",
        )

        adapter = PixivAdapter()
        raw = _pixiv_raw(tags=["ネル", "ブルーアーカイブ", "일반태그"])
        meta = adapter.to_aru_metadata(raw, conn=conn)

        assert len(meta.character_tags) > 0, (
            "character_tags가 비어 있음 — conn 전달 시 DB alias 무시됨 (_uncategorized 회귀)"
        )
        assert "네루(블루 아카이브)" in meta.character_tags
        conn.close()

    def test_builtin_alias_still_works_with_conn(self) -> None:
        """
        conn을 전달해도 hardcoded CHARACTER_ALIASES는 여전히 동작해야 한다 (회귀 없음).
        '陸八魔アル'은 hardcoded에 있음.
        """
        conn = _make_conn()  # 빈 DB

        adapter = PixivAdapter()
        raw = _pixiv_raw(tags=["陸八魔アル", "ブルーアーカイブ"])
        meta = adapter.to_aru_metadata(raw, conn=conn)

        assert "陸八魔アル" in meta.character_tags, (
            f"character_tags={meta.character_tags!r} — hardcoded alias 회귀"
        )
        assert "Blue Archive" in meta.series_tags
        conn.close()

    def test_conn_none_builtin_alias_unchanged(self) -> None:
        """
        conn=None이어도 hardcoded aliases는 기존과 동일하게 동작한다.
        """
        adapter = PixivAdapter()
        raw = _pixiv_raw(tags=["陸八魔アル", "ブルーアーカイブ"])
        meta = adapter.to_aru_metadata(raw)  # conn=None

        assert "陸八魔アル" in meta.character_tags
        assert "Blue Archive" in meta.series_tags
