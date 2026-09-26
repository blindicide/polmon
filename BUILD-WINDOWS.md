# Windows build

GitHub Actions is the authoritative Windows build environment. Run **Build Windows** manually or
push a release tag. The job installs Python 3.12 and pinned build dependencies, runs Ruff and
pytest, builds `polmon-<version>-windows-x64.exe`, then executes `--version` and `--self-test`.

For a manual native Windows build (never Wine/emulation):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,build]"
.venv\Scripts\pyinstaller --clean --noconfirm packaging/windows/polmon.spec
dist\polmon-0.0.1-windows-x64.exe --self-test
```

Troubleshoot by checking the exact Python version, deleting only regenerable `build/` and `dist/`
directories, and reviewing the PyInstaller warnings file. A successful build is not sufficient:
both executable smoke commands must exit zero.

