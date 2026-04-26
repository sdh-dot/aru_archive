"""
Aru Archive 메인 윈도우 — MVP-A GUI.

레이아웃:
  QToolBar (Archive Root 선택 | Inbox 스캔 | DB 초기화)
  QSplitter
    SidebarWidget (160px)
    QStackedWidget
      GalleryView    (index 0)
      NoMetadataView (index 1 — no_metadata 카테고리)
    DetailView (340px)
  LogPanel (130px)

Archive Root 선택 시 Inbox / Classified / Managed / .thumbcache / .runtime
폴더를 자동 생성하고, config.json에 영속 저장한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QToolBar, QVBoxLayout, QWidget,
)

from app.views.detail_view import DetailView
from app.views.gallery_view import GalleryView
from app.views.no_metadata_view import NoMetadataView
from app.widgets.log_panel import LogPanel
from app.widgets.sidebar import SidebarWidget
from core.config_manager import (
    ensure_archive_directories, save_config, update_archive_root,
)
from core.filename_parser import parse_pixiv_filename
from core.inbox_scanner import InboxScanner, ScanResult, compute_file_hash
from core.metadata_reader import read_aru_metadata
from core.thumbnail_manager import generate_thumbnail
from db.database import initialize_database

logger = logging.getLogger(__name__)

_ARCHIVE_SUBDIRS = ["Inbox", "Classified", "Managed", ".thumbcache", ".runtime"]

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
"""

_FAILED_STATUSES = (
    "'file_write_failed','convert_failed','metadata_write_failed',"
    "'db_update_failed','needs_reindex'"
)

_GALLERY_WHERE: dict[str, str] = {
    "all":         "",
    "inbox":       "WHERE g.status = 'inbox'",
    "managed": (
        "WHERE EXISTS ("
        "  SELECT 1 FROM artwork_files af "
        "  WHERE af.group_id = g.group_id AND af.file_role = 'managed'"
        ")"
    ),
    "no_metadata": "",
    "warning":     "WHERE g.metadata_sync_status IN ('xmp_write_failed', 'json_only')",
    "failed":      f"WHERE g.metadata_sync_status IN ({_FAILED_STATUSES})",
}

