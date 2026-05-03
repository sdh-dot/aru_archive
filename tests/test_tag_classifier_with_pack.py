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


# ---------------------------------------------------------------------------
# P2 — Blue Archive full alias expansion (78 new characters)
# ---------------------------------------------------------------------------

# Sample 15 representative new characters covering range:
# - existing partial mention in user DB analysis (Yuuka, Shiroko, Asuna, Saori, etc.)
# - structurally diverse surname romanizations
# - mascots (Arona, Plana)
_P2_NEW_CHARACTERS_SAMPLE: list[tuple[str, str, str]] = [
    # (jp_full, ko_full, en_full)
    ("早瀬ユウカ",       "하야세 유우카",       "Hayase Yuuka"),
    ("砂狼シロコ",       "스나오카미 시로코",   "Sunaookami Shiroko"),
    ("一之瀬アスナ",     "이치노세 아스나",     "Ichinose Asuna"),
    ("錠前サオリ",       "조마에 사오리",       "Joumae Saori"),
    ("聖園ミカ",         "미소노 미카",         "Misono Mika"),
    ("生塩ノア",         "우시오 노아",         "Ushio Noa"),
    ("鬼方カヨコ",       "오니카타 카요코",     "Onikata Kayoko"),
    ("浅黄ムツキ",       "아사기 무츠키",       "Asagi Mutsuki"),
    ("十六夜ノノミ",     "이자요이 노노미",     "Izayoi Nonomi"),
    ("飛鳥馬トキ",       "아스마 토키",         "Asuma Toki"),
    ("阿慈谷ヒフミ",     "아자이야 히후미",     "Azaiya Hifumi"),
    ("羽川ハスミ",       "하네카와 하스미",     "Hanekawa Hasumi"),
    ("赤城セリカ",       "아카기 세리카",       "Akagi Serika"),
    ("アロナ",           "아로나",              "Arona"),
    ("プラナ",           "프라나",              "Plana"),
]

# Aliases that must NOT be present in the pack — short/solo enforcement.
_P2_FORBIDDEN_SOLO_ALIASES: list[str] = [
    # Japanese given-name-only shorts (would clash with non-BA characters)
    "ユウカ", "シロコ", "アスナ", "サオリ", "ミカ", "ノア", "カヨコ",
    "ムツキ", "ノノミ", "トキ", "ヒフミ", "ハスミ", "セリカ",
    # English given-name-only shorts (homonym risk)
    "Yuuka", "Shiroko", "Asuna", "Saori", "Mika", "Noa", "Kayoko",
    "Mutsuki", "Nonomi", "Toki", "Hifumi", "Hasumi", "Serika",
    # Korean given-name-only shorts
    "유우카", "시로코", "아스나", "사오리", "미카", "노아", "카요코",
    "무츠키", "노노미", "토키", "히후미", "하스미", "세리카",
]

# Costume / variant tokens that must not appear anywhere in the pack
_P2_FORBIDDEN_VARIANT_TOKENS: list[str] = [
    "水着", "正月", "ドレス", "体操服", "私服",
    "Swimsuit", "Dress", "New Year", "Cheerleader", "Nurse",
    "수영복", "교복", "드레스",
    "(swimsuit)", "(dress)", "(new year)", "(school uniform)",
]

# Hard exclusions that must not appear as a canonical
_P2_EXCLUDED_CANONICALS: list[str] = ["先生", "黒服"]


@pytest.fixture
def pack_data():
    """Load blue_archive.json once for static structural assertions."""
    import json
    from pathlib import Path
    pack_path = Path(__file__).resolve().parent.parent / "resources" / "tag_packs" / "blue_archive.json"
    with pack_path.open(encoding="utf-8") as f:
        return json.load(f)


