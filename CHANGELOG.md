# Changelog

All notable changes are documented here. Versions follow Semantic Versioning.

## [Unreleased]

## [0.4.0] - 2026-09-27

### Added

- **Russian user interface.** The desktop client is Russian by default; English is selectable at
  run time (*View → Language*, Ctrl+Shift+U, `--language`, `POLMON_LANGUAGE`) without a restart
  or lost state. Every user-visible string comes from a catalog (`polmon/client/locales/`); Qt's
  standard dialogs follow via `qtbase_ru.qm`, which the packaged clients now ship. The self-test
  checks both languages. Terms follow one glossary ([docs/UI-GUIDE.md](docs/UI-GUIDE.md)).
- **Stable message codes on backend errors** (approach (a), [ARCHITECTURE.md](ARCHITECTURE.md)):
  every error document adds `message_code` and `params` beside the unchanged English `message`;
  validation items, experiment errors, benchmark jobs and YAML errors carry codes as well
  ([docs/API.md](docs/API.md)). The client renders refusals — including the L0-only refusal of
  the local backend — in the UI language, never as raw backend text or a traceback.
- Translation gates on both CI platforms: `scripts/i18n-lint.py` rejects hard-coded
  user-facing literals in client code, `scripts/i18n-completeness.py` rejects incomplete or
  inconsistent catalogs, glossary variants and unused or missing keys. The GUI suite runs in
  Russian and in English and walks every screen across a runtime switch.
- [docs/UI-GUIDE.md](docs/UI-GUIDE.md): design tokens, spacing and type scales, components,
  glossary, usability floor and the screenshot inventory with before/after pairs.

### Changed

- **Interface redesign.** Design tokens for light and dark themes (one teal accent on slate
  neutrals, semantic status colours with soft surfaces, every text pair ≥ 4.5:1 and tested), a
  4-px spacing scale, a type scale and 28-px controls in a rewritten stylesheet; a dark
  navigation sidebar and a slim connection header; cards, aligned key/value grids and metric
  tiles; sortable tables with monospaced identifiers and status glyphs; empty, loading and error
  states for every view; a status-bar busy indicator; confirmed, visibly destructive actions;
  accessible names for every input; every page fits 1440×900 in both languages.
- Durations are shown with localized units (мс, с, мин, ч / ms, s, min, h).

## [0.3.2] - 2026-09-27

### Added

- `polmon-backend --data-dir PATH` chooses where telemetry, captures, reports and benchmark
  results go (default unchanged: `./var`). An unusable directory is a one-line error naming the
  path instead of a `PermissionError` traceback — e.g. the standalone Windows backend started
  from a read-only folder. The client passes its local data directory explicitly.
- Linux: with the client and backend tarballs extracted side by side, the packaged client's
  Local backend preset finds and owns the backend of its own version (it previously always
  reported "no backend beside it" on Linux). Build Linux runs the packaged client's local
  self-test, GUI probe and killed-client check against the packaged backend in that layout.

### Changed

- `scripts/ui_screenshots.py` no longer re-applies the theme after building the window, so the
  committed screenshots show exactly what a launch renders (the re-application had hidden the
  overlapping-sidebar bug fixed in v0.3.0); all 13 were regenerated from v0.3.1.
- `uv.lock` names the current version again (it said 0.2.3 through v0.3.1); a unit test keeps
  `uv.lock`, `pyproject.toml` and `polmon.version` in agreement.

## [0.3.1] - 2026-09-27

### Changed

- The Local backend keeps one persistent data directory (`<state>/polmon/data`), so local
  experiment history, reports and captures survive reconnects and restarts; per-start session
  directories now hold only the backend log, and the newest 20 are kept. Previously every
  connect started with an empty history and left a directory (up to the 1 GiB data limit each)
  that was never removed. Sessions from v0.3.0 that contain data are left untouched.

### Fixed

- Windows backends reported no host memory, which silently disabled the admission memory
  reserve on the local backend. They now report available physical memory
  (`GlobalMemoryStatusEx`) and lifetime CPU utilisation (`GetProcessTimes`); swap stays
  unreported on Windows (the page file is not swap) and the dashboard says "not reported by this
  host" instead of implying none is used.
