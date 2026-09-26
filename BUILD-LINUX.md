# Linux build

**Build Linux** (`.github/workflows/build-linux.yml`, also part of every release) produces:

| Artifact | Content |
|---|---|
| `polmon-<version>-linux-x64.tar.gz` (+ `.sha256`) | One-folder PyInstaller bundle of the Qt client: `polmon-<version>-linux-x64/polmon-client` and its `_internal/` libraries |
| `polmon-<version>-py3-none-any.whl` | The Python package (backend, CLI tools, client code; Qt via the `gui` extra) |
| `polmon-backend.service` | The example systemd user unit (see [docs/OPERATIONS.md](docs/OPERATIONS.md)) |

The bundle is built on `ubuntu-22.04`, the oldest supported hosted image, so it runs on glibc 2.35
and newer (Ubuntu 22.04+, Debian 12+). The tarball is reproducible in its metadata: sorted
entries, owner 0, modification time of the commit (`SOURCE_DATE_EPOCH`), `gzip -n`. The build job
runs Ruff, the rootless tests and the GUI tests under Xvfb, extracts the tarball into an empty
directory and runs `--version` (exact), `--self-test` with an empty environment (must list the
bundled `qxcb` plugin) and `--smoke-start 3` under Xvfb (platform `xcb`), then measures start-up
and idle memory (`linux-client-measurements`). A second job on a newer runner (`ubuntu-latest`)
downloads the artifact, verifies the checksum, repeats the smoke tests, installs the wheel into a
fresh virtual environment, checks every backend entry point's version, starts the backend, reads
`/v1/health` and confirms the graceful `shutdown_cleanup`.

## Running the bundle

```bash
sha256sum --check polmon-<version>-linux-x64.tar.gz.sha256
tar -xzf polmon-<version>-linux-x64.tar.gz
./polmon-<version>-linux-x64/polmon-client            # X11 or Wayland session
./polmon-<version>-linux-x64/polmon-client --self-test  # headless check, opens no window
./polmon-<version>-linux-x64/polmon-client --install-desktop-entry  # menu entry + icon (per user)
```

`--install-desktop-entry` writes `~/.local/share/applications/polmon-client.desktop` and the icon
(`$XDG_DATA_HOME` is honoured) pointing at the executable it was run from; run it again after
moving the folder. It works the same for a `pip install polmon[gui]` installation.

The bundle carries Qt, its X11/xcb client libraries and the Wayland platform. The host provides
the display server, fontconfig/fonts and the C runtime. On a minimal Ubuntu/Debian host the xcb
platform additionally needs `libxcb-cursor0` (Qt 6.5+ requires it and not every distribution
installs it); the CI verification installs exactly: `libxcb-cursor0 libxkbcommon-x11-0
libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0
libxcb-xinerama0 libxcb-xfixes0 libegl1 libfontconfig1 libdbus-1-3` plus `xvfb` for headless use.

## Local build

```bash
uv pip install -e '.[dev,gui,build]'
.venv/bin/pyinstaller --clean --noconfirm packaging/linux/polmon-client.spec
dist/polmon-<version>-linux-x64/polmon-client --self-test
```

Bundle pruning is shared with Windows (`packaging/qt_bundle.py`): only the `qxcb`, `qwayland`,
`qoffscreen` and `qminimal` platform plugins are kept; the GTK platform theme (which would pull a
host GTK stack into the bundle), image-format, GL-integration and input-method plugins other than
compose, and Qt translations are removed.

## AppImage (measured, not shipped)

An AppImage was built from the same bundle with the pinned appimagetool 1.9.1 (zstd squashfs) and
measured on the development host (4 vCPU, Xvfb, warm page cache, five launches each;
`scripts/measure-client.py`, raw files in `benchmarks/results/client-qt-linux-*-20260926.json`):

| Form | Download | Launch to window (median) | Idle RSS after 10 s |
|---|---:|---:|---:|
| Extracted tarball bundle | 50.8 MB (`.tar.gz`) | 0.54 s | 93.0 MiB |
| AppImage | 47.4 MB | 0.92 s | 91.5 MiB |

The AppImage saves 3.4 MB of download but adds about 0.4 s to every start (the squashfs is mounted
through FUSE on each launch), requires FUSE 2 (`libfuse2`) on the host or the slower
`--appimage-extract-and-run`, and brings a second, non-PyPI tool plus its runtime into the release
build. The tarball runs without installation just the same, so the AppImage is not built;
revisit if desktop integration (menus, icons) becomes a requirement.
