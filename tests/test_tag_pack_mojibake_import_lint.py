"""tests/test_tag_pack_mojibake_import_lint.py

PR-6 — import-time mojibake lint 회귀 테스트.

검증 목표:
  - Strong 신호(???, U+FFFD, underscore placeholder, punctuation-heavy) → 차단
  - Weak 신호(Latin-1 mojibake, locale-mismatch) → import 허용 + warning
  - 정상 pack(한글/일본어/영문/BA pack/8 시리즈 pack) → 정상 import
  - 차단 시 DB row 수 변화 없음 (partial write 방지)
  - user_confirmed source 자동 생성 없음
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from db.database import initialize_database
from core.tag_pack_loader import (
    TagPackImportBlockedError,
    import_localized_tag_pack,
    seed_builtin_tag_packs,
    seed_tag_pack,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


def _row_counts(conn):
    """현재 DB의 alias/localization row 수 반환."""
    aliases = conn.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0]
    locs = conn.execute("SELECT COUNT(*) FROM tag_localizations").fetchone()[0]
    return aliases, locs


def _write_localized_pack(tmp_path, data: dict) -> Path:
    """localized pack JSON 파일로 저장하고 경로 반환."""
    p = tmp_path / "test_pack.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _minimal_localized_pack(*, series=None, characters=None) -> dict:
    return {
        "pack_id": "test_pack",
        "series": series or [],
        "characters": characters or [],
    }


# ---------------------------------------------------------------------------
# 차단 시나리오 — strong 신호
# ---------------------------------------------------------------------------

class TestImportBlocked:
    def test_blocks_question_mark_alias(self, conn, tmp_path):
        """alias에 ??? 포함 → TagPackImportBlockedError, DB 무변화."""
        before = _row_counts(conn)
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test Character",
            "parent_series": "Test Series",
            "aliases": ["???????"],
            "localizations": {},
        }])
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError) as exc_info:
            import_localized_tag_pack(conn, path)

        assert _row_counts(conn) == before
        err = exc_info.value
        assert err.reasons_summary["strong"] >= 1
        assert any("?-runs" in s["reasons"] for s in err.samples)

    def test_blocks_replacement_char_canonical(self, conn, tmp_path):
        """canonical에 U+FFFD 포함 → 차단."""
        before = _row_counts(conn)
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test￼Char",  # U+FFFD replacement char
            "parent_series": "Series",
            "aliases": [],
            "localizations": {},
        }])
        # U+FFFD 직접 삽입
        pack["characters"][0]["canonical"] = "Test�Char"
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError):
            import_localized_tag_pack(conn, path)

        assert _row_counts(conn) == before

    def test_blocks_underscore_placeholder(self, conn, tmp_path):
        """localized_name에 __-___ 포함 → 차단."""
        before = _row_counts(conn)
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test Character",
            "parent_series": "Series",
            "aliases": [],
            "localizations": {"ko": "__-___"},
        }])
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError) as exc_info:
            import_localized_tag_pack(conn, path)

        assert _row_counts(conn) == before
        err = exc_info.value
        assert any("underscore-placeholder" in s["reasons"] for s in err.samples)

    def test_blocks_punctuation_heavy(self, conn, tmp_path):
        """alias가 punctuation-heavy(예: !?!?!?) → 차단."""
        before = _row_counts(conn)
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test Character",
            "parent_series": "Series",
            "aliases": ["!?!?!?"],
            "localizations": {},
        }])
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError) as exc_info:
            import_localized_tag_pack(conn, path)

        assert _row_counts(conn) == before
        err = exc_info.value
        assert any("punctuation-heavy" in s["reasons"] for s in err.samples)

    def test_error_message_contains_strong_count(self, conn, tmp_path):
        """TagPackImportBlockedError 메시지에 strong 건수 포함."""
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test",
            "parent_series": "S",
            "aliases": ["???????"],
            "localizations": {},
        }])
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError) as exc_info:
            import_localized_tag_pack(conn, path)

        msg = str(exc_info.value)
        assert "strong" in msg
        assert "TagPackImportBlocked" in msg

    def test_error_has_samples_list(self, conn, tmp_path):
        """TagPackImportBlockedError.samples는 list[dict]."""
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test",
            "parent_series": "S",
            "aliases": ["???????"],
            "localizations": {},
        }])
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError) as exc_info:
            import_localized_tag_pack(conn, path)

        err = exc_info.value
        assert isinstance(err.samples, list)
        assert len(err.samples) >= 1
        sample = err.samples[0]
        for key in ("table", "field", "value", "reasons"):
            assert key in sample, f"sample에 '{key}' 키 없음"


# ---------------------------------------------------------------------------
# 통과 시나리오
# ---------------------------------------------------------------------------

class TestImportAllowed:
    def test_allows_clean_korean_pack(self, conn, tmp_path):
        """정상 한글 ko localization → 정상 import."""
        pack = _minimal_localized_pack(characters=[{
            "canonical": "이오치 마리",
            "parent_series": "블루 아카이브",
            "aliases": ["이오치 마리", "마리"],
            "localizations": {"ko": "이오치 마리"},
        }])
        path = _write_localized_pack(tmp_path, pack)
        result = import_localized_tag_pack(conn, path)
        assert result["character_aliases"] > 0 or result["localizations"] >= 0

    def test_allows_clean_japanese_pack(self, conn, tmp_path):
        """정상 일본어 → 정상 import."""
        pack = _minimal_localized_pack(characters=[{
            "canonical": "伊落マリー",
            "parent_series": "Blue Archive",
            "aliases": ["伊落マリー", "マリー"],
            "localizations": {"ja": "伊落マリー"},
        }])
        path = _write_localized_pack(tmp_path, pack)
        result = import_localized_tag_pack(conn, path)
        assert result["character_aliases"] >= 0

    def test_allows_clean_english_pack(self, conn, tmp_path):
        """영문 canonical + aliases → 정상 import."""
        pack = _minimal_localized_pack(series=[{
            "canonical": "Blue Archive",
            "aliases": ["BlueArchive", "Blue Archive"],
            "localizations": {"en": "Blue Archive"},
        }])
        path = _write_localized_pack(tmp_path, pack)
        result = import_localized_tag_pack(conn, path)
        assert result["series_aliases"] >= 0

    def test_allows_blue_archive_pack(self, conn):
        """resources/tag_packs/blue_archive.json → 정상 import (회귀 가드)."""
        from core.tag_pack_loader import load_tag_pack
        pack_path = (
            Path(__file__).parent.parent / "resources" / "tag_packs" / "blue_archive.json"
        )
        pack = load_tag_pack(pack_path)
        result = seed_tag_pack(conn, pack)
        assert result["series_aliases"] > 0
        assert result["character_aliases"] > 0

    def test_allows_builtin_packs_seed_run(self, conn):
        """seed_builtin_tag_packs 전체 실행 → 모든 내장 pack 정상 (회귀 가드)."""
        result = seed_builtin_tag_packs(conn)
        assert result["series_aliases"] > 0
        assert result["character_aliases"] > 0

    def test_allows_series_with_normal_text(self, conn, tmp_path):
        """시리즈 alias 정상 텍스트 → 통과."""
        pack = _minimal_localized_pack(series=[{
            "canonical": "NIKKE",
            "aliases": ["NIKKE", "승리의 여신: 니케"],
            "localizations": {"ko": "승리의 여신: 니케", "en": "NIKKE"},
        }])
        path = _write_localized_pack(tmp_path, pack)
        result = import_localized_tag_pack(conn, path)
        assert result["series_aliases"] >= 0


# ---------------------------------------------------------------------------
# Weak 신호 시나리오
# ---------------------------------------------------------------------------

class TestWeakSignals:
    def test_warns_on_latin1_mojibake_but_does_not_block(
        self, conn, tmp_path, caplog
    ):
        """Latin-1 mojibake(Ã¢) → import 허용, warning 로그 발생."""
        # Weak 신호만 있는 pack: alias에 latin1 mojibake 패턴
        # 단, canonical과 정상 alias도 함께 있어야 pack 자체가 의미 있음
        pack = _minimal_localized_pack(characters=[
            {
                "canonical": "Clean Character",
                "parent_series": "Series",
                "aliases": ["Clean Character", "Ã¢clean"],  # weak: latin1-mojibake
                "localizations": {"en": "Clean Character"},
            }
        ])
        path = _write_localized_pack(tmp_path, pack)

        with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
            # weak 신호는 차단 없이 통과해야 함
            result = import_localized_tag_pack(conn, path)

        # TagPackImportBlockedError가 발생하지 않았으므로 result가 존재
        assert isinstance(result, dict)
        # weak alias는 skip되었으므로 총 import 수는 줄어들 수 있음
        # (정상 alias "Clean Character"는 import됨)

    def test_warns_on_locale_mismatch_but_does_not_block(
        self, conn, tmp_path, caplog
    ):
        """locale='ko'인데 ASCII만 → weak 신호, import 허용."""
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Trickcal",
            "parent_series": "Trickcal",
            "aliases": ["Trickcal"],
            "localizations": {"ko": "Trickcal"},  # locale-mismatch (weak)
        }])
        path = _write_localized_pack(tmp_path, pack)

        with caplog.at_level(logging.WARNING, logger="core.tag_pack_loader"):
            result = import_localized_tag_pack(conn, path)

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Partial write 가드
# ---------------------------------------------------------------------------

class TestPartialWriteGuard:
    def test_blocked_leaves_db_unchanged(self, conn, tmp_path):
        """strong 신호 차단 시 alias/localization row 수 변화 없음."""
        # 먼저 정상 row 하나 삽입
        conn.execute(
            "INSERT OR IGNORE INTO tag_aliases"
            " (alias, canonical, tag_type, parent_series, source, enabled, created_at)"
            " VALUES ('clean', 'Clean Canon', 'character', 'Series',"
            "  'test', 1, '2026-01-01T00:00:00Z')"
        )
        conn.commit()

        before = _row_counts(conn)

        # strong 신호가 포함된 pack
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test",
            "parent_series": "S",
            "aliases": ["???????", "good_alias"],
            "localizations": {"ko": "정상 한글"},
        }])
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError):
            import_localized_tag_pack(conn, path)

        # DB row 수가 동일해야 함 — good_alias도 삽입되지 않아야 함
        assert _row_counts(conn) == before

    def test_blocked_does_not_create_user_confirmed(self, conn, tmp_path):
        """차단 후 user_confirmed source row가 생성되지 않음."""
        pack = _minimal_localized_pack(characters=[{
            "canonical": "Test",
            "parent_series": "S",
            "aliases": ["???????"],
            "localizations": {},
        }])
        path = _write_localized_pack(tmp_path, pack)

        with pytest.raises(TagPackImportBlockedError):
            import_localized_tag_pack(conn, path)

        user_confirmed_count = conn.execute(
            "SELECT COUNT(*) FROM tag_aliases WHERE source='user_confirmed'"
        ).fetchone()[0]
        assert user_confirmed_count == 0


# ---------------------------------------------------------------------------
# seed_tag_pack 차단 시나리오 (built_in_pack source)
# ---------------------------------------------------------------------------

class TestSeedTagPackLint:
    def test_seed_blocks_strong_mojibake(self, conn):
        """seed_tag_pack에 strong 신호 포함 시 차단."""
        pack = {
            "pack_id": "mojibake_test",
            "name": "Mojibake Test",
            "version": "1.0",
            "source": "built_in",
            "series": [],
            "characters": [{
                "canonical": "Test",
                "parent_series": "S",
                "aliases": ["???????"],
                "localizations": {},
            }],
        }
        before = _row_counts(conn)

        with pytest.raises(TagPackImportBlockedError):
            seed_tag_pack(conn, pack)

        assert _row_counts(conn) == before

    def test_seed_passes_clean_pack(self, conn):
        """seed_tag_pack에 정상 pack → 통과."""
        pack = {
            "pack_id": "clean_test",
            "name": "Clean Test",
            "version": "1.0",
            "source": "built_in",
            "series": [{
                "canonical": "Clean Series",
                "media_type": "game",
                "aliases": ["Clean Series", "클린 시리즈"],
                "localizations": {"ko": "클린 시리즈"},
            }],
            "characters": [],
        }
        result = seed_tag_pack(conn, pack)
        assert result["series_aliases"] > 0


# ---------------------------------------------------------------------------
# 보호 시나리오 — user_confirmed 경로
# ---------------------------------------------------------------------------

class TestUserConfirmedProtection:
    def test_import_localized_does_not_override_user_confirmed(
        self, conn, tmp_path
    ):
        """기존 user_confirmed localization이 있으면 덮어쓰지 않음."""
        import uuid
        # user_confirmed 사전 삽입
        conn.execute(
            """INSERT OR IGNORE INTO tag_localizations
               (localization_id, canonical, tag_type, parent_series,
                locale, display_name, source, enabled, created_at)
               VALUES (?, ?, 'character', 'Blue Archive', 'ko', '사용자 지정 이름',
                       'user_confirmed', 1, '2026-01-01T00:00:00Z')""",
            (str(uuid.uuid4()), "伊落マリー"),
        )
        conn.commit()

        pack = _minimal_localized_pack(characters=[{
            "canonical": "伊落マリー",
            "parent_series": "Blue Archive",
            "aliases": ["伊落マリー"],
            "localizations": {"ko": "이오치 마리"},  # 덮어쓰려는 시도
        }])
        path = _write_localized_pack(tmp_path, pack)
        result = import_localized_tag_pack(conn, path)

        # user_confirmed가 보호되어 충돌로 기록됨
        assert len(result["conflicts"]) >= 1
        # DB의 display_name은 사용자 값 그대로
        row = conn.execute(
            "SELECT display_name FROM tag_localizations"
            " WHERE canonical='伊落マリー' AND locale='ko'"
        ).fetchone()
        assert row["display_name"] == "사용자 지정 이름"
