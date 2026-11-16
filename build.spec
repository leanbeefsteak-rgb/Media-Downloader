# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Media Downloader.
# Run via build_windows.ps1 / build_mac.sh, or directly:  pyinstaller build.spec
import os
import sys

APP_NAME = "Media Downloader"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

HERE = os.path.abspath(".")
VENDOR = os.path.join(HERE, "vendor")

# ---- ffmpeg (bundled next to the app's resources) ----
ffmpeg_name = "ffmpeg.exe" if IS_WIN else "ffmpeg"
ffmpeg_path = os.path.join(VENDOR, ffmpeg_name)
binaries = []
if os.path.isfile(ffmpeg_path):
    binaries.append((ffmpeg_path, "."))
else:
    print(f"WARNING: {ffmpeg_path} not found - the app will not be able to merge video "
          f"or make MP3s. See README.md.")

# ---- icons ----
datas = []
icon = None
if os.path.isfile("logo.ico"):
    datas.append(("logo.ico", "."))
    if IS_WIN:
        icon = "logo.ico"
if IS_MAC and os.path.isfile("logo.icns"):
    icon = "logo.icns"

a = Analysis(
    ["media_downloader.py"],
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_WIN:
    # Single .exe that friends can just double-click.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        icon=icon,
        console=False,
        upx=False,
        onefile=True,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        icon=icon,
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.mediadownloader.app",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
