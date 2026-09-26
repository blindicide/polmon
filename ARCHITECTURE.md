# Architecture

The control plane is a Python 3.12 package. FastAPI exposes backend services while the Qt desktop
client communicates only through documented HTTP contracts. Execution backends sit behind an
orchestration interface: shared-process L0 endpoints, Linux namespace L1 endpoints, and a future
KVM-compatible L2 adapter. SQLite stores bounded experiment metadata; YAML is the declarative
input format.

Dependencies point inward: GUI and API depend on control-plane models, while synthetic and Linux
networking implementations never depend on the GUI. This keeps Windows packaging independent of
Linux facilities and permits unit testing without privileges.

The orchestration layer owns lifecycle state and resource claims; backends own implementation
details. This separation lets the mock backend test rollback and legal transitions while later L0,
L1, and L2 implementations share the same control-plane contract.

`polmon.benchmarks` sits outside the control plane: it drives the same orchestrator and backends
through admission-checked, time- and memory-bounded runs, each in a fresh worker process, and
writes raw JSON/CSV results. Nothing in the control plane, API, or client imports it; the API's
benchmark jobs run the `polmon-benchmark` command as a subprocess.

`polmon.demo` is a client of the HTTP API only: it drives the documented contract with the same
`ApiClient` as the desktop client and verifies cleanup independently through the kernel's view.

## Desktop client (Qt)

`polmon.client` is one PySide6 (Qt 6, LGPLv3) code base for Windows and Linux; its design of
record is [docs/UI-PLAN.md](docs/UI-PLAN.md). It replaced the Phase I Tkinter client by operator
order (Phase II mandate). The deviation from the Tkinter baseline of the specification is
deliberate: Qt provides real theming (light/dark palettes), model/view classes for large live
tables (the telemetry stream), HiDPI scaling, non-blocking widgets with thread-safe signal
delivery, and the same look and behaviour on both platforms. PyQt was rejected because its
GPL/commercial licence conflicts with the commercial path; PySide6 is LGPLv3. Only the
`PySide6-Essentials` subset (QtCore, QtGui, QtWidgets) is used, as the optional `gui` extra, so the
backend install stays free of Qt. Its measured cost is in [RESOURCE-BUDGET.md](RESOURCE-BUDGET.md).

```
MainWindow ── ConnectionBar, navigation, 7 pages, activity dock, status bar (OperationProgress)
   │ reads/writes            ▲ signals (GUI thread)
   ▼                         │
Session (state) ◄── Context.run(work) ── TaskRunner (QThreadPool, ≤4 threads)
                                              │ worker threads only
                                              ▼
                                      ApiClient (urllib, timeouts) ──HTTP──► backend /v1
```

The GUI thread never performs I/O: every HTTP call runs on the pool and returns through queued
signals of a GUI-thread `TaskHandle`. Long operations (deploy, experiment, benchmark) run as
sequences of short calls that check a cancel token, report percent/step/elapsed/ETA, and are
cancellable (experiments and benchmark jobs are cancelled on the backend). A 3-second health poll
tracks the connection (`connected`, `unauthorized`, `lost`) and refreshes resources, topologies and
deployments. The client imports no backend implementation module (enforced by a test); the
backend gained additive routes for inspection, live experiment progress, telemetry paging, the
Markdown report and bounded benchmark jobs ([docs/API.md](docs/API.md)).
