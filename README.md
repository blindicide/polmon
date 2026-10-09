# polmon

polmon is a resource-efficient platform for controlled network-security experiments in
explicitly isolated laboratories. Phase I combines shared-process synthetic endpoints (L0),
Linux network namespaces (L1), and a Qt desktop client for Windows and Linux. L2 virtual machines
are an architectural extension, not part of the initial implementation.

Phase I (v0.1.0) provides: a Linux FastAPI backend; a standalone Windows client executable built on
GitHub-hosted runners; declarative YAML topologies; L0 synthetic endpoints with Ethernet, ARP, IPv4,
and ICMP echo; L1 namespace endpoints with built-in services; hybrid L0/L1 communication through
one shared TAP; a closed-action scenario engine; SQLite telemetry with bounded PCAP capture; JSON
and Markdown reports; resource admission control and cancellation; automated cleanup and reset;
reproducible benchmarks with retained raw results. Run the target demonstration (50 L0 + 2 L1, one
controlled experiment, telemetry, report, reset) with `.venv/bin/polmon-demo`; see
[docs/DEMO.md](docs/DEMO.md).

Phase II (v0.2.0) replaces the Tkinter client with a Qt (PySide6) desktop client that runs on
Windows and Linux from one code base — dashboard, topology editor and inspector, deployment with
live resource counters, scenarios and experiments with live progress and cancellation, a filterable
telemetry stream, reports and benchmark jobs — and a CI/CD pipeline that tests, packages, verifies
and releases both platforms. Operator guide: [docs/CLIENT.md](docs/CLIENT.md); real screenshots:
[docs/ui/SCREENSHOTS.md](docs/ui/SCREENSHOTS.md); design: [docs/UI-PLAN.md](docs/UI-PLAN.md).

Phase III (v0.3.0) makes the downloads self-contained. The Windows client starts, monitors and
stops its bundled backend from the **Local backend (L0 only)** preset; no Python install or separate
service is needed. This local Windows path intentionally supports synthetic L0 only: Windows has
no Linux network namespaces, so L1/L2 is refused rather than emulated. Use **Remote Linux backend**
for L1 and hybrid TAP experiments. Linux releases also contain
`polmon-backend-<version>-linux-x64.tar.gz`, a Qt-free backend bundle that runs without Python,
pip, or a virtual environment.

Phase IV (v0.4.0) localizes the desktop client — Russian by default, English switchable at run
time, backend refusals rendered from stable message codes — and redesigns its interface (design
tokens, dark navigation, cards and metric tiles, empty/loading/error states, ≥ 4.5:1 contrast).
Visual system, glossary and before/after screenshots: [docs/UI-GUIDE.md](docs/UI-GUIDE.md).

Phase V (v0.5.0) adds the operator workflow: Topology Studio with persistent named-node and UUID
identity, namespace SSH and VNC console access, an authored scenario library with bounded actions
and assertions, and detailed structured logs with correlation, rotating service output, API
streaming and a localized Logs page. The headless evidence, real privileged gates and known
limitations are recorded in [docs/milestones/v0.5.0.md](docs/milestones/v0.5.0.md) and
[docs/evidence/phase-v/](docs/evidence/phase-v/).

## Which download?

The table below describes the published v0.5.0 release. The Phase VI branch prepares future
Linux `.deb` and `.rpm` packages and a single embedded-L0 client on both platforms; no Phase VI
release has been published. Package builds and their manifest are produced by
`scripts/build-linux-packages.py` and the Build Linux workflow.

Published releases through v0.5.0 carry these assets and a
`SHA256SUMS.txt` (`sha256sum --check --ignore-missing SHA256SUMS.txt`, or
`scripts/verify-release.sh vX.Y.Z`):

