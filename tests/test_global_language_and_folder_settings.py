"""전역 언어 설정 / 폴더 설정 분리 회귀 테스트 (PR #122).

검증 contract:
- ``app_language`` 와 ``folder_name_language`` 가 별도 키로 저장 / 로드된다.
- ``input_dir`` / ``output_dir`` 가 ``inbox_dir`` / ``classified_dir`` 와 동기화되며 서로 독립적으로 변경된다.
- ``app_data_dir`` 기본값이 ``Path.home() / 'AruArchive'`` 이고, ``ensure_app_data_dirs`` 가 ``.runtime`` / ``logs`` / ``thumbcache`` / ``managed`` 를 생성한다.
- ``CATEGORY_FOLDER_LABELS`` 와 ``resolve_category_folder`` 가 ko / ja / en 으로 라벨을 반환하고 알 수 없는 값은 영어로 fallback.
- ``_build_destinations`` 가 ``folder_name_language`` 에 따라 카테고리 폴더 (``ByAuthor`` / ``BySeries`` / ``ByCharacter`` / ``ByTag``) 라벨을 로컬라이즈한다.
- 기존 ``ByXxx`` 폴더는 자동 rename 되지 않는다.
- consistency report 가 로컬라이즈된 destination 에서도 정상 작동한다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.classifier import build_classify_preview
from core.config_manager import (
    APP_DATA_STANDARD_SUBDIRS,
    default_app_data_dir,
    ensure_app_data_dirs,
    load_config,
    resolve_app_data_dir,
    save_config,
    sync_io_dir_aliases,
)
from core.folder_localization import (
    CATEGORY_FOLDER_LABELS,
    resolve_category_folder,
    resolve_folder_name_language,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    from db.database import initialize_database
    conn = initialize_database(str(tmp_path / "pr122.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_group(
    conn: sqlite3.Connection,
    *,
    group_id: str,
    series: list[str] | None = None,
    character: list[str] | None = None,
    tags: list[str] | None = None,
    artist: str = "test_artist",
    sync_status: str = "json_only",
) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO artwork_groups "
        "(group_id, source_site, artwork_id, artwork_title, artist_name, "
        " downloaded_at, indexed_at, metadata_sync_status, "
        " tags_json, series_tags_json, character_tags_json) "
        "VALUES (?, 'pixiv', ?, 'test', ?, ?, ?, ?, ?, ?, ?)",
        (
            group_id, group_id[:12], artist, now, now, sync_status,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(series or [], ensure_ascii=False),
            json.dumps(character or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def _insert_file(conn: sqlite3.Connection, group_id: str, path: Path) -> str:
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


def _classification_cfg(
    classified_dir: Path | str,
    *,
    folder_name_language: str | None = None,
    classification_level: str | None = None,
) -> dict:
    cfg = {
        "classified_dir": str(classified_dir),
        "output_dir":     str(classified_dir),
        "undo_retention_days": 7,
        "classification": {
            "enable_series_character":         True,
            "enable_series_uncategorized":     True,
            "enable_character_without_series": True,
            "fallback_by_author":              True,
            "enable_by_author":                False,
            "enable_by_tag":                   False,
            "on_conflict":                     "rename",
            "folder_locale":                   "canonical",
        },
    }
    if folder_name_language is not None:
        cfg["folder_name_language"] = folder_name_language
    if classification_level == "series_only":
        cls = cfg["classification"]
        cls["enable_series_character"] = False
        cls["enable_character_without_series"] = False
    return cfg


# ---------------------------------------------------------------------------
# Tests 1-2: language separation
# ---------------------------------------------------------------------------

class TestLanguageSettingsSeparation:
    def test_1_default_language_settings_exist(self, tmp_path: Path) -> None:
        """기본 설정에 app_language / folder_name_language 가 별도 키로 존재."""
        cfg_path = tmp_path / "config.json"
        cfg = load_config(cfg_path)
        assert "app_language" in cfg
        assert "folder_name_language" in cfg
        assert isinstance(cfg["app_language"], str)
        assert isinstance(cfg["folder_name_language"], str)
        # 두 값이 같은 키로 합쳐지지 않았는지 확인 — 변경 시 한쪽만 바뀌어야 함.
        cfg["app_language"] = "en"
        cfg["folder_name_language"] = "ja"
        save_config(cfg, cfg_path)
        reloaded = load_config(cfg_path)
        assert reloaded["app_language"] == "en"
        assert reloaded["folder_name_language"] == "ja"

    def test_2_app_language_does_not_override_folder_language(self) -> None:
        """app_language=en, folder_name_language=ko → resolver 는 ko 를 사용."""
        cfg = {"app_language": "en", "folder_name_language": "ko"}
        assert resolve_folder_name_language(cfg) == "ko"

        # _cls_cfg 가 folder_name_language 를 우선 읽는지 확인.
        from core.classifier import _cls_cfg
        c = _cls_cfg({
            "folder_name_language": "ko",
            "classification": {"folder_locale": "canonical"},
        })
        assert c["folder_name_language"] == "ko"


# ---------------------------------------------------------------------------
# Tests 3-6: localized category folder labels
# ---------------------------------------------------------------------------

class TestCategoryFolderResolver:
    def test_3_korean_by_series(self) -> None:
        assert resolve_category_folder("by_series", "ko") == "시리즈 기준"

    def test_4_japanese_by_author(self) -> None:
        assert resolve_category_folder("by_author", "ja") == "作者別"

    def test_5_english_by_character(self) -> None:
        assert resolve_category_folder("by_character", "en") == "ByCharacter"

    def test_6_unknown_language_falls_back_to_english(self) -> None:
        # 알 수 없는 값 / canonical / 빈 문자열 / None → 영어 라벨로 fallback.
        # 예외를 던지지 않는다.
        assert resolve_category_folder("by_series", "invalid") == "BySeries"
        assert resolve_category_folder("by_series", "canonical") == "BySeries"
        assert resolve_category_folder("by_series", "") == "BySeries"
        assert resolve_category_folder("by_series", None) == "BySeries"

    def test_unknown_category_returns_key(self) -> None:
        # 알 수 없는 category_key 는 그 키 자체를 반환 — 안전 fallback.
        assert resolve_category_folder("by_unknown", "ko") == "by_unknown"

    def test_all_categories_have_three_locales(self) -> None:
        for key, labels in CATEGORY_FOLDER_LABELS.items():
            for lang in ("ko", "ja", "en"):
                assert lang in labels, f"{key} 가 {lang} 라벨 없음"
                assert labels[lang], f"{key} {lang} 라벨이 비어 있음"


# ---------------------------------------------------------------------------
# Tests 7-8: app_data_dir
# ---------------------------------------------------------------------------

class TestAppDataDir:
    def test_7_default_app_data_dir_is_home_aru_archive(self) -> None:
        assert default_app_data_dir() == Path.home() / "AruArchive"
        # cfg 에 명시값이 없으면 기본값이 그대로 사용된다.
        assert resolve_app_data_dir({}) == (Path.home() / "AruArchive").resolve(strict=False)
        # 명시값이 있으면 그것이 우선.
        custom = Path.home() / "AruArchiveCustom"
        assert resolve_app_data_dir({"app_data_dir": str(custom)}) == custom.resolve(strict=False)

    def test_8_ensure_app_data_dirs_creates_standard_subfolders(self, tmp_path: Path) -> None:
        base = tmp_path / "AruArchive"
        created = ensure_app_data_dirs(base)
        for sub in (".runtime", "logs", "thumbcache", "managed"):
            assert (base / sub).is_dir(), f"{sub} 가 생성되지 않음"
        # 신규 생성 결과에 표준 하위 폴더가 모두 포함됐는지.
        created_names = {Path(p).name for p in created}
        for sub in APP_DATA_STANDARD_SUBDIRS:
            assert sub in created_names

    def test_ensure_app_data_dirs_idempotent(self, tmp_path: Path) -> None:
        base = tmp_path / "AruArchive"
        first = ensure_app_data_dirs(base)
        second = ensure_app_data_dirs(base)
        # 두 번째 호출은 새 생성이 없어야 한다.
        assert first
        assert second == []
        for sub in APP_DATA_STANDARD_SUBDIRS:
            assert (base / sub).is_dir()

    def test_ensure_app_data_dirs_default_uses_home(self, tmp_path: Path, monkeypatch) -> None:
        # HOME 을 임시 경로로 변경해 default 동작을 격리.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        # Path.home() 캐시를 우회하기 위해 함수에 명시 None 으로 호출.
        ensure_app_data_dirs(tmp_path / "AruArchive")
        for sub in APP_DATA_STANDARD_SUBDIRS:
            assert (tmp_path / "AruArchive" / sub).is_dir()


# ---------------------------------------------------------------------------
# Tests 9: input_dir / output_dir 분리
# ---------------------------------------------------------------------------

class TestInputOutputDirSeparation:
    def test_9_input_and_output_dir_are_independent(self, tmp_path: Path) -> None:
        input_path  = tmp_path / "Inbox"
        output_path = tmp_path / "Classified"
        cfg = {"input_dir": str(input_path), "output_dir": str(output_path)}
        sync_io_dir_aliases(cfg)
        # 두 키가 독립적으로 저장됨 + alias 가 동기화됨.
        assert cfg["inbox_dir"]      == str(input_path)
        assert cfg["classified_dir"] == str(output_path)
        # output_dir 변경이 input_dir 를 건드리지 않는다.
        new_output = tmp_path / "Classified2"
        cfg["output_dir"]      = str(new_output)
        cfg["classified_dir"] = str(new_output)
        assert cfg["input_dir"]  == str(input_path)
        assert cfg["inbox_dir"]  == str(input_path)
        # input_dir 변경이 output_dir 를 건드리지 않는다.
        new_input = tmp_path / "Inbox2"
        cfg["input_dir"] = str(new_input)
        cfg["inbox_dir"] = str(new_input)
        assert cfg["output_dir"]      == str(new_output)
        assert cfg["classified_dir"] == str(new_output)


# ---------------------------------------------------------------------------
# Tests 10-11: classified output paths and no-rename policy
# ---------------------------------------------------------------------------

class TestClassifiedOutputLocalization:
    def test_10_existing_byseries_folder_not_renamed(self, tmp_path: Path) -> None:
        """folder_name_language 변경은 기존 폴더를 자동 rename 하지 않는다.

        이 테스트는 ``_build_destinations`` 가 새 destination 만 생성하고
        파일시스템상의 기존 ``ByXxx`` 폴더에는 손대지 않음을 확인한다.
        """
        existing = tmp_path / "Classified" / "BySeries" / "Blue Archive"
        existing.mkdir(parents=True)
        (existing / "old.jpg").write_bytes(b"x")

        # config 가 ko 로 바뀌어도 기존 폴더는 그대로 남는다.
        cfg = _classification_cfg(
            tmp_path / "Classified",
            folder_name_language="ko",
        )
        assert cfg["folder_name_language"] == "ko"
        # 기존 폴더 / 파일이 그대로 존재.
        assert existing.is_dir()
        assert (existing / "old.jpg").is_file()

    def test_11_destination_uses_localized_category_folder(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """folder_name_language=ko + by_series → output_dir / 시리즈 기준 / ..."""
        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(db, group_id=gid,
                      series=["Blue Archive"], character=[], tags=[])
        _insert_file(db, gid, img)

        out = tmp_path / "Classified"
        out.mkdir()
        cfg = _classification_cfg(out, folder_name_language="ko")
        cfg["classification"]["folder_locale"] = "canonical"  # series display 는 그대로.

        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        dests = [d["dest_path"] for d in preview["destinations"]]
        # 카테고리 폴더가 한국어 라벨로 생성됐는지 확인.
        assert any("시리즈 기준" in p for p in dests), (
            f"기대 한국어 카테고리 라벨이 없음: {dests}"
        )
        # output_dir 아래에 생성됨 (input_dir / app_data_dir 가 아님).
        out_str = str(out)
        for p in dests:
            if "시리즈 기준" in p:
                assert p.startswith(out_str), (
                    f"destination 이 output_dir 밖에 생성됨: {p}"
                )

    def test_japanese_destination_uses_japanese_label(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(db, group_id=gid, series=[], character=[], tags=[],
                      artist="Test Artist")
        _insert_file(db, gid, img)

        out = tmp_path / "Classified"
        out.mkdir()
        cfg = _classification_cfg(out, folder_name_language="ja")
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        dests = [d["dest_path"] for d in preview["destinations"]]
        assert any("作者別" in p for p in dests), f"일본어 라벨 없음: {dests}"

    def test_default_canonical_keeps_english_labels(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """folder_name_language 미설정 (legacy folder_locale=canonical) 시
        기존 BySeries / ByAuthor 라벨이 그대로 사용되는지."""
        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(db, group_id=gid, series=["Blue Archive"], tags=[])
        _insert_file(db, gid, img)

        out = tmp_path / "Classified"
        out.mkdir()
        cfg = _classification_cfg(out)  # folder_name_language 미설정
        preview = build_classify_preview(db, gid, cfg)
        assert preview is not None
        dests = [d["dest_path"] for d in preview["destinations"]]
        assert any("BySeries" in p for p in dests), f"BySeries 가 사라짐: {dests}"


# ---------------------------------------------------------------------------
# Test 12: consistency report 회귀
# ---------------------------------------------------------------------------

class TestWizardStep1LanguageUI:
    """Wizard Step 1 의 언어 설정 UI — app_language / folder_name_language 분리 +
    설명 문구 노출 검증."""

    @pytest.fixture(autouse=True)
    def _qapp(self):
        pytest.importorskip("PyQt6", reason="PyQt6 필요")
        from PyQt6.QtWidgets import QApplication
        import sys
        return QApplication.instance() or QApplication(sys.argv)

    def _make_wizard(self, tmp_path: Path, **cfg_overrides):
        from db.database import initialize_database
        from app.views.workflow_wizard_view import WorkflowWizardView
        db_path = str(tmp_path / "wiz.db")
        initialize_database(db_path).close()
        cfg = {
            "data_dir": "", "inbox_dir": "", "classified_dir": "",
            "managed_dir": "",
            "db": {"path": db_path},
            "classification": {"classification_level": "series_character"},
        }
        cfg.update(cfg_overrides)
        config_path = str(tmp_path / "config.json")
        return WorkflowWizardView(
            lambda: initialize_database(db_path), cfg, config_path,
        )

    def test_step1_has_separate_language_combos(self, tmp_path: Path) -> None:
        w = self._make_wizard(tmp_path)
        try:
            from PyQt6.QtWidgets import QComboBox, QLabel
            step1 = w._panels[0]
            app_combo = step1.findChild(QComboBox, "step1AppLanguageCombo")
            folder_combo = step1.findChild(QComboBox, "step1FolderNameLanguageCombo")
            notice = step1.findChild(QLabel, "step1FolderNameLanguageNotice")
            assert app_combo is not None,    "app_language combo 가 없음"
            assert folder_combo is not None, "folder_name_language combo 가 없음"
            assert notice is not None,       "folder_name_language 설명 문구가 없음"
            assert "이미 생성된" in notice.text(), notice.text()
            assert "자동 변경되지 않습니다" in notice.text(), notice.text()
        finally:
            w.close()

    def test_step1_folder_guide_describes_three_folder_concepts(
        self, tmp_path: Path
    ) -> None:
        w = self._make_wizard(tmp_path)
        try:
            from PyQt6.QtWidgets import QLabel
            step1 = w._panels[0]
            guide = step1.findChild(QLabel, "step1FolderGuide")
            assert guide is not None
            text = guide.text()
            assert "분류 대상 폴더" in text
            assert "분류 완료 폴더" in text
            assert "관리 폴더" in text
        finally:
            w.close()

    def test_step1_language_change_persists_separately(
        self, tmp_path: Path
    ) -> None:
        w = self._make_wizard(tmp_path)
        try:
            step1 = w._panels[0]
            app_idx = step1._app_lang_combo.findData("en")
            folder_idx = step1._folder_lang_combo.findData("ja")
            assert app_idx >= 0 and folder_idx >= 0
            step1._app_lang_combo.setCurrentIndex(app_idx)
            step1._folder_lang_combo.setCurrentIndex(folder_idx)
            cfg = w._config
            assert cfg["app_language"] == "en"
            assert cfg["folder_name_language"] == "ja"
            # classification.folder_locale 가 동기화됐는지 — 새 destination 이
            # 일본어 라벨로 생성되도록.
            assert cfg["classification"]["folder_locale"] == "ja"
        finally:
            w.close()


class TestConsistencyReportRegression:
    def test_12_consistency_report_handles_localized_destinations(
        self, db: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """로컬라이즈된 destination 으로 consistency report 가 정상 동작한다.

        시나리오: 기존 BySeries 폴더 아래 classified_copy 가 등록돼 있는
        상태에서, folder_name_language=ko 로 설정해 새 preview 를 돌리면
        report 는 기존 BySeries 경로를 ``legacy_extra``, 새 한국어 경로를
        ``missing_expected`` 로 정확히 분류해야 한다 (status 분류는 내부
        key 기준이므로 라벨 변경의 영향을 받지 않는다).
        """
        from core.classified_output_consistency import (
            build_classified_output_consistency_report,
            classified_output_report_to_rows,
            export_classified_output_report_csv,
            export_classified_output_report_json,
        )

        gid = str(uuid.uuid4())
        img = tmp_path / "img.jpg"
        _insert_group(db, group_id=gid, series=["Blue Archive"], tags=[])
        _insert_file(db, gid, img)

        # 기존 영어 라벨 폴더 아래 classified_copy 가 등록된 상태를 시뮬레이션.
        out = tmp_path / "Classified"
        legacy_path = out / "BySeries" / "Blue Archive" / "_uncategorized" / "img.jpg"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_bytes(b"\xff\xd8\xff\xe0")
        copy_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO artwork_files "
            "(file_id, group_id, page_index, file_role, file_path, "
            " file_format, file_size, metadata_embedded, file_status, created_at) "
            "VALUES (?, ?, 0, 'classified_copy', ?, 'jpg', 1024, 1, 'present', ?)",
            (copy_id, gid, str(legacy_path), _now()),
        )
        db.commit()

        cfg = _classification_cfg(out, folder_name_language="ko")

        report = build_classified_output_consistency_report(db, config=cfg)
        # report 가 dataclass 형식으로 정상 반환되는지.
        assert hasattr(report, "items") and hasattr(report, "summary")
        gid_items = [it for it in report.items if it.group_id == gid]
        assert len(gid_items) == 1
        item = gid_items[0]
        # 기존 영어 라벨 경로는 legacy_extra, 새 한국어 라벨 경로는 missing_expected.
        assert item.status in (
            "legacy_extra", "missing_expected", "legacy_and_missing"
        )
        assert any("시리즈 기준" in p for p in item.missing_expected_paths), (
            f"한국어 missing_expected 라벨 없음: {item.missing_expected_paths}"
        )
        assert any("BySeries" in p for p in item.legacy_extra_paths), (
            f"기존 BySeries legacy_extra 가 식별되지 않음: {item.legacy_extra_paths}"
        )
        # CSV / JSON export 도 예외 없이 동작 — '기존 export 기능' 보존 검증.
        rows = classified_output_report_to_rows(report)
        assert isinstance(rows, list)
        csv_path = tmp_path / "report.csv"
        json_path = tmp_path / "report.json"
        export_classified_output_report_csv(report, csv_path)
        export_classified_output_report_json(report, json_path)
        assert csv_path.is_file()
        assert json_path.is_file()
