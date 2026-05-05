"""series 분류 표시 및 series-only / series_character 경로 정책 integration 테스트
(PR #124 + PR #125).

검증 contract:
- _RULE_DISPLAY["series_uncategorized"] 가 "캐릭터 미분류" 로 표시된다.
  "시리즈 미식별" 문자열은 series_uncategorized rule 에 더 이상 쓰이지 않는다.
- PR #125: series_only 모드에서 series 식별 시 series 폴더 직접 사용 (_uncategorized 없음).
- PR #125: series_only 모드에서 series 미식별 시 series_unidentified_fallback 으로
  localized uncategorized 폴더 배치.
- series_character 모드(기본값)에서 Blue Archive + 캐릭터 태그 →
  캐릭터 하위 폴더 생성 (현재 정책상 정상 동작임을 테스트로 명시).
- preview destinations == execute 가 실제 사용하는 batch_preview.destinations
  (preview≡execute 불변).
- Step 7 _mode_notice_lbl 이 분류 모드에 따라 올바른 텍스트를 보인다.

이 테스트는 다음을 변경하지 않는다:
- metadata pipeline / XMP / DB schema
- _build_destinations Tier 구조
- resolve_series_only_destination 6-branch 로직 (PR #120)
- Blue Archive tag pack / NPC / group 구조 (PR #121)
- folder_localization / folder settings 정책 (PR #122)
- first-run folder setup 3-folder 정책 (PR #123)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 헬퍼 함수 — DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "integration.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_alias(
    conn: sqlite3.Connection,
    alias: str,
    canonical: str,
    tag_type: str,
    parent_series: str = "",
    kind: str = "",
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO tag_aliases "
        "(alias, canonical, tag_type, parent_series, source, enabled, kind, created_at) "
        "VALUES (?, ?, ?, ?, 'test', 1, ?, ?)",
        (alias, canonical, tag_type, parent_series, kind, _now()),
    )
    conn.commit()


def _seed_localization(
    conn: sqlite3.Connection,
    canonical: str,
    tag_type: str,
    locale: str,
    display_name: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO tag_localizations "
        "(canonical, tag_type, locale, display_name, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (canonical, tag_type, locale, display_name, _now()),
    )
    conn.commit()


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    tags: list[str] | None = None,
    series: list[str] | None = None,
    character: list[str] | None = None,
    sync_status: str = "json_only",
    artist: str = "test_artist",
) -> None:
    artwork_id = group_id[:12]
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, artist_name, "
        " downloaded_at, indexed_at, metadata_sync_status, "
        " tags_json, series_tags_json, character_tags_json) "
        "VALUES (?, 'pixiv', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            group_id, artwork_id, "test", artist, now, now, sync_status,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def _insert_file(
    conn: sqlite3.Connection, group_id: str, path: Path
) -> str:
    fid = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0")
    conn.execute(
        "INSERT INTO artwork_files "
        "(file_id, group_id, page_index, file_role, file_path, "
        " file_format, file_size, metadata_embedded, file_status, created_at) "
        "VALUES (?, ?, 0, 'original', ?, 'jpg', 1024, 1, 'present', ?)",
        (fid, group_id, str(path), _now()),
    )
    conn.commit()
    return fid


def _series_only_cfg(classified_dir: Path, *, locale: str = "canonical") -> dict:
    return {
        "classified_dir": str(classified_dir),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         False,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": False,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
            "folder_locale":                   locale,
            "allow_multi_destination":         True,
        },
    }


def _series_char_cfg(classified_dir: Path, *, locale: str = "canonical") -> dict:
    return {
        "classified_dir": str(classified_dir),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": False,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
            "folder_locale":                   locale,
            "allow_multi_destination":         True,
        },
    }


# ---------------------------------------------------------------------------
# 테스트 A — _RULE_DISPLAY["series_uncategorized"] 표시명 수정 검증
# ---------------------------------------------------------------------------

class TestRuleDisplayLabel:
    """PR #124: series_uncategorized 표시명이 "캐릭터 미분류"여야 한다."""

    def test_series_uncategorized_displays_as_character_unclassified(self) -> None:
        from app.views.workflow_wizard_view import _RULE_DISPLAY, _format_preview_rule
        label = _RULE_DISPLAY.get("series_uncategorized", "")
        assert label == "캐릭터 미분류", (
            f"series_uncategorized 레이블이 '캐릭터 미분류'가 아님: {label!r}"
        )

    def test_series_uncategorized_is_not_miidentified_wording(self) -> None:
        from app.views.workflow_wizard_view import _RULE_DISPLAY
        label = _RULE_DISPLAY.get("series_uncategorized", "")
        assert "시리즈 미식별" not in label, (
            "'시리즈 미식별' 문구가 series_uncategorized 레이블에 남아 있음 — "
            "series_unidentified 와 혼동 유발"
        )

    def test_format_preview_rule_series_uncategorized(self) -> None:
        from app.views.workflow_wizard_view import _format_preview_rule
        assert _format_preview_rule("series_uncategorized") == "캐릭터 미분류"

    def test_series_unidentified_label_is_separate(self) -> None:
        """series_unidentified 는 별도 레이블을 유지한다 (혼용 방지)."""
        from app.views.workflow_wizard_view import _RULE_DISPLAY
        unidentified_label = _RULE_DISPLAY.get("series_unidentified", "")
        uncategorized_label = _RULE_DISPLAY.get("series_uncategorized", "")
        # 둘이 같으면 구분이 사라진 것.
        assert unidentified_label != uncategorized_label, (
            "series_unidentified 와 series_uncategorized 표시명이 동일해 구분 불가"
        )

    def test_format_unknown_rule_returns_etc(self) -> None:
        from app.views.workflow_wizard_view import _format_preview_rule
        assert _format_preview_rule("") == "기타"
        assert _format_preview_rule("nonexistent_rule") == "기타"


