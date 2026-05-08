"""tests/test_tag_pack_blue_archive_enrichment.py

Blue Archive tag pack 사전 보강 회귀 테스트.

Phase A (enrichment-campaign, 5 confirmed characters):
  - 角楯カリン  / 카쿠다테 카린  / Kakudate Karin  — Millennium C&C
  - 白石ウタハ  / 시라이시 우타하 / Shiraishi Utaha — Millennium Seminar
  - 三香本ネル  / 미카모 네루    / Mikamo Neru    — Millennium C&C
  - 白見イオリ  / 시로미 이오리   / Shiromi Iori   — Gehenna 선도부
  - 連川チェリノ / 렌카와 체리노  / Renkawa Cherino — Red Winter

alias 충돌 회귀 가드:
  - 三香本ネル 에 "ネル" 단독 alias 금지 (Trickcal Re:VIVE 네르와 충돌)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database


PACK_PATH = (
    Path(__file__).parent.parent / "resources" / "tag_packs" / "blue_archive.json"
)

CANONICAL_SERIES = "Blue Archive"

# Phase A 보강으로 추가된 5명. 각 (canonical_ja, ko, en) 튜플.
PHASE_A_CHARACTERS: list[tuple[str, str, str]] = [
    ("角楯カリン",  "카쿠다테 카린",  "Kakudate Karin"),
    ("白石ウタハ",  "시라이시 우타하", "Shiraishi Utaha"),
    ("三香本ネル",  "미카모 네루",    "Mikamo Neru"),
    ("白見イオリ",  "시로미 이오리",  "Shiromi Iori"),
    ("連川チェリノ", "렌카와 체리노",  "Renkawa Cherino"),
]

# ネル 단독은 Trickcal 네르와 충돌 — BA pack 에 절대 추가 금지.
ALIAS_CONFLICT_GUARD = "ネル"


# ---------------------------------------------------------------------------
# Static pack file invariants (DB 무관)
# ---------------------------------------------------------------------------

class TestPackFileShape:
    def test_pack_file_exists(self):
        assert PACK_PATH.exists()

    def test_pack_id_and_version(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert pack["pack_id"] == "blue_archive"
        assert pack["source"] == "built_in"
        # Phase A 보강 이후 최소 버전
        major, minor, patch = (int(x) for x in pack["version"].split("."))
        assert (major, minor) >= (1, 5), (
            f"Phase A 보강 후 version >= 1.5.0 이어야 함: {pack['version']!r}"
        )

    def test_character_count_at_least_94(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert len(pack["characters"]) >= 94, (
            f"Phase A 추가 후 최소 94명 기대, 실제: {len(pack['characters'])}"
        )

    def test_phase_a_canonicals_present(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        canonicals = {c["canonical"] for c in pack["characters"]}
        for ja, ko, en in PHASE_A_CHARACTERS:
            assert ja in canonicals, f"canonical 누락: {ja!r}"

    def test_phase_a_ko_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["localizations"].get("ko") == ko, (
                f"{ja!r} ko 불일치: {char['localizations'].get('ko')!r} != {ko!r}"
            )

    def test_phase_a_en_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["localizations"].get("en") == en, (
                f"{ja!r} en 불일치: {char['localizations'].get('en')!r} != {en!r}"
            )

    def test_phase_a_ja_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["localizations"].get("ja") == ja, (
                f"{ja!r} ja localization 불일치: {char['localizations'].get('ja')!r}"
            )

    def test_phase_a_parent_series(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["parent_series"] == CANONICAL_SERIES, (
                f"{ja!r} parent_series 불일치: {char['parent_series']!r}"
            )

    def test_neru_does_not_have_katakana_neru_alias(self):
        """三香本ネル 에 'ネル' 단독 alias 없음 — Trickcal 네르와 충돌 방지."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        neru = char_by_canonical.get("三香本ネル")
        assert neru is not None, "三香本ネル 가 pack 에 없음"
        assert ALIAS_CONFLICT_GUARD not in neru["aliases"], (
            f"三香本ネル 에 충돌 alias {ALIAS_CONFLICT_GUARD!r} 등록됨"
        )

    def test_neru_has_en_neru_alias(self):
        """三香本ネル 에 영문 'Neru' alias 는 있어야 한다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        neru = char_by_canonical["三香本ネル"]
        assert "Neru" in neru["aliases"], (
            "三香本ネル 에 'Neru' EN alias 누락"
        )

    def test_phase_a_ko_aliases_present(self):
        """KR 표기가 각 캐릭터의 aliases 배열에도 포함돼 있어야 한다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A_CHARACTERS:
            char = char_by_canonical[ja]
            assert ko in char["aliases"], (
                f"{ja!r} aliases 에 KR 표기 누락: {ko!r}"
            )


# ---------------------------------------------------------------------------
# Loader 동작 검증 (in-memory SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    pack = load_tag_pack(PACK_PATH)
    seed_tag_pack(c, pack)
    yield c
    c.close()


class TestLoaderEmitsNoLintWarning:
    def test_no_locale_mismatch_warning(self, tmp_path, caplog):
        db = str(tmp_path / "lint.db")
        c = initialize_database(db)
        try:
            pack = load_tag_pack(PACK_PATH)
            with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
                seed_tag_pack(c, pack)
            offending = [
                rec for rec in caplog.records
                if "blue_archive" in rec.getMessage()
                and "locale-mismatch" in rec.getMessage()
            ]
            assert not offending, (
                f"locale-mismatch warning 발생: "
                f"{[r.getMessage() for r in offending]}"
            )
        finally:
            c.close()


class TestPhaseACharactersSeeded:
    def test_ko_alias_resolves_to_correct_canonical(self, conn):
        """KR 표기로 검색하면 JA canonical 이 반환된다."""
        for ja, ko, en in PHASE_A_CHARACTERS:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (ko,),
            ).fetchone()
            assert row is not None, f"KR alias 미등록: {ko!r}"
            assert row["canonical"] == ja, (
                f"{ko!r} → {row['canonical']!r}, 기대: {ja!r}"
            )

    def test_en_alias_resolves_to_correct_canonical(self, conn):
        """EN 표기로 검색하면 JA canonical 이 반환된다."""
        for ja, ko, en in PHASE_A_CHARACTERS:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (en,),
            ).fetchone()
            assert row is not None, f"EN alias 미등록: {en!r}"
            assert row["canonical"] == ja, (
                f"{en!r} → {row['canonical']!r}, 기대: {ja!r}"
            )

    def test_neru_katakana_alias_not_registered(self, conn):
        """'ネル' 단독이 BA character alias 로 DB에 등록되지 않았다."""
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
            (ALIAS_CONFLICT_GUARD,),
        ).fetchone()
        if row is not None:
            assert row["canonical"] != "三香本ネル", (
                f"'ネル' 가 三香本ネル canonical 로 등록됨 — Trickcal 충돌 위험"
            )

    def test_ko_localizations_registered(self, conn):
        """DB tag_localizations 에 ko locale 이 등록돼 있다."""
        for ja, ko, en in PHASE_A_CHARACTERS:
            row = conn.execute(
                "SELECT display_name FROM tag_localizations "
                "WHERE canonical = ? AND tag_type = 'character' AND locale = 'ko'",
                (ja,),
            ).fetchone()
            assert row is not None, f"ko localization 미등록: {ja!r}"
            assert row["display_name"] == ko, (
                f"{ja!r} ko display_name 불일치: {row['display_name']!r} != {ko!r}"
            )
