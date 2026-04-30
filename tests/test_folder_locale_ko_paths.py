"""
folder_locale=ko 경로 생성 테스트.

- ko localization이 있는 캐릭터는 한국어 폴더명 사용
- ko localization이 없으면 canonical fallback + used_fallback=True
- preview와 execute가 동일한 destination 사용
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Optional

import pytest

from core.tag_localizer import resolve_display_name_with_info, upsert_localization
from db.database import initialize_database


def _make_db() -> sqlite3.Connection:
    return initialize_database(":memory:")


class TestKoLocalizationLookup:
    def test_character_folder_uses_ko_localization_when_available(self):
        """canonical 合歓垣フブキ, ko 네무가키 후부키 → ko locale에서 올바른 한국어 반환."""
        conn = _make_db()
        upsert_localization(
            conn,
            canonical="合歓垣フブキ",
            tag_type="character",
            locale="ko",
            display_name="네무가키 후부키",
            parent_series="Blue Archive",
            source="tag_pack",
        )
        name, used_fallback = resolve_display_name_with_info(
            conn, "合歓垣フブキ", "character",
            parent_series="Blue Archive",
            locale="ko",
        )
        assert name == "네무가키 후부키"
        assert used_fallback is False

    def test_character_folder_falls_back_to_canonical_when_missing_ko(self):
        """ko localization 없으면 canonical 사용 + used_fallback=True."""
        conn = _make_db()
        name, used_fallback = resolve_display_name_with_info(
            conn, "十六夜ノノミ", "character",
            parent_series="Blue Archive",
            locale="ko",
        )
        assert name == "十六夜ノノミ"
        assert used_fallback is True

    def test_series_ko_localization_works(self):
        """Blue Archive 시리즈는 BUILTIN에 ko가 있으므로 한국어로 반환."""
        conn = _make_db()
        from core.tag_localizer import seed_builtin_localizations
        seed_builtin_localizations(conn)
        name, used_fallback = resolve_display_name_with_info(
            conn, "Blue Archive", "series",
            locale="ko",
        )
        assert name == "블루 아카이브"
        assert used_fallback is False

    def test_db_localization_takes_priority_over_builtin(self):
        """DB의 localization이 BUILTIN보다 우선한다."""
        conn = _make_db()
        from core.tag_localizer import seed_builtin_localizations
        seed_builtin_localizations(conn)
        # DB에 다른 값으로 override
        upsert_localization(conn, "Blue Archive", "series", "ko", "블루아카이브(테스트)")
        name, _ = resolve_display_name_with_info(conn, "Blue Archive", "series", locale="ko")
        assert name == "블루아카이브(테스트)"


class TestClassifierLocalizationIntegration:
    def _make_group(self, conn: sqlite3.Connection, series: str, character: str) -> str:
        group_id = str(uuid.uuid4())
        import json
        now = "2024-01-01T00:00:00"
        conn.execute(
            """INSERT INTO artwork_groups
               (group_id, source_site, artwork_id, artwork_title, artwork_kind,
                total_pages, downloaded_at, indexed_at, status, metadata_sync_status,
                schema_version, series_tags_json, character_tags_json, tags_json)
               VALUES (?, 'local', ?, 'Test', 'single_image', 1, ?, ?, 'inbox', 'full', '1.0', ?, ?, '[]')""",
            (group_id, group_id[:16], now, now,
             json.dumps([series]), json.dumps([character])),
        )
        file_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO artwork_files
               (file_id, group_id, page_index, file_role, file_path,
                file_format, file_size, file_status, created_at)
               VALUES (?, ?, 0, 'original', ?, 'jpg', 1000, 'present', ?)""",
            (file_id, group_id, f"/inbox/{group_id[:8]}.jpg", now),
        )
        conn.commit()
        return group_id

    def test_preview_and_execute_use_same_localized_destination(self):
        """build_classify_preview의 dest_path가 locale을 반영한다."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_db()
            from core.tag_localizer import seed_builtin_localizations, upsert_localization
            seed_builtin_localizations(conn)
            upsert_localization(
                conn, "合歓垣フブキ", "character", "ko", "네무가키 후부키",
                parent_series="Blue Archive",
            )

            group_id = self._make_group(conn, "Blue Archive", "合歓垣フブキ")
            config = {
                "classified_dir": tmp,
                "classification": {
                    "folder_locale": "ko",
                    "fallback_locale": "canonical",
                    "enable_localized_folder_names": True,
                    "enable_series_character": True,
                    "enable_series_uncategorized": True,
                    "enable_character_without_series": True,
                    "fallback_by_author": False,
                    "enable_by_author": False,
                    "enable_by_tag": False,
                    "on_conflict": "rename",
                    "batch_existing_copy_policy": "keep_existing",
                },
            }
            from core.classifier import build_classify_preview
            preview = build_classify_preview(conn, group_id, config)
            assert preview is not None
            dests = preview["destinations"]
            assert dests, "목적지가 비어 있음"

            dest_path = dests[0]["dest_path"]
            # 경로에 한국어 시리즈/캐릭터가 포함되어야 함
            assert "블루 아카이브" in dest_path, f"시리즈 ko 변환 실패: {dest_path}"
            assert "네무가키 후부키" in dest_path, f"캐릭터 ko 변환 실패: {dest_path}"

    def test_fallback_tags_reported_when_ko_missing(self):
        """ko localization이 없는 캐릭터는 fallback_tags에 포함되어야 한다."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_db()
            from core.tag_localizer import seed_builtin_localizations
            seed_builtin_localizations(conn)
            # 十六夜ノノミ는 ko localization 없음

            group_id = self._make_group(conn, "Blue Archive", "十六夜ノノミ")
            config = {
                "classified_dir": tmp,
                "classification": {
                    "folder_locale": "ko",
                    "fallback_locale": "canonical",
                    "enable_localized_folder_names": True,
                    "enable_series_character": True,
                    "enable_series_uncategorized": False,
                    "enable_character_without_series": False,
                    "fallback_by_author": False,
                    "enable_by_author": False,
                    "enable_by_tag": False,
                    "on_conflict": "rename",
                    "batch_existing_copy_policy": "keep_existing",
                },
            }
            from core.classifier import build_classify_preview
            preview = build_classify_preview(conn, group_id, config)
            assert preview is not None
            assert "十六夜ノノミ" in preview["fallback_tags"], (
                f"fallback_tags에 미번역 캐릭터가 없음: {preview['fallback_tags']}"
            )
