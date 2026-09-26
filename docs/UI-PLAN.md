# Phase II plan: Qt desktop client and a fully exercised GitHub Actions pipeline

Status: plan, committed before implementation (operator mandate, sequence step 1). Target
release: **v0.2.0**, continuing SemVer from v0.1.3. This document is the design of record; where
the implementation deviates, the deviation is recorded here and in `CHANGELOG.md`.

## 1. Scope and decisions

| Decision | Choice | Reason |
|---|---|---|
| GUI toolkit | Qt 6 through **PySide6 6.11.2** (official Qt for Python, LGPLv3) | Operator-ordered. Real theming, model/view, HiDPI, cross-platform parity; LGPL is compatible with the stated commercial path, PyQt (GPL/commercial) is not. |
| Distribution package | `PySide6-Essentials==6.11.2` (pulls `shiboken6==6.11.2`) | `PySide6` is a meta-package = Essentials + Addons. The client needs only QtCore/QtGui/QtWidgets (Essentials, 80 MB wheel); Addons (175 MB: WebEngine, 3D, Charts, Multimedia, ...) is unused. Same project, same version, same license. |
| Where Qt is required | New optional extra `polmon[gui]` | The Linux backend runs on the 2 GB engineering budget and must not install ~300 MB of Qt. `polmon-client --version` works without Qt; any Qt-requiring path without the extra prints an actionable error. |
| Tkinter | **Removed** | Superseded by operator order. Removal is proven by a hygiene test (no `tkinter` import in tracked sources), and no Tk-only tooling remains. |
| `.ui` files | Not used | Widgets are built in code; no designer toolchain in CI. |
| HTTP stack in the client | Existing standard-library `ApiClient` (urllib), run on worker threads | Already hardened (timeouts, token handling, error documents); shared with `polmon-demo`. Qt's QtNetwork would add a second, asynchronous HTTP implementation for no gain. |

## 2. Backend API additions (no dead buttons)

The v0.1.3 API cannot back several required UI surfaces. These additions are made first, are
backward compatible (existing clients and `polmon-demo` keep working), and are documented in
`docs/API.md`:

| Surface | Addition |
|---|---|
| Topology inspection | `validate`/`load` responses gain `topology` (structured nodes, networks, interfaces, MAC, IPv4, class, services). `GET /v1/topologies` lists loaded topologies with estimate and deployment state; `GET /v1/topologies/{id}` returns one. |
| Scenario inspection | `POST /v1/scenarios/validate` returns the structured scenario (required topology, permitted actions, sequence, initial/success/failure conditions, timeout, cleanup policy) and, when the required topology is loaded, checks the scenario against it. |
| Live experiment status | `POST /v1/experiments` accepts `"wait": false`: preflight and admission run synchronously (so 422/429 still surface on the POST), then the run continues on a backend thread and the call returns HTTP 202. `GET /v1/experiments/{id}` reports `running` with progress (`completed_actions`, `total_actions`, `current_action`, `elapsed_seconds`). Observations are recorded to telemetry as each action finishes, not after the run. |
| Experiment browsing | `GET /v1/experiments` lists persisted experiments (SQLite), newest first, bounded. |
| Live telemetry stream | `GET /v1/experiments/{id}/telemetry?after=<sequence>&limit=<n>` for incremental polling. |
| Human-readable report | `GET /v1/experiments/{id}/report/markdown`. |
| Benchmarks | `POST /v1/benchmarks` starts one bounded job (explicit limits, capped by the backend's own admission limits, refused while an experiment or another job runs); `GET /v1/benchmarks/jobs/{id}` (progress parsed from the CLI's step output), `POST /v1/benchmarks/jobs/{id}/cancel` (SIGTERM to the job's process group, SIGKILL after a grace period), `GET /v1/benchmarks/results` and `GET /v1/benchmarks/results/{name}` for retained raw results. Jobs run the existing `polmon-benchmark` CLI in a subprocess, so the per-run worker isolation and limit checks are reused unchanged. |
| Shutdown | Active experiments are cancelled and joined before the shutdown reset; running benchmark jobs are terminated. |

## 3. Window and widget architecture

```
QMainWindow  "polmon 0.2.0 — connected to http://host:8080 (backend 0.2.0)"
├── toolbar: ConnectionBar  [URL][token ••••][timeout s][Connect/Disconnect]  ● health
├── central: QSplitter
│   ├── navigation list (Ctrl+1 … Ctrl+7)
│   └── QStackedWidget
│       ├── Overview      backend identity, limits, live counters, sparklines, activity
│       ├── Topologies    file/folder browser · YAML editor · inspection tree/tables · errors
│       ├── Deployment    deploy / destroy / reset · deployment details · resource counters
│       ├── Scenarios     browser · inspection (sequence, conditions, cleanup) · run / cancel
│       ├── Telemetry     experiment picker · live event table (filter) · capture summary
│       ├── Reports       experiment list · status badge · expected-vs-actual · Markdown · JSON
│       └── Benchmarks    parameter + limit form · run / cancel · retained results · detail
├── dock: Activity log (timestamped operations, outcomes, actionable errors)
└── status bar: connection LED · backend version · OperationProgress (percent, step n/N,
                elapsed, ETA, Cancel) · counters
```

Modules (all under `src/polmon/client/`):

| Module | Responsibility |
|---|---|
| `app.py` | Entry point: `--version` (no Qt import), `--self-test`, `--smoke-start`, `--url`, `--theme`. |
| `api.py` | Standard-library HTTP client (extended for the new routes; malformed/non-JSON responses become `ApiClientError`). |
| `errors.py` | Converts any exception into a short, actionable operator message (401, 413, 422 with field errors, 429 with each violated limit and its configured value, timeouts, refused connections, malformed responses). Never shows a traceback. |
| `tasks.py` | Threading: `TaskRunner` over a bounded `QThreadPool`; `Task` = function + `CancelToken`; results/errors/progress delivered to the GUI thread by queued signals. |
| `state.py` | `AppState(QObject)`: connection state machine and shared session data, emitting change signals. |
| `models.py` | Qt item models: telemetry table model (append-only, bounded) + filter proxy, generic key/value and record table models. |
| `theme.py` | Fusion style + light/dark `QPalette` + a small stylesheet; follows the OS colour scheme by default, toggled with Ctrl+Shift+T, persisted in `QSettings`. |
| `widgets/` | Reusable widgets: `ConnectionBar`, `OperationProgress`, `StatusBadge`, `Sparkline` (QPainter, no charting dependency), `CounterTile`, YAML editor with line numbers. |
| `pages/` | One module per page listed above. |
| `mainwindow.py` | Composition, menus, shortcuts, health polling, window-state persistence, About. |
| `selftest.py` | Headless self-test (section 6). |
| `screenshots.py` | Regenerates `docs/ui/*.png` from the real widgets. |
| `e2e.py` | Live end-to-end demonstration driver (section 8). |

The client never imports Linux networking or backend modules (enforced by the existing module
boundary tests plus a new import check).

## 4. Threading model

- The GUI thread only builds widgets, reads widget values, and applies results. Every HTTP call
  and every file read larger than a few kilobytes runs in a `QRunnable` on a `QThreadPool`
  capped at four threads. Widget values are captured on the GUI thread before the task starts.
- A task reports through a `QObject` signal carrier (`progress`, `succeeded`, `failed`,
  `finished`), connected with queued connections, so results always arrive on the GUI thread.
- Every task carries a `CancelToken`. Cancelling marks the token, drops the pending result, and
  immediately returns the UI to an idle state. Long operations are implemented as sequences of
  short calls (5 s default timeout) that check the token between calls, so cancellation takes
  effect within one call:
  - experiment: runs with `wait: false`; the task polls status and telemetry; Cancel sends
    `POST /cancel`, then waits for the backend to report the terminal state;
  - benchmark: job start + polling; Cancel sends the job cancel;
  - deployment: the backend call itself is not interruptible, so Cancel on a deploy marks the
    task "cancel and roll back": when the call returns, the task destroys the new deployment.
- Health polling runs every 3 s on the pool, never overlaps itself, and backs off after errors.
- Progress for anything that can exceed ~10 s shows percent, step n/N, elapsed, and ETA in the
  status-bar `OperationProgress`; nothing opens a blocking modal while work runs.

## 5. State handling

`AppState` holds: connection (`disconnected → connecting → connected | unauthorized | lost`),
backend identity (version), the last resource status, loaded topologies (source text, backend
validation result), the current scenario, the active experiment id, and the running benchmark
job. Pages subscribe to its signals and enable/disable actions from one place
(`MainWindow.refresh_actions`), so a button is enabled only when its operation can succeed
(for example, Run requires a connection, a validated scenario, and a deployed required topology).
If the backend dies mid-experiment, polling fails, the connection becomes `lost`, the experiment
is shown as "outcome unknown — backend unreachable", and actions are disabled until reconnect.
The token is held in memory only; URL, timeout, theme, window geometry and last folders are
persisted with `QSettings`.

## 6. Headless safety and self-test

`--self-test` forces `QT_QPA_PLATFORM=offscreen` before Qt is imported and never shows a window.
It verifies, printing one line per check: PySide6/QtCore/QtGui/QtWidgets import; the platform
plugin directory exists and contains the offscreen plugin and the native one for the OS
(`qwindows` / `qxcb`); a `QApplication` is constructed and reports platform `offscreen`; the
main window is built, rendered to an image off screen, and destroyed; the API client
configuration is sane (default URL parses, timeouts positive, token unset). `--version` keeps its
exact contract (`polmon <version>`). `--smoke-start SECONDS` is the packaged-build probe on a real
display: it shows the main window on the native platform (`windows` on the Windows runner, `xcb`
under Xvfb), processes events for the given time, reports the platform, and exits 0.

## 7. Theming, HiDPI, shortcuts

Qt 6 enables HiDPI scaling by default; the rounding policy is set to `PassThrough` for crisp
fractional scaling. Icons come from the style's standard pixmaps (no image assets to package).
Layouts are dense: splitters, tables with compact rows, no decorative chrome. Shortcuts: Ctrl+O
open topology, Ctrl+Shift+O open scenario, Ctrl+L focus URL, Ctrl+Return connect, F5 refresh,
Ctrl+Shift+V validate, Ctrl+D deploy, Ctrl+Shift+D destroy, Ctrl+Shift+R reset, Ctrl+R run
experiment, Esc cancel the running operation, Ctrl+1..7 pages, Ctrl+Shift+T theme, Ctrl+Q quit.

## 8. Evidence plan

| Evidence | How |
|---|---|
| `pytest-qt` suite marked `gui` | `tests/gui/`: widgets, error mapping, task cancellation, responsiveness (event loop keeps running while a slow backend stalls), real live-backend workflow. Linux CI: `xvfb-run` (platform `xcb`); Windows CI: `QT_QPA_PLATFORM=offscreen`. |
| Real screenshots | `python -m polmon.client.screenshots docs/ui` renders every page from the running widgets against a real in-process backend (L0 topology, rootless) on the offscreen platform. Committed PNGs; CI regenerates them as an artifact. |
| Live end-to-end demonstration | `python -m polmon.client.e2e --output-dir docs/ui/e2e` starts a real `polmon-backend` process with a token and drives the GUI through connect → validate → deploy → experiment → telemetry → report → reset by triggering the same actions a user clicks; writes the log, a JSON record and the report. The hybrid (L0+L1) variant runs when the privileged lab is available, otherwise it is reported NOT RUN. |
| Resource cost | Wheel size, installed size, cold start, idle RSS of the client measured and recorded in `RESOURCE-BUDGET.md`; Windows numbers from the runner. |
| Runner evidence | Run IDs, artifact names/sizes, SHA-256 values recorded in `docs/milestones/v0.2.0.md`. |
| Tk removal | `git grep` shows no `tkinter`; hygiene test enforces it. |

## 9. Packaging and CI plan

- **Windows** (`packaging/windows/polmon.spec`): one-file `polmon-<version>-windows-x64.exe`,
  PyInstaller's PySide6 hooks bundle the platform plugins; unused Qt modules are excluded. The
  console subsystem is kept so `--version`/`--self-test` work with exit codes in any shell; when
  the EXE is double-clicked (it owns its console) the console is released at GUI start.
- **Linux** (`packaging/linux/polmon-client.spec`): one-folder bundle
  `polmon-<version>-linux-x64/` packed as `polmon-<version>-linux-x64.tar.gz` with a `.sha256`;
  the wheel and the systemd unit are shipped alongside. Built on the oldest supported hosted
  Ubuntu image for the widest glibc compatibility. AppImage: not built unless it proves lean and
  reproducible; the decision and measured cost are documented.
- **Workflows** (actions pinned to commit SHAs, least-privilege `permissions`, concurrency
  groups, pip caching, explicit `timeout-minutes`, no secrets in PR builds):
  - `ci.yml`: matrix `ubuntu-latest` × `windows-latest` — Ruff, unit + integration tests, GUI
    tests (Xvfb / offscreen), smoke of every entry point (including the Qt self-test), coverage
    XML upload and a step summary; dependency audit; screenshot regeneration artifact.
  - `build-windows.yml`: build, verify bundled Qt plugins, `--version` (exact), `--self-test`,
    `--smoke-start` on the runner's desktop, upload; a second job on a fresh runner downloads the
    artifact, checks its SHA-256 and repeats the smoke tests.
  - `build-linux.yml` (new): build bundle + wheel, smoke under Xvfb, upload with SHA-256; a
    second job on a fresh runner downloads, verifies, and smoke-tests the bundle and the wheel.
  - `release.yml`: on tag, both builds, then one release with the EXE, the Linux tarball, the
    wheel, the systemd unit and `SHA256SUMS.txt`; a final job downloads the published release
    assets and smoke-tests them. The `workflow_dispatch` tag input stays, so an existing tag can
    be re-released without moving it.
  - `benchmark.yml` (optional): `workflow_dispatch`, small L0 sizes by default, heavy sizes
    opt-in.
- **Deployed means exercised**: each workflow is run on the hosted runners and fixed until green,
  including a real v0.2.0 release built on both platforms.

## 10. Sequence

1. This plan (committed first).
2. Backend API additions + tests.
3. Qt client, Tk removal, GUI tests, self-test.
4. Packaging specs; screenshots; live E2E demonstration; resource measurements.
5. Workflows; exercise on hosted runners until green; documentation (`ARCHITECTURE.md`,
   `CHANGELOG.md`, `RESOURCE-BUDGET.md`, `BUILD-WINDOWS.md`, `CI.md`, `RELEASE.md`, `README.md`).
6. `docs/milestones/v0.2.0.md` (section-10 format), annotated tag, tag-triggered release, release
   verification. Then self-directed improvement waves, each its own gated commit.