- On Linux a local backend outlived a client that was killed (`SIGKILL`, crash): it runs in its
  own session and only Windows had a kill-on-close job, so it was reparented to init and kept
  serving. The client now holds a lifeline pipe on the backend's stdin (`--exit-with-stdin`);
  EOF — the client stopping it, or the OS closing the pipe when the client dies — shuts the
  backend down gracefully on every platform, so a normal stop on Windows also exits 0 instead of
  being terminated.

### Added

- Build Linux's fresh-runner job starts the bundled systemd user unit for real and drives the
  HTTP workflow through it. The README has a "Which download?" table.

## [0.3.0] - 2026-09-26

Phase III: self-contained backend artifacts and client-owned local execution.

### Added

- `DELETE /v1/topologies/{id}` forgets a loaded definition (refused while deployed); the
  Topologies page's *Loaded on backend* list gains *Unload*.
- Reports page: filter box over the experiment list. Dashboard: memory headroom and data
  directory tiles turn amber/red as they approach the reserve or limit.
- Qt-free PyInstaller backend executables for Windows and Linux. The Linux
  `polmon-backend-<version>-linux-x64.tar.gz` runs with no Python/pip/venv; a second systemd unit
  targets the extracted bundle. Uvicorn's dynamic imports are explicit, and `--self-test` loads
  the application graph and completes a real L0 experiment/report/reset.
- The client connection bar defaults to **Local backend (L0 only)** on Windows (Linux retains its
  remote-backend default). It selects a free loopback port, starts the bundled backend off the GUI
  thread with an ephemeral token and owned process group, captures a user-openable log, detects
  child death, and reaps on disconnect/exit. Windows adds a kill-on-close Job Object for abrupt
  client crashes; an executable override supports development and custom layouts.
- Packaged acceptance probes: Windows runs the real owned L0 HTTP workflow and exact L1 refusal
  from both client forms, plus normal/backend-killed/client-crashed orphan checks. Linux starts the
  extracted backend under `env -i`, performs the real HTTP workflow, and passes or cleanly refuses
  a readiness-gated L1 deployment. A real connected Local-backend screenshot is committed.

### Changed

- Windows backends are authoritatively L0-only. Health/resources publish `l0_only` versus
  `linux_lab`; both UI and API refuse L1/L2 with the Linux namespace-host requirement and never
  silently degrade. Linux probes tools/privileges before constructing an L1/hybrid backend.
- Windows portable archives place `polmon-client.exe` and `polmon-backend.exe` side by side; the
  one-file client embeds the same independently built backend. Release notes and artifacts state
  fidelity explicitly. Unsigned/SmartScreen reality is documented.

### Fixed

- Packaged Windows backend `--self-test` failed with `WinError 32`: the control plane never
  closed its SQLite telemetry handle, so the temporary directory could not be removed. The
  handle is now released (`ControlPlane.close()`), and importing `polmon.backend` no longer
  creates `./var` (the default ASGI app is built on first use).
- Killing the one-file `polmon-backend.exe` launcher (e.g. `Stop-Process`) left its Python child
  serving. The child now watches its launcher and shuts down gracefully when it disappears; the
  client also reaps a dead local backend immediately.
- Sidebar entries overlapped on a normal launch (rows laid out 14 px apart, drawn 30 px tall)
  because rows were added before the themed list was polished.
- Build artifacts mixed `dist/` files with root-level evidence, so the uploaded artifact kept a
  `dist/` prefix and the verify/release jobs could not find the files; evidence now has its own
  artifacts. Packaged backend RSS is read from the backend itself (the launched Windows PID is
  the one-file bootloader).

## [0.2.3] - 2026-09-26

Capture download, workflow shortcuts and the operator guide.

### Added

- Operator guide for the desktop client (`docs/CLIENT.md`); its shortcut table is kept identical
  to the in-app list by a test.
- `GET /v1/experiments/{id}/capture` serves the finished experiment's bounded PCAP, and the
  Telemetry page gains *Save capture…* to open it in Wireshark or tcpdump on the workstation.
- Scenarios page: *Deploy required topology* when the scenario's topology is loaded but not
  deployed. Deployments show an ETA from measured per-namespace creation cost until the client
  has observed the backend's own deployment times.
