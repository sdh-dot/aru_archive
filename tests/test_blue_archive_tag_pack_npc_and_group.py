"""Blue Archive tag pack — NPC 캐릭터 + group 정규화 회귀 테스트 (PR #121).

검증 contract:
- 扇喜アオイ NPC 캐릭터가 Blue Archive 에 seed 되어 ja/ko/en alias 모두로 탐지된다.
- 단일 이름 alias (アオイ / 아오이 / Aoi) 로는 탐지되지 않는다 — parent_series 오탐 방지.
- 흥신소68 / 便利屋68 / Problem Solver 68 group 이 seed 되어 모두 동일 canonical 로 탐지된다.
- group.parent_series 가 PR #120 series-only resolver 의 parent_series_map 에 진입한다.
- explicit series 와 character.parent_series 가 충돌하면 PR #120 needs_review 로 차단된다.
- metadata pipeline / DB metadata status 의미 / classified_copy 정책은 변경되지 않는다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.classifier import (
    SERIES_ONLY_REASON_PARENT_CONFLICT,
    SERIES_ONLY_RULE_PARENT_SERIES,
    _resolve_series_only_inputs,
    build_classify_preview,
    resolve_series_only_destination,
)


PACK_PATH = (
    Path(__file__).parent.parent / "resources" / "tag_packs" / "blue_archive.json"
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pack() -> dict:
    from core.tag_pack_loader import load_tag_pack
    return load_tag_pack(PACK_PATH)


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    from db.database import initialize_database
    from core.tag_pack_loader import load_tag_pack, seed_tag_pack
    db_path = str(tmp_path / "pr121.db")
    c = initialize_database(db_path)
    seed_tag_pack(c, load_tag_pack(PACK_PATH))
    yield c
    c.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify(raw_tags: list[str], conn: sqlite3.Connection) -> dict:
    from core.tag_classifier import classify_pixiv_tags
    return classify_pixiv_tags(raw_tags, conn=conn)


# ---------------------------------------------------------------------------
# JSON pack 구조 (kind / canonical / localizations) 검증
# ---------------------------------------------------------------------------

class TestPackStructure:
    """blue_archive.json 의 새 항목이 spec 대로 적재됐는지 확인."""

    def test_pack_has_groups_array(self, pack) -> None:
        assert "groups" in pack
        assert isinstance(pack["groups"], list)
        assert len(pack["groups"]) >= 1

    def test_oki_aoi_character_kind_npc(self, pack) -> None:
        oki = next(
            (c for c in pack["characters"] if c["canonical"] == "扇喜アオイ"),
            None,
        )
        assert oki is not None, "扇喜アオイ 가 pack 에 없습니다"
        assert oki["parent_series"] == "Blue Archive"
        assert oki.get("kind") == "npc"
        locs = oki.get("localizations", {})
        assert locs.get("ja") == "扇喜アオイ"
        assert locs.get("ko") == "오키 아오이"
        assert locs.get("en") == "Oki Aoi"

    def test_oki_aoi_no_single_name_aliases(self, pack) -> None:
        """단일 이름 alias 금지 — PR #120 parent_series 오탐 방지."""
        oki = next(c for c in pack["characters"] if c["canonical"] == "扇喜アオイ")
        forbidden = {"アオイ", "아오이", "Aoi"}
        leaked = forbidden & set(oki.get("aliases", []))
        assert leaked == set(), f"단일 이름 alias 가 누출됐음: {leaked}"

    def test_problem_solver_68_group_structure(self, pack) -> None:
        ps68 = next(
            (g for g in pack["groups"] if g["canonical"] == "便利屋68"),
            None,
        )
        assert ps68 is not None
        assert ps68["parent_series"] == "Blue Archive"
        # kind 가 group / organization 계열인지 확인.
        assert ps68.get("kind") in ("group", "organization")
        locs = ps68.get("localizations", {})
        assert locs.get("ko") == "흥신소68"
        assert locs.get("ja") == "便利屋68"
        assert locs.get("en") == "Problem Solver 68"

    def test_group_aliases_include_all_three_locales(self, pack) -> None:
        ps68 = next(g for g in pack["groups"] if g["canonical"] == "便利屋68")
        aliases = set(ps68.get("aliases", []))
        for must_have in ("흥신소68", "便利屋68", "Problem Solver 68"):
            assert must_have in aliases


# ---------------------------------------------------------------------------
# Seed → DB 검증
# ---------------------------------------------------------------------------

