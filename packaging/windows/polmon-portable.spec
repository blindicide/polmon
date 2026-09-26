# -*- mode: python ; coding: utf-8 -*-
# Windows one-folder ("portable") build of the Qt client:
#   dist/polmon-<version>-windows-x64-portable/polmon-client.exe
# Starts without unpacking anything (the one-file EXE extracts itself on every launch).
import sys
from pathlib import Path

from polmon.version import __version__

project_root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(project_root / "packaging"))
from qt_bundle import EXCLUDED_MODULES, prune  # noqa: E402

analysis = Analysis(
    [str(project_root / "src/polmon/client/app.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=["polmon.client.selftest", "polmon.client.mainwindow"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
)
analysis.binaries = prune(analysis.binaries, "windows")
analysis.datas = prune(analysis.datas, "windows")
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="polmon-client",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=f"polmon-{__version__}-windows-x64-portable",
)
