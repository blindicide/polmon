#!/usr/bin/env python3
"""Build Debian and RPM packages from the frozen, embedded-L0 Linux client."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

DEB_DEPENDS = (
    "libc6 (>= 2.35), libstdc++6, libgcc-s1, libglib2.0-0, libx11-6, "
    "libx11-xcb1, libxcb1, libxkbcommon0, libxkbcommon-x11-0, "
    "libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, "
    "libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xfixes0, "
    "libxcb-xinerama0, libegl1, libgl1, libfontconfig1, libfreetype6, libdbus-1-3"
)
RPM_REQUIRES = (
    "glibc, libstdc++, libgcc, glib2, libX11, libxcb, libxkbcommon, "
    "libxkbcommon-x11, xcb-util-cursor, xcb-util-wm, xcb-util-image, "
    "xcb-util-keysyms, xcb-util-renderutil, mesa-libEGL, mesa-libGL, "
    "fontconfig, freetype, dbus-libs"
)
COPYRIGHT = """POLMON: no license has been granted by the repository owner.
All rights reserved. Redistribution requires permission from the owner.

The frozen client includes PySide6 Essentials, shiboken6 and Qt libraries,
which carry their own third-party license terms (including LGPLv3).
See the upstream packages' notices and the bundled library metadata.
This statement does not grant a license to POLMON itself.
"""
DESKTOP = """[Desktop Entry]
Type=Application
Name=POLMON
Comment=Isolated network laboratory client
Exec=polmon-client
Icon=polmon
Terminal=false
Categories=Development;Education;
"""


def run(*args: str, **kwargs: object) -> None:
    subprocess.run(args, check=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def touch_tree(root: Path, epoch: int) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if not path.is_symlink():
            os.utime(path, (epoch, epoch))
    os.utime(root, (epoch, epoch))


def stage(bundle: Path, root: Path, epoch: int, icon: Path) -> None:
    files = root / "opt/polmon"
    shutil.copytree(bundle, files, symlinks=True)
    if not (files / "polmon-client").is_file():
        raise SystemExit("bundle lacks polmon-client")
    if any(path.name.startswith("polmon-backend") for path in files.rglob("*")):
        raise SystemExit("bundle contains a separate backend executable")
    if not any(path.name.startswith("_sqlite3") and path.suffix == ".so"
               for path in files.rglob("*")):
        raise SystemExit("bundle lacks the embedded _sqlite3 extension")
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/polmon-client").symlink_to("/opt/polmon/polmon-client")
    desktop = root / "usr/share/applications/polmon-client.desktop"
    desktop.parent.mkdir(parents=True)
    desktop.write_text(DESKTOP, encoding="utf-8")
    target_icon = root / "usr/share/icons/hicolor/256x256/apps/polmon.png"
    target_icon.parent.mkdir(parents=True)
    shutil.copy2(icon, target_icon)
    copyright_file = root / "usr/share/doc/polmon/copyright"
    copyright_file.parent.mkdir(parents=True)
    copyright_file.write_text(COPYRIGHT, encoding="utf-8")
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        else:
            path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
    touch_tree(root, epoch)


def make_deb(root: Path, output: Path, version: str, arch: str, epoch: int) -> Path:
    control = root / "DEBIAN/control"
    control.parent.mkdir()
    control.write_text(
        f"Package: polmon-client\nVersion: {version}\nArchitecture: {arch}\n"
        "Maintainer: polmon contributors\n"
        f"Depends: {DEB_DEPENDS}\n"
        "Section: science\nPriority: optional\n"
        "Description: POLMON isolated network laboratory desktop client\n"
        " Self-contained Qt client with embedded L0 backend and SQLite runtime.\n",
        encoding="utf-8",
    )
    control.parent.chmod(0o755)
    control.chmod(0o644)
    touch_tree(root, epoch)
    package = output / f"polmon-client_{version}_{arch}.deb"
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch)}
    run("dpkg-deb", "--build", "--root-owner-group", "--uniform-compression",
        str(root), str(package), env=env)
    return package


def make_rpm(root: Path, output: Path, version: str, arch: str, epoch: int,
             work: Path) -> Path:
    top = work / "rpm"
    for name in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        (top / name).mkdir(parents=True)
    source = top / "SOURCES/payload.tar.gz"
    payload = work / f"polmon-client-{version}"
    (payload / "root").mkdir(parents=True)
    for child in root.iterdir():
        if child.name != "DEBIAN":
            shutil.copytree(child, payload / "root" / child.name, symlinks=True)
    touch_tree(payload, epoch)
    def root_owner(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        return info

    with (
        source.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=epoch) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        archive.add(payload, arcname=payload.name, recursive=True, filter=root_owner)
    spec = top / "SPECS/polmon-client.spec"
    spec.write_text(
        f"""Name: polmon-client
