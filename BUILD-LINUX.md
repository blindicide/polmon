# Linux build

The `Build Linux` workflow builds one PyInstaller client bundle with the full Linux backend module
graph and SQLite. A small `polmon-backend` launcher re-enters the frozen client in backend mode;
neither Python nor a source checkout is needed. The same bundle is distributed as a tarball, a
Debian package, and an RPM; a Python wheel remains available for source-style installations.

| Asset | Content |
|---|---|
| `polmon-<version>-linux-x64.tar.gz` and `.sha256` | Portable client, `polmon-backend` launcher and `_internal/` runtime |
| `polmon-client_<version>_amd64.deb` | `/opt/polmon` client/backend, `/usr/bin/polmon-client`, `/usr/bin/polmon-backend`, desktop entry, icon |
| `polmon-client-<version>-1.x86_64.rpm` | Same install layout for RPM distributions |
| `package-manifest.json`, `SHA256SUMS-packages.txt` | Dependencies, limits, license status, install/removal behavior, size and hashes |
| `polmon-<version>-py3-none-any.whl` | Python package for separate Python installations |

The CI build uses Ubuntu 22.04 and targets glibc 2.35 or newer. The client includes `_sqlite3`
and `libsqlite3`; `--local-backend-self-test` proves that its own embedded backend can persist an
L0 experiment. `--polmon-run-embedded-backend --diagnostics` exercises backend startup without
loading Qt. The Linux job verifies backend startup from the extracted tarball with a scrubbed
environment, plus Qt startup under Xvfb. A fresh runner downloads the artifact and completes both an
L1 namespace deployment and a hybrid TAP deployment, each with benign ICMP ping and cleanup. Missing
namespace, ping or TUN readiness fails this acceptance check (it is not reported as a pass). It
installs, tests, reinstalls, and removes the native
packages in fresh Debian and Fedora containers and checks that user-owned data survives removal.
A second runner downloads the built artifacts and checks their hashes, embedded backend,
addon import/dispatch and pinned image digest/read-only permissions. Native package installation
also verifies the addon/image bundle. These checks do not boot a guest.

The Linux client includes `polmon_l1_vm` and the exact Alpine 3.24.1 QCOW2 image from
`examples/vm/alpine-3.24.1-manifest.json` (183,697,408 bytes, SHA-256 pinned in that manifest).
The fetcher enforces HTTPS, size/time limits and digest verification. The build refuses a
missing, writable or mismatched image and preserves read-only permissions through tarball,
Debian and RPM staging. Windows and Python wheels do not include the guest image.
Independent VM jobs require external QEMU/KVM, `qemu-img`, `genisoimage`, `/dev/net/tun`
and a permitted network mode under an unprivileged operator account. No host tools or
privileges are installed by the application. Real guest acceptance remains NOT RUN here;
see SECURITY.md for the claim boundary.

Native packages have no maintainer scripts or systemd unit. Run `polmon-backend` after installation,
or `./polmon-backend` from an extracted tarball; it defaults to loopback and uses the backend's
existing token requirement for non-loopback binds. L1/hybrid traffic requires the documented Linux
namespace tools and already configured privileges. The application never grants sudo or changes
host privilege configuration. Package removal leaves results in
`$XDG_STATE_HOME/polmon/data` (usually `~/.local/state/polmon/data`) and settings under the
user's config directory untouched. POLMON has no granted license; the package metadata says
`Proprietary`; bundled PySide6/Qt libraries and Alpine components retain their separate terms.

## Local build

```bash
uv pip install -e '.[dev,gui,build]'
.venv/bin/python scripts/fetch-vm-image.py
.venv/bin/pyinstaller --clean --noconfirm packaging/linux/polmon-client.spec
QT_QPA_PLATFORM=offscreen .venv/bin/python -m polmon.client.icon dist/polmon.png
version="$(.venv/bin/python -c 'from polmon.version import __version__; print(__version__)')"
epoch="$(git log -1 --format=%ct)"
.venv/bin/python scripts/build-linux-packages.py \
  --bundle "dist/polmon-$version-linux-x64" --icon dist/polmon.png \
  --backend-launcher packaging/linux/polmon-backend \
  --output dist --version "$version" --epoch "$epoch"
(cd dist && sha256sum --check --strict SHA256SUMS-packages.txt)
"dist/polmon-$version-linux-x64/polmon-client" --local-backend-self-test
```

The packaging script fixes ownership and timestamps and writes checksums. Repeating packaging
from the same frozen bundle and epoch should produce the same package bytes. A fresh PyInstaller
build is a separate reproducibility question. The packages need standard glibc, libstdc++, Qt
xcb/EGL, fontconfig, and D-Bus libraries; exact declared dependencies are in the manifest.
Desktop launch needs an X11/Qt display, while `--local-backend-self-test` runs headlessly.

The previous standalone backend tarball and its systemd user unit were last released with v0.4.1
(v0.5.0 is tagged but has no GitHub release); they are not assets of the Phase VI build.
