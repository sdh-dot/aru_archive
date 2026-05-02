# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Aru Archive

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "db" / "schema.sql"), "db"),
        (str(ROOT / "config.example.json"), "."),
        (str(ROOT / "assets" / "icon"), "assets/icon"),
        (str(ROOT / "assets" / "splash"), "assets/splash"),
        # LoadingOverlayDialog 좌측 메인 이미지/하단 아이콘
        # frozen 환경에서 sys._MEIPASS/assets/loading/* 로 로드된다
        (str(ROOT / "assets" / "loading"), "assets/loading"),
        # Bundled ExifTool — Windows portable 배포에 포함
        # onedir: dist/aru_archive/tools/exiftool/
        # onefile: sys._MEIPASS/tools/exiftool/ (임시 압축 해제)
        (str(ROOT / "tools" / "exiftool"), "tools/exiftool"),
        # Built-in tag packs (ko/ja localization, source priority 등)
        # frozen 환경에서 sys._MEIPASS/resources/tag_packs/* 로 로드된다
        (str(ROOT / "resources"), "resources"),
        # ExifTool license attribution + 프로젝트 문서
        (str(ROOT / "LICENSES"), "LICENSES"),
        (str(ROOT / "README.md"), "."),
        (str(ROOT / "CHANGELOG.md"), "."),
    ],
    hiddenimports=[
        "piexif",
        "PIL._imaging",
        "PIL.Image",
        "PIL.PngImagePlugin",
        "PIL.JpegImagePlugin",
        "PIL.WebPImagePlugin",
        "PIL.GifImagePlugin",
        "PIL.BmpImagePlugin",
        # core.adapters: 정적 import (importlib 미사용)이지만
        # PyInstaller가 from core.adapters import * 패턴을 놓치지 않도록 명시
        "core.adapters",
        "core.adapters.base",
        "core.adapters.pixiv",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aru_archive",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon" / "aru_archive_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="aru_archive",
)
