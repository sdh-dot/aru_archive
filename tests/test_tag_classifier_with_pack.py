"""
태그 팩 + normalize를 통합한 tag_classifier 테스트.

DB alias (태그 팩) 우선 → built-in alias → 정규화 매칭 순서 검증.
"""
from __future__ import annotations

import pytest

from db.database import initialize_database


@pytest.fixture
def conn(tmp_path):
    db = str(tmp_path / "test.db")
    c = initialize_database(db)
    yield c
    c.close()


@pytest.fixture
def conn_with_pack(conn):
    """blue_archive.json을 시드한 DB 연결."""
    from core.tag_pack_loader import seed_builtin_tag_packs
    seed_builtin_tag_packs(conn)
    return conn


class TestClassifyWithPack:
    def test_series_alias_from_pack(self, conn_with_pack) -> None:
        """팩에 있는 시리즈 alias가 분류된다."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ブルーアーカイブ", "落書き"], conn=conn_with_pack)
        assert "Blue Archive" in result["series_tags"]
        assert "ブルーアーカイブ" not in result["tags"]

    def test_character_alias_from_pack_with_series_context(self, conn_with_pack) -> None:
        """팩 캐릭터 alias → canonical + 소속 시리즈 자동 추가."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["マリー", "ブルアカ"], conn=conn_with_pack)
        assert "伊落マリー" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_character_alone_infers_series(self, conn_with_pack) -> None:
        """캐릭터 alias만 있어도 parent_series가 series_tags에 추가된다."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["マリー"], conn=conn_with_pack)
        assert "伊落マリー" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_fullwidth_series_normalized(self, conn_with_pack) -> None:
        """ＢｌｕｅＡｒｃｈｉｖｅ (전각) → normalize → Blue Archive."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ＢｌｕｅＡｒｃｈｉｖｅ"], conn=conn_with_pack)
        assert "Blue Archive" in result["series_tags"]
        assert "ＢｌｕｅＡｒｃｈｉｖｅ" not in result["tags"]

    def test_builtin_alias_without_db(self) -> None:
        """conn=None이면 built-in만 사용하고 정상 분류된다."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ブルアカ"])
        assert "Blue Archive" in result["series_tags"]

    def test_db_alias_overrides_builtin(self, conn) -> None:
        """DB alias가 built-in을 override한다."""
        from core.tag_classifier import classify_pixiv_tags
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO tag_aliases
               (alias, canonical, tag_type, parent_series, source, enabled, created_at)
               VALUES (?, 'CustomSeries', 'series', '', 'test', 1, ?)""",
            ("ブルアカ", now),
        )
        conn.commit()
        result = classify_pixiv_tags(["ブルアカ"], conn=conn)
        # DB alias가 built-in보다 우선 (dict.update로 덮어씀)
        assert "CustomSeries" in result["series_tags"]

    def test_nakaguro_variant_normalized(self, conn_with_pack) -> None:
        """リクハチマ アル (공백) → normalize → 陸八魔アル 매칭."""
        from core.tag_classifier import classify_pixiv_tags
        # "リクハチマ アル" 는 팩에 없지만 normalize 시 "リクハチマアル"
        # 팩에 "リクハチマ・アル" (중점) → normalize → "リクハチマアル" → 매칭
        result = classify_pixiv_tags(["リクハチマ アル"], conn=conn_with_pack)
        assert "陸八魔アル" in result["character_tags"]

    def test_english_character_alias_from_pack(self, conn_with_pack) -> None:
        """영어 character alias도 분류된다."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Rikuhachima Aru"], conn=conn_with_pack)
        assert "陸八魔アル" in result["character_tags"]

    def test_unmatched_tags_stay_general(self, conn_with_pack) -> None:
        """alias에 없는 태그는 general tags로 남는다."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["未知のタグ", "another_unknown"], conn=conn_with_pack)
        assert "未知のタグ" in result["tags"]
        assert "another_unknown" in result["tags"]
        assert result["series_tags"] == []
        assert result["character_tags"] == []

    def test_multiple_characters(self, conn_with_pack) -> None:
        """여러 캐릭터가 동시에 분류된다."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["マリー", "アル", "ミモリ"], conn=conn_with_pack)
        assert "伊落マリー" in result["character_tags"]
        assert "陸八魔アル" in result["character_tags"]
        assert "水羽ミモリ" in result["character_tags"]


class TestWakamoAliases:
    def test_blue_archive_with_wakamo_halfwidth_parens(self, conn_with_pack) -> None:
        """raw tags ["Blue Archive", "ワカモ(正月)"] → 올바른 분류."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Blue Archive", "ワカモ(正月)"], conn=conn_with_pack)
        assert result["series_tags"] == ["Blue Archive"]
        assert result["character_tags"] == ["狐坂ワカモ"]

    def test_blua_with_asagi_wakamo_halfwidth_parens(self, conn_with_pack) -> None:
        """raw tags ["ブルアカ", "浅黄ワカモ(正月)"] → 캐릭터 분류."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ブルアカ", "浅黄ワカモ(正月)"], conn=conn_with_pack)
        assert "狐坂ワカモ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_wakamo_fullwidth_parens_via_normalize(self, conn_with_pack) -> None:
        """ワカモ（正月）(전각 괄호) → normalize → ワカモ(正月) alias 매칭."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ワカモ（正月）"], conn=conn_with_pack)
        assert "狐坂ワカモ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_asagi_wakamo_fullwidth_parens_via_normalize(self, conn_with_pack) -> None:
        """浅黄ワカモ（正月）(전각 괄호) → normalize 매칭."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["浅黄ワカモ（正月）"], conn=conn_with_pack)
        assert "狐坂ワカモ" in result["character_tags"]

    def test_wakamo_canonical_alias(self, conn_with_pack) -> None:
        """狐坂ワカモ canonical alias 직접 매칭."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["狐坂ワカモ"], conn=conn_with_pack)
        assert "狐坂ワカモ" in result["character_tags"]

    def test_wakamo_english_alias(self, conn_with_pack) -> None:
        """Kosaka Wakamo 영문 alias 매칭."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Kosaka Wakamo"], conn=conn_with_pack)
        assert "狐坂ワカモ" in result["character_tags"]

    def test_wakamo_korean_alias(self, conn_with_pack) -> None:
        """한국어 alias 매칭."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["코사카 와카모"], conn=conn_with_pack)
        assert "狐坂ワカモ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_wakamo_infers_blue_archive_series(self, conn_with_pack) -> None:
        """ワカモ alias만 있어도 parent_series Blue Archive 자동 추가."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ワカモ"], conn=conn_with_pack)
        assert "狐坂ワカモ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]


class TestSinglePreviewLocalizedPath:
    def test_wakamo_single_preview_ko_path(self, conn_with_pack, tmp_path) -> None:
        """단일 분류 미리보기에서 ko locale로 BySeries/블루 아카이브/코사카 와카모/ 경로 생성."""
        import json
        import uuid
        from datetime import datetime, timezone
        from core.classifier import build_classify_preview
        from core.tag_localizer import seed_builtin_localizations

        seed_builtin_localizations(conn_with_pack)

        now = datetime.now(timezone.utc).isoformat()
        gid = str(uuid.uuid4())
        src = tmp_path / "wakamo.jpg"
        src.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        conn_with_pack.execute(
            """INSERT INTO artwork_groups
               (group_id, artwork_id, artwork_title, artist_name,
                series_tags_json, character_tags_json, tags_json,
                metadata_sync_status, downloaded_at, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'full', ?, ?)""",
            (
                gid, f"art-{gid[:8]}", "ワカモ(正月)作品", "test_artist",
                json.dumps(["Blue Archive"]),
                json.dumps(["狐坂ワカモ"]),
                json.dumps(["Blue Archive", "ワカモ(正月)"]),
                now, now,
            ),
        )
        conn_with_pack.execute(
            """INSERT INTO artwork_files
               (file_id, group_id, file_path, file_format,
                file_role, file_status, file_size, created_at)
               VALUES (?, ?, ?, 'jpg', 'original', 'present', 512, ?)""",
            (str(uuid.uuid4()), gid, str(src), now),
        )
        conn_with_pack.commit()

        cls_dir = str(tmp_path / "cls")
        config = {
            "classified_dir": cls_dir,
            "classification": {
                "folder_locale": "ko",
                "on_conflict": "rename",
                "series_rule": "series_only",
                "character_rule": "series_character",
                "fallback_rule": "artist",
                "tag_rule": "none",
            },
        }
        preview = build_classify_preview(conn_with_pack, gid, config)
        assert preview is not None
        paths = [d["dest_path"] for d in preview["destinations"]]
        assert any("블루 아카이브" in p for p in paths), f"paths={paths}"
        assert any("코사카 와카모" in p for p in paths), f"paths={paths}"
