from __future__ import annotations

from pathlib import Path

from core.classification_inference import infer_character_series_candidates
from core.tag_candidate_generator import generate_tag_candidates_for_group
from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database


ROOT = Path(__file__).resolve().parents[1]
TRICKCAL_PACK_PATH = ROOT / "resources" / "tag_packs" / "trickcal_revive.json"


def _insert_observation(conn, artwork_id: str, group_id: str, raw_tag: str, co_tags: list[str]) -> None:
    import json
    import uuid
    from datetime import datetime, timezone

    conn.execute(
        """INSERT OR IGNORE INTO tag_observations
           (observation_id, source_site, artwork_id, group_id,
            raw_tag, translated_tag, co_tags_json, observed_at)
           VALUES (?, 'pixiv', ?, ?, ?, NULL, ?, ?)""",
        (
            str(uuid.uuid4()),
            artwork_id,
            group_id,
            raw_tag,
            json.dumps(co_tags, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def _seed_trickcal_conn(tmp_path) -> object:
    conn = initialize_database(str(tmp_path / "trickcal-pass-1.db"))
    seed_tag_pack(conn, load_tag_pack(TRICKCAL_PACK_PATH))
    return conn


def test_hold_trickcal_pending_english_alias_is_not_seeded(tmp_path) -> None:
    conn = _seed_trickcal_conn(tmp_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM tag_aliases WHERE alias = ? AND tag_type = 'character'",
            ("Haley",),
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_trickcal_single_name_hold_alias_does_not_resolve_without_seed(tmp_path) -> None:
    conn = _seed_trickcal_conn(tmp_path)
    try:
        results = infer_character_series_candidates(conn, ["Haley"])
        assert all(r.tag_type != "character" for r in results)
    finally:
        conn.close()


def test_general_tag_is_not_auto_approved_as_character_candidate(tmp_path) -> None:
    conn = initialize_database(str(tmp_path / "candidate-pass-1.db"))
    try:
        _insert_observation(
            conn,
            artwork_id="art-1",
            group_id="group-1",
            raw_tag="イラスト",
            co_tags=["ブルーアーカイブ", "イラスト"],
        )
        results = generate_tag_candidates_for_group(conn, "group-1")
        assert any(r["raw_tag"] == "イラスト" for r in results)
        assert all(
            not (r["raw_tag"] == "イラスト" and r["suggested_type"] == "character")
            for r in results
        )
    finally:
        conn.close()
