"""tests/test_tag_pack_blue_archive_enrichment.py

Blue Archive tag pack 사전 보강 회귀 테스트.

Phase A 1차 (5 confirmed characters):
  - 角楯カリン / 白石ウタハ / 三香本ネル / 白見イオリ / 連川チェリノ

Phase A 2차 (28 new characters + 2 existing entry fixes):
  - 기존 수정: 佐城トモエ (사죠→사시로), 鷲見セリナ (와시미→스미)
  - 신규: 棗イロハ, 鬼怒川カスミ, 下倉メグ, 和楽チセ, 朝比奈フィーナ,
    勇美カエデ, 千鳥ミチル, 大野ツクヨ, 桑上カホ, 池倉マリナ, 天見ノドカ,
    間宵シグレ, 安守ミノリ, 姫木メル, 秋泉モミジ, 和泉元エイミ, 豊見コトリ,
    室笠アカネ, 乙花スミレ, 薬師サヤ, 朱城ルミ, 近衛ミナ, 戒野ミサキ,
    秤アツコ, 槌永ヒヨリ, 円堂シミコ, 仲正イチカ, 尾刃カンナ

Phase A 3차 (8 groups — BA 전용 정책):
  - ティーパーティー, 正義実現委員会, 補習授業部, セミナー,
    ゲーム開発部, Cleaning&Clearing, 万魔殿, 風紀委員会

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

# Phase A 2차 — 기존 항목 표기 수정 (ko/en 오류 수정)
CORRECTED_ENTRIES: list[tuple[str, str, str, list[str]]] = [
    # (canonical_ja, correct_ko, correct_en, legacy_aliases_must_survive)
    ("佐城トモエ", "사시로 토모에", "Sashiro Tomoe", ["사죠 토모에", "Sajo Tomoe"]),
    ("鷲見セリナ", "스미 세리나",   "Sumi Serina",   ["와시미 세리나", "Washimi Serina"]),
]

# Phase A 2차 — 신규 28명 (canonical_ja, ko, en) 튜플
PHASE_A2_CHARACTERS: list[tuple[str, str, str]] = [
    ("棗イロハ",    "나츠메 이로하",   "Natsume Iroha"),
    ("鬼怒川カスミ", "키누가와 카스미", "Kinugawa Kasumi"),
    ("下倉メグ",    "시모쿠라 메구",   "Shimokura Megu"),
    ("和楽チセ",    "와라쿠 치세",    "Waraku Chise"),
    ("朝比奈フィーナ","아사히나 피나",  "Asahina Pina"),
    ("勇美カエデ",  "이사미 카에데",   "Isami Kaede"),
    ("千鳥ミチル",  "치도리 미치루",   "Chidori Michiru"),
    ("大野ツクヨ",  "오노 츠쿠요",    "Oono Tsukuyo"),
    ("桑上カホ",    "쿠와카미 카호",   "Kuwakami Kaho"),
    ("池倉マリナ",  "이케쿠라 마리나", "Ikekura Marina"),
    ("天見ノドカ",  "아마미 노도카",   "Amami Nodoka"),
    ("間宵シグレ",  "마요이 시구레",   "Mayoi Shigure"),
    ("安守ミノリ",  "야스모리 미노리", "Yasumori Minori"),
    ("姫木メル",    "히메키 메루",    "Himeki Meru"),
    ("秋泉モミジ",  "아키이즈미 모미지","Akiizumi Momiji"),
    ("和泉元エイミ", "이즈미모토 에이미","Izumimoto Eimi"),
    ("豊見コトリ",  "토요미 코토리",   "Toyomi Kotori"),
    ("室笠アカネ",  "무로카사 아카네", "Murokasa Akane"),
    ("乙花スミレ",  "오토하나 스미레", "Otohana Sumire"),
    ("薬師サヤ",    "야쿠시 사야",    "Yakushi Saya"),
    ("朱城ルミ",    "아케시로 루미",   "Akeshiro Rumi"),
    ("近衛ミナ",    "코노에 미나",    "Konoe Mina"),
    ("戒野ミサキ",  "이마시노 미사키", "Imashino Misaki"),
    ("秤アツコ",    "하카리 아츠코",   "Hakari Atsuko"),
    ("槌永ヒヨリ",  "츠치나가 히요리", "Tsuchinaga Hiyori"),
    ("円堂シミコ",  "엔도우 시미코",   "Endo Shimiko"),
    ("仲正イチカ",  "나카마사 이치카", "Nakamasa Ichika"),
    ("尾刃カンナ",  "오가타 칸나",    "Ogata Kanna"),
]


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


# ---------------------------------------------------------------------------
# Phase A 2차 — 기존 항목 표기 수정 (静的 + DB)
# ---------------------------------------------------------------------------

class TestExistingEntryFixes:
    def test_corrected_ko_localizations_in_pack(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, correct_ko, correct_en, legacy in CORRECTED_ENTRIES:
            char = char_by_canonical.get(ja)
            assert char is not None, f"canonical 누락: {ja!r}"
            assert char["localizations"]["ko"] == correct_ko, (
                f"{ja!r} ko 수정 미반영: {char['localizations']['ko']!r} != {correct_ko!r}"
            )
            assert char["localizations"]["en"] == correct_en, (
                f"{ja!r} en 수정 미반영: {char['localizations']['en']!r} != {correct_en!r}"
            )

    def test_legacy_aliases_still_present(self):
        """구 표기 alias 가 하위 호환을 위해 aliases 배열에 남아 있어야 한다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, correct_ko, correct_en, legacy in CORRECTED_ENTRIES:
            char = char_by_canonical[ja]
            for old_alias in legacy:
                assert old_alias in char["aliases"], (
                    f"{ja!r}: 구 alias {old_alias!r} 가 aliases 에서 제거됨 — 하위 호환 파손"
                )

    def test_corrected_ko_aliases_present(self):
        """수정된 KR 표기가 aliases 배열에도 들어 있어야 한다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, correct_ko, correct_en, legacy in CORRECTED_ENTRIES:
            char = char_by_canonical[ja]
            assert correct_ko in char["aliases"], (
                f"{ja!r}: 수정 KR alias {correct_ko!r} 가 aliases 에 없음"
            )

    def test_corrected_ko_resolves_in_db(self, conn):
        """수정된 KR 표기로 DB에서 canonical 이 반환된다."""
        for ja, correct_ko, correct_en, legacy in CORRECTED_ENTRIES:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (correct_ko,),
            ).fetchone()
            assert row is not None, f"수정 KR alias 미등록: {correct_ko!r}"
            assert row["canonical"] == ja

    def test_legacy_aliases_still_resolve_in_db(self, conn):
        """구 alias 도 DB에서 같은 canonical 로 해소된다."""
        for ja, correct_ko, correct_en, legacy in CORRECTED_ENTRIES:
            for old_alias in legacy:
                row = conn.execute(
                    "SELECT canonical FROM tag_aliases "
                    "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                    (old_alias,),
                ).fetchone()
                assert row is not None, f"구 alias 미등록: {old_alias!r}"
                assert row["canonical"] == ja, (
                    f"구 alias {old_alias!r} 가 다른 canonical 로 연결됨: {row['canonical']!r}"
                )


# ---------------------------------------------------------------------------
# Phase A 2차 — 신규 28명 (静的 + DB)
# ---------------------------------------------------------------------------

class TestPhaseA2PackShape:
    def test_character_count_at_least_122(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert len(pack["characters"]) >= 122, (
            f"Phase A 2차 추가 후 최소 122명 기대, 실제: {len(pack['characters'])}"
        )

    def test_phase_a2_canonicals_present(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        canonicals = {c["canonical"] for c in pack["characters"]}
        for ja, ko, en in PHASE_A2_CHARACTERS:
            assert ja in canonicals, f"canonical 누락: {ja!r}"

    def test_phase_a2_ko_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A2_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["localizations"].get("ko") == ko, (
                f"{ja!r} ko 불일치: {char['localizations'].get('ko')!r} != {ko!r}"
            )

    def test_phase_a2_en_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A2_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["localizations"].get("en") == en, (
                f"{ja!r} en 불일치: {char['localizations'].get('en')!r} != {en!r}"
            )

    def test_phase_a2_ja_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A2_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["localizations"].get("ja") == ja, (
                f"{ja!r} ja localization 불일치: {char['localizations'].get('ja')!r}"
            )

    def test_phase_a2_parent_series(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A2_CHARACTERS:
            char = char_by_canonical[ja]
            assert char["parent_series"] == CANONICAL_SERIES

    def test_phase_a2_ko_aliases_present(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        char_by_canonical = {c["canonical"]: c for c in pack["characters"]}
        for ja, ko, en in PHASE_A2_CHARACTERS:
            char = char_by_canonical[ja]
            assert ko in char["aliases"], (
                f"{ja!r} aliases 에 KR 표기 누락: {ko!r}"
            )

    def test_version_at_least_1_6(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        major, minor, _ = (int(x) for x in pack["version"].split("."))
        assert (major, minor) >= (1, 6), (
            f"Phase A 2차 후 version >= 1.6.0 이어야 함: {pack['version']!r}"
        )


class TestPhaseA2CharactersSeeded:
    def test_ko_alias_resolves(self, conn):
        for ja, ko, en in PHASE_A2_CHARACTERS:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (ko,),
            ).fetchone()
            assert row is not None, f"KR alias 미등록: {ko!r}"
            assert row["canonical"] == ja

    def test_en_alias_resolves(self, conn):
        for ja, ko, en in PHASE_A2_CHARACTERS:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (en,),
            ).fetchone()
            assert row is not None, f"EN alias 미등록: {en!r}"
            assert row["canonical"] == ja

    def test_ko_localizations_in_db(self, conn):
        for ja, ko, en in PHASE_A2_CHARACTERS:
            row = conn.execute(
                "SELECT display_name FROM tag_localizations "
                "WHERE canonical = ? AND tag_type = 'character' AND locale = 'ko'",
                (ja,),
            ).fetchone()
            assert row is not None, f"ko localization 미등록: {ja!r}"
            assert row["display_name"] == ko


# ---------------------------------------------------------------------------
# Phase A 3차 — group/entity 8건 (静的 + DB)
# ---------------------------------------------------------------------------

# (canonical, ko, en, spot_check_aliases)
PHASE_A3_GROUPS: list[tuple[str, str, str, list[str]]] = [
    ("ティーパーティー", "티파티",           "Tea Party",               ["티파티", "Tea Party"]),
    ("正義実現委員会",   "정의실현부",        "Justice Task Force",       ["정의실현부", "Justice Task Force", "Justice Realization Committee"]),
    ("補習授業部",       "보충수업부",        "Make-Up Work Club",        ["보충수업부", "Make-Up Work Club", "Supplementary Lessons Club"]),
    ("セミナー",         "세미나",            "Seminar",                  ["세미나", "Seminar"]),
    ("ゲーム開発部",     "게임개발부",        "Game Development Department",["게임개발부", "Game Development Department", "Game Development Club"]),
    ("Cleaning&Clearing","클리닝&클리어링",   "Cleaning & Clearing",      ["C&C", "Cleaning & Clearing", "Cleaning and Clearing", "C and C", "클리닝&클리어링"]),
    ("万魔殿",           "판데모니움 소사이어티","Pandemonium Society",    ["판데모니움 소사이어티", "Pandemonium Society"]),
    ("風紀委員会",       "게헨나 선도부",     "Prefect Team",             ["게헨나 선도부", "선도부", "Prefect Team", "Disciplinary Committee"]),
]


class TestPhaseA3GroupPackShape:
    def test_group_count_at_least_9(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert len(pack.get("groups", [])) >= 9, (
            f"Phase A 3차 후 최소 9개 group 기대, 실제: {len(pack.get('groups', []))}"
        )

    def test_version_at_least_1_7(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        major, minor, _ = (int(x) for x in pack["version"].split("."))
        assert (major, minor) >= (1, 7), (
            f"Phase A 3차 후 version >= 1.7.0 이어야 함: {pack['version']!r}"
        )

    def test_all_groups_have_kind_group(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        for g in pack["groups"]:
            assert g.get("kind") == "group", (
                f"group entry {g['canonical']!r} 에 kind='group' 누락"
            )

    def test_phase_a3_canonicals_present(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        group_canonicals = {g["canonical"] for g in pack["groups"]}
        for canonical, ko, en, _ in PHASE_A3_GROUPS:
            assert canonical in group_canonicals, f"group canonical 누락: {canonical!r}"

    def test_phase_a3_ko_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        group_by_canonical = {g["canonical"]: g for g in pack["groups"]}
        for canonical, ko, en, _ in PHASE_A3_GROUPS:
            g = group_by_canonical[canonical]
            assert g["localizations"].get("ko") == ko, (
                f"{canonical!r} ko 불일치: {g['localizations'].get('ko')!r} != {ko!r}"
            )

    def test_phase_a3_en_localizations(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        group_by_canonical = {g["canonical"]: g for g in pack["groups"]}
        for canonical, ko, en, _ in PHASE_A3_GROUPS:
            g = group_by_canonical[canonical]
            assert g["localizations"].get("en") == en, (
                f"{canonical!r} en 불일치: {g['localizations'].get('en')!r} != {en!r}"
            )

    def test_phase_a3_spot_check_aliases(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        group_by_canonical = {g["canonical"]: g for g in pack["groups"]}
        for canonical, ko, en, spot_aliases in PHASE_A3_GROUPS:
            g = group_by_canonical[canonical]
            for alias in spot_aliases:
                assert alias in g["aliases"], (
                    f"{canonical!r}: alias {alias!r} 누락"
                )

    def test_cleaning_clearing_special_char_aliases(self):
        """C&C 특수문자 alias 전체 확인."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        g = next(x for x in pack["groups"] if x["canonical"] == "Cleaning&Clearing")
        for alias in ["C&C", "Cleaning&Clearing", "Cleaning & Clearing", "Cleaning and Clearing", "C and C"]:
            assert alias in g["aliases"], f"C&C alias 누락: {alias!r}"

    def test_gehenna_prefect_team_aliases(self):
        """게헨나 선도부는 '선도부' 단독 alias 도 포함해야 한다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        g = next(x for x in pack["groups"] if x["canonical"] == "風紀委員会")
        assert "선도부" in g["aliases"]
        assert "게헨나 선도부" in g["aliases"]
        assert "Prefect Team" in g["aliases"]

    def test_groups_have_parent_series(self):
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        for g in pack["groups"]:
            assert g.get("parent_series") == CANONICAL_SERIES, (
                f"group {g['canonical']!r} parent_series 불일치"
            )

    def test_characters_unchanged(self):
        """group 추가가 character 수를 건드리지 않았다."""
        pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        assert len(pack["characters"]) == 122


class TestPhaseA3GroupsSeeded:
    def test_ko_alias_resolves_to_group(self, conn):
        """KR alias 가 tag_type='group' 으로 DB에 등록된다."""
        for canonical, ko, en, _ in PHASE_A3_GROUPS:
            row = conn.execute(
                "SELECT canonical, tag_type FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'group' AND enabled = 1",
                (ko,),
            ).fetchone()
            assert row is not None, f"group KR alias 미등록: {ko!r}"
            assert row["canonical"] == canonical

    def test_en_alias_resolves_to_group(self, conn):
        for canonical, ko, en, _ in PHASE_A3_GROUPS:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'group' AND enabled = 1",
                (en,),
            ).fetchone()
            assert row is not None, f"group EN alias 미등록: {en!r}"
            assert row["canonical"] == canonical

    def test_cleaning_clearing_ampersand_alias_in_db(self, conn):
        """'Cleaning&Clearing' 과 'C&C' 가 DB 에 group 으로 등록된다."""
        for alias in ["Cleaning&Clearing", "C&C", "Cleaning & Clearing"]:
            row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'group' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert row is not None, f"C&C alias 미등록: {alias!r}"
            assert row["canonical"] == "Cleaning&Clearing"

    def test_seminar_registered_as_group_not_character(self, conn):
        """'세미나' / 'Seminar' 가 group 으로만 등록되고 character 로 등록되지 않는다."""
        for alias in ["세미나", "Seminar"]:
            char_row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'character' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert char_row is None, (
                f"{alias!r} 가 character 로도 등록됨 — group 충돌 위험"
            )
            group_row = conn.execute(
                "SELECT canonical FROM tag_aliases "
                "WHERE alias = ? AND tag_type = 'group' AND enabled = 1",
                (alias,),
            ).fetchone()
            assert group_row is not None, f"{alias!r} 가 group 으로 미등록"

    def test_ko_localizations_registered(self, conn):
        for canonical, ko, en, _ in PHASE_A3_GROUPS:
            row = conn.execute(
                "SELECT display_name FROM tag_localizations "
                "WHERE canonical = ? AND tag_type = 'group' AND locale = 'ko'",
                (canonical,),
            ).fetchone()
            assert row is not None, f"group ko localization 미등록: {canonical!r}"
            assert row["display_name"] == ko