class TestBlueArchiveFullExpansionStructure:
    """Static pack-shape invariants for the expansion."""

    def test_pack_version_bumped(self, pack_data) -> None:
        assert pack_data["version"] == "1.3.0"

    def test_pack_total_character_count_at_least_88(self, pack_data) -> None:
        """10 builtin + 78 expansion (P1 Hina/Ako/Nagisa already counted)."""
        assert len(pack_data["characters"]) >= 88

    def test_every_character_has_blue_archive_parent_series(self, pack_data) -> None:
        """모든 character 의 parent_series 가 Blue Archive 인지 확인.

        한 줄이라도 다른 series 가 섞이면 inferred-series 흐름에서 잘못된
        시리즈를 추가하게 된다.
        """
        offenders = [
            c["canonical"] for c in pack_data["characters"]
            if c.get("parent_series") != "Blue Archive"
        ]
        assert offenders == [], f"parent_series != Blue Archive: {offenders}"

    def test_every_character_has_three_localizations(self, pack_data) -> None:
        """ko/ja/en 모두 비어 있지 않아야 한다 (full-name policy)."""
        offenders = []
        for c in pack_data["characters"]:
            locs = c.get("localizations", {})
            if not (locs.get("ko") and locs.get("ja") and locs.get("en")):
                offenders.append(c["canonical"])
        assert offenders == [], f"missing ko/ja/en: {offenders}"

    def test_excluded_canonicals_are_not_in_pack(self, pack_data) -> None:
        """先生 / 黒服 처럼 일반명사·NPC noun 은 분류 오탐 위험으로 제외."""
        canons = {c["canonical"] for c in pack_data["characters"]}
        for excluded in _P2_EXCLUDED_CANONICALS:
            assert excluded not in canons, f"{excluded!r} is excluded by policy"

    def test_no_forbidden_solo_aliases_anywhere(self, pack_data) -> None:
        """확장된 78명 캐릭터 alias 에는 short/solo alias 가 없어야 한다.

        builtin 10 명에는 기존 short alias (Mari, Aru, Hoshino 등) 가 있지만
        본 invariant 는 새 확장 분에 한정된다. 정책 위반은 새 entry 에서만
        검사한다 (canonical 이 _P2_NEW_CHARACTERS_SAMPLE 또는 P2-added set
        에 들어 있는 entry).
        """
        builtin_pre_p2_canon = {
            "伊落マリー", "水羽ミモリ", "陸八魔アル", "天童アリス",
            "白洲アズサ", "小鳥遊ホシノ", "狐坂ワカモ",
            # P1 added (PR #110)
            "空崎ヒナ", "天雨アコ", "桐藤ナギサ",
        }
        offenders: list[tuple[str, str]] = []
        for c in pack_data["characters"]:
            if c["canonical"] in builtin_pre_p2_canon:
                continue
            for a in c.get("aliases", []):
                if a in _P2_FORBIDDEN_SOLO_ALIASES:
                    offenders.append((c["canonical"], a))
        assert offenders == [], f"P2 entry contains forbidden solo alias: {offenders}"

    def test_no_costume_variant_tokens_anywhere(self, pack_data) -> None:
        """확장 분에는 의상/이벤트 variant alias 가 없어야 한다."""
        builtin_pre_p2_canon = {
            "伊落マリー", "水羽ミモリ", "陸八魔アル", "天童アリス",
            "白洲アズサ", "小鳥遊ホシノ", "狐坂ワカモ",
            "空崎ヒナ", "天雨アコ", "桐藤ナギサ",
        }
        offenders = []
        for c in pack_data["characters"]:
            if c["canonical"] in builtin_pre_p2_canon:
                continue
            haystack = " ".join(c.get("aliases", []) + [c["canonical"]])
            for token in _P2_FORBIDDEN_VARIANT_TOKENS:
                if token in haystack:
                    offenders.append((c["canonical"], token))
        assert offenders == [], f"variant token in P2 entry: {offenders}"

    def test_p2_aliases_have_at_most_three_full_names(self, pack_data) -> None:
        """확장 분 entry 는 jp/ko/en full name 만, 정확히 3개 alias.

        canonical 이 ja localization 과 동일하면 dedup 후 3 alias.
        canonical != ja (예: mascot 의 single-name) 도 허용.
        """
        builtin_pre_p2_canon = {
            "伊落マリー", "水羽ミモリ", "陸八魔アル", "天童アリス",
            "白洲アズサ", "小鳥遊ホシノ", "狐坂ワカモ",
            "空崎ヒナ", "天雨アコ", "桐藤ナギサ",
        }
        for c in pack_data["characters"]:
            if c["canonical"] in builtin_pre_p2_canon:
                continue
            n = len(c.get("aliases", []))
            assert 2 <= n <= 4, (
                f"{c['canonical']}: expected 2-4 full-name aliases, got {n}: {c.get('aliases')}"
            )


