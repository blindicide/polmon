# Windows build

GitHub Actions is the authoritative Windows build environment (never Wine or emulation). Run
**Build Windows** manually (`gh workflow run build-windows.yml --ref main`) or push a release tag.
The job installs Python 3.12 and the pinned `dev`, `gui` and `build` extras, runs Ruff, the rootless
tests and the Qt GUI tests (offscreen platform), and builds the one-file
`polmon-<version>-windows-x64.exe` with `packaging/windows/polmon.spec`. It then proves the EXE
starts Qt, not merely that it exits 0:

| Check | Pass condition |
|---|---|
| `--version` | prints exactly `polmon <version>` |
| `--self-test` | offscreen platform; lists the bundled `qwindows` and `qoffscreen` platform plugins; builds, renders and destroys the main window; `self-test: PASS` |
| `--smoke-start 3` | shows the real window on the runner desktop with platform `windows`, reports it visible and exposed |
| SHA-256 | written next to the EXE (`.exe.sha256`) |
| Start-up and memory | `scripts/measure-client.py` (3 launches, 10 s idle) uploaded as `windows-client-measurements` |

A second job on a fresh runner downloads the `polmon-windows-x64` artifact, checks its SHA-256 and
repeats the three launches, so the uploaded file itself is what was verified.

The spec bundles PySide6 through PyInstaller's Qt hooks and prunes what the client cannot use
(`packaging/qt_bundle.py`): Qt modules outside QtCore/QtGui/QtWidgets, platform plugins other
than `qwindows`, `qoffscreen` and `qminimal`, image-format, icon-engine, TLS and theme plugins, and
Qt translations (the UI is English only). The console subsystem is kept so the command-line checks
report and return exit codes in any shell; when the EXE is started by double-click (it owns its
console) the console is released as the window opens.

For a manual native Windows build:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,gui,build]"
.venv\Scripts\pyinstaller --clean --noconfirm packaging/windows/polmon.spec
dist\polmon-<version>-windows-x64.exe --version
dist\polmon-<version>-windows-x64.exe --self-test
dist\polmon-<version>-windows-x64.exe --smoke-start 3
```

Troubleshooting: a missing Qt platform plugin is the classic silent failure of packaged Qt
applications ("could not find the Qt platform plugin"); `--self-test` fails with the plugin
directory it inspected and the plugin names it expected. Check the exact Python version, delete
only the regenerable `build/` and `dist/` directories, and review PyInstaller's warnings file.

Release executables are accompanied by `SHA256SUMS.txt`; `scripts/verify-release.sh vX.Y.Z`
downloads a release and checks its assets' names, versions and hashes.
