# -*- mode: python ; coding: utf-8 -*-
# Qt-free Linux one-folder backend bundle.
import sys
from pathlib import Path

from polmon.version import __version__
from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(project_root / "packaging"))
from backend_bundle import EXCLUDED_MODULES, HIDDEN_IMPORTS  # noqa: E402

sys.path.insert(0, str(project_root / "addons/l1-vm/src"))
from polmon.api.vm import IMAGE_NAME, MANIFEST
from polmon_l1_vm.images import ImageManifest, VMError, digest

vm_image = project_root / "packaging/vm-image" / IMAGE_NAME
manifest = ImageManifest.model_validate(MANIFEST)
if vm_image.is_symlink() or not vm_image.is_file():
    raise SystemExit("missing pinned image: run scripts/fetch-vm-image.py")
if (
    vm_image.stat().st_mode & 0o222
    or digest(vm_image, limit=manifest.max_file_bytes) != manifest.sha256
):
    raise VMError("vm.image_checksum")

analysis = Analysis(
    [str(project_root / "src/polmon/backend.py")],
    pathex=[str(project_root / "src"), str(project_root / "addons/l1-vm/src")],
    binaries=[],
    datas=[
        (str(vm_image), "vm"),
        (str(project_root / "examples/vm/alpine-3.24.1-manifest.json"), "vm"),
    ],
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
bundle = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=True,
    upx=False,
    name=f"polmon-backend-{__version__}-linux-x64",
)

# PyInstaller copies DATA with default permissions; the trusted backing image stays read-only.
(Path(bundle.name) / "_internal/vm" / IMAGE_NAME).chmod(0o444)