- The backend CPU tile shows current load (CPU-seconds delta between polls) with the lifetime
  average as secondary information.

## [0.2.2] - 2026-09-26

Robustness and usability waves after v0.2.1.

### Added

- Accessible names for every input, editor, table and list of the client (explicit for the
  connection bar and editors, derived from tooltips, placeholders, form labels and table headers
  elsewhere), enforced by a GUI test across all pages.
- Finished experiments and benchmark jobs are announced in the status bar and, when the window is
  not focused, with a task-bar alert; Telemetry and Reports explain what to do when empty.
- YAML syntax highlighting in the topology and scenario editors (keys, comments, strings,
  scalars, list markers), following the light/dark theme.

### Changed

- The client connects to pre-v0.2.0 backends instead of refusing: routes they lack (topology and
  experiment listing, scenario validation, Markdown report, benchmark jobs) degrade to a single
  "Older backend" warning naming the missing features; deployments the client loads stay
  tracked and the Reports page works without the Markdown route.
- The backend keeps at most 256 finished experiments in memory with full detail; older ones are
  served from SQLite (`persisted: true`), so a long-running backend no longer grows without
  bound.

## [0.2.1] - 2026-09-26

Improvement waves after v0.2.0: faster Windows start, smaller Linux bundle, client conveniences.

### Added

- Portable Windows client `polmon-<version>-windows-x64-portable.zip` (one-folder build) next to
  the one-file EXE: it does not unpack itself on every launch, so it starts much faster. Built,
  smoke-tested, re-verified on a fresh runner, released and verified after publication like the
  EXE; `scripts/verify-release.sh` requires it from v0.2.1.
- Client: Ctrl+S saves the topology or scenario being edited (with an unsaved-changes marker; the
  Scenarios page gains *Save as…*), *Export CSV…* writes the telemetry events currently shown
  (filters applied), and the last page is restored on start.
- `polmon-client --install-desktop-entry` (Linux): per-user menu entry and icon (XDG) for the
  extracted bundle or a pip installation; exercised by the Linux build.
- The backend URL field remembers the last eight backends connected to (editable drop-down).
- Application icon, drawn with QPainter (no binary asset): window and task-bar icon on both
  platforms, embedded in the Windows executables at build time (`python -m polmon.client.icon`).

### Changed

- The Linux bundle is stripped of debug symbols; the hosted runners' Python ships `libpython`
  with debug information (28.7 MB instead of 8.6 MB).

## [0.2.0] - 2026-09-26

Phase II: a Qt desktop client for Windows and Linux, and a CI/CD pipeline that tests, packages,
verifies and releases both platforms (operator mandate; design in `docs/UI-PLAN.md`).

### Added

- Qt (PySide6) desktop client `polmon-client`, one code base for Windows and Linux: dashboard with
  live resource counters and admission limits; topology library, YAML editor, backend validation
  with errors mapped to YAML lines, node/interface/MAC/IPv4 inspector and admission fit;
  deployment control (deploy with cancel-and-roll-back, destroy, reset); scenario inspection and
  experiments with live per-action status, percent/step/elapsed/ETA progress and graceful cancel;
  a live, filterable telemetry stream with capture summary; reports (overall status, expected vs
  actual, observations, Markdown, JSON, save); bounded benchmark jobs with explicit limits and
  retained results. All I/O runs off the GUI thread; light/dark themes, HiDPI, keyboard
  shortcuts, persisted settings; the API token stays in memory only.
- `polmon-client --self-test` verifies Qt, the bundled platform plugins, the main window and the
  API client on the offscreen platform without opening a window; `--smoke-start SECONDS` shows the
  real window on the native platform and reports start-up time and idle memory.
- Backend API (additive): structured topology inspection and listing, scenario validation against
  the loaded topology, experiments that return once admitted (`"wait": false`) with live progress,
  observations recorded as they happen, telemetry paging (`after`, `limit`), experiment listing
  across restarts, the Markdown report route, and bounded benchmark jobs
  (`/v1/benchmarks`) that run the unchanged CLI with limits capped by admission control.
