# -*- mode: python ; coding: utf-8 -*-
# Qt-free Windows console backend: dist/polmon-backend.exe
import sys
from pathlib import Path

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
EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="polmon-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