class TestSeedNpcAndGroup:
    def test_seed_inserts_oki_aoi_with_kind(self, conn) -> None:
        rows = conn.execute(
            "SELECT canonical, parent_series, kind FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character'",
            ("扇喜アオイ",),
        ).fetchall()
        assert rows, "扇喜アオイ 가 tag_aliases 에 seed 되지 않았습니다"
        row = rows[0]
        assert row["canonical"] == "扇喜アオイ"
        assert row["parent_series"] == "Blue Archive"
        assert row["kind"] == "npc"

    def test_seed_inserts_problem_solver_group(self, conn) -> None:
        rows = conn.execute(
            "SELECT alias, canonical, parent_series, kind FROM tag_aliases "
            "WHERE tag_type = 'group' AND canonical = '便利屋68'"
        ).fetchall()
        aliases = {r["alias"] for r in rows}
        assert {"흥신소68", "便利屋68", "Problem Solver 68"}.issubset(aliases)
        for r in rows:
            assert r["parent_series"] == "Blue Archive"
            assert r["kind"] == "group"

    def test_seed_localizations_for_group(self, conn) -> None:
        rows = conn.execute(
            "SELECT locale, display_name FROM tag_localizations "
            "WHERE tag_type = 'group' AND canonical = '便利屋68'"
        ).fetchall()
        loc_map = {r["locale"]: r["display_name"] for r in rows}
        assert loc_map.get("ko") == "흥신소68"
        assert loc_map.get("ja") == "便利屋68"
        assert loc_map.get("en") == "Problem Solver 68"


# ---------------------------------------------------------------------------
# 캐릭터/그룹 탐지 — 사용자 spec 1~7
# ---------------------------------------------------------------------------

class TestNpcCharacterDetection:
    def test_1_japanese_alias_detects_oki_aoi(self, conn) -> None:
        result = _classify(["扇喜アオイ"], conn)
        assert "扇喜アオイ" in result["character_tags"]
        ev = next(
            (e for e in result["evidence"]["characters"]
             if e["canonical"] == "扇喜アオイ"),
            None,
        )
        assert ev is not None
        assert ev["parent_series"] == "Blue Archive"
        assert ev["matched_raw_tag"] == "扇喜アオイ"

    def test_2_korean_alias_detects_oki_aoi(self, conn) -> None:
        result = _classify(["오키 아오이"], conn)
        assert "扇喜アオイ" in result["character_tags"]
        ev = next(
            e for e in result["evidence"]["characters"]
            if e["canonical"] == "扇喜アオイ"
        )
        assert ev["parent_series"] == "Blue Archive"

    def test_3_english_alias_detects_oki_aoi(self, conn) -> None:
        result = _classify(["Oki Aoi"], conn)
        assert "扇喜アオイ" in result["character_tags"]
        ev = next(
            e for e in result["evidence"]["characters"]
            if e["canonical"] == "扇喜アオイ"
        )
        assert ev["parent_series"] == "Blue Archive"

    def test_4_single_name_aliases_do_not_match_oki_aoi(self, conn) -> None:
        """アオイ / 아오이 / Aoi 단일 이름이 扇喜アオイ 로 매칭되면 안 된다."""
        for raw in ("アオイ", "아오이", "Aoi"):
            result = _classify([raw], conn)
            assert "扇喜アオイ" not in result["character_tags"], (
                f"단일 이름 alias {raw!r} 가 扇喜アオイ 로 매칭됨"
            )
            for ev in result["evidence"].get("series", []):
                assert ev.get("matched_character") != "扇喜アオイ", (
                    f"단일 이름 alias {raw!r} 가 parent_series 추론에 사용됨"
                )


class TestProblemSolver68GroupDetection:
    def test_5_korean_alias_detects_problem_solver_68(self, conn) -> None:
        result = _classify(["흥신소68"], conn)
        assert "便利屋68" in result["group_tags"]
        ev = next(
            e for e in result["evidence"]["groups"]
            if e["canonical"] == "便利屋68"
        )
        assert ev["parent_series"] == "Blue Archive"

    def test_6_japanese_alias_detects_problem_solver_68(self, conn) -> None:
        result = _classify(["便利屋68"], conn)
        assert "便利屋68" in result["group_tags"]
        ev = next(
            e for e in result["evidence"]["groups"]
            if e["canonical"] == "便利屋68"
        )
        assert ev["parent_series"] == "Blue Archive"

    def test_7_english_alias_detects_problem_solver_68(self, conn) -> None:
        result = _classify(["Problem Solver 68"], conn)
        assert "便利屋68" in result["group_tags"]
        ev = next(
            e for e in result["evidence"]["groups"]
            if e["canonical"] == "便利屋68"
        )
        assert ev["parent_series"] == "Blue Archive"


