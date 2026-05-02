"""
Aru Archive 메인 윈도우.

레이아웃:
  QToolBar (작업 폴더 설정 | Inbox 스캔 | DB 초기화)
  QSplitter
    SidebarWidget (160px)
    QStackedWidget
      GalleryView    (index 0)
      NoMetadataView (index 1 — no_metadata 카테고리)
    DetailView (340px)
  LogPanel (130px)

작업 폴더 설정 시 선택한 폴더를 Inbox로 사용하고 같은 레벨에
Classified / Managed를 자동 생성한다.
앱 내부 데이터는 data_dir 아래 .thumbcache / .runtime 등에 저장한다.

이 파일은 UI 조립과 사용자 액션 orchestration을 담당한다.
실제 도메인 로직은 core.* 모듈에 두고, 여기서는 백그라운드 스레드 실행,
DB 연결 수명, 화면 갱신 순서를 관리한다.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal as Signal
from PyQt6.QtGui import QAction, QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from app.views.detail_view import DetailView
from app.views.gallery_view import GalleryView
from app.views.loading_overlay_dialog import LoadingOverlayDialog
from app.views.no_metadata_view import NoMetadataView
from app.views.path_setup_dialog import PathSetupDialog
from app.widgets.log_panel import LogPanel
from app.widgets.sidebar import SidebarWidget
from core.config_manager import (
    ensure_app_directories,
    ensure_workspace_directories,
    save_config,
    update_workspace_from_inbox,
)
from core.filename_parser import parse_pixiv_filename
from core.inbox_scanner import InboxScanner, ScanResult, compute_file_hash
from core.metadata_reader import read_aru_metadata
from core.thumbnail_manager import generate_thumbnail
from app.views.database_reset_confirm_dialog import DatabaseResetConfirmDialog
from db.database import backup_database, initialize_database

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Timing instrumentation helpers
# ------------------------------------------------------------------

_TIMING_LOG = logging.getLogger("aru.timing")


def _log_phase(phase: str, elapsed_ms: float, **extra) -> None:
    """Emit a [TIMING] line for a single phase. Never raises."""
    try:
        suffix = " ".join(f"{k}={v}" for k, v in extra.items())
        msg = f"[TIMING] {phase} elapsed_ms={elapsed_ms:.1f}"
        if suffix:
            msg += " " + suffix
        _TIMING_LOG.debug(msg)
    except Exception:
        pass  # timing must never break the app


class _TimingPhase:
    """Context manager that logs elapsed time for a named phase."""

    def __init__(self, phase: str, **extra):
        self.phase = phase
        self.extra = extra
        self.t0 = 0.0

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        elapsed_ms = (time.perf_counter() - self.t0) * 1000
        _log_phase(self.phase, elapsed_ms, **self.extra)
        return False  # never swallow exceptions


# ------------------------------------------------------------------
# DB 쿼리 상수
# ------------------------------------------------------------------

_GALLERY_BASE = """
    SELECT
        g.group_id,
        g.artwork_title,
        g.artwork_id,
        g.metadata_sync_status,
        g.status,
        g.source_site,
        (SELECT af.file_format FROM artwork_files af
         WHERE af.group_id = g.group_id AND af.file_role = 'original'
         ORDER BY af.page_index LIMIT 1) AS file_format,
        (SELECT tc.thumb_path
         FROM artwork_files af2
         JOIN thumbnail_cache tc ON tc.file_id = af2.file_id
         WHERE af2.group_id = g.group_id
         ORDER BY af2.page_index LIMIT 1) AS thumb_path,
        (SELECT GROUP_CONCAT(DISTINCT af3.file_role)
         FROM artwork_files af3
         WHERE af3.group_id = g.group_id) AS role_summary
    FROM artwork_groups g
    WHERE EXISTS (
        SELECT 1 FROM artwork_files af_present
        WHERE af_present.group_id = g.group_id
          AND af_present.file_status = 'present'
    )
"""

_PRESENT_EXISTS_FRAGMENT = (
    "EXISTS ("
    "SELECT 1 FROM artwork_files af_present "
    "WHERE af_present.group_id = g.group_id "
    "AND af_present.file_status = 'present'"
    ")"
)

# present-only base의 WHERE 조건을 missing 으로 뒤집은 미러 프래그먼트
_MISSING_EXISTS_FRAGMENT = (
    "EXISTS ("
    "SELECT 1 FROM artwork_files af_missing "
    "WHERE af_missing.group_id = g.group_id "
    "AND af_missing.file_status = 'missing'"
    ")"
)

# missing 카테고리 전용 Gallery SQL
# _GALLERY_BASE 는 present 필터를 내장하므로 missing 카테고리에는 사용 불가 — 별도 정의
_GALLERY_MISSING_SQL = """
    SELECT
        g.group_id,
        g.artwork_title,
        g.artwork_id,
        g.metadata_sync_status,
        g.status,
        g.source_site,
        (SELECT af.file_format FROM artwork_files af
         WHERE af.group_id = g.group_id AND af.file_role = 'original'
         ORDER BY af.page_index LIMIT 1) AS file_format,
        (SELECT tc.thumb_path
         FROM artwork_files af2
         JOIN thumbnail_cache tc ON tc.file_id = af2.file_id
         WHERE af2.group_id = g.group_id
         ORDER BY af2.page_index LIMIT 1) AS thumb_path,
        (SELECT GROUP_CONCAT(DISTINCT af3.file_role)
         FROM artwork_files af3
         WHERE af3.group_id = g.group_id) AS role_summary
    FROM artwork_groups g
    WHERE {missing_exists}
    ORDER BY g.indexed_at DESC
