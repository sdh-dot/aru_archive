"""tests/test_tag_pack_fate_grand_order_lint.py

fate_grand_order tag pack 의 ja localization locale-mismatch 회귀 테스트.

배경:
  ``localizations.ja`` 가 ``"Fate/Grand Order"`` (ASCII-only) 로 설정되어 있어
  ``core.tag_pack_loader`` 의 mojibake lint 가 ``locale-mismatch`` (weak) 신호
  를 발화하고 해당 row 를 skip 했다. ``_apply_pack_lint`` 가 value 단위로
  skip set 을 구성하므로, 같은 문자열 ``"Fate/Grand Order"`` 가 alias[0] /
  localizations.en 에도 존재해 collateral skip 으로 전이되어 자동 분류 매칭과
  EN 표시명 fallback 이 깨졌다.

수정:
  ``localizations.ja`` 값을 같은 pack 에 이미 존재하는 일본어 음역 alias
  ``"フェイト/グランドオーダー"`` 로 교체. lint 통과 → skip set 미진입 →
  alias / en localization 정상 등록.

본 테스트는 아래 invariant 을 lock 한다:
  1. fate_grand_order pack seed 시 lint warning 이 발생하지 않는다.
  2. alias ``"Fate/Grand Order"`` 가 collateral skip 없이 등록된다.
  3. localization en/ja/ko 가 모두 등록되며 ja 값이 일본어 음역이다.
  4. 향후 ja localization 이 ASCII-only 로 다시 회귀하지 않는다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from core.tag_pack_loader import load_tag_pack, seed_tag_pack
from db.database import initialize_database


PACK_PATH = (
    Path(__file__).parent.parent / "resources" / "tag_packs" / "fate_grand_order.json"
)


# ---------------------------------------------------------------------------
# Static pack file invariants (DB 무관)
# ---------------------------------------------------------------------------

class TestPackFileShape:
    def test_pack_file_exists(self):
        assert PACK_PATH.exists(), f"fate_grand_order pack 누락: {PACK_PATH}"

    def test_ja_localization_is_japanese_script(self):
        """ja localization 이 일본어 문자(히라가나/카타카나/한자) ≥ 30%."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        ja = pack["series"][0]["localizations"]["ja"]
        ja_count = sum(
            1 for ch in ja
            if ("぀" <= ch <= "ゟ")   # hiragana
            or ("゠" <= ch <= "ヿ")   # katakana
            or ("一" <= ch <= "鿿")   # CJK unified
        )
        ratio = ja_count / max(len(ja), 1)
        assert ratio >= 0.30, (
            f"ja localization 의 일본어 문자 비율이 30% 미만: {ratio:.0%} ({ja!r})"
        )

    def test_ja_localization_not_ascii_only(self):
        """ja localization 이 ASCII-only 가 아니다 (회귀 가드)."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        ja = pack["series"][0]["localizations"]["ja"]
        assert not ja.isascii(), (
            f"ja localization 이 ASCII-only 로 회귀했다: {ja!r}"
        )

    def test_canonical_and_aliases_unchanged(self):
        """canonical 과 핵심 alias 가 보존되어 있다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        s = pack["series"][0]
        assert s["canonical"] == "Fate/Grand Order"
        assert "Fate/Grand Order" in s["aliases"]
        assert "FGO" in s["aliases"]
        assert "フェイト/グランドオーダー" in s["aliases"]


# ---------------------------------------------------------------------------
# Loader 동작 검증 (in-memory SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


class TestSeedingProducesNoLintWarning:
    def test_seed_emits_no_locale_mismatch_warning(self, conn, caplog):
        """seed_tag_pack 실행 시 fate_grand_order 관련 lint warning 이 없다."""
        pack = load_tag_pack(PACK_PATH)
        with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
            seed_tag_pack(conn, pack)

        offending = [
            rec for rec in caplog.records
            if "fate_grand_order" in rec.getMessage()
            and "locale-mismatch" in rec.getMessage()
        ]
        assert not offending, (
            f"locale-mismatch warning 이 여전히 발생: "
            f"{[r.getMessage() for r in offending]}"
        )


class TestAliasesAreRegistered:
    def test_fate_grand_order_alias_registered(self, conn):
        """alias 'Fate/Grand Order' 가 collateral skip 없이 등록된다."""
        pack = load_tag_pack(PACK_PATH)
        seed_tag_pack(conn, pack)

        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
            ("Fate/Grand Order",),
        ).fetchone()
        assert row is not None, "alias 'Fate/Grand Order' 가 등록되지 않음"
        assert row["canonical"] == "Fate/Grand Order"

    def test_all_aliases_registered(self, conn):
        """pack 의 모든 alias 가 등록된다."""
        pack = load_tag_pack(PACK_PATH)
        seed_tag_pack(conn, pack)

        for alias in pack["series"][0]["aliases"]:
            row = conn.execute(
                "SELECT 1 FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'series' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert row is not None, f"alias 미등록: {alias!r}"


class TestLocalizationsAreRegistered:
    def test_en_localization_registered(self, conn):
        """en localization 'Fate/Grand Order' 가 collateral skip 없이 등록된다."""
        pack = load_tag_pack(PACK_PATH)
        seed_tag_pack(conn, pack)

        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'series' AND locale = 'en'",
            ("Fate/Grand Order",),
        ).fetchone()
        assert row is not None, "en localization 이 등록되지 않음"
        assert row["display_name"] == "Fate/Grand Order"

    def test_ja_localization_registered_with_japanese_value(self, conn):
        """ja localization 이 일본어 음역 표기로 등록된다."""
        pack = load_tag_pack(PACK_PATH)
        seed_tag_pack(conn, pack)

        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'series' AND locale = 'ja'",
            ("Fate/Grand Order",),
        ).fetchone()
        assert row is not None, "ja localization 이 등록되지 않음"
        assert row["display_name"] == "フェイト/グランドオーダー"

    def test_ko_localization_registered(self, conn):
        """ko localization 도 정상 등록된다 (기존 동작 보존)."""
        pack = load_tag_pack(PACK_PATH)
        seed_tag_pack(conn, pack)

        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = ? AND tag_type = 'series' AND locale = 'ko'",
            ("Fate/Grand Order",),
        ).fetchone()
        assert row is not None, "ko localization 이 등록되지 않음"
        assert row["display_name"] == "페이트/그랜드 오더"