# ---------------------------------------------------------------------------
# PR #120 series-only resolver 연동 — 사용자 spec 8~10
# ---------------------------------------------------------------------------

class TestSeriesOnlyResolverIntegration:
    """character.parent_series / group.parent_series 가 series-only resolver 를
    통과해 destination / needs_review 를 결정하는지 검증한다."""

    def test_8_group_parent_series_drives_resolver(self, conn) -> None:
        explicit, parent_map = _resolve_series_only_inputs(["흥신소68"], conn)
        assert explicit == [] or "Blue Archive" not in explicit, (
            "explicit series 에 inferred 가 누출됨"
        )
        # 便利屋68 의 parent_series 가 매핑에 들어와야 한다.
        assert "便利屋68" in parent_map
        assert parent_map["便利屋68"] == "Blue Archive"

        result = resolve_series_only_destination(explicit, parent_map)
        assert result["status"] == "ready"
        assert result["rule"] == SERIES_ONLY_RULE_PARENT_SERIES
        assert result["series"] == ["Blue Archive"]

    def test_9_npc_character_parent_series_drives_resolver(self, conn) -> None:
        explicit, parent_map = _resolve_series_only_inputs(["扇喜アオイ"], conn)
        assert "扇喜アオイ" in parent_map
        assert parent_map["扇喜アオイ"] == "Blue Archive"

        result = resolve_series_only_destination(explicit, parent_map)
        assert result["status"] == "ready"
        assert result["rule"] == SERIES_ONLY_RULE_PARENT_SERIES
        assert result["series"] == ["Blue Archive"]

    def test_10_explicit_series_conflict_with_npc_blocks_destination(
        self, conn, tmp_path
    ) -> None:
        """explicit Fate/Grand Order + 扇喜アオイ (parent=Blue Archive) →
        series_parent_conflict, destination 없음 (multi-destination 분류 금지)."""
        # explicit series 매칭을 위해 Fate/Grand Order alias 도 seed.
        from core.tag_pack_loader import load_tag_pack, seed_tag_pack
        fgo_pack_path = (
            Path(__file__).parent.parent / "resources" / "tag_packs"
            / "fate_grand_order.json"
        )
        if fgo_pack_path.exists():
            seed_tag_pack(conn, load_tag_pack(fgo_pack_path))

        # build_classify_preview 통합 — series-only mode 로 호출.
        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"\xff\xd8\xff\xe0")

        now = _now()
        conn.execute(
            "INSERT INTO artwork_groups "
            "(group_id, source_site, artwork_id, artwork_title, artist_name, "
            " downloaded_at, indexed_at, metadata_sync_status, "
            " tags_json, series_tags_json, character_tags_json) "
            "VALUES (?, 'pixiv', ?, 'test', 'artist', ?, ?, 'json_only', ?, ?, ?)",
            (
                gid, gid[:12], now, now,
                json.dumps(["Fate/Grand Order", "扇喜アオイ"], ensure_ascii=False),
                json.dumps(["Fate/Grand Order"], ensure_ascii=False),
                json.dumps(["扇喜アオイ"], ensure_ascii=False),
            ),
        )
        conn.execute(
            "INSERT INTO artwork_files "
            "(file_id, group_id, page_index, file_role, file_path, "
            " file_format, file_size, metadata_embedded, file_status, created_at) "
            "VALUES (?, ?, 0, 'original', ?, 'jpg', 1024, 1, 'present', ?)",
            (str(uuid.uuid4()), gid, str(img), now),
        )
        conn.commit()

        classified = tmp_path / "Classified"
        classified.mkdir()
        cfg = {
            "classified_dir": str(classified),
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
        preview = build_classify_preview(conn, gid, cfg)

        assert preview is not None
        ci = preview.get("classification_info") or {}
        assert ci.get("classification_reason") == SERIES_ONLY_REASON_PARENT_CONFLICT, (
            f"expected series_parent_conflict, got {ci!r} dests={preview.get('destinations')}"
        )
        # series destination 이 생성되면 안 된다 (author_fallback 제외).
        non_author = [
            d for d in preview["destinations"]
            if d.get("rule_type") != "author_fallback"
        ]
        assert non_author == [], f"conflict 인데 series destination 이 생성됨: {non_author}"
