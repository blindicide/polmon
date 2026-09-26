# Continuous integration

All workflows pin third-party actions to reviewed commit SHAs (Node 24 releases), declare
`permissions: contents: read` at the top level (release write access exists only in the release
job), use concurrency groups, cache pip downloads keyed on `pyproject.toml`, and set an explicit
`timeout-minutes` on every job. Checkouts do not persist credentials, and pull-request jobs receive
no repository secrets.

| Workflow | Trigger | What it proves |
|---|---|---|
| `ci.yml` | push to `main`, pull requests, manual | Matrix `ubuntu-latest` × `windows-latest`: Ruff; every entry point prints `polmon <version>`; `polmon-client --self-test`; rootless unit + integration tests; the `pytest-qt` GUI suite (Linux: `xvfb-run`, platform `xcb`; Windows: `QT_QPA_PLATFORM=offscreen`); the client on the native platform (`--smoke-start`); the small rootless benchmark (Linux). JUnit and combined coverage XML are uploaded per OS (`test-results-<os>`) and summarised in the run. A `UI screenshots` job renders every page from the running client against a real backend and runs the live end-to-end demonstration (artifact `ui-screenshots`). `dependency-audit` runs `pip-audit` over the pinned `dev`, `gui` and `build` sets. |
| `build-windows.yml` | manual, called by `release.yml` | See [BUILD-WINDOWS.md](BUILD-WINDOWS.md): Qt-bundled EXE, exact `--version`, self-test proving the `qwindows` plugin, native smoke start, SHA-256, start-up/memory measurement, and re-verification of the downloaded artifact on a fresh runner. Inputs `ref` and `pytest-deselect`. |
| `build-linux.yml` | manual, called by `release.yml` | See [BUILD-LINUX.md](BUILD-LINUX.md): bundle, reproducible tarball + SHA-256, wheel, systemd unit, smoke tests of the extracted bundle; a newer fresh runner re-verifies the artifact and installs the wheel. Input `ref`. |
| `release.yml` | `v*` tag push, manual repair | Both builds, one release with the EXE, Linux tarball, wheel, unit and `SHA256SUMS.txt`, then the published assets are downloaded from the release and smoke-tested on Windows and Linux. See [RELEASE.md](RELEASE.md). |
| `benchmark.yml` | manual | Bounded L0 benchmark (default 10 and 25 endpoints, 1 repeat; counts above 50 need the explicit `large` input), raw results as the `benchmark-results` artifact. Hosted-runner numbers characterise the runner, not the development host. |

Download artifacts from a run page (**Artifacts**) or with `gh run download <run-id> -n <name>`.
Test XML is uploaded even when a test step fails, so failures stay inspectable. Privileged
laboratory tests and large benchmarks never run on hosted runners: they need the authorised lab
host (`scripts/privileged-tests.sh`, `scripts/run-benchmarks.sh`).
