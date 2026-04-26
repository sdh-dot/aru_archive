"""
core/tag_candidate_generator.py 테스트.
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


def _insert_observation(conn, artwork_id, group_id, raw_tag, co_tags, translated_tag=None):
    import uuid
    from datetime import datetime, timezone
    conn.execute(
        """INSERT OR IGNORE INTO tag_observations
           (observation_id, source_site, artwork_id, group_id,
            raw_tag, translated_tag, co_tags_json, observed_at)
           VALUES (?, 'pixiv', ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            artwork_id,
            group_id,
            raw_tag,
            translated_tag,
            json.dumps(co_tags, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# calculate_candidate_confidence
# ---------------------------------------------------------------------------

def test_confidence_base():
    from core.tag_candidate_generator import calculate_candidate_confidence
    score = calculate_candidate_confidence(
        has_translated_tag=False,
        cooccurs_with_known_series=False,
        evidence_count=1,
        appears_in_multiple_series=False,
        is_blacklisted_general=False,
    )
    assert abs(score - 0.20) < 1e-9


def test_confidence_known_series():
    from core.tag_candidate_generator import calculate_candidate_confidence
    score = calculate_candidate_confidence(
        has_translated_tag=False,
        cooccurs_with_known_series=True,
        evidence_count=1,
        appears_in_multiple_series=False,
        is_blacklisted_general=False,
    )
    assert abs(score - 0.50) < 1e-9


def test_confidence_full_bonus():
    from core.tag_candidate_generator import calculate_candidate_confidence
    score = calculate_candidate_confidence(
        has_translated_tag=True,
        cooccurs_with_known_series=True,
        evidence_count=5,
        appears_in_multiple_series=False,
        is_blacklisted_general=False,
    )
    assert abs(score - 0.90) < 1e-9


def test_confidence_multiple_series_penalty():
    from core.tag_candidate_generator import calculate_candidate_confidence
    score = calculate_candidate_confidence(
        has_translated_tag=False,
        cooccurs_with_known_series=True,
        evidence_count=1,
        appears_in_multiple_series=True,
        is_blacklisted_general=False,
    )
    assert abs(score - 0.20) < 1e-9


def test_confidence_blacklist_penalty():
    """블랙리스트 태그는 -0.50 패널티를 받는다 (0.90 - 0.50 = 0.40)."""
    from core.tag_candidate_generator import calculate_candidate_confidence
    score = calculate_candidate_confidence(
        has_translated_tag=True,
        cooccurs_with_known_series=True,
        evidence_count=5,
        appears_in_multiple_series=False,
        is_blacklisted_general=True,
    )
    assert abs(score - 0.40) < 1e-9


def test_confidence_clamped_to_zero():
    from core.tag_candidate_generator import calculate_candidate_confidence
    score = calculate_candidate_confidence(
        has_translated_tag=False,
        cooccurs_with_known_series=False,
        evidence_count=1,
        appears_in_multiple_series=True,
        is_blacklisted_general=True,
    )
    assert score == 0.0


# ---------------------------------------------------------------------------
# generate_tag_candidates_for_group
# ---------------------------------------------------------------------------

def test_known_series_cooccur_becomes_character_candidate(conn):
    """기지 시리즈와 함께 등장하는 태그는 character 후보가 된다."""
    from core.tag_candidate_generator import generate_tag_candidates_for_group

    co_tags = ["ブルーアーカイブ", "新キャラ"]
    _insert_observation(conn, "art1", "g1", "新キャラ", co_tags)

    results = generate_tag_candidates_for_group(conn, "g1")
    assert any(r["raw_tag"] == "新キャラ" and r["suggested_type"] == "character" for r in results)


def test_blacklisted_tag_not_character_candidate(conn):
    """GENERAL_TAG_BLACKLIST 태그는 character 후보가 되지 않는다."""
    from core.tag_candidate_generator import generate_tag_candidates_for_group

    co_tags = ["ブルーアーカイブ", "1girl"]
    _insert_observation(conn, "art2", "g2", "1girl", co_tags)

    results = generate_tag_candidates_for_group(conn, "g2")
    char_candidates = [r for r in results if r["raw_tag"] == "1girl" and r["suggested_type"] == "character"]
    assert len(char_candidates) == 0


def test_translated_tag_increases_confidence(conn):
    """번역 태그가 있으면 번역 없는 경우보다 신뢰도가 높다."""
    from core.tag_candidate_generator import generate_tag_candidates_for_group

    co_tags = ["ブルーアーカイブ", "キャラA"]
    _insert_observation(conn, "art3", "g3", "キャラA", co_tags, translated_tag="Chara A")
    _insert_observation(conn, "art4", "g4", "キャラB", co_tags)

    results_a = generate_tag_candidates_for_group(conn, "g3")
    results_b = generate_tag_candidates_for_group(conn, "g4")

    score_a = next(r["confidence_score"] for r in results_a if r["raw_tag"] == "キャラA")
    score_b = next(r["confidence_score"] for r in results_b if r["raw_tag"] == "キャラB")
    assert score_a > score_b


def test_already_in_tag_aliases_skipped(conn):
    """tag_aliases에 이미 확정된 태그는 후보 생성에서 건너뛴다."""
    from core.tag_candidate_generator import generate_tag_candidates_for_group
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO tag_aliases (alias, canonical, tag_type, parent_series, created_at) "
        "VALUES ('確定済み', '確定済み', 'general', '', ?)",
        (now,),
    )
    conn.commit()

    co_tags = ["ブルーアーカイブ", "確定済み"]
    _insert_observation(conn, "art5", "g5", "確定済み", co_tags)

    results = generate_tag_candidates_for_group(conn, "g5")
    assert all(r["raw_tag"] != "確定済み" for r in results)


def test_evidence_count_3_increases_confidence(conn):
    """evidence_count >= 3이면 신뢰도 +0.20."""
    from core.tag_candidate_generator import generate_tag_candidates_from_observations

    co_tags = ["ブルーアーカイブ", "rare_char"]
    for art_id in ("a1", "a2", "a3"):
        _insert_observation(conn, art_id, f"g_{art_id}", "rare_char", co_tags)

    results = generate_tag_candidates_from_observations(conn)
    candidate = next((r for r in results if r["raw_tag"] == "rare_char"), None)
    assert candidate is not None
    # base(0.20) + series(0.30) + evidence>=3(0.20) = 0.70
    assert abs(candidate["confidence_score"] - 0.70) < 1e-9
