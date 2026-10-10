# Windows build

GitHub Actions is the authoritative Windows build environment. Dispatch **Build Windows** on
the Phase VI branch to build and test a one-file client and a portable one-folder client. Both
client executables embed the L0 backend, SQLite, and the Qt runtime. Neither distribution ships
`polmon-backend.exe` or needs a Python installation.

The job installs Python 3.12 and the pinned development, GUI, and build dependencies, runs Ruff,
rootless tests, and offscreen GUI tests, then builds `packaging/windows/polmon.spec` and
`packaging/windows/polmon-portable.spec`. Each artifact is exercised with `--version`, Qt
`--self-test`, native-window `--smoke-start 3`, embedded-backend `--diagnostics`, and
`--local-backend-self-test`. The latter starts the client's own backend process, opens SQLite,
completes a real L0 deploy-to-reset workflow, confirms L1/L2 refusal, and reaps the child.
GUI lifecycle and simulated client-crash probes check cleanup. A fresh Windows runner downloads
both artifacts, checks their SHA-256 hashes, and repeats the startup and embedded-L0 checks.

| Asset | Contents |
|---|---|
| `polmon-<version>-windows-x64.exe` | One-file client; extracts its own runtime at launch |
| `polmon-<version>-windows-x64-portable.zip` | One-folder client; starts without extraction |

The console subsystem stays enabled so command-line diagnostics return visible output and exit
codes. L1/L2 require a remote Linux laboratory backend; Windows local mode is L0 only.
Unsigned binaries may trigger SmartScreen.

For a manual native Windows build:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,gui,build]"
.venv\Scripts\pyinstaller --clean --noconfirm packaging/windows/polmon.spec
.venv\Scripts\pyinstaller --noconfirm packaging/windows/polmon-portable.spec
dist\polmon-<version>-windows-x64.exe --local-backend-self-test
dist\polmon-<version>-windows-x64-portable\polmon-client.exe --local-backend-self-test
```

A missing Qt platform plugin causes `--self-test` to fail with the inspected plugin directory.
The produced files have not been published as a Phase VI release.
