# -*- mode: python ; coding: utf-8 -*-
# Qt-free Linux one-folder backend bundle.
import sys
from pathlib import Path

from polmon.version import __version__

project_root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(project_root / "packaging"))
from backend_bundle import EXCLUDED_MODULES, HIDDEN_IMPORTS  # noqa: E402
from PyInstaller.utils.hooks import collect_submodules  # noqa: E402

# Дополнение ВМ и образ гостя входят в сборку; образ кладёт scripts/fetch-vm-image.py.
sys.path.insert(0, str(project_root / "addons/l1-vm/src"))
vm_image = project_root / "packaging/vm-image"
if not list(vm_image.glob("*.qcow2")):
    raise SystemExit("нет образа гостя: выполните scripts/fetch-vm-image.py перед сборкой")

analysis = Analysis(
    [str(project_root / "src/polmon/backend.py")],
    pathex=[str(project_root / "src"), str(project_root / "addons/l1-vm/src")],
    binaries=[],
    datas=[(str(vm_image), "vm")],
    hiddenimports=[*HIDDEN_IMPORTS, *collect_submodules("polmon_l1_vm")],
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