- `pytest-qt` GUI suite (`tests/gui`, marker `gui`) against real in-process backends, including
  unreachable, slow, malformed, unauthorised, rejecting and dying backends.
- Linux client bundle (`polmon-<version>-linux-x64.tar.gz`, built on ubuntu-22.04) next to the
  wheel and the systemd unit; `BUILD-LINUX.md`.
- `scripts/ui_screenshots.py` (real renders in `docs/ui/`), `scripts/ui_e2e.py` (live
  end-to-end demonstration through the client), `scripts/measure-client.py`, the rootless
  `l0-office` example pair, and `scripts/privileged-tests.sh -- COMMAND`.
- Workflows: CI matrix on `ubuntu-latest` and `windows-latest` with GUI tests under Xvfb and
  offscreen, `build-linux.yml`, fresh-runner re-verification of both build artifacts, release
  assets for both platforms with a post-publication download-and-smoke job, and a manual
  `benchmark.yml`.

### Changed

- **Tkinter client replaced by Qt** (operator-ordered deviation from the specification's Tkinter
  baseline; rationale in `ARCHITECTURE.md`). PySide6-Essentials 6.11.2 (LGPLv3) is the new
  optional `gui` extra; the backend install does not need it. Measured cost in
  `RESOURCE-BUDGET.md`.
- PyInstaller 6.22.3 with pyinstaller-hooks-contrib 2026.7; the Windows spec bundles a pruned Qt
  plugin set and proves the `qwindows` plugin in the packaged self-test.
- GitHub Actions upgraded to Node 24 releases (checkout v7.0.1, setup-python v7.0.0,
  upload-artifact v7.0.1, download-artifact v8.0.1), still pinned by commit SHA; every job has
  an explicit timeout, workflows have concurrency groups and pip caching.
- Experiment identifiers are unique across backend restarts; the backend cancels and joins
  active experiments and stops benchmark jobs before its shutdown reset.
- The TAP responder is woken through a self-pipe on stop, so teardown no longer waits for its
  poll interval, and the idle poll lengthens from 0.1 s to 1 s (fewer idle wake-ups). Measured
  target teardown median 0.191 s → 0.133 s (`benchmarks/results/SUMMARY-wave19-responder-wake.md`).

### Removed

- The Tkinter client, its tests and the `tkinter` hidden import; a hygiene test keeps Tk out of
  code and packaging.

### Fixed

- A cancel request that reached the backend before the experiment thread started was cleared by
  the run; the engine is fresh per experiment and is no longer reset.
- Reusing an experiment identifier from an earlier backend process failed inside SQLite instead
  of returning a clear HTTP 422.

## [0.1.3] - 2026-09-26

Windows client fixes found by driving the real GUI on Windows and Linux.

### Added

- GUI tests drive the real Tk client against a live, token-protected backend (connect, validate,
  deploy, run experiment, reset; offline error handling). CI runs them under Xvfb.
- CI `dependency-audit` job: `pip-audit` over the installed, pinned dependency set on every push.

### Fixed

- The Windows client read Tk variables from its worker thread when validating, deploying, or
  running experiments ("main thread is not in main loop"); the API client is now built on the UI
  thread. The API token field moved next to the backend URL.
- On Windows, a request with a wrong or missing token failed with `WinError 10053` instead of
  HTTP 401, because the backend answered before reading the body; the backend now discards the
  bounded body first, and the client wraps connection-level errors in `ApiClientError`.

## [0.1.2] - 2026-09-26

Hardening, security, and bidirectional hybrid networking after v0.1.1.

### Added

- Hybrid networking is bidirectional: a per-TAP responder answers ARP and ICMP echo for L0
  endpoints, so L1 namespaces can resolve and ping L0 endpoints with the kernel's own tools.
  Scenario actions L1→L0 ICMP are now executed (path `l1->l0`) instead of reported unsupported;
  TCP to or from L0 remains unsupported. The MVP scenario gains a `server-to-sensor` probe.
- `polmon-benchmark --settle-seconds` pauses between runs; recorded in the workload.
- Admission-estimate calibration against measurements and an L1 scaling study (2/4/8 namespaces)
  in RESOURCE-BUDGET.md.
