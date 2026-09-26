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
```

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

## AppImage

Not built. An AppImage would wrap the same bundle and add the AppImage runtime plus a FUSE
dependency on the host (or `--appimage-extract-and-run`), and the tooling (`appimagetool`) is an
unpinned download outside PyPI, which makes the build less reproducible than the tarball. The
tarball already runs without installation, so the AppImage adds no capability for its cost.
