# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSET_ROOT = PROJECT_ROOT / "video_downloader" / "assets"
if sys.platform == "win32":
    executable_icon = str(ASSET_ROOT / "video_downloader.ico")
elif sys.platform == "darwin":
    executable_icon = str(ASSET_ROOT / "video_downloader.icns")
else:
    executable_icon = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(ASSET_ROOT / "video_downloader.png"), "video_downloader/assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    icon=executable_icon,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoDownloader",
)
