"""
Aru Archive 진입점.

사용법:
  python main.py                        # GUI 모드 (기본)
  python main.py --config path/to.json  # 설정 파일 지정
  python main.py --headless             # GUI 없이 IPC 서버만 실행 (서버 모드)
"""
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _load_config(config_path: str | None) -> dict:
    from core.config_manager import load_config

    if config_path is None:
        for candidate in [
            Path.cwd() / "config.json",
            Path.home() / ".aru_archive" / "config.json",
        ]:
            if candidate.exists():
                config_path = str(candidate)
                break
        else:
            config_path = "config.json"

    return load_config(config_path)


def _setup_logging(config: dict) -> None:
    log_cfg = config.get("log", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_dir = log_cfg.get("dir")
    if log_dir:
        log_dir = log_dir.replace("{data_dir}", str(_resolve_data_dir(config)))

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_dir:
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            str(log_dir_path / "aru_archive.log"),
            maxBytes=log_cfg.get("max_bytes", 5_242_880),
            backupCount=log_cfg.get("backup_count", 3),
            encoding="utf-8",
        )
        handlers.append(fh)

    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers)


def _resolve_data_dir(config: dict) -> Path:
    raw = config.get("data_dir", str(Path.home() / "AruArchive"))
    return Path(raw).expanduser().resolve()


def run_gui(config: dict, config_path: str = "config.json") -> int:
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        logging.critical("PyQt6가 설치되어 있지 않습니다.")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("Aru Archive")
    app.setApplicationVersion("0.1.0")

    from PyQt6.QtGui import QIcon
    from app.resources import icon_path
    app.setWindowIcon(QIcon(icon_path()))

    from app.main_window import MainWindow, _apply_wine_style  # type: ignore[import]
    _apply_wine_style(app)

    window = MainWindow(config, config_path=config_path)
    window.show()

    return app.exec()


def run_headless(config: dict) -> int:
    import signal
    import time

    data_dir = _resolve_data_dir(config)
    data_dir.mkdir(parents=True, exist_ok=True)

    from db.database import initialize_database
    db_path_tpl = config.get("db", {}).get("path", "{data_dir}/aru_archive.db")
    db_path = db_path_tpl.replace("{data_dir}", str(data_dir))
    initialize_database(db_path)
    logging.info("DB 초기화 완료: %s", db_path)

    from app.http_server import AppHttpServer
    port = config.get("http_server", {}).get("port", 18456)
    server = AppHttpServer(data_dir=str(data_dir), port=port)
    server.start()
    logging.info("IPC 서버 시작: 포트 %d", port)

    stop = False

    def _handle_signal(signum, frame):  # noqa: ANN001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        while not stop:
            time.sleep(0.5)
    finally:
        server.stop()
        logging.info("서버 종료")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Aru Archive")
    parser.add_argument("--config", metavar="PATH", help="설정 파일 경로")
    parser.add_argument("--headless", action="store_true", help="GUI 없이 서버 모드로 실행")
    args = parser.parse_args()

    config = _load_config(args.config)
    _setup_logging(config)

    data_dir = _resolve_data_dir(config)
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.headless:
        return run_headless(config)

    gui_config = dict(config)
    gui_config["data_dir"] = str(data_dir)
    cfg_path = args.config or "config.json"
    return run_gui(gui_config, config_path=cfg_path)


if __name__ == "__main__":
    sys.exit(main())