- Storage admission: experiments are refused (HTTP 429) when the data directory would exceed
  `--max-data-mb` or free disk would fall below `--disk-reserve-mb`; artefacts are never deleted
  automatically. `GET /v1/resources` reports `data_directory_bytes`.
- `polmon-diagnostics --lab`: read-only privileged-lab readiness checks with a non-zero exit
  status when the host is not ready.
- Operator runbook (`docs/OPERATIONS.md`) and an example systemd user unit
  (`packaging/linux/polmon-backend.service`).
- Rootless tests of the complete L0→L1 ARP/ICMP exchange across the TAP against a simulated L1
  peer (including unrelated frames on the bridge, timeouts, and unknown sources).

### Changed

- Hybrid TAP setup and teardown run as one privileged `ip` batch each; TAP names are owned before
  creation, and a pre-existing interface with a generated TAP name is refused instead of adopted.

### Fixed

- Scenario `initial_conditions` were parsed but never checked, so a scenario declaring
  `services_started` ran against dead services. The control plane now verifies each declared
  condition against the live deployment before the first action; unmet or unverifiable conditions
  fail the experiment without running actions.

### Security

- Dependency audit (`pip-audit`) found 8 advisories in the pinned starlette 0.41.3 (multipart
  spooling, `FileResponse` Range, Host/path URL reconstruction, `StaticFiles`, `HTTPEndpoint`,
  urlencoded form limits) and one in pytest 8.3.4. polmon uses none of the affected starlette
  features, but the stack is upgraded anyway: FastAPI 0.141.1, starlette 1.7.0 (now pinned
  explicitly), uvicorn 0.54.0, pydantic 2.13.5, PyYAML 6.0.3, pytest 9.1.1, pytest-cov 7.1.0.
  `pip-audit` reports no known vulnerabilities afterwards.
- ICMP probes, ping statistics, and TCP probes inside lab namespaces ran as root; they now run as
  the invoking user through `setpriv` like the built-in services (`ping` keeps working through its
  `cap_net_raw` file capability), and the probe interpreter runs isolated (`-I -S`).
- SECURITY.md now states plainly that `sudo ip` is root-equivalent in the Phase I privilege model.

## [0.1.1] - 2026-09-26

Security and hardening release after the Phase I MVP.

### Added

- Optional bearer-token API authentication (`POLMON_API_TOKEN` / `--api-token-file`, owner-only
  file, ≥ 24 characters, constant-time comparison, checked before the body is read). The backend
  refuses to listen on a non-loopback address without a token. The Windows client gains an API
  token field (memory only), `ApiClient` a `token` argument, and `polmon-demo` authenticates every
  local run with a fresh random token.

### Changed

- L1 deployment runs one privileged `ip -batch` on the host plus one per namespace instead of about
  ten `sudo ip` calls per namespace; teardown is a single forced batch. Measured on the development
  host (5 repeats, `benchmarks/results/SUMMARY-wave4-batched-ip.md`): 2-namespace creation median
  1.321 s → 0.184 s, teardown 0.119 s → 0.087 s; 50 L0 + 2 L1 deployment 1.493 s → 0.453 s.

### Security

- The built-in L1 `static_http` service ran `python -m http.server` in the backend's working
  directory and listed it — including `.git/`, `.venv/`, reports, and telemetry — to every lab
  peer. It is now a standalone standard-library responder that returns a fixed body, never touches
  the filesystem, bounds request size, time, and concurrency, and runs in an isolated interpreter
  (`python -I -S`). `static_http` declared with a non-TCP protocol is rejected.
  Measured side effect (`benchmarks/results/SUMMARY-wave5-static-http.md`): service tree RSS
  26.6 → 19.4 MiB per service; 50 L0 + 2 L1 attributed memory 54.5 → 39.1 MiB.

### Fixed

- Rollback leaked a host veth pair whose peer had not yet moved into its namespace.
- Deployment now refuses when an object with a generated name already exists, instead of adopting
  it and deleting it on rollback.

- A hung privileged command raised `TimeoutExpired`, which could abort best-effort teardown midway
  or crash a probe; timeouts now return exit code 124 (or raise a clear error when checked).
- Oversized request bodies were read and parsed before model limits applied; bodies above 5 MiB,
  including chunked uploads, are now refused with HTTP 413 before parsing.