""".format(missing_exists=_MISSING_EXISTS_FRAGMENT)

_FAILED_STATUSES = (
    "'file_write_failed','convert_failed','metadata_write_failed',"
    "'db_update_failed','needs_reindex'"
)

_GALLERY_WHERE: dict[str, str] = {
    "all":         "",
    "inbox":       "AND g.status = 'inbox'",
    "managed": (
        "AND EXISTS ("
        "  SELECT 1 FROM artwork_files af "
        "  WHERE af.group_id = g.group_id AND af.file_role = 'managed'"
        ")"
    ),
    "no_metadata": "",
    "warning":     "AND g.metadata_sync_status IN ('xmp_write_failed', 'json_only')",
    "failed":      f"AND g.metadata_sync_status IN ({_FAILED_STATUSES})",
}

_COUNT_SQL: dict[str, str] = {
    "all": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE {_PRESENT_EXISTS_FRAGMENT}"
    ),
    "inbox": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE {_PRESENT_EXISTS_FRAGMENT} AND g.status = 'inbox'"
    ),
    "managed": (
        "SELECT COUNT(DISTINCT g.group_id) FROM artwork_groups g "
        "JOIN artwork_files af ON af.group_id = g.group_id "
        f"WHERE af.file_role = 'managed' AND {_PRESENT_EXISTS_FRAGMENT}"
    ),
    "no_metadata": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status = 'metadata_missing' "
        f"AND {_PRESENT_EXISTS_FRAGMENT}"
    ),
    "warning": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status IN ('xmp_write_failed', 'json_only') "
        f"AND {_PRESENT_EXISTS_FRAGMENT}"
    ),
    "failed": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE g.metadata_sync_status IN ({_FAILED_STATUSES}) "
        f"AND {_PRESENT_EXISTS_FRAGMENT}"
    ),
    "missing": (
        "SELECT COUNT(*) FROM artwork_groups g "
        f"WHERE {_MISSING_EXISTS_FRAGMENT}"
    ),
}

_NO_META_IDX = 1
_GALLERY_IDX  = 0

_STYLE_PATH_OK   = "color: #D8AEBB; font-size: 11px; padding: 0 8px;"
_STYLE_PATH_WARN = "color: #FF6B7A; font-size: 11px; padding: 0 8px;"
_STYLE_PATH_NONE = "color: #8F6874; font-size: 11px; padding: 0 8px;"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# 백그라운드 스캔 스레드
# ------------------------------------------------------------------

class XmpRetryThread(QThread):
    """XMP 메타데이터 재처리를 UI freeze 없이 실행한다."""

    log_msg    = Signal(str)
    xmp_done   = Signal(dict)

    def __init__(
        self,
        group_id: Optional[str],   # None = 전체 재처리
        db_path:  str,
        exiftool_path: Optional[str],
        group_ids: Optional[list[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._group_id     = group_id
        self._group_ids    = group_ids or []
        self._db_path      = db_path
        self._exiftool_path = exiftool_path

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.xmp_retry import (
                retry_xmp_for_all, retry_xmp_for_group, retry_xmp_for_groups,
            )
            if self._group_ids:
                total = len(self._group_ids)
                self.log_msg.emit(f"[INFO] 선택 XMP 재처리 대상: {total}개")

                def _progress(done: int, total_groups: int, gid: str, status: str) -> None:
                    if status == "running":
                        self.log_msg.emit(
                            f"[INFO] XMP 재처리 진행: {done + 1}/{total_groups} — {gid[:8]}…"
                        )

                r = retry_xmp_for_groups(
                    conn, self._group_ids, self._exiftool_path, progress_fn=_progress
                )
                self.xmp_done.emit({"mode": "selected", **r})
            elif self._group_id:
                r = retry_xmp_for_group(conn, self._group_id, self._exiftool_path)
                self.xmp_done.emit({"mode": "single", "group_ids": [self._group_id], **r})
            else:
                r = retry_xmp_for_all(conn, self._exiftool_path)
                self.xmp_done.emit({"mode": "all", **r})
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] XMP 재처리 예외: {exc}")
            if self._group_ids:
                mode = "selected"
            else:
                mode = "single" if self._group_id else "all"
            self.xmp_done.emit({"mode": mode, "status": "error"})
        finally:
            conn.close()


class RichXmpRetryThread(QThread):
    log_msg  = Signal(str)
    progress = Signal(int, int, str, str)
    xmp_done = Signal(dict)

    def __init__(
        self,
        group_id: Optional[str],
        db_path: str,
        exiftool_path: Optional[str],
        group_ids: Optional[list[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._group_id = group_id
        self._group_ids = group_ids or []
        self._db_path = db_path
        self._exiftool_path = exiftool_path

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.xmp_retry import (
                retry_xmp_for_all,
                retry_xmp_for_group,
                retry_xmp_for_groups,
            )

            def _progress(done: int, total_groups: int, gid: str, status: str) -> None:
                self.progress.emit(done, total_groups, gid, status)

            if self._group_ids:
                total = len(self._group_ids)
                self.log_msg.emit(f"[INFO] 선택 XMP 재처리 대상: {total}개")
                result = retry_xmp_for_groups(
                    conn,
                    self._group_ids,
                    self._exiftool_path,
                    progress_fn=_progress,
                )
                self.xmp_done.emit({"mode": "selected", **result})
            elif self._group_id:
                self.progress.emit(0, 1, self._group_id, "running")
                result = retry_xmp_for_group(conn, self._group_id, self._exiftool_path)
                self.progress.emit(1, 1, self._group_id, result.get("status", "done"))
                self.xmp_done.emit(
                    {"mode": "single", "group_ids": [self._group_id], **result}
                )
            else:
                result = retry_xmp_for_all(
                    conn,
                    self._exiftool_path,
                    progress_fn=_progress,
                )
                self.xmp_done.emit({"mode": "all", **result})
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] XMP 재처리 예외: {exc}")
            mode = "selected" if self._group_ids else ("single" if self._group_id else "all")
            self.xmp_done.emit({"mode": mode, "status": "error"})
        finally:
            conn.close()


class ExplorerMetaRepairThread(QThread):
    log_msg = Signal(str)
    progress = Signal(int, int, str, str)
    done = Signal(dict)

    def __init__(
        self,
        group_ids: list[str],
        db_path: str,
        exiftool_path: Optional[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._group_ids = group_ids
        self._db_path = db_path
        self._exiftool_path = exiftool_path

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.explorer_meta_repair import repair_explorer_meta_for_groups

            result = repair_explorer_meta_for_groups(
                conn,
                self._group_ids,
                self._exiftool_path,
                progress_fn=lambda done, total, gid, status: self.progress.emit(
                    done, total, gid, status
                ),
            )
            self.done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] Explorer metadata repair exception: {exc}")
            self.done.emit(
                {
                    "total": len(self._group_ids),
                    "success": 0,
                    "failed": len(self._group_ids),
                    "skipped": 0,
                    "errors": [str(exc)],
                    "group_ids": list(self._group_ids),
                    "exception": str(exc),
                }
            )
        finally:
            conn.close()


class ReindexThread(QThread):
    log_msg  = Signal(str)
    progress = Signal(int, int, str)
    done     = Signal(dict)

    def __init__(
        self,
        group_ids: list[str],
        data_dir: str,
        managed_dir: str,
        db_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._group_ids = group_ids
        self._data_dir = data_dir
        self._managed_dir = managed_dir
        self._db_path = db_path

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            scanner = InboxScanner(
                conn,
                self._data_dir,
                managed_dir=self._managed_dir,
                log_fn=self.log_msg.emit,
            )
            total = len(self._group_ids)
            for index, group_id in enumerate(self._group_ids, start=1):
                self.progress.emit(index - 1, total, f"재색인 중: {group_id[:8]}…")
                scanner.reprocess_group(group_id)
                self.progress.emit(index, total, f"완료: {group_id[:8]}…")
            self.done.emit({"success": True, "group_ids": list(self._group_ids)})
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 재색인 예외: {exc}")
            self.done.emit({"success": False, "error": str(exc), "group_ids": list(self._group_ids)})
        finally:
            conn.close()


class ExactDuplicateCheckThread(QThread):
    log_msg  = Signal(str)
    progress = Signal(int, int, str)
    done     = Signal(dict)

    def __init__(
        self,
        db_path: str,
        inbox_dir: str,
        scope: str,
        group_ids: Optional[list[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._inbox_dir = inbox_dir
        self._scope = scope
        self._group_ids = group_ids

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.duplicate_finder import (
                build_exact_duplicate_cleanup_preview,
                find_exact_duplicates,
                get_duplicate_check_summary,
            )

            self.progress.emit(0, 3, "대상 파일 수를 계산하는 중…")
            summary = get_duplicate_check_summary(
                conn, self._inbox_dir, scope=self._scope, group_ids=self._group_ids
            )
            self.progress.emit(1, 3, "완전 중복 파일을 찾는 중…")
            dup_groups = find_exact_duplicates(
                conn, scope=self._scope, group_ids=self._group_ids
            )
            self.progress.emit(2, 3, "정리 후보를 계산하는 중…")
            cleanup = build_exact_duplicate_cleanup_preview(conn, dup_groups) if dup_groups else None

            delete_file_ids: list[str] = []
            if cleanup:
                for group in cleanup.get("groups", []):
                    for file_info in group.get("delete_candidates", []):
                        file_id = file_info.get("file_id")
                        if file_id:
                            delete_file_ids.append(file_id)

            self.progress.emit(3, 3, "중복 검사 준비가 끝났습니다.")
            self.done.emit(
                {
                    "success": True,
                    "summary": summary,
                    "dup_groups": dup_groups,
                    "cleanup": cleanup,
                    "delete_file_ids": delete_file_ids,
                }
            )
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 완전 중복 검사 예외: {exc}")
            self.done.emit({"success": False, "error": str(exc)})
        finally:
            conn.close()


class VisualDuplicateCheckThread(QThread):
    log_msg  = Signal(str)
    progress = Signal(int, int, str)
    done     = Signal(dict)

    def __init__(
        self,
        db_path: str,
        inbox_dir: str,
        scope: str,
        group_ids: Optional[list[str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._inbox_dir = inbox_dir
        self._scope = scope
        self._group_ids = group_ids

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.duplicate_finder import get_duplicate_check_summary
            from core.visual_duplicate_decision import decide_visual_duplicate_groups
            from core.visual_duplicate_finder import find_visual_duplicates

            self.progress.emit(0, 4, "대상 파일 수를 계산하는 중…")
            summary = get_duplicate_check_summary(
                conn, self._inbox_dir, scope=self._scope, group_ids=self._group_ids
            )
            self.progress.emit(1, 4, "시각 중복 후보를 찾는 중…")
            dup_groups = find_visual_duplicates(
                conn, scope=self._scope, group_ids=self._group_ids
            )
            initial_decisions: dict[str, str] = {}

            if dup_groups:
                self.progress.emit(3, 4, "자동 keep/delete 추천을 계산하는 중…")
                try:
                    decisions_per_group = decide_visual_duplicate_groups(dup_groups)
                    for group_decisions in decisions_per_group:
                        for decision in group_decisions:
                            if decision.file_id:
                                initial_decisions[decision.file_id] = decision.decision
                except Exception as exc:
                    self.log_msg.emit(
                        f"[WARN] 자동 keep/delete 계산 실패 (수동 검토 필요): {exc}"
                    )

            self.progress.emit(4, 4, "검토 화면을 준비하는 중…")
            self.done.emit(
                {
                    "success": True,
                    "summary": summary,
                    "dup_groups": dup_groups,
                    "initial_decisions": initial_decisions,
                }
            )
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 시각 중복 검사 예외: {exc}")
            self.done.emit({"success": False, "error": str(exc)})
        finally:
            conn.close()


class ClassifyThread(QThread):
    """사용자 승인 후 execute_classify_preview()를 별도 스레드에서 실행한다."""

    log_msg       = Signal(str)
    classify_done = Signal(dict)

    def __init__(
        self,
        preview: dict,
        config:  dict,
        db_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._preview = preview
        self._config  = config
        self._db_path = db_path

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.classifier import execute_classify_preview
            result = execute_classify_preview(conn, self._preview, self._config)
            for path in result.get("copy_log", []):
                self.log_msg.emit(f"[INFO] Copied: {path}")
            self.classify_done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 분류 실행 오류: {exc}")
            self.classify_done.emit({
                "success": False, "copied": 0, "skipped": 0,
                "group_id": self._preview.get("group_id", ""),
            })
        finally:
            conn.close()


class EnrichThread(QThread):
    """Pixiv 메타데이터 보강을 UI freeze 없이 실행한다."""

    log_msg     = Signal(str)
    enrich_done = Signal(dict)

    def __init__(self, file_id: str, db_path: str, exiftool_path: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self._file_id       = file_id
        self._db_path       = db_path
        self._exiftool_path = exiftool_path

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.metadata_enricher import enrich_file_from_pixiv
            result = enrich_file_from_pixiv(conn, self._file_id, exiftool_path=self._exiftool_path)
            self.enrich_done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 보강 예외: {exc}")
            self.enrich_done.emit({
                "status": "error",
                "sync_status": None,
                "message": str(exc),
            })
        finally:
            conn.close()


class ScanThread(QThread):
    """Configured inbox scan without UI freeze."""

    log_msg   = Signal(str)
    scan_done = Signal(object)   # ScanResult

    def __init__(
        self,
        data_dir: str,
        inbox_dir: str,
        managed_dir: str,
        db_path: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.data_dir  = data_dir
        self.inbox_dir = inbox_dir
        self.managed_dir = managed_dir
        self.db_path   = db_path

    def run(self) -> None:
        conn = initialize_database(self.db_path)
        try:
            scanner = InboxScanner(
                conn, self.data_dir, managed_dir=self.managed_dir, log_fn=self.log_msg.emit
            )
            result  = scanner.scan(self.inbox_dir)
            self.scan_done.emit(result)
        except Exception as exc:
            self.log_msg.emit(f"[ERROR] 스캔 예외: {exc}")
            self.scan_done.emit(ScanResult(failed=1, errors=[str(exc)]))
        finally:
            conn.close()


# ------------------------------------------------------------------
# 공개 함수
# ------------------------------------------------------------------

def load_config(config_path: str = "config.json") -> dict:
    """config.json 로드. 없으면 example → 기본값 순으로 fallback."""
    from core.config_manager import load_config as _load
    try:
        return _load(config_path)
    except Exception:
        example = Path("config.example.json")
        if example.exists():
            return json.loads(example.read_text(encoding="utf-8"))
        return {
            "data_dir": "",
            "db": {"path": ""},
            "http_server": {"port": 18456},
        }


def run_app(config: dict, config_path: str = "config.json") -> int:
    """독립 실행용."""
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("Aru Archive")
    _apply_wine_style(app)
    window = MainWindow(config, config_path=config_path)
    window.show()
    return app.exec()


def _apply_wine_style(app: QApplication) -> None:
    """와인/버건디 다크 테마 전역 적용 — 팔레트 + QSS."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor("#1A0F14"))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor("#F7E8EC"))
    palette.setColor(QPalette.ColorRole.Base,            QColor("#211018"))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor("#2B1720"))
    palette.setColor(QPalette.ColorRole.Button,          QColor("#3A202B"))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor("#F7E8EC"))
    palette.setColor(QPalette.ColorRole.Text,            QColor("#F7E8EC"))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor("#5C2A3A"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#F7E8EC"))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor("#2B1720"))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor("#F7E8EC"))
    app.setPalette(palette)

    app.setStyleSheet(
        "QWidget { background: #1A0F14; color: #F7E8EC; }"
        "QGroupBox {"
        "  border: 1px solid #4A2030; border-radius: 5px; margin-top: 8px;"
        "  color: #E69AAA; font-size: 11px;"
        "}"
        "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        "QScrollBar:vertical { background: #1A0F14; width: 8px; border: none; }"
        "QScrollBar::handle:vertical {"
        "  background: #4A2030; border-radius: 4px; min-height: 20px;"
        "}"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        "QSplitter::handle { background: #4A2030; }"
        "QToolTip { background: #2B1720; color: #F7E8EC; border: 1px solid #B5526C; }"
        "QTextEdit { background: #211018; color: #F7E8EC; border: 1px solid #4A2030; }"
        "QHeaderView::section {"
        "  background: #2B1720; color: #D8AEBB; border: none; padding: 4px;"
        "}"
    )


# ------------------------------------------------------------------
# 메인 윈도우
# ------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(
        self,
        config: dict,
        config_path: str = "config.json",
    ) -> None:
        super().__init__()
        self.config = config
        self._config_path = config_path
        self._scan_thread: Optional[ScanThread] = None
        self._loading_dialog: Optional[LoadingOverlayDialog] = None
        self._reindex_thread: Optional[ReindexThread] = None
        self._explorer_meta_thread: Optional[QThread] = None
        self._dup_thread: Optional[QThread] = None
        self._current_category = "all"
        self._initial_workspace_prompt_scheduled = False
        self._initial_workspace_prompt_attempted = False
        self._initial_workspace_setup_checked = False

        self.setWindowTitle("Aru Archive")
        self.resize(1400, 900)

        from PyQt6.QtGui import QIcon
        from app.resources import icon_path
        self.setWindowIcon(QIcon(icon_path()))

        self._setup_ui()
        self._connect_signals()
        self._restore_workspace_paths()

        if Path(self._db_path()).exists():
            try:
                conn = self._get_conn()
                self._seed_localizations(conn)
                conn.close()
            except Exception:
                pass
            self._refresh_gallery()
            self._refresh_counts()

        self._start_ipc_server()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._initial_workspace_setup_checked:
            return
        self._initial_workspace_setup_checked = True
        self._schedule_initial_workspace_setup()

    def _ensure_loading_dialog(self) -> LoadingOverlayDialog:
        if self._loading_dialog is None:
            self._loading_dialog = LoadingOverlayDialog(self)
        return self._loading_dialog

    def _show_loading(
        self,
        title: str,
        message: str,
        *,
        detail: str = "",
        total: Optional[int] = None,
        current: int = 0,
    ) -> None:
        _t0 = time.perf_counter()
        dialog = self._ensure_loading_dialog()
        dialog.set_title_text(title)
        dialog.set_message_text(message)
        dialog.set_detail_text(detail)
        if total is None:
            dialog.set_indeterminate("작업 중…")
        else:
            dialog.set_progress(current, total, f"{current}/{max(total, 1)}")
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        QApplication.processEvents()
        _log_phase("loading.show", (time.perf_counter() - _t0) * 1000, title=title)

    def _update_loading(
        self,
        *,
        message: Optional[str] = None,
        detail: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        dialog = self._loading_dialog
        if dialog is None:
            return
        if message is not None:
            dialog.set_message_text(message)
        if detail is not None:
            dialog.set_detail_text(detail)
        if current is not None and total is not None:
            dialog.set_progress(current, total, f"{current}/{max(total, 1)}")

    def _hide_loading(self) -> None:
        if self._loading_dialog is None:
            return
        _t0 = time.perf_counter()
        self._loading_dialog.hide()
        _log_phase("loading.hide", (time.perf_counter() - _t0) * 1000)

    def _mirror_loading_log(self, message: str) -> None:
        dialog = self._loading_dialog
        if dialog is None:
            return
        clean = message.strip()
        for prefix in ("[INFO] ", "[WARN] ", "[ERROR] "):
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break
        dialog.set_detail_text(clean)
        QApplication.processEvents()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        tb = QToolBar("메인 툴바")
        tb.setMovable(False)
        tb.setStyleSheet(
            "QToolBar {"
            "  background: #2B1720; border-bottom: 1px solid #4A2030;"
            "  spacing: 4px; padding: 2px 6px;"
            "}"
            "QToolButton {"
            "  background: #3A202B; color: #F7E8EC;"
            "  border: 1px solid #B5526C; border-radius: 4px;"
            "  padding: 4px 10px; font-size: 12px;"
            "}"
            "QToolButton:hover { background: #5C2A3A; border-color: #E69AAA; }"
            "QToolButton:disabled { color: #8F6874; border-color: #4A2030; }"
            "QToolButton::menu-indicator { image: none; width: 0; }"
        )
        self.addToolBar(tb)

        # ── 작업 마법사 (단독 버튼) ──────────────────────────────────────
        self._btn_wizard = _tb_btn("🧭 작업 마법사", tb)
        self._btn_wizard.setToolTip(
            "분류 작업을 단계별로 진행하는 마법사를 엽니다. (9단계)"
        )
        tb.addSeparator()

        # ── 폴더 ▼ ───────────────────────────────────────────────────────
        folder_menu = QMenu(self)
        self._act_select_root   = folder_menu.addAction("📁 작업 폴더 설정")
        self._act_archive_root  = folder_menu.addAction("🗂 Archive Root 선택")
        self._act_archive_root.triggered.connect(self._on_select_root)
        _add_tb_menu(tb, "폴더 ▼", folder_menu)

        # ── 스캔 ▼ ───────────────────────────────────────────────────────
        scan_menu = QMenu(self)
        self._act_inbox_scan  = scan_menu.addAction("🔍 이미지 스캔")
        self._act_refresh     = scan_menu.addAction("🔄 갱신")
        self._act_refresh.setToolTip("갤러리와 사이드바 카운트를 새로고침합니다.")
        scan_menu.addSeparator()
        self._act_integrity   = scan_menu.addAction("🛡 파일 무결성 검사")
        self._act_integrity.setToolTip(
            "파일이 외부에서 삭제됐는지 확인하고 DB에 누락 상태를 기록합니다."
        )
        self._act_integrity.setEnabled(True)
        _add_tb_menu(tb, "스캔 ▼", scan_menu)

        # ── 중복 검사 ▼ ──────────────────────────────────────────────────
        dup_menu = QMenu(self)
        self._act_exact_dup   = dup_menu.addAction("🧬 완전 중복 검사")
        self._act_exact_dup.setToolTip("SHA-256 해시 기준 완전 일치 중복을 찾습니다.")
        self._act_visual_dup  = dup_menu.addAction("👁 시각적 중복 검사")
        self._act_visual_dup.setToolTip("유사한 이미지(perceptual hash 기반)를 찾습니다.")
        _add_tb_menu(tb, "중복 검사 ▼", dup_menu)

        # ── 메타데이터 ▼ ─────────────────────────────────────────────────
        meta_menu = QMenu(self)
        self._act_read_meta   = meta_menu.addAction("📄 파일 내 메타데이터 읽기")
        self._act_pixiv_meta  = meta_menu.addAction("🖼 Pixiv 메타데이터 가져오기")
        meta_menu.addSeparator()
        self._act_explorer_meta_repair = meta_menu.addAction("🛠 선택 Explorer 메타 복구")
        self._act_xmp_sel     = meta_menu.addAction("🔄 선택 XMP 재처리")
        self._act_xmp_all     = meta_menu.addAction("🔄 전체 XMP 재처리")
        self._act_explorer_meta_repair.setToolTip(
            "Windows 탐색기에서 보이는 제목, 태그, 만든 이를 선택 항목 기준으로 다시 기록합니다."
        )
        self._act_xmp_all.setToolTip(
            "모든 항목의 XMP 메타데이터를 다시 기록합니다. 시간이 오래 걸릴 수 있습니다."
        )
        _add_tb_menu(tb, "메타데이터 ▼", meta_menu)

        # ── 정규화 ▼ ─────────────────────────────────────────────────────
        norm_menu = QMenu(self)
        self._act_retag       = norm_menu.addAction("🏷 태그 다시 분석")
        self._act_retag.setToolTip(
            "현재 태그와 사용자 보정값을 바탕으로 분류 결과를 다시 계산합니다."
        )
        self._act_candidates  = norm_menu.addAction("🏷 태그 후보 검토")
        self._act_candidates.setToolTip(
            "자동 생성된 태그 후보를 검토하고 사전에 추가합니다."
        )
        self._act_dict_import = norm_menu.addAction("🌐 외부 사전 가져오기")
        self._act_dict_import.setToolTip(
            "외부 웹 소스에서 시리즈/캐릭터 사전을 가져옵니다."
        )
        self._act_tag_pack    = norm_menu.addAction("📦 번역 태그팩 가져오기")
        self._act_tag_pack.setToolTip(
            "한국어/일본어 이름이 포함된 태그팩 파일을 가져옵니다."
        )
        self._act_tag_pack.triggered.connect(self._on_show_dict_import)
        norm_menu.addSeparator()
        self._act_dict_export = norm_menu.addAction("📤 태그 사전 내보내기 (JSON)")
        self._act_dict_export.setToolTip("현재 사전을 JSON 파일로 내보냅니다.")
        _add_tb_menu(tb, "정규화 ▼", norm_menu)

        # ── 분류 ▼ ───────────────────────────────────────────────────────
        cls_menu = QMenu(self)
        self._act_cls_preview    = cls_menu.addAction("📋 분류 미리보기")
        self._act_cls_preview.setToolTip("전체 갤러리의 분류 결과를 미리 봅니다.")
        self._act_cls_sel_prev   = cls_menu.addAction("📋 선택 분류 미리보기")
        self._act_cls_sel_prev.setToolTip("현재 선택된 항목만 분류 결과를 미리 봅니다.")
        cls_menu.addSeparator()
        self._act_batch_classify = cls_menu.addAction("📋 일괄 분류")
        self._act_cls_run        = cls_menu.addAction("▶ 분류 실행")
        self._act_cls_run.setToolTip(
            "현재 선택된 항목을 즉시 분류합니다. 미리보기를 먼저 확인하세요."
        )
        _add_tb_menu(tb, "분류 ▼", cls_menu)

        # ── 도구 ▼ ───────────────────────────────────────────────────────
        tool_menu = QMenu(self)
        self._act_work_log   = tool_menu.addAction("🕘 작업 로그")
        self._act_save_jobs  = tool_menu.addAction("💾 저장 작업")
        self._act_dict_backup = tool_menu.addAction("💾 백업 내보내기")
        tool_menu.addSeparator()
        self._act_db_init    = tool_menu.addAction("⚠ 전체 DB 초기화")
        self._act_db_init.setToolTip(
            "⚠ 위험: DB에 저장된 모든 작품/파일/분류/사용자 사전 기록을 삭제합니다.\n"
            "원본 이미지 파일은 삭제되지 않습니다.\n"
            "실행 전 자동 백업이 생성됩니다."
        )
        _add_tb_menu(tb, "도구 ▼", tool_menu)

        tb.addSeparator()

        self._lbl_root = QLabel("분류 대상 폴더 미설정")
        self._lbl_root.setStyleSheet(_STYLE_PATH_NONE)
        self._lbl_root.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._lbl_root.setToolTip("분류 대상 폴더 경로")
        tb.addWidget(self._lbl_root)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        self._sidebar = SidebarWidget()
        self._sidebar.setFixedWidth(160)
        splitter.addWidget(self._sidebar)

        self._stack   = QStackedWidget()
        self._gallery = GalleryView()
        self._no_meta = NoMetadataView()
        self._stack.addWidget(self._gallery)   # index 0
        self._stack.addWidget(self._no_meta)   # index 1
        splitter.addWidget(self._stack)

        self._detail = DetailView()
        splitter.addWidget(self._detail)

        splitter.setSizes([160, 900, 340])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(2, False)
        outer.addWidget(splitter, 1)

        self._log = LogPanel()
        self._log.setFixedHeight(130)
        outer.addWidget(self._log)

    # ------------------------------------------------------------------
    # 시그널 연결
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        # 툴바 — 마법사 (단독 버튼)
        self._btn_wizard.clicked.connect(self._on_show_wizard)

        # 툴바 — 폴더 메뉴
        self._act_select_root.triggered.connect(self._on_select_root)

        # 툴바 — 스캔 메뉴
        self._act_inbox_scan.triggered.connect(self._on_inbox_scan)
        self._act_refresh.triggered.connect(self._on_refresh)
        self._act_integrity.triggered.connect(self._on_integrity_check)

        # 툴바 — 중복 검사 메뉴
        self._act_exact_dup.triggered.connect(self._on_exact_duplicate_check)
        self._act_visual_dup.triggered.connect(self._on_visual_duplicate_check)

        # 툴바 — 메타데이터 메뉴
        self._act_read_meta.triggered.connect(self._on_read_meta_selected)
        self._act_pixiv_meta.triggered.connect(self._on_pixiv_meta_selected)
        self._act_explorer_meta_repair.triggered.connect(self._on_explorer_meta_repair_selected)
        self._act_xmp_sel.triggered.connect(self._on_xmp_retry_selected)
        self._act_xmp_all.triggered.connect(self._on_xmp_retry_all)

        # 툴바 — 정규화 메뉴
        self._act_retag.triggered.connect(self._on_retag)
        self._act_candidates.triggered.connect(self._on_show_candidates)
        self._act_dict_import.triggered.connect(self._on_show_dict_import)
        self._act_dict_export.triggered.connect(self._on_dict_export)

        # 툴바 — 분류 메뉴
        self._act_cls_preview.triggered.connect(self._on_classify_preview)
        self._act_cls_sel_prev.triggered.connect(self._on_classify_preview)
        self._act_batch_classify.triggered.connect(self._on_batch_classify)
        self._act_cls_run.triggered.connect(self._on_classify_run)

        # 툴바 — 도구 메뉴
        self._act_work_log.triggered.connect(self._on_show_work_log)
        self._act_save_jobs.triggered.connect(self._on_show_save_jobs)
        self._act_dict_backup.triggered.connect(self._on_dict_backup)
        self._act_db_init.triggered.connect(self._on_db_init)

        # 사이드바 / 갤러리
        self._sidebar.category_selected.connect(self._on_category_changed)
        self._gallery.item_selected.connect(self._on_item_selected)
        self._gallery.delete_requested.connect(self._on_gallery_delete_requested)
        self._gallery.open_location_requested.connect(self._on_open_file_location)
        self._gallery.read_meta_requested.connect(self._on_read_meta)
        self._gallery.refresh_requested.connect(self._on_refresh)

        # 상세 패널
        self._detail.read_meta_requested  .connect(self._on_read_meta)
        self._detail.pixiv_meta_requested .connect(self._on_pixiv_meta)
        self._detail.xmp_retry_requested  .connect(self._on_xmp_retry)
        self._detail.explorer_meta_repair_requested.connect(self._on_explorer_meta_repair_selected)
        self._detail.regen_thumb_requested.connect(self._on_regen_thumb)
        self._detail.bmp_convert_requested.connect(self._on_bmp_convert)
        self._detail.gif_convert_requested.connect(self._on_gif_convert)
        self._detail.sidecar_requested    .connect(self._on_sidecar)
        self._detail.reindex_requested    .connect(self._on_reindex)

        self._no_meta.retry_requested .connect(self._on_nm_retry)
        self._no_meta.ignore_requested.connect(self._on_nm_ignore)

    # ------------------------------------------------------------------
    # 경로 헬퍼
    # ------------------------------------------------------------------

    def _data_dir(self) -> str:
        return str(self.config.get("data_dir", ""))

    def _inbox_dir(self) -> str:
        return str(self.config.get("inbox_dir", ""))

    def _managed_dir(self) -> str:
        return str(self.config.get("managed_dir", ""))

    def _classified_dir(self) -> str:
        return str(self.config.get("classified_dir", ""))

    def _db_path(self) -> str:
        raw = self.config.get("db", {}).get("path", "")
        if raw:
            return raw
        dd = self._data_dir()
        return f"{dd}/.runtime/aru_archive.db" if dd else "aru_archive.db"

    def _get_conn(self):
        db_path = self._db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return initialize_database(db_path)

    # ------------------------------------------------------------------
    # Workspace path restore (앱 시작 시)
    # ------------------------------------------------------------------

    def _restore_workspace_paths(self) -> None:
        ensure_app_directories(self.config)

        inbox_dir = self._inbox_dir()
        if not inbox_dir:
            self._lbl_root.setText("분류 대상 폴더 미설정 — [📁 작업 폴더 설정] 클릭")
            self._lbl_root.setStyleSheet(_STYLE_PATH_NONE)
            return

        self._lbl_root.setToolTip(inbox_dir)
        if Path(inbox_dir).exists():
            self._lbl_root.setText(inbox_dir)
            self._lbl_root.setStyleSheet(_STYLE_PATH_OK)
            try:
                ensure_workspace_directories(self.config)
            except Exception as exc:
                logger.warning("폴더 생성 실패: %s", exc)
        else:
            self._lbl_root.setText(f"⚠ {inbox_dir}  (경로 없음)")
            self._lbl_root.setStyleSheet(_STYLE_PATH_WARN)
            logger.warning("Inbox path not found: %s", inbox_dir)

    def _ensure_initial_workspace_setup(self) -> None:
        inbox_dir = self._inbox_dir().strip()
        classified_dir = self._classified_dir().strip()
        managed_dir = self._managed_dir().strip()

        inbox_exists = bool(inbox_dir) and Path(inbox_dir).exists()
        classified_exists = bool(classified_dir) and Path(classified_dir).exists()
        managed_exists = bool(managed_dir) and Path(managed_dir).exists()

        if inbox_exists:
            if not classified_dir or not managed_dir:
                update_workspace_from_inbox(self.config, inbox_dir)
            if not classified_exists or not managed_exists:
                ensure_workspace_directories(self.config)
                try:
                    save_config(self.config, self._config_path)
                except Exception:
                    pass
                self._restore_workspace_paths()
            return

        if self._initial_workspace_prompt_attempted:
            return
        self._initial_workspace_prompt_attempted = True
        self._open_path_setup_dialog(first_run=True)

    def _schedule_initial_workspace_setup(self) -> None:
        if self._initial_workspace_prompt_scheduled:
            return
        self._initial_workspace_prompt_scheduled = True
        QTimer.singleShot(0, self._run_initial_workspace_setup)

    def _run_initial_workspace_setup(self) -> None:
        self._initial_workspace_prompt_scheduled = False
        self._ensure_initial_workspace_setup()

    # ------------------------------------------------------------------
    # 갤러리 / 카운트 갱신
    # ------------------------------------------------------------------

    def _refresh_gallery(self) -> None:
        _t0 = time.perf_counter()
        cat = self._current_category
        if cat == "no_metadata":
            self._stack.setCurrentIndex(_NO_META_IDX)
            self._load_no_metadata_panel()
            _log_phase("gallery_refresh", (time.perf_counter() - _t0) * 1000, cat=cat)
            return

        self._stack.setCurrentIndex(_GALLERY_IDX)

        # missing 카테고리는 _GALLERY_BASE(present-only) 를 우회하는 전용 SQL 사용
        if cat == "missing":
            sql = _GALLERY_MISSING_SQL
        else:
            where = _GALLERY_WHERE.get(cat, "")
            sql   = f"{_GALLERY_BASE} {where} ORDER BY g.indexed_at DESC"

        try:
            conn = self._get_conn()
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
            conn.close()
            self._gallery.load_groups(rows)
        except Exception as exc:
            logger.warning("갤러리 로드 실패: %s", exc)
            self._gallery.load_groups([])
        _log_phase("gallery_refresh", (time.perf_counter() - _t0) * 1000, cat=cat)

    def _refresh_gallery_item(self, group_id: str) -> None:
        sql = _GALLERY_BASE + " AND g.group_id = ?"
        try:
            conn = self._get_conn()
            row  = conn.execute(sql, (group_id,)).fetchone()
            conn.close()
            if row:
                self._gallery.refresh_item(group_id, dict(row))
        except Exception:
            pass

    def _refresh_counts(self) -> None:
        _t0 = time.perf_counter()
        try:
            conn   = self._get_conn()
            counts = {
                key: (conn.execute(sql).fetchone() or (0,))[0]
                for key, sql in _COUNT_SQL.items()
            }
            conn.close()
            self._sidebar.update_counts(counts)
        except Exception as exc:
            logger.warning("카운트 로드 실패: %s", exc)
        _log_phase("sidebar_counts", (time.perf_counter() - _t0) * 1000)

    def _load_no_metadata_panel(self) -> None:
        try:
            conn = self._get_conn()
            rows = [dict(r) for r in conn.execute(
                "SELECT queue_id, file_path, fail_reason, detected_at, resolved, notes "
                "FROM no_metadata_queue ORDER BY resolved, detected_at DESC"
            ).fetchall()]
            conn.close()
            self._no_meta.load_queue(rows)
        except Exception as exc:
            logger.warning("No Metadata 큐 로드 실패: %s", exc)
            self._no_meta.load_queue([])

    def _refresh_detail(self, group_id: str) -> None:
        _t0 = time.perf_counter()
        try:
            conn = self._get_conn()
            g    = conn.execute(
                "SELECT * FROM artwork_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            files = conn.execute(
                "SELECT af.*, tc.thumb_path FROM artwork_files af "
                "LEFT JOIN thumbnail_cache tc ON tc.file_id = af.file_id "
                "WHERE af.group_id = ? ORDER BY af.page_index, af.file_role",
                (group_id,),
            ).fetchall()
            conn.close()
            if g:
                self._detail.show_group(dict(g), [dict(f) for f in files])
        except Exception as exc:
            logger.warning("상세 정보 로드 실패: %s", exc)
        _log_phase("detail_refresh", (time.perf_counter() - _t0) * 1000)

    # ------------------------------------------------------------------
    # 툴바 핸들러
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        """갤러리와 카운트를 수동으로 갱신한다."""
        self._refresh_gallery()
        self._refresh_counts()

    def _on_integrity_check(self) -> None:
        """파일 무결성 검사 — 외부 삭제 파일을 DB missing으로 표시.

        1. inbox_dir / managed_dir reachability probe
        2. dry-run scan
        3. 0건이면 info, N건이면 IntegrityConfirmDialog
        4. confirm 시 wet-run + _on_refresh
        """
        from pathlib import Path as _Path

        # 1. reachability probe
        inbox = self._inbox_dir()
        managed = self._managed_dir()

        for label, path in (("Inbox", inbox), ("Managed", managed)):
            if path and not _Path(path).exists():
                QMessageBox.warning(
                    self,
                    "드라이브 접근 불가",
                    f"{label} 폴더에 접근할 수 없습니다:\n{path}\n\n"
                    f"NAS / 외장 드라이브 연결 상태를 확인한 뒤 다시 시도하세요.",
                )
                self._log.append(
                    f"[WARN] 무결성 검사 중단: {label} 경로 접근 불가 ({path})"
                )
                return

        # 2. dry-run scan
        from core.integrity_scanner import run_integrity_scan
        try:
            conn = self._get_conn()
            try:
                scan = run_integrity_scan(conn, dry_run=True)
            finally:
                conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 무결성 검사 실패: {exc}")
            return

        missing_count = scan["missing_count"]

        # 3. 0건 처리
        if missing_count == 0:
            QMessageBox.information(
                self,
                "파일 무결성 검사",
                "누락된 파일이 없습니다.\n"
                "DB의 모든 파일이 디스크에서 정상 확인되었습니다.",
            )
            self._log.append("[INFO] 무결성 검사 완료: 누락 파일 0건")
            return

        # 4. confirm dialog
        from app.views.integrity_confirm_dialog import IntegrityConfirmDialog
        dlg = IntegrityConfirmDialog(scan, parent=self)
        if dlg.exec() != IntegrityConfirmDialog.DialogCode.Accepted:
            self._log.append(
                f"[INFO] 무결성 검사 취소 — {missing_count}건 미반영"
            )
            return

        # 5. wet-run
        try:
            conn = self._get_conn()
            try:
                apply_result = run_integrity_scan(conn, dry_run=False)
            finally:
                conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 무결성 반영 실패: {exc}")
            return

        mismatch_count = apply_result.get("restore_skipped_hash_mismatch", 0)
        msg = (
            f"[INFO] 누락으로 표시: {apply_result['updated']}건 / "
            f"다시 확인됨: {apply_result['restore_updated']}건"
        )
        if mismatch_count:
            msg += f" / 해시 불일치로 복원 보류: {mismatch_count}건"
        self._log.append(msg)

        # 6. hash mismatch 복원 보류 항목이 있으면 상세 dialog 표시
        mismatch_files = apply_result.get("hash_mismatch_files", [])
        if mismatch_files:
            from app.views.integrity_restore_hold_dialog import IntegrityRestoreHoldDialog
            hold_dlg = IntegrityRestoreHoldDialog(mismatch_files, parent=self)
            hold_dlg.view_missing_files_requested.connect(self._navigate_to_missing_category)
            hold_dlg.exec()

        # 7. refresh
        self._on_refresh()

    def _navigate_to_missing_category(self) -> None:
        """Sidebar의 '⚠ 누락 파일' 카테고리를 선택한다.

        IntegrityRestoreHoldDialog의 view_missing_files_requested 시그널에 연결된다.
        category_selected 시그널이 이미 _on_category_changed에 연결되어 있으므로
        카테고리 선택만으로 갤러리 갱신이 트리거된다.
        """
        self._sidebar.select_category("missing")

    def _on_select_root(self) -> None:
        self._open_path_setup_dialog(first_run=False)

    def _open_path_setup_dialog(self, *, first_run: bool) -> None:
        start_dir = self._inbox_dir() or str(Path.home())
        dlg = PathSetupDialog(
            start_dir=start_dir,
            data_dir=self._data_dir(),
            parent=self,
        )
        if first_run:
            dlg.setWindowTitle("첫 실행 폴더 설정")
            self._log.append("[INFO] 첫 실행 감지: 분류 대상 폴더를 먼저 설정하세요.")
        if dlg.exec() != PathSetupDialog.DialogCode.Accepted:
            return

        paths = dlg.selected_paths()
        if not paths:
            return

        update_workspace_from_inbox(self.config, paths["inbox_dir"])
        try:
            ensure_app_directories(self.config)
            ensure_workspace_directories(self.config)
            save_config(self.config, self._config_path)
            self._log.append(f"[INFO] Config saved: {self._config_path}")
        except Exception as exc:
            self._log.append(f"[ERROR] Config 저장 실패: {exc}")
            return

        self._restore_workspace_paths()
        self._log.append(f"[INFO] Inbox folder set: {self._inbox_dir()}")
        self._log.append(f"[INFO] Classified folder set: {self._classified_dir()}")
        self._log.append(f"[INFO] Managed folder set: {self._managed_dir()}")

        if Path(self._db_path()).exists():
            self._refresh_gallery()
            self._refresh_counts()

    def _on_inbox_scan(self) -> None:
        if self._scan_thread and self._scan_thread.isRunning():
            return

        inbox    = self._inbox_dir()
        data_dir = self._data_dir()
        db_path  = self._db_path()

        if not inbox:
            self._log.append(
                "[WARN] 분류 대상 폴더가 설정되지 않았습니다. "
                "[📁 작업 폴더 설정]을 먼저 실행하세요."
            )
            return

        inbox_path = Path(inbox)
        if not inbox_path.exists():
            try:
                inbox_path.mkdir(parents=True, exist_ok=True)
                self._log.append(f"[INFO] Created Inbox folder: {inbox}")
            except Exception as exc:
                self._log.append(f"[ERROR] Cannot create Inbox folder: {exc}")
                return

        self._log.append(f"[INFO] 이미지 스캔 시작: {inbox}")
        self._act_inbox_scan.setEnabled(False)
        self._show_loading(
            "Inbox 스캔",
            "폴더와 DB를 대조하며 작품을 정리하고 있어요.",
            detail=inbox,
        )

        self._scan_thread = ScanThread(
            data_dir, inbox, self._managed_dir(), db_path, parent=self
        )
        self._scan_thread.log_msg.connect(self._log.append)
        self._scan_thread.log_msg.connect(self._mirror_loading_log)
        self._scan_thread.scan_done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, result: ScanResult) -> None:
        self._act_inbox_scan.setEnabled(True)
        self._hide_loading()
        self._log.append(
            f"[INFO] 스캔 완료 — 신규: {result.new}, "
            f"스킵: {result.skipped}, 실패: {result.failed}"
        )
        self._refresh_gallery()
        self._refresh_counts()

    def _on_db_init(self) -> None:
        db_path = self._db_path()
        backup_path = self._build_reset_backup_path(db_path)

        dialog = DatabaseResetConfirmDialog(
            db_path=db_path,
            backup_path=backup_path,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._log.append("[INFO] DB 초기화가 취소되었습니다.")
            return

        # DB 파일이 없으면 백업 없이 바로 초기화(새 DB 생성)
        db_file = Path(db_path)
        if db_file.exists():
            if not backup_database(db_path, backup_path):
                QMessageBox.critical(
                    self,
                    "백업 실패",
                    f"백업 파일 생성에 실패했습니다.\n경로: {backup_path}\n\n"
                    "DB 초기화를 중단합니다.\n"
                    "대상 경로에 쓰기 권한이 있는지 확인하세요.",
                )
                self._log.append(f"[ERROR] DB 초기화 중단 — 백업 실패: {backup_path}")
                return
            self._log.append(f"[INFO] DB 백업 생성 완료: {backup_path}")

            # 기존 DB 파일 및 WAL/SHM 삭제
            try:
                for suffix in ("", "-wal", "-shm"):
                    p = Path(f"{db_path}{suffix}")
                    if not p.exists():
                        continue
                    try:
                        p.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        # Busy/locked files: best-effort; WAL/SHM은 무시
                        if suffix == "":
                            raise
                        try:
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass
            except sqlite3.OperationalError as exc:
                self._log.append(
                    f"[ERROR] DB 초기화 실패: {exc} "
                    "(다른 작업이 DB를 사용 중인지 확인하세요.)"
                )
                return
            except Exception as exc:
                self._log.append(f"[ERROR] DB 초기화 실패: {exc}")
                return

        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = initialize_database(db_path)
            self._seed_localizations(conn)
            conn.close()
        except sqlite3.OperationalError as exc:
            self._log.append(
                f"[ERROR] DB 초기화 실패: {exc} "
                "(다른 작업이 DB를 사용 중인지 확인하세요.)"
            )
            return
        except Exception as exc:
            self._log.append(f"[ERROR] DB 초기화 실패: {exc}")
            return

        self._log.append(f"[INFO] DB 초기화 완료: {db_path}")
        QMessageBox.information(
            self,
            "초기화 완료",
            f"DB 초기화가 완료되었습니다.\n백업 파일: {backup_path}",
        )
        self._detail.clear()
        self._refresh_gallery()
        self._refresh_counts()

    def _build_reset_backup_path(self, db_path: str) -> str:
        """DB 초기화 전 자동 백업 파일 경로를 생성한다 (타임스탬프 suffix)."""
        from datetime import datetime as _dt
        src = Path(db_path)
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        return str(src.parent / f"{src.stem}_before_reset_{stamp}{src.suffix}")

    def _seed_localizations(self, conn) -> None:
        try:
            from core.tag_localizer import seed_builtin_localizations
            n = seed_builtin_localizations(conn)
            if n:
                self._log.append(f"[INFO] 내장 로컬라이제이션 {n}개 추가")
        except Exception as exc:
            logger.warning("로컬라이제이션 시드 실패: %s", exc)
        try:
            from core.tag_pack_loader import seed_builtin_tag_packs
            result = seed_builtin_tag_packs(conn)
            total = sum(result.values())
            if total:
                self._log.append(
                    f"[INFO] 태그 팩 시드 완료: "
                    f"series={result['series_aliases']} "
                    f"character={result['character_aliases']} "
                    f"localization={result['localizations']}"
                )
        except Exception as exc:
            logger.warning("태그 팩 시드 실패: %s", exc)

    # ------------------------------------------------------------------
    # 사이드바 / 갤러리 핸들러
    # ------------------------------------------------------------------

    def _on_category_changed(self, key: str) -> None:
        self._current_category = key
        self._detail.clear()
        self._refresh_gallery()

    def _on_item_selected(self, group_id: str) -> None:
        self._refresh_detail(group_id)

    # ------------------------------------------------------------------
    # 상세 패널 버튼 핸들러
    # ------------------------------------------------------------------

    def _on_read_meta(self, group_id: str) -> None:
        try:
            conn = self._get_conn()
            row  = conn.execute(
                "SELECT file_path, file_format FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'original' LIMIT 1",
                (group_id,),
            ).fetchone()
            conn.close()
            if not row:
                self._log.append("[WARN] 원본 파일 없음")
                return
            meta = read_aru_metadata(row["file_path"], row["file_format"])
            if meta:
                snippet = json.dumps(meta, ensure_ascii=False)[:200]
                self._log.append(f"[INFO] 파일 내 메타데이터: {snippet}")
            else:
                self._log.append(
                    f"[INFO] AruArchive JSON 없음: {Path(row['file_path']).name}"
                )
        except Exception as exc:
            self._log.append(f"[ERROR] 메타데이터 읽기 실패: {exc}")

    def _on_pixiv_meta(self, group_id: str) -> None:
        """파일명 → artwork_id 추출 → Pixiv AJAX fetch → 메타데이터 기록."""
        if getattr(self, "_enrich_thread", None) and self._enrich_thread.isRunning():
            self._log.append("[WARN] 이미 보강 작업이 진행 중입니다")
            return
        try:
            conn = self._get_conn()
            row  = conn.execute(
                "SELECT file_id, file_path FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'original' LIMIT 1",
                (group_id,),
            ).fetchone()
            conn.close()
            if not row:
                self._log.append("[WARN] 원본 파일 없음")
                return

            fp      = row["file_path"]
            file_id = row["file_id"]

            parsed = parse_pixiv_filename(fp)
            if parsed is None:
                self._log.append(
                    f"[WARN] 파일명에서 Pixiv artwork_id 추출 실패: {Path(fp).name}  "
                    "(지원 형식: {artwork_id}_p{n}.ext)"
                )
                return

            self._detail.show_pixiv_result(parsed.artwork_id, parsed.artwork_url)
            self._log.append(
                f"[INFO] Pixiv fetch 시작: artwork_id={parsed.artwork_id}"
            )

            thread = EnrichThread(
                file_id, self._db_path(),
                exiftool_path=self._exiftool_path(),
                parent=self,
            )
            thread.log_msg.connect(self._log.append)
            thread.enrich_done.connect(
                lambda res, gid=group_id: self._on_enrich_done(res, gid)
            )
            thread.start()
            self._enrich_thread = thread

        except Exception as exc:
            self._log.append(f"[ERROR] Pixiv 메타데이터 가져오기 실패: {exc}")

    def _on_enrich_done(self, result: dict, group_id: str) -> None:
        msg = result.get("message", "")
        if result.get("status") == "success":
            self._log.append(f"[INFO] {msg}")
            self._refresh_gallery_item(group_id)
            self._refresh_detail(group_id)
            self._refresh_counts()
        else:
            self._log.append(f"[WARN] 보강 실패: {msg}")

    def _on_regen_thumb(self, group_id: str) -> None:
        try:
            conn    = self._get_conn()
            orig    = conn.execute(
                "SELECT file_path, file_id, file_hash FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'original' LIMIT 1",
                (group_id,),
            ).fetchone()
            managed = conn.execute(
                "SELECT file_path FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'managed' LIMIT 1",
                (group_id,),
            ).fetchone()

            src: Optional[Path] = None
            if managed:
                p = Path(managed["file_path"])
                if p.exists():
                    src = p
            if src is None and orig:
                p = Path(orig["file_path"])
                if p.exists():
                    src = p

            if src and orig:
                fhash = compute_file_hash(src)
                generate_thumbnail(
                    conn, str(src), self._data_dir(), orig["file_id"], fhash
                )
                conn.close()
                self._log.append(f"[INFO] 썸네일 재생성 완료: {src.name}")
                self._refresh_gallery_item(group_id)
            else:
                conn.close()
                self._log.append("[WARN] 썸네일 소스 파일 없음")
        except Exception as exc:
            self._log.append(f"[ERROR] 썸네일 재생성 실패: {exc}")

    def _on_bmp_convert(self, group_id: str) -> None:
        try:
            conn = self._get_conn()
            row  = conn.execute(
                "SELECT file_path, file_id FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'original' AND file_format = 'bmp' LIMIT 1",
                (group_id,),
            ).fetchone()
            conn.close()
            if not row:
                self._log.append("[WARN] BMP 파일 없음")
                return
            conn    = self._get_conn()
            scanner = InboxScanner(
                conn, self._data_dir(), managed_dir=self._managed_dir(), log_fn=self._log.append
            )
            scanner._handle_bmp(Path(row["file_path"]), group_id, row["file_id"], _now_iso())
            conn.close()
            self._refresh_gallery_item(group_id)
            self._refresh_detail(group_id)
        except Exception as exc:
            self._log.append(f"[ERROR] BMP 변환 실패: {exc}")

    def _on_gif_convert(self, group_id: str) -> None:
        try:
            conn = self._get_conn()
            row  = conn.execute(
                "SELECT file_path, file_id FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'original' AND file_format = 'gif' LIMIT 1",
                (group_id,),
            ).fetchone()
            conn.close()
            if not row:
                self._log.append("[WARN] GIF 파일 없음")
                return
            conn    = self._get_conn()
            scanner = InboxScanner(
                conn, self._data_dir(), managed_dir=self._managed_dir(), log_fn=self._log.append
            )
            scanner._handle_animated_gif(
                Path(row["file_path"]), group_id, row["file_id"], _now_iso()
            )
            conn.close()
            self._refresh_gallery_item(group_id)
            self._refresh_detail(group_id)
        except Exception as exc:
            self._log.append(f"[ERROR] GIF 변환 실패: {exc}")

    def _on_sidecar(self, group_id: str) -> None:
        try:
            conn = self._get_conn()
            row  = conn.execute(
                "SELECT file_path, file_id FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'original' LIMIT 1",
                (group_id,),
            ).fetchone()
            conn.close()
            if not row:
                self._log.append("[WARN] 원본 파일 없음")
                return
            conn    = self._get_conn()
            scanner = InboxScanner(
                conn, self._data_dir(), managed_dir=self._managed_dir(), log_fn=self._log.append
            )
            scanner._handle_static_gif(
                Path(row["file_path"]), group_id, row["file_id"], _now_iso()
            )
            conn.close()
            self._refresh_detail(group_id)
        except Exception as exc:
            self._log.append(f"[ERROR] Sidecar 생성 실패: {exc}")

    def _on_reindex(self) -> None:
        group_ids = list(dict.fromkeys(self._gallery.get_selected_group_ids()))
        if not group_ids:
            current_id = self._gallery.get_selected_group_id()
            if current_id:
                group_ids = [current_id]
        if not group_ids:
            self._log.append("[WARN] 선택된 파일 없음")
            return
        try:
            conn    = self._get_conn()
            scanner = InboxScanner(
                conn, self._data_dir(), managed_dir=self._managed_dir(), log_fn=self._log.append
            )
            total = len(group_ids)
            if total > 1:
                self._log.append(f"[INFO] DB 재색인 시작: {total}개 그룹")
            for idx, group_id in enumerate(group_ids, start=1):
                if total > 1:
                    self._log.append(f"[INFO] DB 재색인 진행 중... ({idx}/{total}) {group_id[:8]}")
                scanner.reprocess_group(group_id)
            conn.close()
            if total == 1:
                self._refresh_gallery_item(group_ids[0])
                self._refresh_detail(group_ids[0])
            else:
                self._refresh_gallery()
                current_id = self._gallery.get_selected_group_id()
                if current_id:
                    self._refresh_detail(current_id)
            self._refresh_counts()
            if total > 1:
                self._log.append(f"[INFO] DB 재색인 완료: {total}개 그룹")
        except Exception as exc:
            self._log.append(f"[ERROR] 재색인 실패: {exc}")

    # ------------------------------------------------------------------
    # 분류 핸들러
    # ------------------------------------------------------------------

    def _build_preview_for_selected(self) -> dict | None:
        """현재 선택된 그룹의 분류 미리보기를 생성한다."""
        from core.classifier import build_classify_preview
        group_id = self._gallery.get_selected_group_id()
        if not group_id:
            self._log.append("[WARN] 선택된 파일 없음")
            return None
        classified_dir = self.config.get("classified_dir", "")
        if not classified_dir:
            self._log.append(
                "[WARN] classified_dir 미설정 — "
                "[📁 작업 폴더 설정]을 먼저 실행하세요."
            )
            return None
        try:
            conn = self._get_conn()
            try:
                from core.tag_reclassifier import retag_groups_from_existing_tags
                retag_groups_from_existing_tags(conn, [group_id])
            except Exception as retag_exc:
                logger.debug("단일 미리보기 retag 실패 (무시): %s", retag_exc)
            preview = build_classify_preview(conn, group_id, self.config)
            # developer: 분류 실패 export (conn이 열린 상태에서 실행)
            if preview is not None:
                try:
                    from core.classification_failure_exporter import export_from_preview
                    dev_msg = export_from_preview(conn, preview, self.config)
                    if dev_msg:
                        self._log.append(dev_msg)
                except Exception as _dev_exc:
                    logger.debug("단일 dev failure export 실패 (무시): %s", _dev_exc)
            conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 미리보기 생성 실패: {exc}")
            return None
        if preview is None:
            self._log.append(
                "[WARN] 분류 미리보기 없음 — "
                "metadata_sync_status가 분류 가능 상태(full/json_only/xmp_write_failed)인지 확인하세요."
            )
        return preview

    def _on_classify_preview(self) -> None:
        """분류 미리보기 다이얼로그를 열고, [실행]이면 분류 실행."""
        from app.views.classify_dialog import ClassifyPreviewDialog
        preview = self._build_preview_for_selected()
        if preview is None:
            return
        self._log.append(
            f"[INFO] Classification preview created: "
            f"{preview['estimated_copies']} destinations"
        )
        dlg = ClassifyPreviewDialog(preview, parent=self)
        if dlg.exec() == ClassifyPreviewDialog.DialogCode.Accepted:
            self._run_classify(preview)

    def _on_classify_run(self) -> None:
        """미리보기 확인 후 바로 분류 실행 (다이얼로그 포함)."""
        self._on_classify_preview()

    def _run_classify(self, preview: dict) -> None:
        if getattr(self, "_classify_thread", None) and self._classify_thread.isRunning():
            self._log.append("[WARN] 이미 분류 작업이 진행 중입니다")
            return
        self._btn_classify_preview.setEnabled(False)
        self._btn_classify_run    .setEnabled(False)
        thread = ClassifyThread(preview, self.config, self._db_path(), parent=self)
        thread.log_msg      .connect(self._log.append)
        thread.classify_done.connect(self._on_classify_done)
        thread.finished     .connect(lambda: self._btn_classify_preview.setEnabled(True))
        thread.finished     .connect(lambda: self._btn_classify_run    .setEnabled(True))
        thread.start()
        self._classify_thread = thread

    def _on_classify_done(self, result: dict) -> None:
        if result.get("success"):
            self._log.append(
                f"[INFO] Classification completed: "
                f"{result['copied']} copied, {result['skipped']} skipped"
            )
            group_id = result.get("group_id", "")
            if group_id:
                self._refresh_gallery_item(group_id)
                self._refresh_detail(group_id)
            self._refresh_counts()
        else:
            self._log.append("[ERROR] 분류 실행 실패")

    # ------------------------------------------------------------------
    # XMP 재처리 핸들러
    # ------------------------------------------------------------------

    def _exiftool_path(self) -> Optional[str]:
        from core.exiftool_resolver import resolve_exiftool_path
        return resolve_exiftool_path(self.config)

    def _on_xmp_retry(self, group_id: str) -> None:
        """선택 group XMP 재시도."""
        et = self._exiftool_path()
        if not et:
            self._log.append(
                "[WARN] ExifTool 경로가 설정되어 있지 않습니다. "
                "config.json의 exiftool_path를 설정해주세요. "
                "(docs/metadata-policy.md 참고)"
            )
            return
        if getattr(self, "_xmp_thread", None) and self._xmp_thread.isRunning():
            self._log.append("[WARN] 이미 XMP 작업이 진행 중입니다")
            return
        self._log.append(f"[INFO] XMP 재시도 시작: {group_id[:8]}…")
        thread = XmpRetryThread(group_id, self._db_path(), et, parent=self)
        thread.log_msg .connect(self._log.append)
        thread.xmp_done.connect(self._on_xmp_done)
        thread.start()
        self._xmp_thread = thread

    def _on_xmp_retry_selected(self) -> None:
        """갤러리에서 다중 선택된 group의 XMP를 일괄 재시도."""
        group_ids = self._gallery.get_selected_group_ids()
        if not group_ids:
            self._log.append("[WARN] XMP 재처리할 파일을 먼저 선택해주세요")
            return
        et = self._exiftool_path()
        if not et:
            self._log.append(
                "[WARN] ExifTool 경로가 설정되어 있지 않습니다. "
                "config.json의 exiftool_path를 설정해주세요. "
                "(docs/metadata-policy.md 참고)"
            )
            return
        if getattr(self, "_xmp_thread", None) and self._xmp_thread.isRunning():
            self._log.append("[WARN] 이미 XMP 작업이 진행 중입니다")
            return
        self._log.append(f"[INFO] 선택 XMP 재처리 시작 — {len(group_ids)}개")
        thread = XmpRetryThread(
            None, self._db_path(), et, group_ids=group_ids, parent=self
        )
        thread.log_msg .connect(self._log.append)
        thread.xmp_done.connect(self._on_xmp_done)
        thread.start()
        self._xmp_thread = thread

    def _on_xmp_retry_all(self) -> None:
        """전체 json_only / xmp_write_failed XMP 재처리."""
        et = self._exiftool_path()
        if not et:
            self._log.append(
                "[WARN] ExifTool 경로가 설정되어 있지 않습니다. "
                "config.json의 exiftool_path를 설정해주세요. "
                "(docs/metadata-policy.md 참고)"
            )
            return
        if getattr(self, "_xmp_thread", None) and self._xmp_thread.isRunning():
            self._log.append("[WARN] 이미 XMP 작업이 진행 중입니다")
            return
        self._log.append("[INFO] 전체 XMP 재처리 시작…")
        thread = XmpRetryThread(None, self._db_path(), et, parent=self)
        thread.log_msg .connect(self._log.append)
        thread.xmp_done.connect(self._on_xmp_done)
        thread.start()
        self._xmp_thread = thread

    def _on_xmp_done(self, result: dict) -> None:
        mode = result.get("mode", "single")
        if mode == "single":
            status = result.get("status", "")
            msg    = result.get("message", "")
            if status == "success":
                self._log.append(f"[INFO] XMP 재시도 완료: {msg}")
            elif status == "no_exiftool":
                self._log.append(f"[WARN] {msg}")
            elif status == "no_target":
                self._log.append(f"[WARN] {msg}")
            else:
                self._log.append(f"[ERROR] XMP 재시도 실패: {msg}")
        else:
            total   = result.get("total", 0)
            success = result.get("success", 0)
            failed  = result.get("failed", 0)
            skipped = result.get("skipped", 0)
            label   = "선택 XMP 재처리" if mode == "selected" else "전체 XMP 재처리"
            self._log.append(
                f"[INFO] {label} 완료 — "
                f"전체: {total}  성공: {success}  실패: {failed}  건너뜀: {skipped}"
            )
            for err in result.get("errors", [])[:5]:
                self._log.append(f"[WARN] {err}")

        for done_gid in result.get("group_ids", []):
            self._refresh_gallery_item(done_gid)
        gid = self._gallery.get_selected_group_id()
        if gid:
            self._refresh_detail(gid)
        self._refresh_counts()

    def _get_current_filter_group_ids(self) -> list[str]:
        if self._current_category == "no_metadata":
            return []
        cat = self._current_category
        if cat == "missing":
            sql = (
                "SELECT g.group_id FROM artwork_groups g "
                f"WHERE {_MISSING_EXISTS_FRAGMENT} ORDER BY g.indexed_at DESC"
            )
        else:
            where = _GALLERY_WHERE.get(cat, "")
            sql   = f"SELECT g.group_id FROM artwork_groups g {where} ORDER BY g.indexed_at DESC"
        try:
            conn = self._get_conn()
            ids  = [r[0] for r in conn.execute(sql).fetchall()]
            conn.close()
            return ids
        except Exception:
            return []

    def _build_duplicate_scope_request(self) -> tuple[str, list[str] | None, str] | None:
        dup_cfg = self.config.get("duplicates", {})
        configured_scope = dup_cfg.get("default_scope", "inbox_managed")
        selected_ids = list(dict.fromkeys(self._gallery.get_selected_group_ids()))
        current_ids = list(dict.fromkeys(self._get_current_filter_group_ids()))

        scope = configured_scope
        group_ids: list[str] | None = None

        if configured_scope == "inbox_managed":
            if len(selected_ids) >= 2:
                scope = "selected"
                group_ids = selected_ids
            elif self._current_category != "all" and current_ids:
                scope = "current_view"
                group_ids = current_ids
        elif configured_scope == "selected":
            if len(selected_ids) < 2:
                QMessageBox.information(
                    self,
                    "선택 항목 부족",
                    "선택 범위 중복 검사는 갤러리에서 2개 이상 항목을 선택해야 실행할 수 있습니다.",
                )
                return None
            group_ids = selected_ids
        elif configured_scope == "current_view":
            if not current_ids:
                QMessageBox.information(
                    self,
                    "현재 화면 없음",
                    "현재 화면 범위에서 검사할 항목이 없습니다.",
                )
                return None
            group_ids = current_ids

        if scope == "all_archive":
            allow = dup_cfg.get("allow_all_archive_scan", False)
            if not allow:
                QMessageBox.warning(
                    self,
                    "전체 Archive 검사 차단됨",
                    "config.json의 duplicates.allow_all_archive_scan 값이 false입니다.\n"
                    "전체 Archive 검사를 허용하려면 해당 값을 true로 변경해 주세요.",
                )
                return None
            reply = QMessageBox.warning(
                self,
                "전체 Archive 검사",
                "전체 Archive 검사는 Classified 복사본까지 포함할 수 있습니다.\n\n"
                "분류 결과물이 원본과 중복으로 감지될 수 있고,\n"
                "파일 수가 많으면 시간이 오래 걸릴 수 있습니다.\n\n"
                "정말 전체 Archive를 검사하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return None

        labels = {
            "inbox_managed": "Inbox / Managed",
            "inbox_only": "Inbox만",
            "managed_only": "Managed만",
            "classified_only": "Classified만",
            "all_archive": "전체 Archive",
            "current_view": "현재 화면",
            "selected": "선택 항목",
        }
        label = labels.get(scope, scope)
        if scope in {"current_view", "selected"} and group_ids is not None:
            label = f"{label} {len(group_ids)}개"
        return scope, group_ids, label

    def _on_batch_classify(self) -> None:
        classified_dir = self.config.get("classified_dir", "")
        if not classified_dir:
            self._log.append(
                "[WARN] classified_dir 미설정 — "
                "[📁 작업 폴더 설정]을 먼저 실행하세요."
            )
            return
        from app.views.batch_classify_dialog import BatchClassifyDialog
        dlg = BatchClassifyDialog(
            self._get_conn,
            self.config,
            selected_group_ids=self._gallery.get_selected_group_ids(),
            current_filter_group_ids=self._get_current_filter_group_ids(),
            parent=self,
        )
        dlg.log_msg   .connect(self._log.append)
        dlg.batch_done.connect(self._on_batch_classify_done)
        dlg.exec()

    def _on_batch_classify_done(self, result: dict) -> None:
        self._refresh_gallery()
        self._refresh_counts()

    def _on_retag(self) -> None:
        """
        선택된 그룹의 원본 tags_json을 현재 alias 정책으로 다시 분류한다.

        Pixiv adapter 보강 이후 alias 사전이 늘어난 경우, 기존 항목도 이 액션으로
        series/character_tags_json과 tags 정규화 테이블을 최신 정책에 맞출 수 있다.
        """
        group_id = self._gallery.get_selected_group_id()
        if not group_id:
            self._log.append("[WARN] 선택된 파일 없음")
            return
        try:
            from core.tag_classifier import classify_pixiv_tags

            conn = self._get_conn()
            row  = conn.execute(
                "SELECT tags_json FROM artwork_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            if not row:
                conn.close()
                self._log.append("[WARN] 그룹 없음")
                return

            raw_tags: list[str] = []
            if row["tags_json"]:
                try:
                    raw_tags = json.loads(row["tags_json"])
                except Exception:
                    pass

            classified = classify_pixiv_tags(raw_tags, conn=conn)
            now = _now_iso()

            conn.execute(
                "UPDATE artwork_groups SET "
                "series_tags_json=?, character_tags_json=?, updated_at=? "
                "WHERE group_id=?",
                (
                    json.dumps(classified["series_tags"],    ensure_ascii=False),
                    json.dumps(classified["character_tags"], ensure_ascii=False),
                    now,
                    group_id,
                ),
            )
            conn.execute("DELETE FROM tags WHERE group_id=?", (group_id,))
            for tag in classified["tags"]:
                conn.execute(
                    "INSERT INTO tags (group_id, tag, tag_type) VALUES (?, ?, 'general')",
                    (group_id, tag),
                )
            for tag in classified["series_tags"]:
                conn.execute(
                    "INSERT INTO tags (group_id, tag, tag_type) VALUES (?, ?, 'series')",
                    (group_id, tag),
                )
            for tag in classified["character_tags"]:
                conn.execute(
                    "INSERT INTO tags (group_id, tag, tag_type) VALUES (?, ?, 'character')",
                    (group_id, tag),
                )
            conn.commit()
            conn.close()

            self._log.append(
                f"[INFO] 태그 재분류 완료: "
                f"series={classified['series_tags']}, "
                f"character={classified['character_tags']}"
            )
            self._refresh_detail(group_id)
        except Exception as exc:
            self._log.append(f"[ERROR] 태그 재분류 실패: {exc}")

    def _on_show_candidates(self) -> None:
        """태그 후보 검토 다이얼로그를 연다."""
        try:
            conn = self._get_conn()
            from app.views.tag_candidate_view import TagCandidateView
            dlg = TagCandidateView(conn, parent=self)
            dlg.exec()
            conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 후보 태그 다이얼로그 오류: {exc}")

    def _on_show_dict_import(self) -> None:
        """외부 사전 후보 가져오기 다이얼로그를 연다."""
        try:
            from app.views.dictionary_import_view import DictionaryImportView
            current_gids = self._gallery.get_visible_group_ids() if hasattr(self._gallery, "get_visible_group_ids") else []
            dlg = DictionaryImportView(
                self._get_conn,
                current_group_ids=current_gids,
                parent=self,
            )
            dlg.log_msg.connect(self._log.append)
            dlg.exec()
        except Exception as exc:
            self._log.append(f"[ERROR] 웹 사전 다이얼로그 오류: {exc}")

    def _on_dict_export(self) -> None:
        """공개용 tag pack (aliases + localizations) 을 JSON 파일로 내보낸다."""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, "사전 내보내기", "tag_pack_export.json",
                "JSON 파일 (*.json)"
            )
            if not path:
                return
            conn = self._get_conn()
            try:
                from core.tag_pack_exporter import export_public_tag_pack, save_to_file
                pack_id   = Path(path).stem
                pack_name = pack_id.replace("_", " ").title()
                data = export_public_tag_pack(conn, pack_id, pack_name)
                save_to_file(data, path)
                self._log.append(
                    f"[INFO] 사전 내보내기 완료: {path} "
                    f"(series {len(data['series'])}건, characters {len(data['characters'])}건)"
                )
            finally:
                conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 사전 내보내기 오류: {exc}")

    def _on_dict_backup(self) -> None:
        """전체 사전 백업 (aliases + localizations + external entries) 을 내보낸다."""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, "백업 내보내기", "dictionary_backup.json",
                "JSON 파일 (*.json)"
            )
            if not path:
                return
            conn = self._get_conn()
            try:
                from core.tag_pack_exporter import export_dictionary_backup, save_to_file
                data = export_dictionary_backup(conn)
                save_to_file(data, path)
                self._log.append(
                    f"[INFO] 백업 내보내기 완료: {path} "
                    f"(aliases {len(data['tag_aliases'])}건, "
                    f"localizations {len(data['tag_localizations'])}건, "
                    f"external {len(data['external_dictionary_entries'])}건)"
                )
            finally:
                conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 백업 내보내기 오류: {exc}")

    def _on_show_wizard(self) -> None:
        """워크플로우 마법사 다이얼로그를 연다."""
        try:
            from app.views.workflow_wizard_view import WorkflowWizardView
            dlg = WorkflowWizardView(
                self._get_conn,
                self.config,
                self._config_path,
                parent=self,
            )
            dlg.refresh_main.connect(self._refresh_gallery)
            dlg.refresh_main.connect(self._refresh_counts)
            # Step 3 중복 검사 버튼 → Top Menu와 동일한 MainWindow handler 재사용
            dlg.exact_duplicate_scan_requested.connect(self._on_exact_duplicate_check)
            dlg.visual_duplicate_scan_requested.connect(self._on_visual_duplicate_check)
            dlg.exec()
        except Exception as exc:
            self._log.append(f"[ERROR] 작업 마법사 오류: {exc}")

    def _on_show_save_jobs(self) -> None:
        """저장 작업 상태 다이얼로그를 연다."""
        try:
            conn = self._get_conn()
            from app.views.save_jobs_view import SaveJobsView
            dlg = SaveJobsView(conn, parent=self)
            dlg.exec()
            conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 저장 작업 뷰 오류: {exc}")

    def _on_show_work_log(self) -> None:
        """작업 로그 / Undo 다이얼로그를 연다."""
        try:
            conn = self._get_conn()
            from app.views.work_log_view import WorkLogView
            dlg = WorkLogView(conn, config=self.config, parent=self)
            dlg.log_msg.connect(self._log.append)
            dlg.exec()
            conn.close()
            # Undo 실행 여부에 관계없이 상태 갱신 (안전)
            self._refresh_gallery()
            self._refresh_counts()
        except Exception as exc:
            self._log.append(f"[ERROR] 작업 로그 오류: {exc}")

    # ------------------------------------------------------------------
    # No Metadata 패널 핸들러
    # ------------------------------------------------------------------

    def _on_nm_retry(self, queue_id: str) -> None:
        if getattr(self, "_enrich_thread", None) and self._enrich_thread.isRunning():
            self._log.append("[WARN] 이미 보강 작업이 진행 중입니다")
            return
        try:
            conn = self._get_conn()
            q_row = conn.execute(
                "SELECT file_path FROM no_metadata_queue WHERE queue_id = ?",
                (queue_id,),
            ).fetchone()
            if not q_row:
                self._log.append(f"[WARN] queue 항목 없음: {queue_id[:8]}…")
                conn.close()
                return

            f_row = conn.execute(
                "SELECT file_id, group_id FROM artwork_files "
                "WHERE file_path = ? AND file_role = 'original' LIMIT 1",
                (q_row["file_path"],),
            ).fetchone()
            conn.close()

            if not f_row:
                self._log.append(
                    f"[WARN] DB에서 파일을 찾을 수 없음: {Path(q_row['file_path']).name}"
                )
                return

            file_id  = f_row["file_id"]
            group_id = f_row["group_id"]
            self._log.append(
                f"[INFO] No Metadata 재시도: {Path(q_row['file_path']).name}"
            )

            thread = EnrichThread(
                file_id, self._db_path(),
                exiftool_path=self._exiftool_path(),
                parent=self,
            )
            thread.log_msg.connect(self._log.append)
            thread.enrich_done.connect(
                lambda res, gid=group_id, qid=queue_id:
                    self._on_nm_enrich_done(res, gid, qid)
            )
            thread.start()
            self._enrich_thread = thread

        except Exception as exc:
            self._log.append(f"[ERROR] 재시도 실패: {exc}")

    def _on_nm_enrich_done(self, result: dict, group_id: str, queue_id: str) -> None:
        msg = result.get("message", "")
        if result.get("status") == "success":
            try:
                conn = self._get_conn()
                conn.execute(
                    "UPDATE no_metadata_queue SET resolved = 1, resolved_at = ? "
                    "WHERE queue_id = ?",
                    (_now_iso(), queue_id),
                )
                conn.commit()
                conn.close()
            except Exception as exc:
                self._log.append(f"[WARN] queue resolved 업데이트 실패: {exc}")
            self._log.append(f"[INFO] 재시도 완료 — {msg}")
            self._refresh_gallery_item(group_id)
            self._refresh_counts()
            self._load_no_metadata_panel()
        else:
            self._log.append(f"[WARN] 재시도 실패: {msg}")

    def _on_nm_ignore(self, queue_id: str) -> None:
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE no_metadata_queue SET resolved = 1, resolved_at = ? "
                "WHERE queue_id = ?",
                (_now_iso(), queue_id),
            )
            conn.commit()
            conn.close()
            self._log.append(f"[INFO] 무시 처리 완료: {queue_id[:8]}…")
            self._load_no_metadata_panel()
            self._refresh_counts()
        except Exception as exc:
            self._log.append(f"[ERROR] 무시 처리 실패: {exc}")

    def _on_read_meta_selected(self) -> None:
        """툴바에서 호출 — 현재 선택된 group의 메타데이터 읽기."""
        gid = self._gallery.get_selected_group_id()
        if not gid:
            self._log.append("[WARN] 선택된 파일 없음")
            return
        self._on_read_meta(gid)

    def _on_pixiv_meta_selected(self) -> None:
        """툴바에서 호출 — 현재 선택된 group의 Pixiv 메타데이터 가져오기."""
        gid = self._gallery.get_selected_group_id()
        if not gid:
            self._log.append("[WARN] 선택된 파일 없음")
            return
        self._on_pixiv_meta(gid)

    def _on_open_file_location(self, group_id: str) -> None:
        """선택된 group의 original 파일이 있는 폴더를 파일 탐색기로 연다."""
        import subprocess
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT file_path FROM artwork_files "
                "WHERE group_id = ? AND file_role = 'original' LIMIT 1",
                (group_id,),
            ).fetchone()
            conn.close()
            if not row:
                self._log.append("[WARN] 원본 파일 없음")
                return
            fp = Path(row["file_path"])
            if not fp.exists():
                self._log.append(f"[WARN] 파일 없음: {fp.name}")
                return
            # Windows: explorer /select,{path}
            subprocess.Popen(["explorer", "/select,", str(fp)])
        except Exception as exc:
            self._log.append(f"[ERROR] 파일 위치 열기 실패: {exc}")

    def _on_gallery_delete_requested(self, group_ids: list) -> None:
        """Gallery 컨텍스트 메뉴 삭제 요청을 처리한다."""
        self._delete_groups(group_ids)

    # ------------------------------------------------------------------
    # 삭제 핸들러
    # ------------------------------------------------------------------

    def _delete_groups(self, group_ids: list[str]) -> None:
        """group_ids 목록의 파일을 DeletePreviewDialog를 거쳐 삭제한다."""
        if not group_ids:
            QMessageBox.information(self, "선택 없음", "갤러리에서 삭제할 항목을 선택하세요.")
            return
        try:
            conn = self._get_conn()
            from core.delete_manager import build_delete_preview, execute_delete_preview
            from app.views.delete_preview_dialog import DeletePreviewDialog

            preview = build_delete_preview(conn, group_ids=group_ids, reason="manual_delete")
            dlg = DeletePreviewDialog(preview, parent=self)
            if dlg.exec() == DeletePreviewDialog.DialogCode.Accepted and dlg.is_confirmed():
                result = execute_delete_preview(conn, preview, confirmed=True)
                self._log.append(
                    f"[INFO] 삭제 완료 — "
                    f"deleted={result['deleted']} failed={result['failed']} "
                    f"skipped={result['skipped']}"
                )
                self._refresh_gallery()
                self._refresh_counts()
            conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 삭제 실패: {exc}")

    def _on_delete_selected(self) -> None:
        """다중 선택된 group_id를 대상으로 삭제 미리보기 → 영구 삭제를 실행한다."""
        group_ids = self._gallery.get_selected_group_ids()
        self._delete_groups(group_ids)

    def _get_dup_scope(self) -> str | None:
        request = self._build_duplicate_scope_request()
        return request[0] if request else None
        """
        config에서 중복 검사 scope를 읽는다.
        all_archive이고 allow_all_archive_scan=False면 사용자 확인 후 None 반환.
        """
        dup_cfg = self.config.get("duplicates", {})
        scope = dup_cfg.get("default_scope", "inbox_managed")
        if scope == "all_archive":
            allow = dup_cfg.get("allow_all_archive_scan", False)
            if not allow:
                QMessageBox.warning(
                    self, "전체 Archive 검사 차단됨",
                    "config.json의 duplicates.allow_all_archive_scan이 false입니다.\n"
                    "전체 Archive 검사를 허용하려면 해당 값을 true로 변경하세요.",
                )
                return None
            # allow=True인 경우에도 경고 표시
            reply = QMessageBox.warning(
                self, "전체 Archive 검사",
                "전체 Archive 검사는 Classified 복사본까지 포함할 수 있습니다.\n\n"
                "분류 결과물이 원본과 중복으로 감지될 수 있으며,\n"
                "파일 수가 많으면 시간이 오래 걸릴 수 있습니다.\n\n"
                "정말 전체 Archive를 검사하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return None
        return scope

    def _on_exact_duplicate_check(self) -> None:
        """SHA-256 완전 중복 그룹을 검사하고 DeletePreviewDialog로 연결한다."""
        try:
            request = self._build_duplicate_scope_request()
            if request is None:
                return
            scope, group_ids, scope_label = request
            conn = self._get_conn()
            from core.duplicate_finder import (
                find_exact_duplicates,
                build_exact_duplicate_cleanup_preview,
                get_duplicate_check_summary,
            )
            from core.delete_manager import build_delete_preview, execute_delete_preview
            from app.views.delete_preview_dialog import DeletePreviewDialog

            # unindexed 파일 보고
            summary = get_duplicate_check_summary(
                conn, self._inbox_dir(), scope=scope, group_ids=group_ids
            )
            info_lines = [f"중복 검사 대상:"]
            info_lines.append(f"  DB 등록 Inbox/Managed 파일: {summary['db_file_count']}개")
            if summary["unindexed_count"] > 0:
                info_lines.append(f"  DB 미등록 Inbox 파일: {summary['unindexed_count']}개")
                info_lines.append("  ⚠ 미등록 파일까지 검사하려면 먼저 이미지 스캔을 실행하세요.")
            for line in info_lines:
                self._log.append(f"[INFO] {line}")

            self._log.append(f"[INFO] 완전 중복 검사 중… (범위: {scope_label})")
            dup_groups = find_exact_duplicates(conn, scope=scope, group_ids=group_ids)
            if not dup_groups:
                QMessageBox.information(self, "완전 중복 검사", "완전 중복 파일이 없습니다.")
                conn.close()
                return

            cleanup = build_exact_duplicate_cleanup_preview(conn, dup_groups)
            total_del = cleanup["total_delete_candidates"]

            # 삭제 후보 file_id 목록 수집
            delete_file_ids: list[str] = []
            for g in cleanup["groups"]:
                for f in g.get("delete_candidates", []):
                    fid = f.get("file_id")
                    if fid:
                        delete_file_ids.append(fid)

            if not delete_file_ids:
                QMessageBox.information(self, "완전 중복 검사", "삭제 후보 파일이 없습니다.")
                conn.close()
                return

            msg = (
                f"완전 중복 그룹: {cleanup['total_groups']}개\n"
                f"보존 파일: {cleanup['total_keep']}개\n"
                f"삭제 후보: {total_del}개\n\n"
                "삭제 미리보기로 이동하시겠습니까?"
            )
            if QMessageBox.question(
                self, "완전 중복 검사 결과", msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                conn.close()
                return

            preview = build_delete_preview(
                conn, file_ids=delete_file_ids, reason="exact_duplicate_cleanup"
            )
            dlg = DeletePreviewDialog(preview, parent=self)
            if dlg.exec() == DeletePreviewDialog.DialogCode.Accepted and dlg.is_confirmed():
                result = execute_delete_preview(conn, preview, confirmed=True)
                self._log.append(
                    f"[INFO] 완전 중복 정리 완료 — "
                    f"deleted={result['deleted']} failed={result['failed']}"
                )
                self._refresh_gallery()
                self._refresh_counts()
            conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 완전 중복 검사 실패: {exc}")

    def _on_visual_duplicate_check(self) -> None:
        """시각적 중복 후보를 검사하고 리뷰 다이얼로그를 표시한다."""
        try:
            request = self._build_duplicate_scope_request()
            if request is None:
                return
            scope, group_ids, scope_label = request
            conn = self._get_conn()
            from core.duplicate_finder import (
                get_duplicate_check_summary,
                select_duplicate_candidate_files,
            )
            from core.visual_duplicate_finder import find_visual_duplicates
            from core.visual_duplicate_decision import decide_visual_duplicate_groups
            from core.delete_manager import build_delete_preview, execute_delete_preview
            from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
            from app.views.delete_preview_dialog import DeletePreviewDialog

            # 대상 파일 수 계산 + unindexed 보고
            summary = get_duplicate_check_summary(
                conn, self._inbox_dir(), scope=scope, group_ids=group_ids
            )
            db_count  = summary["db_file_count"]
            unindexed = summary["unindexed_count"]

            dup_cfg = self.config.get("duplicates", {})
            max_files = dup_cfg.get("max_visual_files_per_run", 300)
            confirm   = dup_cfg.get("confirm_visual_scan", True)

            if confirm:
                warn_lines = [
                    "시각적 중복 검사는 이미지 내용을 분석하므로 시간이 오래 걸릴 수 있습니다.\n",
                    f"검사 범위: {scope_label}",
                    f"대상 파일 수: {db_count}개",
                    "예상 소요 시간은 파일 수와 이미지 크기에 따라 달라집니다.",
                ]
                if unindexed > 0:
                    warn_lines.append(
                        f"\n⚠ DB 미등록 Inbox 파일 {unindexed}개는 검사 대상에서 제외됩니다.\n"
                        "  미등록 파일까지 검사하려면 먼저 이미지 스캔을 실행하세요."
                    )
                if db_count > max_files:
                    warn_lines.insert(0,
                        f"⚠ 대상 파일 수({db_count}개)가 권장 한도({max_files}개)를 초과합니다.\n"
                        "선택 항목 또는 현재 목록 기준으로 줄여서 검사하는 것을 권장합니다.\n"
                    )
                reply = QMessageBox.question(
                    self,
                    "시각적 중복 검사",
                    "\n".join(warn_lines) + "\n\n계속하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    conn.close()
                    return

            self._log.append(f"[INFO] 시각적 중복 검사 중… (범위: {scope_label}, 시간이 걸릴 수 있습니다)")
            dup_groups = find_visual_duplicates(conn, scope=scope, group_ids=group_ids)
            if not dup_groups:
                QMessageBox.information(self, "시각적 중복 검사", "유사 이미지 그룹이 없습니다.")
                conn.close()
                return

            # 자동 keep/delete 후보를 계산해 dialog 초기 상태로 주입한다.
            # decision 모듈이 예외를 던지면 빈 dict로 fallback해 dialog가 정상 열린다.
            initial_decisions: dict[str, str] = {}
            try:
                decisions_per_group = decide_visual_duplicate_groups(dup_groups)
                for group_decisions in decisions_per_group:
                    for decision in group_decisions:
                        if decision.file_id:
                            initial_decisions[decision.file_id] = decision.decision

                if initial_decisions:
                    self._log.append(
                        "[INFO] 시각적 중복 검사: 자동 유지/삭제 후보를 적용했습니다. "
                        "검토 후 변경할 수 있습니다."
                    )
            except Exception as exc:
                self._log.append(
                    f"[WARN] 자동 keep/delete 계산 실패 (수동 검토 필요): {exc}"
                )

            review_dlg = VisualDuplicateReviewDialog(
                dup_groups,
                parent=self,
                initial_decisions=initial_decisions,
            )
            if review_dlg.exec() != VisualDuplicateReviewDialog.DialogCode.Accepted:
                conn.close()
                return

            delete_file_ids = review_dlg.selected_for_delete()
            if not delete_file_ids:
                conn.close()
                return

            preview = build_delete_preview(
                conn, file_ids=delete_file_ids, reason="visual_duplicate_cleanup"
            )
            dlg = DeletePreviewDialog(preview, parent=self)
            if dlg.exec() == DeletePreviewDialog.DialogCode.Accepted and dlg.is_confirmed():
                result = execute_delete_preview(conn, preview, confirmed=True)
                self._log.append(
                    f"[INFO] 시각적 중복 정리 완료 — "
                    f"deleted={result['deleted']} failed={result['failed']}"
                )
                self._refresh_gallery()
                self._refresh_counts()
            conn.close()
        except Exception as exc:
            self._log.append(f"[ERROR] 시각적 중복 검사 실패: {exc}")

    # ------------------------------------------------------------------
    # IPC 서버
    # ------------------------------------------------------------------

    def _on_inbox_scan(self) -> None:
        if self._scan_thread and self._scan_thread.isRunning():
            return

        inbox = self._inbox_dir()
        data_dir = self._data_dir()
        db_path = self._db_path()

        if not inbox:
            self._log.append(
                "[WARN] 분류 대상 폴더가 설정되지 않았습니다. "
                "[빠른 작업 폴더 설정]을 먼저 실행하세요."
            )
            return

        inbox_path = Path(inbox)
        if not inbox_path.exists():
            try:
                inbox_path.mkdir(parents=True, exist_ok=True)
                self._log.append(f"[INFO] Created Inbox folder: {inbox}")
            except Exception as exc:
                self._log.append(f"[ERROR] Cannot create Inbox folder: {exc}")
                return

        self._log.append(f"[INFO] 이미지 스캔 시작: {inbox}")
        self._act_inbox_scan.setEnabled(False)
        self._show_loading(
            "Inbox 스캔",
            "폴더와 DB를 대조하며 작품을 정리하고 있어요.",
            detail=inbox,
        )

        self._scan_thread = ScanThread(
            data_dir, inbox, self._managed_dir(), db_path, parent=self
        )
        self._scan_thread.log_msg.connect(self._log.append)
        self._scan_thread.log_msg.connect(self._mirror_loading_log)
        self._scan_thread.scan_done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, result: ScanResult) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="scan")
        self._act_inbox_scan.setEnabled(True)
        self._hide_loading()
        self._log.append(
            f"[INFO] 스캔 완료 — 신규: {result.new}, "
            f"스킵: {result.skipped}, 실패: {result.failed}"
        )
        _log_phase("postprocess.start", 0.0, op="scan")
        self._refresh_gallery()
        self._refresh_counts()
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="scan")

    def _on_reindex(self) -> None:
        group_ids = list(dict.fromkeys(self._gallery.get_selected_group_ids()))
        if not group_ids:
            current_id = self._gallery.get_selected_group_id()
            if current_id:
                group_ids = [current_id]
        if not group_ids:
            self._log.append("[WARN] 선택된 파일이 없습니다")
            return
        if self._reindex_thread and self._reindex_thread.isRunning():
            self._log.append("[WARN] 이미 재색인 작업이 진행 중입니다")
            return

        total = len(group_ids)
        if total > 1:
            self._log.append(f"[INFO] DB 재색인 시작: {total}개 그룹")
        self._show_loading(
            "DB 재색인",
            "파일 상태와 메타데이터를 다시 읽고 있어요.",
            detail=f"대상 그룹: {total}개",
            total=total,
            current=0,
        )

        thread = ReindexThread(
            group_ids,
            self._data_dir(),
            self._managed_dir(),
            self._db_path(),
            parent=self,
        )
        thread.log_msg.connect(self._log.append)
        thread.log_msg.connect(self._mirror_loading_log)
        thread.progress.connect(
            lambda done, total_groups, message: self._update_loading(
                message="선택한 작품들을 순서대로 재색인하고 있어요.",
                detail=message,
                current=done,
                total=total_groups,
            )
        )
        thread.done.connect(self._on_reindex_done)
        thread.start()
        self._reindex_thread = thread

    def _on_reindex_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="reindex")
        self._hide_loading()
        group_ids = result.get("group_ids", [])
        if not result.get("success"):
            self._log.append(f"[ERROR] 재색인 실패: {result.get('error', '')}")
            return

        _log_phase("postprocess.start", 0.0, op="reindex")
        total = len(group_ids)
        if total == 1 and group_ids:
            self._refresh_gallery_item(group_ids[0])
            self._refresh_detail(group_ids[0])
        else:
            self._refresh_gallery()
            current_id = self._gallery.get_selected_group_id()
            if current_id:
                self._refresh_detail(current_id)
        self._refresh_counts()
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="reindex")
        if total > 1:
            self._log.append(f"[INFO] DB 재색인 완료: {total}개 그룹")

    def _on_xmp_retry(self, group_id: str) -> None:
        et = self._exiftool_path()
        if not et:
            self._log.append(
                "[WARN] ExifTool 경로가 설정되어 있지 않습니다. "
                "config.json의 exiftool_path를 확인하세요."
            )
            return
        if getattr(self, "_xmp_thread", None) and self._xmp_thread.isRunning():
            self._log.append("[WARN] 이미 XMP 작업이 진행 중입니다")
            return
        self._log.append(f"[INFO] XMP 재시도 시작: {group_id[:8]}…")
        self._show_loading(
            "XMP 재처리",
            "선택한 파일의 메타데이터를 다시 기록하고 있어요.",
            detail=group_id,
            total=1,
            current=0,
        )
        thread = RichXmpRetryThread(group_id, self._db_path(), et, parent=self)
        thread.log_msg.connect(self._log.append)
        thread.log_msg.connect(self._mirror_loading_log)
        thread.progress.connect(self._on_xmp_progress)
        thread.xmp_done.connect(self._on_xmp_done)
        thread.start()
        self._xmp_thread = thread

    def _on_xmp_retry_selected(self) -> None:
        group_ids = self._gallery.get_selected_group_ids()
        if not group_ids:
            self._log.append("[WARN] XMP 재처리할 파일을 먼저 선택해주세요")
            return
        et = self._exiftool_path()
        if not et:
            self._log.append(
                "[WARN] ExifTool 경로가 설정되어 있지 않습니다. "
                "config.json의 exiftool_path를 확인하세요."
            )
            return
        if getattr(self, "_xmp_thread", None) and self._xmp_thread.isRunning():
            self._log.append("[WARN] 이미 XMP 작업이 진행 중입니다")
            return
        self._log.append(f"[INFO] 선택 XMP 재처리 시작 — {len(group_ids)}개")
        self._show_loading(
            "선택 XMP 재처리",
            "선택한 작품들의 XMP 메타데이터를 다시 기록하고 있어요.",
            detail=f"대상 그룹: {len(group_ids)}개",
            total=len(group_ids),
            current=0,
        )
        thread = RichXmpRetryThread(
            None, self._db_path(), et, group_ids=group_ids, parent=self
        )
        thread.log_msg.connect(self._log.append)
        thread.log_msg.connect(self._mirror_loading_log)
        thread.progress.connect(self._on_xmp_progress)
        thread.xmp_done.connect(self._on_xmp_done)
        thread.start()
        self._xmp_thread = thread

    def _on_xmp_retry_all(self) -> None:
        et = self._exiftool_path()
        if not et:
            self._log.append(
                "[WARN] ExifTool 경로가 설정되어 있지 않습니다. "
                "config.json의 exiftool_path를 확인하세요."
            )
            return
        if getattr(self, "_xmp_thread", None) and self._xmp_thread.isRunning():
            self._log.append("[WARN] 이미 XMP 작업이 진행 중입니다")
            return
        self._log.append("[INFO] 전체 XMP 재처리 시작")
        self._show_loading(
            "전체 XMP 재처리",
            "json_only / xmp_write_failed 대상을 다시 처리하고 있어요.",
            detail="대상 수를 계산하는 중…",
        )
        thread = RichXmpRetryThread(None, self._db_path(), et, parent=self)
        thread.log_msg.connect(self._log.append)
        thread.log_msg.connect(self._mirror_loading_log)
        thread.progress.connect(self._on_xmp_progress)
        thread.xmp_done.connect(self._on_xmp_done)
        thread.start()
        self._xmp_thread = thread

    def _on_xmp_progress(self, done: int, total: int, group_id: str, status: str) -> None:
        status_map = {
            "running": "메타데이터를 다시 쓰는 중…",
            "success": "메타데이터 기록 완료",
            "skipped": "건너뜀",
            "failed": "기록 실패",
            "no_target": "대상 파일 없음",
            "no_exiftool": "ExifTool 없음",
        }
        current = done if status == "running" else max(done, 0)
        self._update_loading(
            message=status_map.get(status, "작업 중…"),
            detail=f"{group_id[:8]}…",
            current=current,
            total=max(total, 1),
        )

    def _on_xmp_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="xmp")
        self._hide_loading()
        mode = result.get("mode", "single")
        if mode == "single":
            status = result.get("status", "")
            msg = result.get("message", "")
            if status == "success":
                self._log.append(f"[INFO] XMP 재시도 완료: {msg}")
            elif status == "no_exiftool":
                self._log.append(f"[WARN] {msg}")
            elif status in {"no_target", "skipped"}:
                self._log.append(f"[WARN] {msg}")
            else:
                self._log.append(f"[ERROR] XMP 재시도 실패: {msg}")
        else:
            total = result.get("total", 0)
            success = result.get("success", 0)
            failed = result.get("failed", 0)
            skipped = result.get("skipped", 0)
            label = "선택 XMP 재처리" if mode == "selected" else "전체 XMP 재처리"
            self._log.append(
                f"[INFO] {label} 완료 — "
                f"전체: {total}  성공: {success}  실패: {failed}  건너뜀: {skipped}"
            )
            for err in result.get("errors", [])[:5]:
                self._log.append(f"[WARN] {err}")

        _log_phase("postprocess.start", 0.0, op="xmp")
        for done_gid in result.get("group_ids", []):
            self._refresh_gallery_item(done_gid)
        gid = self._gallery.get_selected_group_id()
        if gid:
            self._refresh_detail(gid)
        self._refresh_counts()
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="xmp")

    def _on_explorer_meta_repair_selected(self) -> None:
        group_ids = list(dict.fromkeys(self._gallery.get_selected_group_ids()))
        if not group_ids:
            current_id = self._gallery.get_selected_group_id()
            if current_id:
                group_ids = [current_id]
        if not group_ids:
            self._log.append("[WARN] Explorer 메타 복구할 파일을 먼저 선택해주세요")
            return

        et = self._exiftool_path()
        if not et:
            self._log.append(
                "[WARN] ExifTool 경로가 설정되어 있지 않습니다. "
                "config.json의 exiftool_path를 확인해주세요."
            )
            return

        if self._explorer_meta_thread and self._explorer_meta_thread.isRunning():
            self._log.append("[WARN] 이미 Explorer 메타 복구 작업이 진행 중입니다")
            return

        total = len(group_ids)
        self._log.append(f"[INFO] Explorer 메타 복구 시작: {total}개 그룹")
        self._show_loading(
            "Explorer 메타 복구",
            "Windows 탐색기용 제목, 태그, 만든 이를 다시 기록하고 있어요.",
            detail=f"대상 그룹: {total}개",
            total=total,
            current=0,
        )

        thread = ExplorerMetaRepairThread(group_ids, self._db_path(), et, parent=self)
        thread.log_msg.connect(self._log.append)
        thread.log_msg.connect(self._mirror_loading_log)
        thread.progress.connect(self._on_explorer_meta_repair_progress)
        thread.done.connect(self._on_explorer_meta_repair_done)
        thread.start()
        self._explorer_meta_thread = thread

    def _on_explorer_meta_repair_progress(
        self,
        done: int,
        total: int,
        group_id: str,
        status: str,
    ) -> None:
        status_map = {
            "running": "Explorer 메타를 다시 쓰는 중…",
            "success": "Explorer 메타 기록 완료",
            "skipped": "건너뜀",
            "failed": "기록 실패",
            "no_target": "대상 파일 없음",
            "no_exiftool": "ExifTool 없음",
        }
        current = done if status == "running" else max(done, 0)
        self._update_loading(
            message=status_map.get(status, "작업 중…"),
            detail=f"{group_id[:8]}…",
            current=current,
            total=max(total, 1),
        )

    def _on_explorer_meta_repair_done(self, result: dict) -> None:
        _t_post = time.perf_counter()
        _log_phase("worker.done", 0.0, op="explorer_meta_repair")
        self._hide_loading()

        total = result.get("total", 0)
        success = result.get("success", 0)
        failed = result.get("failed", 0)
        skipped = result.get("skipped", 0)
        self._log.append(
            f"[INFO] Explorer 메타 복구 완료 — 전체: {total} 성공: {success} 실패: {failed} 건너뜀: {skipped}"
        )
        for err in result.get("errors", [])[:5]:
            self._log.append(f"[WARN] {err}")

        _log_phase("postprocess.start", 0.0, op="explorer_meta_repair")
        for done_gid in result.get("group_ids", []):
            self._refresh_gallery_item(done_gid)
        gid = self._gallery.get_selected_group_id()
        if gid:
            self._refresh_detail(gid)
        self._refresh_counts()
        _log_phase("postprocess.end", (time.perf_counter() - _t_post) * 1000, op="explorer_meta_repair")

    def _on_exact_duplicate_check(self) -> None:
        try:
            request = self._build_duplicate_scope_request()
            if request is None:
                return
            scope, group_ids, scope_label = request
            self._show_loading(
                "완전 중복 검사",
                "해시 기준으로 같은 파일을 찾고 있어요.",
                detail=f"범위: {scope_label}",
                total=3,
                current=0,
            )
            thread = ExactDuplicateCheckThread(
                self._db_path(),
                self._inbox_dir(),
                scope,
                group_ids=group_ids,
                parent=self,
            )
            thread.log_msg.connect(self._log.append)
            thread.log_msg.connect(self._mirror_loading_log)
            thread.progress.connect(
                lambda done, total_steps, message: self._update_loading(
                    message="완전 중복 후보를 계산하고 있어요.",
                    detail=message,
                    current=done,
                    total=total_steps,
                )
            )
            thread.done.connect(
                lambda result, label=scope_label: self._on_exact_duplicate_check_done(
                    label, result
                )
            )
            thread.start()
            self._dup_thread = thread
        except Exception as exc:
            self._hide_loading()
            self._log.append(f"[ERROR] 완전 중복 검사 실패: {exc}")

    def _on_exact_duplicate_check_done(self, scope_label: str, result: dict) -> None:
        self._hide_loading()
        if not result.get("success"):
            self._log.append(f"[ERROR] 완전 중복 검사 실패: {result.get('error', '')}")
            return

        summary = result.get("summary", {})
        self._log.append("[INFO] 중복 검사 대상")
        self._log.append(f"[INFO]   DB 등록 Inbox/Managed 파일: {summary.get('db_file_count', 0)}개")
        if summary.get("unindexed_count", 0) > 0:
            self._log.append(
                f"[INFO]   DB 미등록 Inbox 파일: {summary.get('unindexed_count', 0)}개"
            )
            self._log.append(
                "[INFO]   미등록 파일까지 검사하려면 먼저 이미지 스캔을 실행하세요."
            )

        cleanup = result.get("cleanup")
        if not cleanup:
            QMessageBox.information(self, "완전 중복 검사", "완전 중복 파일이 없습니다.")
            return

        delete_file_ids = result.get("delete_file_ids", [])
        if not delete_file_ids:
            QMessageBox.information(self, "완전 중복 검사", "삭제 후보 파일이 없습니다.")
            return

        msg = (
            f"완전 중복 그룹: {cleanup['total_groups']}개\n"
            f"보존 파일: {cleanup['total_keep']}개\n"
            f"삭제 후보: {cleanup['total_delete_candidates']}개\n\n"
            f"검사 범위: {scope_label}\n"
            "삭제 미리보기로 이동하시겠습니까?"
        )
        if QMessageBox.question(
            self,
            "완전 중복 검사 결과",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        conn = self._get_conn()
        try:
            from core.delete_manager import build_delete_preview, execute_delete_preview
            from app.views.delete_preview_dialog import DeletePreviewDialog

            preview = build_delete_preview(
                conn, file_ids=delete_file_ids, reason="exact_duplicate_cleanup"
            )
            dlg = DeletePreviewDialog(preview, parent=self)
            if dlg.exec() == DeletePreviewDialog.DialogCode.Accepted and dlg.is_confirmed():
                result_delete = execute_delete_preview(conn, preview, confirmed=True)
                self._log.append(
                    f"[INFO] 완전 중복 정리 완료 — "
                    f"deleted={result_delete['deleted']} failed={result_delete['failed']}"
                )
                self._refresh_gallery()
                self._refresh_counts()
        finally:
            conn.close()

    def _on_visual_duplicate_check(self) -> None:
        try:
            request = self._build_duplicate_scope_request()
            if request is None:
                return
            scope, group_ids, scope_label = request

            conn = self._get_conn()
            try:
                from core.duplicate_finder import get_duplicate_check_summary
                summary = get_duplicate_check_summary(
                    conn, self._inbox_dir(), scope=scope, group_ids=group_ids
                )
            finally:
                conn.close()

            db_count = summary["db_file_count"]
            unindexed = summary["unindexed_count"]
            dup_cfg = self.config.get("duplicates", {})
            max_files = dup_cfg.get("max_visual_files_per_run", 300)
            confirm = dup_cfg.get("confirm_visual_scan", True)

            if confirm:
                warn_lines = [
                    "시각 중복 검사는 이미지 내용을 분석하므로 시간이 오래 걸릴 수 있습니다.\n",
                    f"검사 범위: {scope_label}",
                    f"대상 파일 수: {db_count}개",
                    "예상 시간은 파일 수와 이미지 크기에 따라 달라집니다.",
                ]
                if unindexed > 0:
                    warn_lines.append(
                        f"\nDB 미등록 Inbox 파일 {unindexed}개는 검사 대상에서 제외됩니다.\n"
                        "미등록 파일까지 검사하려면 먼저 이미지 스캔을 실행하세요."
                    )
                if db_count > max_files:
                    warn_lines.insert(
                        0,
                        f"대상 파일 수 {db_count}개가 권장 한도({max_files}개)를 초과합니다.\n"
                        "선택 항목이나 현재 목록 기준으로 줄여서 검사하는 편을 권장합니다.\n",
                    )
                reply = QMessageBox.question(
                    self,
                    "시각 중복 검사",
                    "\n".join(warn_lines) + "\n\n계속하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            self._show_loading(
                "시각 중복 검사",
                "이미지 내용을 비교해서 비슷한 작품을 찾고 있어요.",
                detail=f"범위: {scope_label}",
                total=4,
                current=0,
            )
            thread = VisualDuplicateCheckThread(
                self._db_path(),
                self._inbox_dir(),
                scope,
                group_ids=group_ids,
                parent=self,
            )
            thread.log_msg.connect(self._log.append)
            thread.log_msg.connect(self._mirror_loading_log)
            thread.progress.connect(
                lambda done, total_steps, message: self._update_loading(
                    message="시각 중복 후보를 계산하고 있어요.",
                    detail=message,
                    current=done,
                    total=total_steps,
                )
            )
            thread.done.connect(
                lambda result, label=scope_label: self._on_visual_duplicate_check_done(
                    label, result
                )
            )
            thread.start()
            self._dup_thread = thread
        except Exception as exc:
            self._hide_loading()
            self._log.append(f"[ERROR] 시각 중복 검사 실패: {exc}")

    def _on_visual_duplicate_check_done(self, scope_label: str, result: dict) -> None:
        self._hide_loading()
        if not result.get("success"):
            self._log.append(f"[ERROR] 시각 중복 검사 실패: {result.get('error', '')}")
            return

        dup_groups = result.get("dup_groups") or []
        if not dup_groups:
            QMessageBox.information(self, "시각 중복 검사", "유사 이미지 그룹이 없습니다.")
            return

        initial_decisions = result.get("initial_decisions", {})
        if initial_decisions:
            self._log.append(
                "[INFO] 시각 중복 검사 자동 유지/삭제 추천을 적용했습니다. "
                "검토 화면에서 변경할 수 있습니다."
            )

        from app.views.delete_preview_dialog import DeletePreviewDialog
        from app.views.visual_duplicate_review_dialog import VisualDuplicateReviewDialog
        from core.delete_manager import build_delete_preview, execute_delete_preview

        review_dlg = VisualDuplicateReviewDialog(
            dup_groups,
            parent=self,
            initial_decisions=initial_decisions,
        )
        if review_dlg.exec() != VisualDuplicateReviewDialog.DialogCode.Accepted:
            return

        delete_file_ids = review_dlg.selected_for_delete()
        if not delete_file_ids:
            return

        conn = self._get_conn()
        try:
            preview = build_delete_preview(
                conn, file_ids=delete_file_ids, reason="visual_duplicate_cleanup"
            )
            dlg = DeletePreviewDialog(preview, parent=self)
            if dlg.exec() == DeletePreviewDialog.DialogCode.Accepted and dlg.is_confirmed():
                result_delete = execute_delete_preview(conn, preview, confirmed=True)
                self._log.append(
                    f"[INFO] 시각 중복 정리 완료 — "
                    f"deleted={result_delete['deleted']} failed={result_delete['failed']}"
                )
                self._refresh_gallery()
                self._refresh_counts()
        finally:
            conn.close()

    def _start_ipc_server(self) -> None:
        try:
            from app.http_server import AppHttpServer
            port = self.config.get("http_server", {}).get("port", 18456)
            self._ipc_server = AppHttpServer(
                data_dir=self._data_dir(),
                port=port,
                on_add_job=self._on_ipc_add_job,
                on_get_job=self._on_ipc_get_job,
                on_notify=self._on_ipc_notify,
            )
            self._ipc_server.start()
        except Exception as exc:
            logger.warning("IPC 서버 시작 실패 (무시): %s", exc)
            self._ipc_server = None

    def _on_ipc_add_job(self, payload: dict) -> dict:
        return {"success": True, "data": {"job_id": "placeholder"}}

    def _on_ipc_get_job(self, job_id: str) -> dict:
        return {"job_id": job_id, "status": "pending", "saved_pages": 0}

    def _on_ipc_notify(self, payload: dict) -> None:
        self._refresh_gallery()
        self._refresh_counts()

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(3000)
        if getattr(self, "_ipc_server", None):
            self._ipc_server.stop()
        super().closeEvent(event)


# ------------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------------

def _tb_btn(text: str, tb: QToolBar) -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(
        "QPushButton {"
        "  background: #3A202B; color: #F7E8EC;"
        "  border: 1px solid #B5526C; border-radius: 4px;"
        "  padding: 4px 10px; font-size: 12px;"
        "}"
        "QPushButton:hover { background: #5C2A3A; border-color: #E69AAA; }"
        "QPushButton:disabled { color: #8F6874; border-color: #4A2030; }"
    )
    tb.addWidget(b)
    return b


def _add_tb_menu(tb: QToolBar, label: str, menu: QMenu) -> QToolButton:
    """드롭다운 메뉴를 가진 QToolButton을 툴바에 추가한다."""
    btn = QToolButton()
    btn.setText(label)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn.setMenu(menu)
    tb.addWidget(btn)
    return btn
