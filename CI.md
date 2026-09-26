# Continuous integration

All workflows pin third-party actions to reviewed commit SHAs (Node 24 releases), declare
`permissions: contents: read` at the top level (release write access exists only in the release
job), use concurrency groups, cache pip downloads keyed on `pyproject.toml`, and set an explicit
`timeout-minutes` on every job. Checkouts do not persist credentials, and pull-request jobs receive
no repository secrets.

| Workflow | Trigger | What it proves |
|---|---|---|
| `ci.yml` | push to `main`, pull requests, manual | Matrix `ubuntu-latest` × `windows-latest`: Ruff; every entry point prints `polmon <version>`; `polmon-client --self-test`; rootless unit + integration tests; the `pytest-qt` GUI suite (Linux: `xvfb-run`, platform `xcb`; Windows: `QT_QPA_PLATFORM=offscreen`); the client on the native platform (`--smoke-start`); the small rootless benchmark (Linux). JUnit and combined coverage XML are uploaded per OS (`test-results-<os>`) and summarised in the run; on Linux the combined line coverage of the rootless and GUI runs must stay at or above 80 % (`--cov-fail-under=80`; 84 % at v0.2.1). A `UI screenshots` job renders every page from the running client against a real backend and runs the live end-to-end demonstration (artifact `ui-screenshots`). `dependency-audit` runs `pip-audit` over the pinned `dev`, `gui` and `build` sets. |
| `build-windows.yml` | manual, called by `release.yml` | See [BUILD-WINDOWS.md](BUILD-WINDOWS.md): Qt client plus Qt-free backend, backend graph self-test, owned L0 workflow and L1 refusal from both packaged client forms, normal/killed/crashed cleanup proofs, native Qt smoke, measurements, hashes, then fresh-runner re-verification. Inputs `ref` and `pytest-deselect`. |
| `build-linux.yml` | manual, called by `release.yml` | See [BUILD-LINUX.md](BUILD-LINUX.md): client and no-Python backend bundles, reproducible tarballs + SHA-256, wheel and both systemd units; `env -i` backend execution, real L0 HTTP workflow, L1 capability/pass-or-clean-refusal evidence, then fresh-runner re-verification. Input `ref`. |
| `release.yml` | `v*` tag push, manual repair | Both builds, all Windows/Linux client and backend forms, wheel, units and `SHA256SUMS.txt`, then published assets are downloaded and smoke-tested on Windows and Linux. Release notes state the fidelity boundary. See [RELEASE.md](RELEASE.md). |
| `benchmark.yml` | manual | Bounded L0 benchmark (default 10 and 25 endpoints, 1 repeat; counts above 50 need the explicit `large` input), raw results as the `benchmark-results` artifact. Hosted-runner numbers characterise the runner, not the development host. |

On Windows the GUI suite runs with `--no-qt-log`: with both pytest's output capture and pytest-qt's
capture of Qt log messages active, the test interpreter aborts natively on the hosted Windows
runner, while either capture alone passes all GUI tests (isolated in diagnostic run 36260679968; the
client is unaffected). Qt messages are then printed instead of attached to test reports.

Download artifacts from a run page (**Artifacts**) or with `gh run download <run-id> -n <name>`.
Test XML is uploaded even when a test step fails, so failures stay inspectable. The Linux build
performs a bounded readiness-gated two-node L1 probe; the full privileged suite and large
benchmarks remain explicit lab-host work (`scripts/privileged-tests.sh`,
`scripts/run-benchmarks.sh`).