Version: {version}
Release: 1
Summary: POLMON isolated network laboratory desktop client
License: Proprietary
URL: https://github.com/blindicide/polmon
Source0: payload.tar.gz
BuildArch: {arch}
AutoReqProv: no
Requires: {RPM_REQUIRES}

%description
Self-contained Qt client with embedded L0 backend and SQLite runtime.

%prep
%setup -q -n polmon-client-{version}

%build

%install
mkdir -p %{{buildroot}}
cp -a root/. %{{buildroot}}/

%files
%defattr(-,root,root,-)
/opt/polmon
/usr/bin/polmon-client
/usr/share/applications/polmon-client.desktop
/usr/share/icons/hicolor/256x256/apps/polmon.png
/usr/share/doc/polmon/copyright
""",
        encoding="utf-8",
    )
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch)}
    run(
        "rpmbuild", "-bb", str(spec), "--define", f"_topdir {top}",
        "--define", "_buildhost reproducible",
        "--define", "clamp_mtime_to_source_date_epoch 1",
        "--define", "use_source_date_epoch_as_buildtime 1",
        "--define", "__os_install_post %{nil}",
        env=env,
    )
    built = list((top / "RPMS").rglob("*.rpm"))
    if len(built) != 1:
        raise SystemExit(f"expected one RPM, found {built}")
    package = output / built[0].name
    shutil.copy2(built[0], package)
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--icon", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--epoch", type=int, required=True)
    args = parser.parse_args()
    machine = platform.machine()
    arches = {"x86_64": ("amd64", "x86_64"), "aarch64": ("arm64", "aarch64")}
    if machine not in arches:
        raise SystemExit(f"unsupported package architecture: {machine}")
    deb_arch, rpm_arch = arches[machine]
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="polmon-packages-") as temporary:
        work = Path(temporary)
        root = work / "root"
        stage(args.bundle.resolve(), root, args.epoch, args.icon.resolve())
        deb = make_deb(root, args.output, args.version, deb_arch, args.epoch)
        rpm = make_rpm(root, args.output, args.version, rpm_arch, args.epoch, work)
    packages = [deb, rpm]
    sums = args.output / "SHA256SUMS-packages.txt"
    sums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in packages),
        encoding="ascii",
    )
    manifest = {
        "version": args.version,
        "architectures": {"deb": deb_arch, "rpm": rpm_arch},
        "source_date_epoch": args.epoch,
        "contents": ["/opt/polmon (single client with embedded L0 and _sqlite3)",
                     "/usr/bin/polmon-client", "/usr/share/applications/polmon-client.desktop",
                     "/usr/share/icons/hicolor/256x256/apps/polmon.png",
                     "/usr/share/doc/polmon/copyright"],
        "dependencies": {"deb": DEB_DEPENDS, "rpm": RPM_REQUIRES},
        "license": "No license granted for POLMON; bundled PySide6/Qt terms apply separately.",
        "user_data": (
            "No maintainer scripts; removal leaves home directories, results and settings intact."
        ),
        "platform_limits": "Linux glibc 2.35+; GUI requires X11/Qt xcb libraries. "
                           "L1/L2 require a separately configured Linux laboratory backend.",
        "packages": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in packages
        ],
    }
    (args.output / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["packages"], indent=2))


if __name__ == "__main__":
    main()