_COUNT_SQL: dict[str, str] = {
    "all":
        "SELECT COUNT(*) FROM artwork_groups",
    "inbox":
        "SELECT COUNT(*) FROM artwork_groups WHERE status = 'inbox'",
    "managed": (
        "SELECT COUNT(DISTINCT g.group_id) FROM artwork_groups g "
        "JOIN artwork_files af ON af.group_id = g.group_id "
        "WHERE af.file_role = 'managed'"
    ),
    "no_metadata":
        "SELECT COUNT(*) FROM artwork_groups "
        "WHERE metadata_sync_status = 'metadata_missing'",
    "warning":
        "SELECT COUNT(*) FROM artwork_groups "
        "WHERE metadata_sync_status IN ('xmp_write_failed', 'json_only')",
    "failed":
        f"SELECT COUNT(*) FROM artwork_groups "
        f"WHERE metadata_sync_status IN ({_FAILED_STATUSES})",
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

class ClassifyThread(QThread):
    """execute_classify_preview()를 별도 스레드에서 실행한다."""

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
    """enrich_file_from_pixiv()를 별도 스레드에서 실행한다."""

    log_msg     = Signal(str)
    enrich_done = Signal(dict)

    def __init__(self, file_id: str, db_path: str, parent=None) -> None:
        super().__init__(parent)
        self._file_id = file_id
        self._db_path = db_path

    def run(self) -> None:
        conn = initialize_database(self._db_path)
        try:
            from core.metadata_enricher import enrich_file_from_pixiv
            result = enrich_file_from_pixiv(conn, self._file_id)
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
    """InboxScanner를 별도 스레드에서 실행한다."""

    log_msg   = Signal(str)
    scan_done = Signal(object)   # ScanResult

    def __init__(
        self,
        data_dir: str,
        inbox_dir: str,
        db_path: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.data_dir  = data_dir
        self.inbox_dir = inbox_dir
        self.db_path   = db_path

    def run(self) -> None:
        conn = initialize_database(self.db_path)
        try:
            scanner = InboxScanner(conn, self.data_dir, log_fn=self.log_msg.emit)
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
        self._current_category = "all"

        self.setWindowTitle("Aru Archive")
        self.resize(1400, 900)
        self._setup_ui()
        self._connect_signals()
        self._restore_archive_root()

        if Path(self._db_path()).exists():
            self._refresh_gallery()
            self._refresh_counts()

        self._start_ipc_server()

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
        )
        self.addToolBar(tb)

        self._btn_root    = _tb_btn("📁 Archive Root 선택", tb)
        tb.addSeparator()
        self._btn_scan    = _tb_btn("🔍 Inbox 스캔", tb)
        self._btn_db_init = _tb_btn("🗄 DB 초기화",  tb)
        tb.addSeparator()
        self._btn_classify_preview = _tb_btn("📋 분류 미리보기", tb)
        self._btn_classify_run     = _tb_btn("▶ 분류 실행",     tb)
        tb.addSeparator()

        self._lbl_root = QLabel("Archive Root 미설정")
        self._lbl_root.setStyleSheet(_STYLE_PATH_NONE)
        self._lbl_root.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._lbl_root.setToolTip("Archive Root 폴더 경로")
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
        self._btn_root   .clicked.connect(self._on_select_root)
        self._btn_scan   .clicked.connect(self._on_inbox_scan)
        self._btn_db_init.clicked.connect(self._on_db_init)
        self._btn_classify_preview.clicked.connect(self._on_classify_preview)
        self._btn_classify_run    .clicked.connect(self._on_classify_run)

        self._sidebar.category_selected.connect(self._on_category_changed)
        self._gallery.item_selected.connect(self._on_item_selected)

        self._detail.read_meta_requested  .connect(self._on_read_meta)
        self._detail.pixiv_meta_requested .connect(self._on_pixiv_meta)
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
        raw = self.config.get("inbox_dir", "")
        if raw:
            return raw
        dd = self._data_dir()
        return f"{dd}/Inbox" if dd else ""

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
    # Archive Root 복원 (앱 시작 시)
    # ------------------------------------------------------------------

    def _restore_archive_root(self) -> None:
        data_dir = self._data_dir()
        if not data_dir:
            self._lbl_root.setText(
                "Archive Root 미설정 — [📁 Archive Root 선택] 클릭"
            )
            self._lbl_root.setStyleSheet(_STYLE_PATH_NONE)
            return

        self._lbl_root.setToolTip(data_dir)
        if Path(data_dir).exists():
            self._lbl_root.setText(data_dir)
            self._lbl_root.setStyleSheet(_STYLE_PATH_OK)
            try:
                ensure_archive_directories(self.config)
            except Exception as exc:
                logger.warning("폴더 생성 실패: %s", exc)
        else:
            self._lbl_root.setText(f"⚠ {data_dir}  (경로 없음)")
            self._lbl_root.setStyleSheet(_STYLE_PATH_WARN)
            logger.warning("Archive Root not found: %s", data_dir)

    # ------------------------------------------------------------------
    # 갤러리 / 카운트 갱신
    # ------------------------------------------------------------------

    def _refresh_gallery(self) -> None:
        cat = self._current_category
        if cat == "no_metadata":
            self._stack.setCurrentIndex(_NO_META_IDX)
            self._load_no_metadata_panel()
            return

        self._stack.setCurrentIndex(_GALLERY_IDX)
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

    def _refresh_gallery_item(self, group_id: str) -> None:
        sql = _GALLERY_BASE + " WHERE g.group_id = ?"
        try:
            conn = self._get_conn()
            row  = conn.execute(sql, (group_id,)).fetchone()
            conn.close()
            if row:
                self._gallery.refresh_item(group_id, dict(row))
        except Exception:
            pass

    def _refresh_counts(self) -> None:
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

    # ------------------------------------------------------------------
    # 툴바 핸들러
    # ------------------------------------------------------------------

    def _on_select_root(self) -> None:
        start = self._data_dir() or str(Path.home())
        path  = QFileDialog.getExistingDirectory(
            self, "Archive Root 폴더 선택", start
        )
        if not path:
            return

        update_archive_root(self.config, path)
        try:
            save_config(self.config, self._config_path)
            self._log.append(f"[INFO] Config saved: {self._config_path}")
        except Exception as exc:
            self._log.append(f"[ERROR] Config 저장 실패: {exc}")

        self._lbl_root.setText(path)
        self._lbl_root.setStyleSheet(_STYLE_PATH_OK)
        self._lbl_root.setToolTip(path)
        self._log.append(f"[INFO] Archive Root updated: {path}")

        for sub in _ARCHIVE_SUBDIRS:
            full    = Path(path) / sub
            existed = full.exists()
            try:
                full.mkdir(parents=True, exist_ok=True)
                if not existed:
                    self._log.append(f"[INFO] Created folder: {full}")
            except Exception as exc:
                self._log.append(f"[ERROR] Failed to create folder {full}: {exc}")

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
                "[WARN] Archive Root가 설정되지 않았습니다. "
                "[📁 Archive Root 선택]을 먼저 클릭하세요."
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

        self._log.append(f"[INFO] Inbox 스캔 시작: {inbox}")
        self._btn_scan.setEnabled(False)

        self._scan_thread = ScanThread(data_dir, inbox, db_path, parent=self)
        self._scan_thread.log_msg.connect(self._log.append)
        self._scan_thread.scan_done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, result: ScanResult) -> None:
        self._btn_scan.setEnabled(True)
        self._log.append(
            f"[INFO] 스캔 완료 — 신규: {result.new}, "
            f"스킵: {result.skipped}, 실패: {result.failed}"
        )
        self._refresh_gallery()
        self._refresh_counts()

    def _on_db_init(self) -> None:
        db_path = self._db_path()
        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            initialize_database(db_path)
            self._log.append(f"[INFO] DB 초기화 완료: {db_path}")
            self._refresh_gallery()
            self._refresh_counts()
        except Exception as exc:
            self._log.append(f"[ERROR] DB 초기화 실패: {exc}")

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

            thread = EnrichThread(file_id, self._db_path(), parent=self)
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
            scanner = InboxScanner(conn, self._data_dir(), log_fn=self._log.append)
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
            scanner = InboxScanner(conn, self._data_dir(), log_fn=self._log.append)
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
            scanner = InboxScanner(conn, self._data_dir(), log_fn=self._log.append)
            scanner._handle_static_gif(
                Path(row["file_path"]), group_id, row["file_id"], _now_iso()
            )
            conn.close()
            self._refresh_detail(group_id)
        except Exception as exc:
            self._log.append(f"[ERROR] Sidecar 생성 실패: {exc}")

    def _on_reindex(self) -> None:
        group_id = self._gallery.get_selected_group_id()
        if not group_id:
            self._log.append("[WARN] 선택된 파일 없음")
            return
        try:
            conn    = self._get_conn()
            scanner = InboxScanner(conn, self._data_dir(), log_fn=self._log.append)
            scanner.reprocess_group(group_id)
            conn.close()
            self._refresh_gallery_item(group_id)
            self._refresh_detail(group_id)
            self._refresh_counts()
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
                "[📁 Archive Root 선택]을 먼저 실행하세요."
            )
            return None
        try:
            conn    = self._get_conn()
            preview = build_classify_preview(conn, group_id, self.config)
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

            thread = EnrichThread(file_id, self._db_path(), parent=self)
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

    # ------------------------------------------------------------------
    # IPC 서버
    # ------------------------------------------------------------------

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
