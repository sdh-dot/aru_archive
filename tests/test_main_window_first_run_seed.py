"""tests/test_main_window_first_run_seed.py

Release clean first-run 에서 built-in tag pack / localization seed 가
실제로 실행되는지 lock 한다.

회귀 시나리오:
- DB 파일이 없는 사용자 환경에서 앱을 처음 실행
- MainWindow.__init__ 가 DB exists 조건으로 seed 를 건너뛰면 tag_aliases /
  tag_localizations 가 비고, Wizard manual override / autocomplete 후보가
  표시되지 않음
- 사용자 입장에서는 "Wizard 에서 캐릭터/시리즈 자동완성이 동작하지 않음" 으로 보임

본 테스트는 clean DB 상태에서도 seed 가 보장되며, 이미 seed 된 second-run
에서도 idempotent 하게 동작함을 검증한다.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

# offscreen Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6 필요")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def tmp_config(tmp_path):
    """clean first-run 흉내 — 모든 path 가 tmp_path 안의 비어 있는 폴더."""
    return {
        "data_dir":  str(tmp_path / "archive"),
        "inbox_dir": str(tmp_path / "inbox"),
        "classified_dir": str(tmp_path / "Classified"),
        "managed_dir": str(tmp_path / "Managed"),
        "db": {"path": str(tmp_path / "archive" / ".runtime" / "aru.db")},
        "http_server": {"port": 19999},
    }


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _count(conn, table: str, where: str = "") -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return conn.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# A. clean first-run seed
# ---------------------------------------------------------------------------

class TestCleanFirstRunSeed:
    """DB 파일이 존재하지 않는 상태에서 MainWindow 를 init 해도 tag pack /
    localization seed 가 즉시 실행되어야 한다.
    """

    def test_db_file_does_not_exist_initially(self, tmp_path, tmp_config):
        """전제 조건: 시작 전엔 DB 파일이 없다."""
        from pathlib import Path
        assert not Path(tmp_config["db"]["path"]).exists()

    def test_main_window_init_seeds_tag_aliases(self, qt_app, tmp_config, tmp_path):
        """MainWindow 초기화 후 tag_aliases 에 row 가 채워져야 한다."""
        from app.main_window import MainWindow

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            db_path = tmp_config["db"]["path"]
            assert os.path.exists(db_path), "_get_conn() 이 DB 파일을 생성하지 못함"
            conn = _open_db(db_path)
            try:
                n = _count(conn, "tag_aliases", "enabled = 1")
                assert n > 0, (
                    f"clean first-run 에서 tag_aliases 가 비어 있음 ({n}). "
                    "Wizard manual override / autocomplete 가 동작 안 함."
                )
            finally:
                conn.close()
        finally:
            win.close()

    def test_main_window_init_seeds_tag_localizations(self, qt_app, tmp_config, tmp_path):
        """tag_localizations 도 seed 되어야 한다 (folder name localization)."""
        from app.main_window import MainWindow

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                n = _count(conn, "tag_localizations", "enabled = 1")
                assert n > 0, f"tag_localizations 가 비어 있음 ({n})"
            finally:
                conn.close()
        finally:
            win.close()

    def test_main_window_seeds_blue_archive_aliases(self, qt_app, tmp_config, tmp_path):
        """대표 캐릭터 (Blue Archive) alias 가 즉시 매칭 가능."""
        from app.main_window import MainWindow

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                rows = conn.execute(
                    "SELECT alias, canonical, tag_type FROM tag_aliases "
                    "WHERE enabled=1 AND canonical IN ('Blue Archive', '空崎ヒナ', '伊落マリー')"
                ).fetchall()
                canonicals = {r["canonical"] for r in rows}
                assert "Blue Archive" in canonicals, (
                    f"Blue Archive series alias seed 누락: {canonicals}"
                )
                # P1+P2 캐릭터 중 최소 1명 (空崎ヒナ 또는 伊落マリー) 매칭 가능해야 한다.
                assert canonicals & {"空崎ヒナ", "伊落マリー"}, (
                    f"Blue Archive character alias seed 누락: {canonicals}"
                )
            finally:
                conn.close()
        finally:
            win.close()

    def test_main_window_seeds_trickcal_aliases(self, qt_app, tmp_config, tmp_path):
        """다른 작품 (Trickcal Re:VIVE) seed 도 정상."""
        from app.main_window import MainWindow

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                rows = conn.execute(
                    "SELECT alias FROM tag_aliases "
                    "WHERE enabled=1 AND canonical = 'Trickcal Re:VIVE'"
                ).fetchall()
                assert len(rows) > 0, "Trickcal Re:VIVE series alias seed 누락"
            finally:
                conn.close()
        finally:
            win.close()


# ---------------------------------------------------------------------------
# B. DB exists 조건이 더 이상 seed 를 가로막지 않는다
# ---------------------------------------------------------------------------

class TestSeedNotBlockedByDbExistsCondition:
    def test_seed_runs_even_without_existing_db_file(self, qt_app, tmp_config, tmp_path):
        """이전 회귀: ``if Path(self._db_path()).exists():`` 가 seed 를 가로막음.

        본 테스트는 db_path 가 존재하지 않는 시점에 MainWindow 를 만들어도
        seed 가 작동하는지 (즉 그 조건이 제거되었는지) 확인한다.
        """
        from pathlib import Path
        from app.main_window import MainWindow

        db_path = tmp_config["db"]["path"]
        # 사전 조건: 절대 존재하지 않는다.
        assert not Path(db_path).exists()

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            assert getattr(win, "_builtin_tag_packs_seeded", False) is True, (
                "_builtin_tag_packs_seeded flag 가 False — startup seed 가 실패했거나 "
                "DB exists 조건이 다시 막고 있음"
            )
            assert Path(db_path).exists()
        finally:
            win.close()


# ---------------------------------------------------------------------------
# C. helper / autocomplete affected tables
# ---------------------------------------------------------------------------

class TestHelperAutocompleteSourceTables:
    """Wizard manual override / autocomplete 가 조회하는 source 테이블에
    실제로 후보가 들어 있는지.
    """

    def test_classify_pixiv_tags_finds_blue_archive_after_first_run(
        self, qt_app, tmp_config, tmp_path
    ):
        """conn 을 받은 classify_pixiv_tags 가 즉시 Blue Archive 를 매칭."""
        from app.main_window import MainWindow
        from core.tag_classifier import classify_pixiv_tags

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                result = classify_pixiv_tags(["ブルーアーカイブ"], conn=conn)
                assert "Blue Archive" in result["series_tags"], (
                    "clean first-run 직후 ブルーアーカイブ → Blue Archive 매칭 실패"
                )
            finally:
                conn.close()
        finally:
            win.close()

    def test_classify_pixiv_tags_finds_korean_alias_after_first_run(
        self, qt_app, tmp_config, tmp_path
    ):
        """한국어 alias (블루 아카이브) 도 즉시 매칭."""
        from app.main_window import MainWindow
        from core.tag_classifier import classify_pixiv_tags

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                result = classify_pixiv_tags(["블루 아카이브"], conn=conn)
                assert "Blue Archive" in result["series_tags"]
            finally:
                conn.close()
        finally:
            win.close()


# ---------------------------------------------------------------------------
# D. idempotency — second run does not duplicate rows
# ---------------------------------------------------------------------------

class TestSeedIdempotency:
    def test_second_init_does_not_duplicate_aliases(
        self, qt_app, tmp_config, tmp_path
    ):
        """동일 config 로 MainWindow 를 두 번 만들어도 tag_aliases 가 늘지 않는다."""
        from app.main_window import MainWindow

        win1 = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                n_first = _count(conn, "tag_aliases")
            finally:
                conn.close()
        finally:
            win1.close()

        # second run
        win2 = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                n_second = _count(conn, "tag_aliases")
            finally:
                conn.close()
        finally:
            win2.close()

        assert n_first == n_second, (
            f"두 번째 MainWindow init 후 tag_aliases 가 변동: "
            f"{n_first} → {n_second}"
        )

    def test_helper_method_idempotent_when_called_directly(
        self, qt_app, tmp_config, tmp_path
    ):
        """``_seed_localizations(conn)`` 단독 호출도 idempotent."""
        from app.main_window import MainWindow

        win = MainWindow(tmp_config, config_path=str(tmp_path / "cfg.json"))
        try:
            conn = _open_db(tmp_config["db"]["path"])
            try:
                n_before = _count(conn, "tag_aliases")
            finally:
                conn.close()

            # 직접 한 번 더 호출.
            conn2 = win._get_conn()
            try:
                win._seed_localizations(conn2)
            finally:
                conn2.close()

            conn = _open_db(tmp_config["db"]["path"])
            try:
                n_after = _count(conn, "tag_aliases")
            finally:
                conn.close()

            assert n_before == n_after, (
                f"_seed_localizations 두 번째 호출이 row 를 추가함: "
                f"{n_before} → {n_after}"
            )
        finally:
            win.close()


# ---------------------------------------------------------------------------
# E. Scope guard — 본 PR 은 metadata writer / inbox scanner / classifier 무수정
# ---------------------------------------------------------------------------

class TestScopeGuard:
    def test_metadata_writer_not_modified_for_seed_path(self):
        """seed 변경이 metadata_writer / inbox_scanner / classifier 의 import
        chain 에 추가 의존성을 만들지 않았는지 (무관성) 확인.

        clean first-run seed 는 app/main_window.py 와 core/tag_pack_loader,
        core/tag_localizer 만 사용해야 한다.
        """
        import inspect
        import app.main_window as mw_mod
        # __init__ 안에서 새로 import 된 모듈 — 단순 source-grep guard.
        src = inspect.getsource(mw_mod.MainWindow.__init__)
        assert "metadata_writer" not in src
        assert "inbox_scanner" not in src
        assert "core.classifier" not in src