- The privileged host-network guard compared nft set contents, so fail2ban adding a ban during a
  run was reported as a host change; it now compares ruleset structure (`nft -s -t`).
- Client errors embedded the server's error document as a Python dict repr; `ApiClientError` now
  states the HTTP status, error code, and message, and exposes `status`, `code`, and `details`.

### Added

- Tests for the topology CLI, client error handling against a live backend, and UTF-8 JSON logs.

## [0.1.0] - 2026-09-26

Phase I MVP.

### Added

- `polmon-demo`: the Phase I target demonstration over the HTTP API — 50 L0 sensors and two L1
  service endpoints on one isolated network, a controlled reconnaissance experiment, telemetry and
  PCAP capture, JSON/Markdown report, reset, and independent kernel-level cleanup verification.
- `examples/topologies/mvp-demo.yml` and `examples/scenarios/mvp-recon.yml`.
- `docs/DEMO.md` and recorded demonstration evidence in `docs/demo/`.

### Fixed

- Telemetry resource samples reported zero active endpoints and namespaces during experiments; they
  now carry live counts and the topology deployment time (also in `GET /v1/resources` and
  deployment status).
- Reports rendered a failure condition that correctly did not fire as `MISMATCH`; comparisons now
  carry a role and outcome (`met`/`not_met`, `triggered`/`not_triggered`).

## [0.0.15] - 2026-09-26

Release candidate: feature freeze, audits, and corrections found by release testing.

### Added

- Experiments on hybrid L0/L1 deployments: L0→L0 and L0→L1 ICMP use the synthetic engine and the
  shared TAP, L1→L1 uses the kernel; L1→L0 and L0-sourced TCP are reported as `unsupported`.
  Boundary frames are written to the experiment capture. (Required by the v0.1.0 demonstration.)

### Fixed

- Path-like experiment/topology identifiers returned HTTP 500; they are now rejected with 422 at the
  API boundary, and the report writer and reader refuse them independently.
- Stopping the backend with SIGINT/SIGTERM left deployed namespaces, bridges, veths, and services
  behind; graceful shutdown now tears down every deployment and logs the result.
- A benchmark run that hit its time limit was SIGKILLed before its teardown; it now receives
  SIGTERM with a grace period. `lab-cleanup.sh` also stops processes inside leftover namespaces.
- Topology subnets outside RFC 1918 / RFC 2544 laboratory ranges were accepted; they are rejected.

### Removed

