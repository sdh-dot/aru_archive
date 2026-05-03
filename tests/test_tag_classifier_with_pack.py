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


class TestBlueArchiveCoreCharactersP1:
    """Blue Archive 1차 핵심 캐릭터 alias 보강 회귀 lock.

    실 사용자 DB 에서 분류 실패가 확인된 3명 (ヒナ / アコ / ナギサ) 의
    canonical / 일본어 단축 / 한국어 풀네임 / 한국어 단축 / 영문 풀네임이
    모두 매칭되어야 한다. 영어 단독 (Hina/Ako/Nagisa) 은 동명이인 위험으로
    pack 에서 의도적으로 제외했으므로 본 테스트도 검증하지 않는다.
    """

    # ---- 空崎ヒナ (Sorasaki Hina / 소라사키 히나) ------------------------

    def test_hina_canonical_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["空崎ヒナ"], conn=conn_with_pack)
        assert "空崎ヒナ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_hina_short_japanese_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ヒナ"], conn=conn_with_pack)
        assert "空崎ヒナ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_hina_korean_full_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["소라사키 히나"], conn=conn_with_pack)
        assert "空崎ヒナ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_hina_korean_short_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["히나"], conn=conn_with_pack)
        assert "空崎ヒナ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_hina_english_full_alias(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Sorasaki Hina"], conn=conn_with_pack)
        assert "空崎ヒナ" in result["character_tags"]

    # ---- 天雨アコ (Amau Ako / 아마우 아코) -------------------------------

    def test_ako_canonical_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["天雨アコ"], conn=conn_with_pack)
        assert "天雨アコ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_ako_short_japanese_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["アコ"], conn=conn_with_pack)
        assert "天雨アコ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_ako_korean_full_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["아마우 아코"], conn=conn_with_pack)
        assert "天雨アコ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_ako_korean_short_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["아코"], conn=conn_with_pack)
        assert "天雨アコ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_ako_english_full_alias(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Amau Ako"], conn=conn_with_pack)
        assert "天雨アコ" in result["character_tags"]

    # ---- 桐藤ナギサ (Kirifuji Nagisa / 키리후지 나기사) ------------------

    def test_nagisa_canonical_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["桐藤ナギサ"], conn=conn_with_pack)
        assert "桐藤ナギサ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_nagisa_short_japanese_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["ナギサ"], conn=conn_with_pack)
        assert "桐藤ナギサ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_nagisa_korean_full_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["키리후지 나기사"], conn=conn_with_pack)
        assert "桐藤ナギサ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_nagisa_korean_short_infers_blue_archive(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["나기사"], conn=conn_with_pack)
        assert "桐藤ナギサ" in result["character_tags"]
        assert "Blue Archive" in result["series_tags"]

    def test_nagisa_english_full_alias(self, conn_with_pack) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["Kirifuji Nagisa"], conn=conn_with_pack)
        assert "桐藤ナギサ" in result["character_tags"]

    # ---- English-only solo aliases must remain unmatched -----------------

    def test_english_solo_aliases_excluded(self, conn_with_pack) -> None:
        """동명이인 위험으로 1차 PR 에서 의도적으로 제외한 solo 영어.

        이 invariant 가 깨지면 누군가 'Hina' / 'Ako' / 'Nagisa' alias 를
        섣불리 추가한 것이며 다른 시리즈 캐릭터와 충돌할 수 있다.
        """
        from core.tag_classifier import classify_pixiv_tags
        for solo in ("Hina", "Ako", "Nagisa"):
            result = classify_pixiv_tags([solo], conn=conn_with_pack)
            assert result["character_tags"] == [], (
                f"solo English alias {solo!r} 가 매칭됨 — 1차 PR 정책 위반"
            )

    # ---- retag flow: tags_json → series/character DB columns -------------

    def test_retag_populates_series_for_hina_only_tag(self, conn_with_pack, tmp_path) -> None:
        """tags_json 에 캐릭터만 있어도 retag 후 series_tags_json 에 BA 가 들어간다.

        실 사용자 시나리오: enrichment 가 Pixiv API raw 만 가져오고 series
        토큰이 빠졌을 때, retag 가 character alias 의 parent_series 로
        series 를 역추론하는 흐름.
        """
        import json
        import uuid
        from datetime import datetime, timezone
        from core.tag_reclassifier import retag_groups_from_existing_tags

        gid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn_with_pack.execute(
            "INSERT INTO artwork_groups "
            "(group_id, source_site, artwork_id, downloaded_at, indexed_at, "
            " metadata_sync_status, tags_json, series_tags_json, character_tags_json) "
            "VALUES (?, 'pixiv', '99999', ?, ?, 'json_only', ?, '[]', '[]')",
            (gid, now, now, json.dumps(["空崎ヒナ"], ensure_ascii=False)),
        )
        conn_with_pack.commit()

        result = retag_groups_from_existing_tags(conn_with_pack, [gid])
        assert result["updated"] == 1

        row = conn_with_pack.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups WHERE group_id=?",
            (gid,),
        ).fetchone()
        assert "Blue Archive" in json.loads(row["series_tags_json"])
        assert "空崎ヒナ" in json.loads(row["character_tags_json"])


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