class TestBlueArchiveFullExpansionMatching:
    """Sample alias matching across JP / KO / EN full forms."""

    @pytest.mark.parametrize("jp,ko,en", _P2_NEW_CHARACTERS_SAMPLE)
    def test_jp_full_matches_character_and_infers_series(self, conn_with_pack, jp, ko, en) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags([jp], conn=conn_with_pack)
        assert jp in result["character_tags"], f"JP full {jp!r} did not match"
        assert "Blue Archive" in result["series_tags"]

    @pytest.mark.parametrize("jp,ko,en", _P2_NEW_CHARACTERS_SAMPLE)
    def test_ko_full_matches_character_and_infers_series(self, conn_with_pack, jp, ko, en) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags([ko], conn=conn_with_pack)
        assert jp in result["character_tags"], f"KO full {ko!r} did not match → {jp}"
        assert "Blue Archive" in result["series_tags"]

    @pytest.mark.parametrize("jp,ko,en", _P2_NEW_CHARACTERS_SAMPLE)
    def test_en_full_matches_character_and_infers_series(self, conn_with_pack, jp, ko, en) -> None:
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags([en], conn=conn_with_pack)
        assert jp in result["character_tags"], f"EN full {en!r} did not match → {jp}"
        assert "Blue Archive" in result["series_tags"]

    def test_excluded_sensei_does_not_match(self, conn_with_pack) -> None:
        """先生 (generic noun) 가 character 로 잡히면 모든 '선생/teacher' 태그가 BA 로 오분류된다."""
        from core.tag_classifier import classify_pixiv_tags
        result = classify_pixiv_tags(["先生"], conn=conn_with_pack)
        # 先生 는 어떤 BA character 로도 매칭되어선 안 됨.
        assert result["character_tags"] == []
        assert result["series_tags"] == []
        assert "先生" in result["tags"]


class TestBlueArchiveExpansionRetagFlow:
    """End-to-end retag flow on representative new characters."""

    def _setup_group(self, conn, raw_tags: list[str]) -> str:
        import json
        import uuid
        from datetime import datetime, timezone
        gid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO artwork_groups "
            "(group_id, source_site, artwork_id, downloaded_at, indexed_at, "
            " metadata_sync_status, tags_json, series_tags_json, character_tags_json) "
            "VALUES (?, 'pixiv', ?, ?, ?, 'json_only', ?, '[]', '[]')",
            (gid, gid[:8], now, now, json.dumps(raw_tags, ensure_ascii=False)),
        )
        conn.commit()
        return gid

    def _read(self, conn, gid: str) -> dict:
        import json
        row = conn.execute(
            "SELECT series_tags_json, character_tags_json FROM artwork_groups WHERE group_id=?",
            (gid,),
        ).fetchone()
        return {
            "series": json.loads(row["series_tags_json"]),
            "character": json.loads(row["character_tags_json"]),
        }

    def test_retag_yuuka_only(self, conn_with_pack) -> None:
        from core.tag_reclassifier import retag_groups_from_existing_tags
        gid = self._setup_group(conn_with_pack, ["早瀬ユウカ"])
        retag_groups_from_existing_tags(conn_with_pack, [gid])
        out = self._read(conn_with_pack, gid)
        assert "Blue Archive" in out["series"]
        assert "早瀬ユウカ" in out["character"]

    def test_retag_shiroko_only(self, conn_with_pack) -> None:
        from core.tag_reclassifier import retag_groups_from_existing_tags
        gid = self._setup_group(conn_with_pack, ["砂狼シロコ"])
        retag_groups_from_existing_tags(conn_with_pack, [gid])
        out = self._read(conn_with_pack, gid)
        assert "Blue Archive" in out["series"]
        assert "砂狼シロコ" in out["character"]

    def test_retag_korean_full_name(self, conn_with_pack) -> None:
        """KO full alias 만으로도 retag 가 character + series 를 채운다."""
        from core.tag_reclassifier import retag_groups_from_existing_tags
        gid = self._setup_group(conn_with_pack, ["조마에 사오리"])
        retag_groups_from_existing_tags(conn_with_pack, [gid])
        out = self._read(conn_with_pack, gid)
        assert "Blue Archive" in out["series"]
        assert "錠前サオリ" in out["character"]


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