| You want | Download | Fidelity | Needs |
|---|---|---|---|
| Try polmon on Windows | `polmon-<version>-windows-x64.exe` (one file) or `…-portable.zip` (unzip; starts ~2.5× faster) | L0 via the bundled local backend; **Remote Linux backend** for L1/hybrid | Nothing. Unsigned: SmartScreen warns on first run |
| The desktop client on Linux | `polmon-<version>-linux-x64.tar.gz` | Connects to any backend | Qt's xcb libraries ([BUILD-LINUX.md](BUILD-LINUX.md)) |
| A Linux lab backend without Python | `polmon-backend-<version>-linux-x64.tar.gz` + `polmon-backend-bundled.service` | L0; L1 and hybrid TAP when the host permits | glibc 2.35+; for L1/hybrid `iproute2`, `setpriv`, `/dev/net/tun`, passwordless `sudo` for `ip` (check with `--lab-readiness`) |
| A headless Windows backend | `polmon-backend-<version>-windows-x64.exe` | L0 only | Nothing |
| A Python install | `polmon-<version>-py3-none-any.whl` (+ `polmon-backend.service`) | As the Linux backend | Python 3.12; `polmon[gui]` for the client |

Since v0.1.0 (see [CHANGELOG.md](CHANGELOG.md)): hybrid traffic works in both directions (L1
namespaces can ARP for and ping L0 endpoints), optional bearer-token API authentication that is
mandatory off loopback, in-namespace workloads that never run as root, verified scenario
preconditions, storage admission, `polmon-diagnostics --lab`, GUI tests on Windows and under Xvfb,
and a CI dependency audit. Releases carry `SHA256SUMS.txt`; check a download with
`scripts/verify-release.sh vX.Y.Z`. Documentation index: [docs/README.md](docs/README.md).

## Quick start

Source-development requirements: Linux, `/usr/bin/python3.12`, and `uv`. The privileged laboratory (L1/hybrid)
additionally needs `iproute2`, `setpriv`, `/dev/net/tun`, and passwordless `sudo` for `ip`; check
with `.venv/bin/polmon-diagnostics --lab`.

```bash
uv venv --python /usr/bin/python3.12
uv pip install -e '.[dev,gui]'
scripts/check.sh              # lint + rootless tests
.venv/bin/polmon-backend
```

Helper scripts in `scripts/`: `check.sh` (ordinary gate), `privileged-tests.sh` (laboratory tests
with a before/after proof that the host network was untouched), `lab-cleanup.sh` (list or remove
leftover platform-named namespaces and interfaces), `run-benchmarks.sh` (recorded benchmark suite),
and `verify-release.sh` (download a release and check its SHA-256).

Benchmarks run only on explicit request: `.venv/bin/polmon-benchmark l0|l1|target|summarize`. See
[docs/BENCHMARKS.md](docs/BENCHMARKS.md) for limits, method, and the retained raw results.

To control a backend from another machine (for example the desktop client on Windows), start it
with a token:
`POLMON_API_TOKEN=... .venv/bin/polmon-backend --host <lab-host-address>` (or `--api-token-file`),
and enter the same token in the client; see [SECURITY.md](SECURITY.md) and the operator runbook
[docs/OPERATIONS.md](docs/OPERATIONS.md).

Run `.venv/bin/polmon-client` to open the desktop client; the default local preset starts its own
L0-only backend on a free loopback port. `--self-test` checks Qt and the client without opening a
window, while `--local-backend-self-test` proves the owned deploy-to-reset workflow. Packaged clients for
Windows (`.exe`) and Linux (`.tar.gz`) are attached to every release; see
[BUILD-WINDOWS.md](BUILD-WINDOWS.md) and [BUILD-LINUX.md](BUILD-LINUX.md).

Use `.venv/bin/polmon-diagnostics --json` to inspect the Python version, host capabilities,
network-tool availability, and an allow-listed resource snapshot without exposing environment
variables or credentials. Add `--lab` for a read-only check that this host can run the privileged
laboratory (tools, `/dev/net/tun`, ping's `cap_net_raw`, passwordless `sudo ip`); it exits 1 when
not ready. The backend emits structured JSON startup and shutdown logs.

See [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPMENT.md](DEVELOPMENT.md),
[docs/LOGS.md](docs/LOGS.md), and [SECURITY.md](SECURITY.md). No license has been granted; a license file will be added only after
the repository owner makes an explicit licensing decision.
