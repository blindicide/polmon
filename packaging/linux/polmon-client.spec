# -*- mode: python ; coding: utf-8 -*-
# Linux one-folder build of the Qt client: dist/polmon-<version>-linux-x64/polmon-client
import sys
from pathlib import Path

from polmon.version import __version__

project_root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(project_root / "packaging"))
from backend_bundle import HIDDEN_IMPORTS as BACKEND_HIDDEN_IMPORTS  # noqa: E402
from qt_bundle import EXCLUDED_MODULES, prune  # noqa: E402

analysis = Analysis(
    [str(project_root / "src/polmon/client/app.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "polmon.client.selftest",
        "polmon.client.mainwindow",
        # Embedded L0 backend: app.main re-invokes this same executable in backend mode, so the
        # one bundled client must also contain the backend module graph and the SQLite extension.
        # "sqlite3" pulls in the _sqlite3 C extension and prevents the polmon 0.4.1 Linux startup
        # failure (ModuleNotFoundError: No module named '_sqlite3'). The backend hidden imports
        # mirror the Qt-free backend bundle so uvicorn/polmon.* modules resolved by dotted name at
        # request time are collected even though the client imports backend lazily.
        "sqlite3",
        *BACKEND_HIDDEN_IMPORTS,
    ],
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
    # Strip debug symbols: the hosted runners' Python ships libpython with debug info (~20 MB).
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
    name=f"polmon-{__version__}-linux-x64",
)
