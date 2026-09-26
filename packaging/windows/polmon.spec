# -*- mode: python ; coding: utf-8 -*-
# Windows one-file build of the Qt client: dist/polmon-<version>-windows-x64.exe
import os
import subprocess
import sys
from pathlib import Path

from polmon.version import __version__

project_root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(project_root / "packaging"))
from qt_bundle import EXCLUDED_MODULES, prune  # noqa: E402

name = f"polmon-{__version__}-windows-x64"
backend_executable = project_root / "dist/polmon-backend.exe"
if not backend_executable.is_file():
    raise SystemExit("build packaging/windows/polmon-backend.spec before the client")
# The executable's icon is drawn by the client's own icon code (no binary asset in the repo).
icon_path = Path(workpath) / "polmon.ico"
icon_path.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(
    [sys.executable, "-m", "polmon.client.icon", str(icon_path)],
    check=True,
    env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
)
analysis = Analysis(
    [str(project_root / "src/polmon/client/app.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    # The one-file client extracts the independently built, Qt-free backend beside its runtime
    # files; LocalBackendManager resolves it from sys._MEIPASS.
    datas=[(str(backend_executable), ".")],
    # The self-test and page modules are imported lazily; list them for static analysis.
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
    analysis.binaries,
    analysis.datas,
    [],
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Console subsystem so --version/--self-test report and return exit codes in any shell; a
    # double-clicked EXE releases its console when the GUI starts (polmon.client.app).
    console=True,
    icon=str(icon_path),
    disable_windowed_traceback=False,
    argv_emulation=False,
)
