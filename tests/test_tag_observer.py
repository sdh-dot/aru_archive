"""
core/tag_observer.py 테스트.
"""
from __future__ import annotations

import json
import pytest
from db.database import initialize_database


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def test_record_stores_per_tag_rows(conn):
    """tags 목록의 각 태그마다 행이 생성된다."""
    from core.tag_observer import record_tag_observations

    record_tag_observations(
        conn,
        source_site="pixiv",
        artwork_id="111",
        group_id="g1",
        tags=["tagA", "tagB", "tagC"],
    )
    conn.commit()

    rows = conn.execute(
        "SELECT raw_tag FROM tag_observations WHERE artwork_id = '111'"
    ).fetchall()
    assert {r["raw_tag"] for r in rows} == {"tagA", "tagB", "tagC"}


def test_record_translated_tag(conn):
    """translated_tags 매핑이 올바르게 저장된다."""
    from core.tag_observer import record_tag_observations

    record_tag_observations(
        conn,
        source_site="pixiv",
        artwork_id="222",
        group_id="g2",
        tags=["日本語タグ"],
        translated_tags={"日本語タグ": "Japanese Tag"},
    )
    conn.commit()

    row = conn.execute(
        "SELECT translated_tag FROM tag_observations WHERE raw_tag = '日本語タグ'"
    ).fetchone()
    assert row["translated_tag"] == "Japanese Tag"


def test_record_co_tags_json(conn):
    """co_tags_json에 전체 태그 목록이 저장된다."""
    from core.tag_observer import record_tag_observations

    tags = ["alpha", "beta", "gamma"]
    record_tag_observations(
        conn,
        source_site="pixiv",
        artwork_id="333",
        group_id="g3",
        tags=tags,
    )
    conn.commit()

    row = conn.execute(
        "SELECT co_tags_json FROM tag_observations WHERE raw_tag = 'alpha'"
    ).fetchone()
    assert json.loads(row["co_tags_json"]) == tags


def test_record_unique_dedup(conn):
    """동일 (source_site, artwork_id, raw_tag) 중복 호출 시 행이 하나만 생성된다."""
    from core.tag_observer import record_tag_observations

    record_tag_observations(
        conn, source_site="pixiv", artwork_id="444", group_id="g4", tags=["dup"]
    )
    record_tag_observations(
        conn, source_site="pixiv", artwork_id="444", group_id="g4", tags=["dup"]
    )
    conn.commit()

    count = conn.execute(
        "SELECT COUNT(*) FROM tag_observations "
        "WHERE artwork_id = '444' AND raw_tag = 'dup'"
    ).fetchone()[0]
    assert count == 1


def test_record_artist_id(conn):
    """artist_id가 올바르게 저장된다."""
    from core.tag_observer import record_tag_observations

    record_tag_observations(
        conn,
        source_site="pixiv",
        artwork_id="555",
        group_id="g5",
        tags=["x"],
        artist_id="artist123",
    )
    conn.commit()

    row = conn.execute(
        "SELECT artist_id FROM tag_observations WHERE raw_tag = 'x'"
    ).fetchone()
    assert row["artist_id"] == "artist123"