- The obsolete v0.0.2 privileged placeholder test that reported a misleading skip.
- `INSTRUCTION.md` from version control (operator instructions are not repository content; the
  file remains in history and on the operator's disk).

## [0.0.14] - 2026-09-26

### Added

- `polmon-benchmark` with L0 (10/25/50, explicit `--large` 100/250), L1 namespace, and Phase I
  target (50 L0 + 2 L1) benchmarks, admission-checked and time/memory-bounded per run, each in a
  fresh worker process, retaining raw JSON/CSV with host, workload, limits, and source commit.
- Generated Markdown summaries, `tests/performance/`, and the first recorded results.
- Helper scripts: `check.sh`, `privileged-tests.sh`, `lab-cleanup.sh`, `run-benchmarks.sh`,
  `verify-release.sh`.

### Fixed

- Synthetic endpoints stopped answering after 256 received frames because delivered frames were
  never consumed from their bounded receive queues (latent since 0.0.6).

## [0.0.13] - 2026-09-26

### Added

- Pre-deployment endpoint, namespace, and available-memory admission with detailed HTTP 429 errors.
- Configurable concurrency, capture, duration, and host-memory reserve limits through API policy and
  backend CLI flags.
- Runtime resource sampling, cooperative automatic/manual cancellation, and resource status API.
- Release workflow `workflow_dispatch` repairs build the pinned tag's own source, reject a
  mismatched executable version, and attach `SHA256SUMS.txt`.

### Fixed

- Hybrid L0-to-L1 traffic could lose its first ARP frame while the TAP bridge port was still
  disabled after attach; deployment now waits for every bridge port to forward (latent since 0.0.8).

## [0.0.12] - 2026-09-26

### Added

- Atomic JSON and Markdown reports with normalized inputs, observations, condition comparisons,
  errors, resource samples, capture statistics, status, timestamps, and version.
- Process-wide reset API that preserves topology definitions for repeatable deployment.
- Exception-path telemetry closure and best-effort recovery that retains failed teardown state.

## [0.0.11] - 2026-09-26

### Added

- Versioned FastAPI contracts for topology, deployment, experiment, status, telemetry, and reset.
- Stateful Linux control plane connecting validated models to L0/L1/hybrid backends and telemetry.
- Responsive Tkinter client with background HTTP operations, explicit timeouts, and useful errors.

## [0.0.10] - 2026-09-26

Release note: the `v0.0.10` tag's own release run (36238266300) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36241102476, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36238264377). See `docs/milestones/v0.0.10.md`.

### Added

- SQLite experiment metadata and ordered structured events with secret-key redaction.
- Resource samples and bounded classic PCAP capture with drop/truncation accounting.
- Foreign-key association and tcpdump interoperability coverage.

## [0.0.9] - 2026-09-26

Release note: the `v0.0.9` tag's own release run (36238094325) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36241097856, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36238093059). See `docs/milestones/v0.0.9.md`.

### Added

- Strict topology-bound scenario YAML with closed ICMP/TCP probe actions and declared targets.
- Deterministic sequence execution, deadlines, cancellation, conditions, observations, and cleanup.
- Controlled reconnaissance example and invalid/preflight/failure-path tests.

## [0.0.8] - 2026-09-26

Release note: the `v0.0.8` tag's own release run (36237923759) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36241093673, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36237921993). See `docs/milestones/v0.0.8.md`.

### Added

- One shared TAP per hybrid network connecting the synthetic engine to isolated Linux bridges.
- Cross-boundary ARP and ICMP echo with bounded raw-frame capture and deterministic teardown.
- Unit command-plan and real privileged L0-to-L1 integration coverage.

## [0.0.7] - 2026-09-26

Release note: the `v0.0.7` tag's own release run (36237741029) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36240994208, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36237739216). See `docs/milestones/v0.0.7.md`.

### Added

- Linux namespace backend with isolated bridges, veth interfaces, addressing, and direct routing.
- Predefined lightweight HTTP service lifecycle and connectivity probes.
- Narrow privileged command boundary, deterministic teardown, unit command-plan checks, and opt-in
  real namespace integration coverage.

## [0.0.6] - 2026-09-26

### Added

- Validated Ethernet II, ARP, minimal IPv4, and ICMP echo packet codecs.
- Deterministic synthetic address resolution and ping exchange with bounded frame capture.
- Known-byte fixtures for Internet, IPv4, and ICMP checksum validation.

## [0.0.5] - 2026-09-26

### Added

- Shared-process L0 endpoint registry with unique instance, MAC, and IPv4 identities.
- Bounded virtual networks, packet queues, deterministic event scheduling, and resource accounting.
- Synthetic orchestration backend and repeated 50-endpoint lifecycle coverage.

## [0.0.4] - 2026-09-26

### Added

- Backend-neutral execution interface and explicit topology lifecycle state machine.
- Process-wide resource ownership tracking, atomic create rollback, and idempotent cleanup.
- Failure-injectable mock backend and comprehensive transition/failure tests.

## [0.0.3] - 2026-09-26

### Added

- Strict YAML topology model with nodes, networks, interfaces, resources, and safe service metadata.
- Duplicate, overlap, address-conflict, and unsupported-configuration validation.
- Stable serialization, privilege-free resource estimation, inspection CLI, and hybrid example.

## [0.0.2] - 2026-09-26

### Added

- Secret-free environment diagnostics and process/system resource snapshots.
- Structured JSON logging, backend startup resource events, and consistent public API errors.
- Explicit integration and privileged markers, coverage XML, JUnit artifacts, and CI summaries.

## [0.0.1] - 2026-09-26

### Added

- Python project foundation with FastAPI backend and standalone Tkinter client.
- Headless `--version` and `--self-test` client commands.
- Linux CI, GitHub-hosted Windows packaging, executable smoke validation, and release automation.
- Initial test suite and development, architecture, security, resource, build, CI, and release docs.
