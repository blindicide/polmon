# Windows build

GitHub Actions is the authoritative Windows build environment (never Wine or emulation). Run
**Build Windows** manually (`gh workflow run build-windows.yml --ref main`) or push a release tag.
The job installs Python 3.12 and the pinned `dev`, `gui` and `build` extras, runs Ruff, the rootless
tests and the Qt GUI tests (offscreen platform), builds the Qt-free console
`polmon-backend.exe`, then embeds it in the one-file
`polmon-<version>-windows-x64.exe` with `packaging/windows/polmon.spec`. It then proves the EXE
starts Qt, not merely that it exits 0:

| Check | Pass condition |
|---|---|
| `--version` | prints exactly `polmon <version>` |
| `--self-test` | offscreen platform; lists the bundled `qwindows` and `qoffscreen` platform plugins; builds, renders and destroys the main window; `self-test: PASS` |
| `--smoke-start 3` | shows the real window on the runner desktop with platform `windows`, reports it visible and exposed |
| backend `--self-test` | loads uvicorn/FastAPI under PyInstaller and completes deploy → scenario → telemetry → report → reset |
| standalone backend | `polmon-backend.exe` started on its own (no client) serves a real L0 workflow over HTTP (`scripts/packaged-backend-smoke.sh` via Git Bash: deploy → scenario → telemetry → JSON/Markdown report → reset) and answers an L1 deploy with HTTP 422; then only its one-file launcher PID is killed and its Python child must log `launcher_exit` and `shutdown_cleanup` and leave by itself |
| client `--local-backend-self-test` | starts the embedded backend through the client manager, completes the real L0 HTTP workflow, verifies exact L1 refusal and reaps it |
| client `--local-backend-gui-probe` | drives the real main window off screen: Local preset connect, L1 refused by the backend (422) and in the UI (exact banner text, screenshot), then disconnect, backend killed and window closed |
| cleanup | after every exit path (normal stop, disconnect, backend killed, client killed with `os._exit`, window closed; one-file and portable) `tasklist /FI "IMAGENAME eq polmon-backend.exe"` must report no task; each result is kept in `windows-cleanup-proof.txt` |
| SHA-256 | written next to the EXE (`.exe.sha256`) |
| Start-up and memory | `scripts/measure-client.py` (3 launches, 10 s idle) uploaded as `windows-client-measurements` |

The same job also builds the **portable** one-folder client (`packaging/windows/polmon-portable.spec`)
and ships it as `polmon-<version>-windows-x64-portable.zip` (+ `.sha256`): unzip anywhere and run
`polmon-client.exe`; `polmon-backend.exe` is beside it. It contains the same runtime as the one-file EXE but starts without unpacking
them on every launch, so it opens several times faster (see RESOURCE-BUDGET.md). The zip is
extracted and put through the same `--version`, `--self-test` and `--smoke-start` checks, and both
forms are measured.

A second job on a fresh runner downloads the `polmon-windows-x64` artifact, checks its SHA-256 and
repeats the launches for both the EXE and the portable zip, so the uploaded files themselves are
what was verified.

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
.venv\Scripts\pyinstaller --clean --noconfirm packaging/windows/polmon-backend.spec
.venv\Scripts\pyinstaller --clean --noconfirm packaging/windows/polmon.spec
dist\polmon-<version>-windows-x64.exe --version
dist\polmon-<version>-windows-x64.exe --self-test
dist\polmon-<version>-windows-x64.exe --smoke-start 3
dist\polmon-<version>-windows-x64.exe --local-backend-self-test
```

Troubleshooting: a missing Qt platform plugin is the classic silent failure of packaged Qt
applications ("could not find the Qt platform plugin"); `--self-test` fails with the plugin
directory it inspected and the plugin names it expected. Check the exact Python version, delete
only the regenerable `build/` and `dist/` directories, and review PyInstaller's warnings file.

Release executables are accompanied by `SHA256SUMS.txt`; `scripts/verify-release.sh vX.Y.Z`
downloads a release and checks its assets' names, versions and hashes.