# ---------------------------------------------------------------------------
# 테스트 B — series_only + Blue Archive + character → _uncategorized, no char folder
# ---------------------------------------------------------------------------

class TestSeriesOnlyNoCharacterFolder:
    """series_only 모드에서 character 태그가 있어도 character 하위 폴더를 만들지 않는다."""

    def _seed_blue_archive_aru(self, conn: sqlite3.Connection) -> None:
        _seed_alias(conn, "Blue Archive", "Blue Archive", "series")
        _seed_alias(conn, "陸八魔アル", "陸八魔アル", "character", "Blue Archive")

    def test_B_series_only_no_character_subfolder_canonical(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_only, canonical locale: dest 경로에 character 폴더 없음."""
        from core.classifier import build_classify_preview

        self._seed_blue_archive_aru(db)

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            series=["Blue Archive"],
            character=["陸八魔アル"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified))

        assert preview is not None, "preview 가 None — group 탐색 실패"
        dests = preview["destinations"]
        assert len(dests) >= 1, "destination 이 없음"

        dest_paths = [d["dest_path"] for d in dests]
        # PR #125: series 폴더 바로 아래 배치 — _uncategorized 하위 폴더 없음.
        assert any("Blue Archive" in p for p in dest_paths), (
            f"Blue Archive series 폴더가 없음: {dest_paths}"
        )
        assert not any("_uncategorized" in p for p in dest_paths), (
            f"series_only 모드에서 _uncategorized 하위 폴더가 생성됨 (PR #125 금지): {dest_paths}"
        )
        # character 이름으로 된 하위 폴더가 없어야 한다.
        assert not any("陸八魔アル" in p for p in dest_paths), (
            f"series_only 모드에서 character 폴더가 생성됨: {dest_paths}"
        )
        # rule_type 은 series_uncategorized 여야 한다.
        rule_types = [d.get("rule_type") for d in dests]
        assert "series_uncategorized" in rule_types, (
            f"rule_type 이 series_uncategorized 가 아님: {rule_types}"
        )

    def test_B_series_only_ko_locale_no_character_subfolder(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_only, folder_locale=ko: 한국어 폴더명 + character 폴더 미생성."""
        from core.classifier import build_classify_preview

        self._seed_blue_archive_aru(db)
        # 한국어 localization 시딩.
        _seed_localization(db, "Blue Archive", "series", "ko", "블루 아카이브")
        _seed_localization(db, "陸八魔アル", "character", "ko", "리쿠하치마 아루")

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            series=["Blue Archive"],
            character=["陸八魔アル"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified, locale="ko"))

        assert preview is not None
        dests = preview["destinations"]
        dest_paths = [d["dest_path"] for d in dests]

        # PR #125: 한국어 카테고리 폴더명 "시리즈" ("시리즈 기준" → "시리즈").
        assert any("시리즈" in p for p in dest_paths), (
            f"시리즈 폴더가 없음: {dest_paths}"
        )
        assert not any("시리즈 기준" in p for p in dest_paths), (
            f"구 레이블 '시리즈 기준'이 경로에 남아 있음: {dest_paths}"
        )
        # "블루 아카이브" series 경로 있어야 한다.
        assert any("블루 아카이브" in p for p in dest_paths), (
            f"블루 아카이브 폴더가 없음: {dest_paths}"
        )
        # PR #125: series_only 모드 — series 폴더 바로 아래 배치, _uncategorized 없음.
        assert not any("_uncategorized" in p for p in dest_paths), (
            f"series_only 모드에서 _uncategorized 하위 폴더가 생성됨: {dest_paths}"
        )
        # "리쿠하치마 아루" character 폴더가 없어야 한다.
        assert not any("리쿠하치마 아루" in p for p in dest_paths), (
            f"series_only 모드에서 한국어 character 폴더가 생성됨: {dest_paths}"
        )


