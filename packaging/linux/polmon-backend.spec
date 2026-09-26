# -*- mode: python ; coding: utf-8 -*-
# Qt-free Linux one-folder backend bundle.
import sys
from pathlib import Path

from polmon.version import __version__

project_root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(project_root / "packaging"))
from backend_bundle import EXCLUDED_MODULES, HIDDEN_IMPORTS  # noqa: E402

analysis = Analysis(
    [str(project_root / "src/polmon/backend.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="polmon-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=True,
)
COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=True,
    upx=False,
    name=f"polmon-backend-{__version__}-linux-x64",
)
