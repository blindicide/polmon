# Architecture

The control plane is a Python 3.12 package. FastAPI exposes backend services while the Qt desktop
client communicates only through documented HTTP contracts. Execution backends sit behind an
orchestration interface: shared-process L0 endpoints, Linux namespace L1 endpoints, and a future
KVM-compatible L2 adapter. SQLite stores bounded experiment metadata; YAML is the declarative
input format.

Dependencies point inward: GUI and API depend on control-plane models, while synthetic and Linux
networking implementations never depend on the GUI. This keeps Windows packaging independent of
Linux facilities and permits unit testing without privileges.

## Self-contained execution and fidelity

The backend has two explicit fidelity policies. `linux_lab` permits L0 and, after a read-only host
capability probe, Linux namespace L1 / hybrid TAP execution. `l0_only` permits only the shared-
process synthetic engine. Windows selects `l0_only` automatically; the desktop client's local
child also passes `--local-l0-only`. Health and resource documents publish this policy. Deployment
checks it before constructing an orchestrator, so an L1/L2 request returns HTTP 422 with the Linux
host requirement and cannot silently degrade or create partial resources.

```
Windows client EXE ──LocalBackendManager──► bundled polmon-backend.exe (127.0.0.1, L0 only)
        │                 │ process group + log + Windows kill-on-close Job Object
        │                 └── ephemeral bearer token, dynamic port, owned start/stop
        └──Remote Linux preset────────────► self-contained/Python Linux backend (L0/L1/hybrid)
```

The client lifecycle module imports no backend implementation. It resolves an override, an
executable beside the client / in the one-file extraction directory, or the checkout's console
script, then uses only the HTTP contract. The backend PyInstaller graph is built independently and
excludes PySide6; uvicorn's dynamically selected loops, protocols and lifespan handlers are
collected explicitly. Frozen benchmark jobs re-enter that executable through a private fixed
dispatch flag instead of assuming `python -m` exists.

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

### Localization and backend text (approach (a))

The UI is Russian by default and English on request, switched at run time without a restart
([docs/UI-GUIDE.md](docs/UI-GUIDE.md), plan of record [docs/UI-RU-PLAN.md](docs/UI-RU-PLAN.md)).
`polmon.client.i18n` is Qt-free: catalogs are Python modules (`locales/ru.py`, `locales/en.py`)
with CLDR plurals; widgets bind to catalog keys and computed text is held as lazy `Msg` values,
so a switch re-renders every screen in place. Qt's own strings follow via `qtbase_<lang>.qm`.

Backend-originated text uses **approach (a): machine code plus parameters.** The backend is not
localized and needs no locale negotiation. Every error document keeps its English `message`
(the Phase III contract and every existing API consumer stay valid) and adds `message_code` and
`params`: `{"error": {"code", "message", "message_code", "params", "details"}}`. Validation
items, experiment `error_details`, benchmark jobs (`message_code`, `message_params`) and YAML
errors (line, column, `problem_code`) carry codes the same way. The client renders
`backend.<message_code>` from its catalog with the parameters; only a backend without codes (an
older version) gets its English text shown, quoted inside a localized sentence. Approach (b)
(the backend translating per request) was rejected: it would put a second catalog and locale
handling into a service that has no UI, and codes are testable identifiers. Two tests keep the
contract: every backend raise site passes a code (`tests/unit/test_error_codes.py`), and every
code the backend can send has a Russian and an English entry (`scripts/i18n-completeness.py`).