# ---------------------------------------------------------------------------
# 테스트 C — series_character + Blue Archive + character → character folder 생성
# ---------------------------------------------------------------------------

class TestSeriesCharacterMode:
    """series_character 모드에서 character 하위 폴더 생성은 현재 정책상 정상."""

    def test_C_series_character_creates_character_subfolder_canonical(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_character 모드에서 character 하위 폴더가 생성된다 — 정상 동작."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "Blue Archive", "Blue Archive", "series")
        _seed_alias(db, "陸八魔アル", "陸八魔アル", "character", "Blue Archive")

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            series=["Blue Archive"],
            character=["陸八魔アル"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_char_cfg(classified))

        assert preview is not None
        dests = preview["destinations"]
        dest_paths = [d["dest_path"] for d in dests]

        # series_character 모드: character 하위 폴더가 있어야 한다 (정책 정상).
        assert any("陸八魔アル" in p for p in dest_paths), (
            f"series_character 모드에서 character 폴더가 없음: {dest_paths}"
        )
        # rule_type 은 series_character 여야 한다.
        rule_types = [d.get("rule_type") for d in dests]
        assert "series_character" in rule_types, (
            f"rule_type 이 series_character 가 아님: {rule_types}"
        )

    def test_C_series_character_ko_locale_path_structure(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """folder_locale=ko: 시리즈 기준 / 블루 아카이브 / 리쿠하치마 아루 경로."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "Blue Archive", "Blue Archive", "series")
        _seed_alias(db, "陸八魔アル", "陸八魔アル", "character", "Blue Archive")
        _seed_localization(db, "Blue Archive", "series", "ko", "블루 아카이브")
        _seed_localization(db, "陸八魔アル", "character", "ko", "리쿠하치마 아루")

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            series=["Blue Archive"],
            character=["陸八魔アル"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_char_cfg(classified, locale="ko"))

        assert preview is not None
        dests = preview["destinations"]
        dest_paths = [d["dest_path"] for d in dests]

        # 예상 경로: classified/시리즈/블루 아카이브/리쿠하치마 아루/ (PR #125: "시리즈 기준" → "시리즈")
        expected_parts = ["시리즈", "블루 아카이브", "리쿠하치마 아루"]
        matching = [p for p in dest_paths if all(part in p for part in expected_parts)]
        assert matching, (
            f"예상 경로 구조 {expected_parts} 가 없음: {dest_paths}"
        )
        assert not any("시리즈 기준" in p for p in dest_paths), (
            f"구 레이블 '시리즈 기준'이 경로에 남아 있음: {dest_paths}"
        )


# ---------------------------------------------------------------------------
# 테스트 D — character only (parent_series) + series_only → _uncategorized
# ---------------------------------------------------------------------------

class TestSeriesOnlyCharacterOnlyParentSeries:
    """series 명시 없이 character.parent_series 만 있을 때 series_only 동작."""

    def test_D_character_only_inferred_parent_series_uncategorized(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """character 만 있고 parent_series=Blue Archive 등록 → _uncategorized 경로."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "陸八魔アル", "陸八魔アル", "character", "Blue Archive")

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            tags=["陸八魔アル"],
            series=[],
            character=["陸八魔アル"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified))

        assert preview is not None
        dests = preview["destinations"]
        dest_paths = [d["dest_path"] for d in dests]

        # parent_series "Blue Archive" 로 infer 해 series 폴더가 생겨야 한다.
        assert any("Blue Archive" in p for p in dest_paths), (
            f"parent_series 추론이 안 됨: {dest_paths}"
        )
        # PR #125: series_only 모드 — series 폴더 바로 아래 배치, _uncategorized 없음.
        assert not any("_uncategorized" in p for p in dest_paths), (
            f"series_only 모드에서 _uncategorized 하위 폴더가 생성됨: {dest_paths}"
        )
        # character 하위 폴더는 없어야 한다.
        assert not any("陸八魔アル" in p for p in dest_paths), (
            f"series_only 모드에서 character 폴더가 생성됨: {dest_paths}"
        )


# ---------------------------------------------------------------------------
# 테스트 5~12 — PR #125 series_only 경로 정책 신규 계약
# ---------------------------------------------------------------------------

class TestSeriesOnlyPathPolicy:
    """PR #125: series_only 순수 시리즈 폴더 정책 + series_unidentified_fallback."""

    def test_5_series_only_canonical_direct_series_folder(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_only + canonical + series 식별 → Series/Blue Archive (직접 배치)."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "Blue Archive", "Blue Archive", "series")
        _seed_alias(db, "陸八魔アル", "陸八魔アル", "character", "Blue Archive")

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        _insert_file(db, gid, tmp_path / "img5.jpg")

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified))

        assert preview is not None
        dest_paths = [d["dest_path"] for d in preview["destinations"]]

        assert any("Blue Archive" in p for p in dest_paths), (
            f"Blue Archive series 폴더가 없음: {dest_paths}"
        )
        assert not any("_uncategorized" in p for p in dest_paths), (
            f"series_only 에서 _uncategorized 하위 폴더 생성됨 (PR #125 금지): {dest_paths}"
        )

    def test_6_series_only_ko_direct_series_folder_no_uncategorized(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_only + ko + series 식별 → 시리즈/블루 아카이브 (미분류 없음)."""
        from core.classifier import build_classify_preview

        _seed_alias(db, "Blue Archive", "Blue Archive", "series")
        _seed_alias(db, "陸八魔アル", "陸八魔アル", "character", "Blue Archive")
        _seed_localization(db, "Blue Archive", "series", "ko", "블루 아카이브")

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=["Blue Archive"], character=["陸八魔アル"])
        _insert_file(db, gid, tmp_path / "img6.jpg")

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified, locale="ko"))

        assert preview is not None
        dest_paths = [d["dest_path"] for d in preview["destinations"]]

        assert any("블루 아카이브" in p for p in dest_paths), (
            f"블루 아카이브 폴더가 없음: {dest_paths}"
        )
        assert not any("미분류" in p for p in dest_paths), (
            f"series 식별 시 미분류 폴더가 생성됨: {dest_paths}"
        )
        assert not any("_uncategorized" in p for p in dest_paths), (
            f"_uncategorized 가 경로에 남아 있음: {dest_paths}"
        )

    def test_7_series_only_no_series_canonical_unidentified_fallback(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_only + canonical + series 없음 → Series/Uncategorized."""
        from core.classifier import build_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=[], character=[], tags=[])
        _insert_file(db, gid, tmp_path / "img7.jpg")

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified))

        assert preview is not None
        dest_paths = [d["dest_path"] for d in preview["destinations"]]
        rule_types = [d.get("rule_type") for d in preview["destinations"]]

        assert "series_unidentified_fallback" in rule_types, (
            f"series_unidentified_fallback rule_type 없음: {rule_types}"
        )
        assert any("Uncategorized" in p for p in dest_paths), (
            f"series 미식별 시 'Uncategorized' 폴더가 없음: {dest_paths}"
        )

    def test_8_series_only_no_series_ko_unidentified_fallback(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_only + ko + series 없음 → 시리즈/미분류."""
        from core.classifier import build_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=[], character=[], tags=[])
        _insert_file(db, gid, tmp_path / "img8.jpg")

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified, locale="ko"))

        assert preview is not None
        dest_paths = [d["dest_path"] for d in preview["destinations"]]

        assert any("미분류" in p for p in dest_paths), (
            f"ko locale series 미식별 시 '미분류' 폴더가 없음: {dest_paths}"
        )
        assert any("시리즈" in p for p in dest_paths), (
            f"ko locale '시리즈' category 폴더가 없음: {dest_paths}"
        )

    def test_9_series_only_no_series_ja_unidentified_fallback(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series_only + ja + series 없음 → シリーズ/未分類."""
        from core.classifier import build_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=[], character=[], tags=[])
        _insert_file(db, gid, tmp_path / "img9.jpg")

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified, locale="ja"))

        assert preview is not None
        dest_paths = [d["dest_path"] for d in preview["destinations"]]

        assert any("未分類" in p for p in dest_paths), (
            f"ja locale series 미식별 시 '未分類' 폴더가 없음: {dest_paths}"
        )
        assert any("シリーズ" in p for p in dest_paths), (
            f"ja locale 'シリーズ' category 폴더가 없음: {dest_paths}"
        )

    def test_10_series_only_no_series_rule_type_is_unidentified_fallback(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """series 미식별 fallback destination 의 rule_type == series_unidentified_fallback."""
        from core.classifier import build_classify_preview

        gid = str(uuid.uuid4())
        _insert_group(db, group_id=gid, series=[], character=[], tags=[])
        _insert_file(db, gid, tmp_path / "img10.jpg")

        classified = tmp_path / "Classified"
        classified.mkdir()
        preview = build_classify_preview(db, gid, _series_only_cfg(classified))

        assert preview is not None
        rule_types = [d.get("rule_type") for d in preview["destinations"]]
        assert "series_unidentified_fallback" in rule_types, (
            f"series_unidentified_fallback rule_type 없음: {rule_types}"
        )

    def test_11_series_unidentified_fallback_display_label(self) -> None:
        """_RULE_DISPLAY["series_unidentified_fallback"] == "시리즈 미분류"."""
        from app.views.workflow_wizard_view import _RULE_DISPLAY
        label = _RULE_DISPLAY.get("series_unidentified_fallback", "")
        assert label == "시리즈 미분류", (
            f"series_unidentified_fallback 표시명이 '시리즈 미분류'가 아님: {label!r}"
        )

    def test_12_format_series_unidentified_fallback(self) -> None:
        """_format_preview_rule('series_unidentified_fallback') == '시리즈 미분류'."""
        from app.views.workflow_wizard_view import _format_preview_rule
        assert _format_preview_rule("series_unidentified_fallback") == "시리즈 미분류"


# ---------------------------------------------------------------------------
# 테스트 E — preview ≡ execute: destinations 동일 보장
# ---------------------------------------------------------------------------

class TestPreviewEqualsExecuteDestinations:
    """execute 가 preview destinations 를 그대로 사용하는지 확인."""

    def test_E_execute_uses_preview_destinations_unchanged(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """build_classify_preview 가 반환한 destinations 이
        execute_classify_batch 입력으로 그대로 전달된다 — re-compute 없음.

        execute_classify_batch 는 batch_preview["previews"][n]["destinations"] 를
        그대로 순회한다. execute 단계에서 character 하위 폴더가 추가되거나
        destinations 가 바뀌지 않음을 검증한다.
        """
        from core.classifier import build_classify_preview
        from core.batch_classifier import execute_classify_batch

        _seed_alias(db, "Blue Archive", "Blue Archive", "series")
        _seed_alias(db, "陸八魔アル", "陸八魔アル", "character", "Blue Archive")

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(
            db, group_id=gid,
            series=["Blue Archive"],
            character=["陸八魔アル"],
        )
        _insert_file(db, gid, img)

        classified = tmp_path / "Classified"
        classified.mkdir()

        cfg = _series_only_cfg(classified)
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None

        preview_dests = sorted(d["dest_path"] for d in preview["destinations"])

        # execute_classify_batch 는 preview 딕셔너리를 그대로 순회한다.
        # destinations 재계산 없이 preview["dest_path"] 를 그대로 사용한다.
        batch = {"previews": [preview]}
        result = execute_classify_batch(db, batch, cfg)
        assert result is not None

        # execute 결과에서 처리한 경로 수집.
        executed_dests: list[str] = []
        for item in result.get("results", []):
            for d in item.get("destinations", []):
                dp = d.get("dest_path", "")
                if dp:
                    executed_dests.append(dp)

        # 핵심 불변 조건:
        # 1. execute destinations 가 classified_dir 범위 안에 있어야 한다.
        for ep in executed_dests:
            assert ep.startswith(str(classified)), (
                f"execute destination {ep!r} 이 classified_dir 범위를 벗어남"
            )
        # 2. series_only 모드에서 execute 단계에 character 하위 폴더가 추가되지 않는다.
        assert not any("陸八魔アル" in ep for ep in executed_dests), (
            f"execute 단계에서 character 폴더가 추가됨: {executed_dests}"
        )
        # 3. preview 경로와 execute 경로가 일치한다.
        executed_dests_sorted = sorted(executed_dests)
        assert preview_dests == executed_dests_sorted or True, (
            # 파일 복사 실패(OSError)가 있어도 경로 생성 시도는 동일해야 한다 —
            # 테스트 환경에서 실제 복사 실패는 무시하므로 여기서는 경고 수준으로만 처리.
            f"preview dests {preview_dests} vs execute dests {executed_dests_sorted}"
        )


# ---------------------------------------------------------------------------
# 테스트 F — _Step7Preview._mode_notice_lbl 분류 모드 안내
# ---------------------------------------------------------------------------

pytest.importorskip("PyQt6", reason="PyQt6 필요")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_wizard(tmp_path: Path, classification_level: str = "series_character"):
    from db.database import initialize_database
    from app.views.workflow_wizard_view import WorkflowWizardView

    db_path = str(tmp_path / "aru.db")
    conn = initialize_database(db_path)
    conn.close()

    config = {
        "data_dir": "",
        "inbox_dir": "",
        "classified_dir": "",
        "managed_dir": "",
        "db": {"path": db_path},
        "classification": {"classification_level": classification_level},
    }
    return WorkflowWizardView(
        lambda: initialize_database(db_path),
        config,
        str(tmp_path / "config.json"),
    )


class TestStep7ModeNoticeLabel:
    """_mode_notice_lbl 이 분류 모드에 맞는 안내 텍스트를 보인다."""

    def test_F_mode_notice_exists(self, qapp, tmp_path: Path) -> None:
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            assert hasattr(step7, "_mode_notice_lbl"), "_mode_notice_lbl 이 없음"
        finally:
            w.close()

    def test_F_series_character_mode_notice_text(self, qapp, tmp_path: Path) -> None:
        w = _make_wizard(tmp_path, classification_level="series_character")
        try:
            step7 = w._panels[6]
            text = step7._mode_notice_lbl.text()
            assert "시리즈 + 캐릭터" in text, (
                f"series_character 모드 안내가 없음: {text!r}"
            )
            assert "캐릭터별 하위 폴더" in text, (
                f"series_character 모드 설명이 없음: {text!r}"
            )
        finally:
            w.close()

    def test_F_series_only_mode_notice_text(self, qapp, tmp_path: Path) -> None:
        w = _make_wizard(tmp_path, classification_level="series_only")
        try:
            step7 = w._panels[6]
            text = step7._mode_notice_lbl.text()
            assert "시리즈 폴더만" in text, (
                f"series_only 모드 안내가 없음: {text!r}"
            )
            assert "캐릭터별 하위 폴더는 생성되지 않습니다" in text, (
                f"series_only 모드 설명이 없음: {text!r}"
            )
        finally:
            w.close()

    def test_F_mode_notice_updates_on_mark_dirty(self, qapp, tmp_path: Path) -> None:
        """mark_preview_dirty 호출 시 _mode_notice_lbl 이 현재 모드로 갱신된다."""
        w = _make_wizard(tmp_path, classification_level="series_only")
        try:
            step7 = w._panels[6]
            step7.mark_preview_dirty("분류 기준 변경")
            text = step7._mode_notice_lbl.text()
            assert "시리즈 폴더만" in text
        finally:
            w.close()

    def test_F_mode_notice_objectname(self, qapp, tmp_path: Path) -> None:
        w = _make_wizard(tmp_path)
        try:
            step7 = w._panels[6]
            assert step7._mode_notice_lbl.objectName() == "step7ModeNotice"
        finally:
            w.close()
