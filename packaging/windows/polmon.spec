# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from polmon.version import __version__

project_root = Path(SPECPATH).parents[1]
name = f"polmon-{__version__}-windows-x64"
analysis = Analysis(
    [str(project_root / "src/polmon/client/app.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=["polmon.version"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
