"""
localized tag pack import 테스트.

- ko/ja localizations가 tag_localizations에 저장됨
- _review 필드가 있어도 import 실패하지 않음
- merge_candidate는 자동 병합되지 않음
- review_items count 반환
- 기존 localization conflict report 생성
- import 후 resolve_display_name(locale='ko') 동작
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.tag_pack_loader import (
    import_localized_tag_pack,
    validate_localized_tag_pack,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _write_pack(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "test_localized.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _minimal_pack(extras: list[dict] | None = None) -> dict:
    chars = [
        {
            "aliases": ["wakamo"],
            "canonical": "狐坂ワカモ",
            "localizations": {"en": "Kosaka Wakamo", "ja": "狐坂ワカモ", "ko": "코사카 와카모"},
            "parent_series": "Blue Archive",
        }
    ]
    if extras:
        chars.extend(extras)
    return {
        "pack_id": "test_localized",
        "name": "Test Localized Pack",
        "version": "1.0.0",
        "source": "user_export",
        "series": [
            {
                "aliases": ["Blue Archive"],
                "canonical": "Blue Archive",
                "localizations": {"en": "Blue Archive", "ja": "ブルーアーカイブ", "ko": "블루 아카이브"},
            }
        ],
        "characters": chars,
    }


class TestValidateLocalizedTagPack:
    def test_valid_pack_returns_valid(self, tmp_path):
        path = _write_pack(tmp_path, _minimal_pack())
        result = validate_localized_tag_pack(path)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_invalid_json_returns_error(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        result = validate_localized_tag_pack(p)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_counts_review_items(self, tmp_path):
        pack = _minimal_pack([
            {
                "aliases": ["short_mari"],
                "canonical": "Mari",
                "localizations": {"en": "Mari"},
                "parent_series": "Blue Archive",
                "_review": {
                    "merge_candidate": "伊落マリー",
                    "reason": "short name",
                    "needs_merge_review": True,
                },
            }
        ])
        path = _write_pack(tmp_path, pack)
        result = validate_localized_tag_pack(path)
        assert result["valid"] is True
        assert result["stats"]["review_items"] >= 1

    def test_review_field_does_not_break_validation(self, tmp_path):
        pack = _minimal_pack([
            {
                "aliases": ["x"],
                "canonical": "X",
                "localizations": {},
                "parent_series": "Test",
                "_review": {"possibly_general_or_group_tag": True},
            }
        ])
        path = _write_pack(tmp_path, pack)
        result = validate_localized_tag_pack(path)
        assert result["valid"] is True


class TestImportLocalizedTagPack:
    def test_ko_ja_localizations_stored(self, db, tmp_path):
        path = _write_pack(tmp_path, _minimal_pack())
        result = import_localized_tag_pack(db, path)
        assert result["localizations"] >= 2  # ko + ja for ワカモ

        rows = db.execute(
            "SELECT locale, display_name FROM tag_localizations "
            "WHERE canonical='狐坂ワカモ'",
        ).fetchall()
        locales = {r["locale"]: r["display_name"] for r in rows}
        assert locales.get("ko") == "코사카 와카모"
        assert locales.get("ja") == "狐坂ワカモ"

    def test_review_field_does_not_fail_import(self, db, tmp_path):
        pack = _minimal_pack([
            {
                "aliases": ["short"],
                "canonical": "ShortChar",
                "localizations": {"en": "Short"},
                "parent_series": "Test",
                "_review": {"merge_candidate": "LongChar", "reason": "test"},
            }
        ])
        path = _write_pack(tmp_path, pack)
        result = import_localized_tag_pack(db, path)
        assert result is not None
        assert "localizations" in result

    def test_merge_candidate_not_auto_merged(self, db, tmp_path):
        # ShortChar와 LongChar가 각각 별도 canonical로 남아야 함
        pack = _minimal_pack([
            {
                "aliases": ["short"],
                "canonical": "ShortChar",
                "localizations": {"en": "Short"},
                "parent_series": "Test",
                "_review": {"merge_candidate": "LongChar"},
            },
            {
                "aliases": ["long"],
                "canonical": "LongChar",
                "localizations": {"en": "Long"},
                "parent_series": "Test",
            },
        ])
        path = _write_pack(tmp_path, pack)
        result = import_localized_tag_pack(db, path)

        # 두 canonical이 각각 존재해야 함
        rows = db.execute(
            "SELECT canonical FROM tag_aliases "
            "WHERE canonical IN ('ShortChar', 'LongChar')"
        ).fetchall()
        canonicals = {r["canonical"] for r in rows}
        assert "ShortChar" in canonicals
        assert "LongChar" in canonicals

    def test_merge_candidate_count_in_report(self, db, tmp_path):
        pack = _minimal_pack([
            {
                "aliases": ["m1"],
                "canonical": "MergeMe",
                "localizations": {},
                "parent_series": "Test",
                "_review": {"merge_candidate": "TargetChar"},
            }
        ])
        path = _write_pack(tmp_path, pack)
        result = import_localized_tag_pack(db, path)
        assert result["merge_candidates"] >= 1
        assert result["review_items"] >= 1

    def test_variant_items_counted(self, db, tmp_path):
        pack = _minimal_pack([
            {
                "aliases": ["variant_char"],
                "canonical": "VariantChar",
                "localizations": {},
                "parent_series": "Test",
                "_review": {"variant_tag": True, "base_character_candidate": "BaseChar"},
            }
        ])
        path = _write_pack(tmp_path, pack)
        result = import_localized_tag_pack(db, path)
        assert result["variant_items"] >= 1

    def test_conflict_with_user_source_reported(self, db, tmp_path):
        # 미리 user source localization 등록
        lid = str(uuid.uuid4())
        db.execute(
            """INSERT INTO tag_localizations
               (localization_id, canonical, tag_type, parent_series,
                locale, display_name, source, enabled, created_at)
               VALUES (?, '狐坂ワカモ', 'character', 'Blue Archive',
                       'ko', '다른표시명', 'user', 1, ?)""",
            (lid, _now()),
        )
        db.commit()

        path = _write_pack(tmp_path, _minimal_pack())
        result = import_localized_tag_pack(db, path)
        # conflict가 감지되어야 함
        assert any(
            c["canonical"] == "狐坂ワカモ" and c["locale"] == "ko"
            for c in result["conflicts"]
        )
        # 기존 user source 값이 유지됨
        row = db.execute(
            "SELECT display_name FROM tag_localizations "
            "WHERE canonical='狐坂ワカモ' AND locale='ko' AND source='user'",
        ).fetchone()
        assert row is not None
        assert row["display_name"] == "다른표시명"

    def test_resolve_display_name_after_import(self, db, tmp_path):
        path = _write_pack(tmp_path, _minimal_pack())
        import_localized_tag_pack(db, path)

        from core.tag_localizer import resolve_display_name
        ko_name = resolve_display_name(db, "狐坂ワカモ", "character",
                                       parent_series="Blue Archive", locale="ko")
        assert ko_name == "코사카 와카모"

    def test_aliases_inserted_to_tag_aliases(self, db, tmp_path):
        path = _write_pack(tmp_path, _minimal_pack())
        result = import_localized_tag_pack(db, path)
        assert result["character_aliases"] >= 1
        row = db.execute(
            "SELECT canonical FROM tag_aliases WHERE alias='wakamo' AND tag_type='character'"
        ).fetchone()
        assert row is not None
        assert row["canonical"] == "狐坂ワカモ"
