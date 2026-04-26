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
        (str(ROOT / "app" / "resources" / "icons" / "aru_archive_icon.ico"),
         "app/resources/icons"),
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
    icon=str(ROOT / "app" / "resources" / "icons" / "aru_archive_icon.ico"),
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
