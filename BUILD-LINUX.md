# Linux build

The Phase VI `Build Linux` workflow builds one PyInstaller client bundle with embedded L0 and
SQLite. The client runs without Python, a source checkout, or a sibling backend executable. The
same bundle is distributed as a tarball, a Debian package, and an RPM; a Python wheel remains
available for source-style installations. No standalone backend bundle or service is produced.

| Asset | Content |
|---|---|
| `polmon-<version>-linux-x64.tar.gz` and `.sha256` | Portable client and `_internal/` runtime |
| `polmon-client_<version>_amd64.deb` | `/opt/polmon` client, `/usr/bin/polmon-client`, desktop entry, icon |
| `polmon-client-<version>-1.x86_64.rpm` | Same install layout for RPM distributions |
| `package-manifest.json`, `SHA256SUMS-packages.txt` | Dependencies, limits, license status, install/removal behavior, size and hashes |
| `polmon-<version>-py3-none-any.whl` | Python package for separate Python installations |

The CI build uses Ubuntu 22.04 and targets glibc 2.35 or newer. The client includes `_sqlite3`
and `libsqlite3`; `--local-backend-self-test` proves that its own embedded backend can persist an
L0 experiment. `--polmon-run-embedded-backend --diagnostics` exercises backend startup without
loading Qt. The Linux job verifies these operations from the extracted tarball with an empty
environment, plus Qt startup under Xvfb. It installs, tests, reinstalls, and removes the native
packages in fresh Debian and Fedora containers and checks that user-owned data survives removal.
A second runner downloads the built artifacts and checks their hashes and embedded backend.

Native packages have no maintainer scripts or systemd unit. L1/hybrid traffic requires a
separately configured Linux laboratory backend with the documented namespace privileges; the
packaged local backend supports L0 only. Package removal leaves results in
`$XDG_STATE_HOME/polmon/data` (usually `~/.local/state/polmon/data`) and settings under the
user's config directory untouched. POLMON has no granted license; the package metadata says
`Proprietary`, and bundled PySide6/Qt libraries retain their separate terms.

## Local build

```bash
uv pip install -e '.[dev,gui,build]'
.venv/bin/pyinstaller --clean --noconfirm packaging/linux/polmon-client.spec
QT_QPA_PLATFORM=offscreen .venv/bin/python -m polmon.client.icon dist/polmon.png
version="$(.venv/bin/python -c 'from polmon.version import __version__; print(__version__)')"
epoch="$(git log -1 --format=%ct)"
.venv/bin/python scripts/build-linux-packages.py \
  --bundle "dist/polmon-$version-linux-x64" --icon dist/polmon.png \
  --output dist --version "$version" --epoch "$epoch"
(cd dist && sha256sum --check --strict SHA256SUMS-packages.txt)
"dist/polmon-$version-linux-x64/polmon-client" --local-backend-self-test
```

The packaging script fixes ownership and timestamps and writes checksums. Repeating packaging
from the same frozen bundle and epoch should produce the same package bytes. A fresh PyInstaller
build is a separate reproducibility question. The packages need standard glibc, libstdc++, Qt
xcb/EGL, fontconfig, and D-Bus libraries; exact declared dependencies are in the manifest.
Desktop launch needs an X11/Qt display, while `--local-backend-self-test` runs headlessly.

The previous standalone backend tarball and its systemd user unit remain documented in the
published v0.5.0 release; they are not assets of the Phase VI build.
