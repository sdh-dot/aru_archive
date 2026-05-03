"""tests/test_tag_pack_collateral_skip_lint.py

Tag pack loader 의 weak lint skip 단위가 row-key tuple 임을 lock 하는 회귀 테스트.

배경:
  PR #94 (FGO ja localization 수정) 분석에서 ``_apply_pack_lint`` 가 weak hit
  의 value 문자열을 set 에 담아 skip 했고, 같은 value 가 alias / 다른 locale 에
  도 등장하면 collateral 로 함께 skip 되는 구조적 문제를 발견했다.

  본 PR 은 skip 단위를 ``(kind, canonical, locale, value)`` 4-tuple 로 변경해
  collateral skip 을 차단했다. 본 테스트는 그 invariant 을 lock 한다.

invariant:
  1. ja/ko ASCII-only localization 이 weak hit 을 발화해도 같은 value 의 alias 는
     등록된다.
  2. ja/ko ASCII-only localization 이 weak hit 을 발화해도 같은 value 의 다른
     locale (en) localization 은 등록된다.
  3. lint hit 발생한 localization row 자체는 여전히 skip 된다 (정책 보존).
  4. 같은 value 가 series 와 character 양쪽에 있어도 row 단위로만 skip 된다.
  5. hard signal (TagPackImportBlockedError) 동작은 변경되지 않는다.
  6. 모든 built-in pack 을 seed 했을 때 lint warning 0건이다.

본 테스트는 ``core/tag_pack_loader.py`` / ``core/mojibake_heuristics.py`` 의
정책을 변경하지 않는다. ASCII-only 영문 고유명사 예외 / warn-only 정책은 도입
하지 않았다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from core.tag_pack_loader import (
    TagPackImportBlockedError,
    import_localized_tag_pack,
    load_tag_pack,
    seed_builtin_tag_packs,
    seed_tag_pack,
)
from db.database import initialize_database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "collateral.db")
    c = initialize_database(db)
    yield c
    c.close()


def _write_localized_pack(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _builtin_pack(*, series=None, characters=None) -> dict:
    return {
        "pack_id": "collateral_test",
        "name": "Collateral Test",
        "version": "1.0",
        "source": "built_in",
        "series": series or [],
        "characters": characters or [],
    }


# ---------------------------------------------------------------------------
# 1. Series alias / en localization collateral skip 차단
# ---------------------------------------------------------------------------

class TestSeriesCollateralSkip:
    """ja localization 이 ASCII-only 라 weak hit (locale-mismatch) 가 떠도
    같은 value 의 alias / en localization 은 그대로 등록된다."""

    PACK = _builtin_pack(series=[{
        "canonical": "Shared Name",
        "media_type": "game",
        "aliases": ["Shared Name", "약칭"],
        "localizations": {
            "ko": "한국어 이름",
            "ja": "Shared Name",          # weak hit (locale-mismatch, ASCII-only)
            "en": "Shared Name",
        },
    }])

    def test_alias_with_same_value_as_weak_loc_is_preserved(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = 'Shared Name' AND tag_type = 'series' AND enabled = 1"
        ).fetchone()
        assert row is not None, "alias 'Shared Name' 이 collateral skip 됨"
        assert row["canonical"] == "Shared Name"

    def test_other_alias_is_preserved(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = '약칭' AND tag_type = 'series' AND enabled = 1"
        ).fetchone()
        assert row is not None
        assert row["canonical"] == "Shared Name"

    def test_en_localization_with_same_value_is_preserved(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = 'Shared Name' AND tag_type = 'series' "
            "AND locale = 'en'"
        ).fetchone()
        assert row is not None, "en localization 이 collateral skip 됨"
        assert row["display_name"] == "Shared Name"

    def test_ko_localization_is_preserved(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = 'Shared Name' AND tag_type = 'series' "
            "AND locale = 'ko'"
        ).fetchone()
        assert row is not None
        assert row["display_name"] == "한국어 이름"

    def test_target_ja_localization_row_still_skipped(self, conn):
        """정책 보존 — locale-mismatch row 자체는 여전히 등록되지 않는다."""
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT 1 FROM tag_localizations "
            "WHERE canonical = 'Shared Name' AND tag_type = 'series' "
            "AND locale = 'ja'"
        ).fetchone()
        assert row is None, "ja localization row 가 skip 되지 않음 — 정책 미적용"

    def test_warning_emitted_only_for_target_row(self, conn, caplog):
        with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
            seed_tag_pack(conn, self.PACK)
        offending = [
            rec for rec in caplog.records
            if "tag pack lint 경고" in rec.getMessage()
        ]
        assert len(offending) == 1, (
            f"warning 은 ja loc 1건이어야 함. 실제 {len(offending)}건: "
            f"{[r.getMessage() for r in offending]}"
        )
        msg = offending[0].getMessage()
        assert "locale-mismatch" in msg
        assert "'Shared Name'" in msg


# ---------------------------------------------------------------------------
# 2. Character alias / en localization collateral skip 차단
# ---------------------------------------------------------------------------

class TestCharacterCollateralSkip:
    PACK = _builtin_pack(
        series=[{
            "canonical": "Test Series",
            "media_type": "game",
            "aliases": ["Test Series"],
            "localizations": {"en": "Test Series"},
        }],
        characters=[{
            "canonical": "Shared Character",
            "parent_series": "Test Series",
            "aliases": ["Shared Character", "공유캐"],
            "localizations": {
                "ja": "Shared Character",   # weak hit (locale-mismatch)
                "en": "Shared Character",
                "ko": "공유캐",
            },
        }],
    )

    def test_character_alias_with_same_value_preserved(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT canonical, parent_series FROM tag_aliases "
            "WHERE alias = 'Shared Character' AND tag_type = 'character' "
            "AND enabled = 1"
        ).fetchone()
        assert row is not None, "character alias 가 collateral skip 됨"
        assert row["canonical"] == "Shared Character"
        assert row["parent_series"] == "Test Series", (
            "parent_series 가 보존되지 않음"
        )

    def test_character_en_localization_with_same_value_preserved(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = 'Shared Character' AND tag_type = 'character' "
            "AND locale = 'en'"
        ).fetchone()
        assert row is not None, "en localization 이 collateral skip 됨"
        assert row["display_name"] == "Shared Character"

    def test_target_ja_row_skipped(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT 1 FROM tag_localizations "
            "WHERE canonical = 'Shared Character' AND tag_type = 'character' "
            "AND locale = 'ja'"
        ).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# 3. Cross-section: 같은 value 가 series 와 character 양쪽에 있어도
#    canonical 이 다르면 row 단위로만 skip 된다
# ---------------------------------------------------------------------------

class TestCrossSectionSkipIsolated:
    """series 의 ja loc 가 weak hit 으로 skip 돼도, 같은 value 를 가진 다른
    canonical 의 character alias 는 등록된다."""

    PACK = _builtin_pack(
        series=[{
            "canonical": "Series Name",
            "media_type": "game",
            "aliases": ["Series Name"],
            "localizations": {
                "ko": "시리즈 한국어 이름",
                "ja": "Shared Token",         # weak hit
                "en": "Series Name",
            },
        }],
        characters=[{
            "canonical": "Char Name",
            "parent_series": "Series Name",
            "aliases": ["Char Name", "Shared Token"],   # 동일 value, 다른 row
            "localizations": {"ko": "캐릭터 한국어 이름"},
        }],
    )

    def test_series_ja_loc_row_skipped(self, conn):
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT 1 FROM tag_localizations "
            "WHERE canonical = 'Series Name' AND tag_type = 'series' "
            "AND locale = 'ja'"
        ).fetchone()
        assert row is None

    def test_character_alias_with_same_value_preserved_under_diff_canonical(
        self, conn
    ):
        """같은 token 'Shared Token' 이 character alias 로도 있지만 canonical 이
        다르므로 별도 row-key — collateral skip 되지 않는다."""
        seed_tag_pack(conn, self.PACK)
        row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = 'Shared Token' AND tag_type = 'character' "
            "AND enabled = 1"
        ).fetchone()
        assert row is not None, (
            "다른 canonical 의 character alias 가 cross-section collateral "
            "skip 됨"
        )
        assert row["canonical"] == "Char Name"


# ---------------------------------------------------------------------------
# 4. Hard signal behavior 미변경
# ---------------------------------------------------------------------------

class TestHardSignalUnchanged:
    def test_hard_question_runs_blocks_import(self, conn, tmp_path):
        pack = _builtin_pack(characters=[{
            "canonical": "Test",
            "parent_series": "S",
            "aliases": ["???????"],
            "localizations": {},
        }])
        with pytest.raises(TagPackImportBlockedError) as exc_info:
            seed_tag_pack(conn, pack)
        assert exc_info.value.reasons_summary["strong"] >= 1

    def test_hard_replacement_char_blocks_import(self, conn, tmp_path):
        pack = _builtin_pack(characters=[{
            "canonical": "Test�Char",  # U+FFFD
            "parent_series": "S",
            "aliases": [],
            "localizations": {},
        }])
        with pytest.raises(TagPackImportBlockedError):
            seed_tag_pack(conn, pack)


# ---------------------------------------------------------------------------
# 5. import_localized_tag_pack 도 동일 동작
# ---------------------------------------------------------------------------

class TestImportLocalizedRowKeySkip:
    def test_import_localized_preserves_alias_with_same_value_as_weak_loc(
        self, conn, tmp_path
    ):
        pack = {
            "pack_id": "imp_test",
            "characters": [{
                "canonical": "Shared Char",
                "parent_series": "Imp Series",
                "aliases": ["Shared Char", "다른 alias"],
                "localizations": {
                    "ja": "Shared Char",         # weak hit
                    "en": "Shared Char",
                    "ko": "다른 한국어",
                },
            }],
            "series": [],
        }
        path = _write_localized_pack(tmp_path, pack)
        import_localized_tag_pack(conn, path)

        # alias 'Shared Char' 등록
        alias_row = conn.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE alias = 'Shared Char' AND tag_type = 'character' "
            "AND enabled = 1"
        ).fetchone()
        assert alias_row is not None
        assert alias_row["canonical"] == "Shared Char"

        # en localization 등록
        en_row = conn.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical = 'Shared Char' AND tag_type = 'character' "
            "AND locale = 'en'"
        ).fetchone()
        assert en_row is not None

        # ja localization row 만 skip
        ja_row = conn.execute(
            "SELECT 1 FROM tag_localizations "
            "WHERE canonical = 'Shared Char' AND tag_type = 'character' "
            "AND locale = 'ja'"
        ).fetchone()
        assert ja_row is None


# ---------------------------------------------------------------------------
# 6. Built-in pack lint audit — 모든 built-in pack 이 lint hit 0건
# ---------------------------------------------------------------------------

class TestBuiltinPackLintAudit:
    def test_seed_builtin_packs_emits_no_lint_warnings(self, conn, caplog):
        """전체 built-in pack seed 후 lint warning 0건.

        현재 모든 pack 은 FGO PR #94 fix 와 Trickcal pack 의 script ratio 준수
        덕에 깨끗한 상태. 새 pack 추가 시 ASCII-only ko/ja localization 을
        넣으면 이 테스트가 즉시 실패해 회귀를 잡는다.
        """
        with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
            seed_builtin_tag_packs(conn)

        offending = [
            rec for rec in caplog.records
            if "tag pack lint 경고" in rec.getMessage()
            or "locale-mismatch" in rec.getMessage()
        ]
        assert not offending, (
            "built-in pack 에서 lint warning 발생 — 신규 pack 의 localization "
            f"script ratio 점검 필요:\n"
            + "\n".join(f"  - {r.getMessage()}" for r in offending)
        )
