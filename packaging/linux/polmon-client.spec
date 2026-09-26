# -*- mode: python ; coding: utf-8 -*-
# Linux one-folder build of the Qt client: dist/polmon-<version>-linux-x64/polmon-client
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
analysis.binaries = prune(analysis.binaries, "linux")
analysis.datas = prune(analysis.datas, "linux")
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
    name=f"polmon-{__version__}-linux-x64",
)
