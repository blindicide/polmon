# Resource budget

The engineering budget is two CPU cores and 2 GB physical RAM. Normal tests use small topologies;
100- and 250-endpoint benchmarks require explicit invocation. The initial target is 50 L0 plus two
L1 endpoints within about 1 GB incremental RSS, subject to measurement. Admission control must
reject unsafe workloads before the OOM killer becomes relevant. Swap is recorded but is never
counted as usable budget.

Measurements supporting or refuting the target are produced by `polmon-benchmark target` (50 L0 +
2 L1 service endpoints) and retained with their host description in `benchmarks/results/`. Memory
attributable to processes (control process plus L1 service process trees) is reported separately
from the host `MemAvailable` delta, which also includes unattributable kernel objects and unrelated
host activity. See [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Admission estimates versus measurements

Admission uses per-class defaults unless a node declares `resources`: L0 1 MiB, L1 32 MiB, L2
512 MiB (L2 is not implemented). Measured on the development host (4 logical CPUs, 7.8 GiB, shared
with other services; raw files and summaries in `benchmarks/results/`):

| Class | Default estimate | Measured | Source |
|---|---|---|---|
| L0 endpoint | 1 MiB | 2.6–2.8 KiB Python heap per endpoint; RSS growth 0.29 MiB for 250 endpoints | `SUMMARY-v0.1.1.md` (L0, 5 repeats) |
| L1 endpoint with the built-in service | 32 MiB | 19.4 MiB service process tree (sudo launcher + isolated interpreter); kernel objects unattributable, host MemAvailable delta noisy (run medians 4.8–32.6 MiB for 2–8 namespaces, individual samples −22 to +82 MiB) | `SUMMARY-v0.1.1.md`, `SUMMARY-l1-scaling.md` |
| Phase I target, 50 L0 + 2 L1 | 114 MiB | 39.2 MiB attributed (0.3 MiB control process + 38.8 MiB services); host delta median 10.8 MiB | `SUMMARY-v0.1.1.md` (target, 5 repeats) |

The defaults are deliberately conservative — about 2.9× the attributed memory of the target
workload and several hundred times the per-endpoint L0 heap — so admission refuses early rather
than late. Operators who have measured their own services can declare per-node `resources` to
admit denser topologies. The ≈1 GB engineering target for 50 L0 + 2 L1 is met on both measures.

L1 creation time is dominated by the host-side batch, and within it by `ip link add ... type veth`:
the first pair is created in about 20 ms, later pairs sporadically take 0.5–1.3 s on this host,
whether or not peers are moved between namespaces in between and whether or not runs are spaced by
`--settle-seconds` (`SUMMARY-l1-scaling.md`; one 8-namespace run there is labelled "dirty tree"
because a changelog edit landed during it — code was unchanged, and a clean rerun follows it). The
delay is outside polmon's control (contention for the kernel's RTNL lock
after new links appear is the likely cause; the responsible host component was not identified).
Consequently 4 and 8 namespaces take roughly 0.3–1.9 s to create while 2 take about 0.2 s; per-
namespace batches inside the namespaces stay near 40 ms.

## Desktop client (Qt / PySide6)

The Qt client is a new major dependency (operator-ordered; see [ARCHITECTURE.md](ARCHITECTURE.md)).
It runs on the operator's workstation, not on the 2 GB backend host: the backend install does not
include it (`gui` extra). Purpose: the operator console (threaded, themed, model/view UI on
Windows and Linux). Measured cost:

| Item | Value | Source |
|---|---:|---|
| `PySide6-Essentials` 6.11.2 wheel | 80.1 MB (Linux x86_64), 76.9 MB (Windows x64) | PyPI file sizes |
| `shiboken6` 6.11.2 wheel | 0.27 MB (Linux), 1.23 MB (Windows) | PyPI file sizes |
| Not installed: `PySide6-Addons` | 175 MB (Linux), 168 MB (Windows) | PyPI file sizes |
| Installed size, Linux venv | 225.6 MiB (`PySide6/` 236 MB incl. 129 MB Qt libraries, 9.7 MB plugins; `shiboken6/` 0.65 MB) | `du -sb` on the development host |
| Linux bundle | 132.1 MB unpacked, 50.8 MB `.tar.gz` | PyInstaller one-folder build, pruned plugins |
| Launch to window, Linux (source install) | 0.53 s median (0.49–0.56) | `scripts/measure-client.py`, 5 launches, Xvfb |
| Launch to window, Linux bundle | 0.54 s median (0.53–0.56) | same |
| Idle RSS after 10 s, Linux | 96.3 MiB (source), 93.0 MiB (bundle) | same |
| Windows one-file EXE | 34.6 MB (34,574,625 bytes) | Build Windows run 36260899692 |
| Launch to window, Windows EXE | 3.41 s median (3.39–3.63); in-process part 0.47–0.49 s | same run, `scripts/measure-client.py`, 3 launches on the hosted runner |
| Idle working set after 10 s, Windows | 89.9 MiB (Python process; the one-file bootloader parent adds a few MiB) | same |

| Windows portable (one-folder) zip | 35.7 MB (35,697,588 bytes) | Build Windows run 36263250482 |
| Launch to window, Windows | EXE 2.23 s median (2.08–5.40); portable 0.82 s median (0.82–0.86) | same run, 3 launches each |
| Linux bundle built on the runner (stripped) | 127.4 MB unpacked, 49.7 MB `.tar.gz`; 0.48 s to window, 90.9 MiB idle | Build Linux run 36263251867 |

On Windows most of the one-file EXE's start-up time is its bootloader unpacking the bundled Qt and
Python runtime into a temporary directory on every launch; the portable one-folder build skips
that and opens 2.7× faster, at the price of shipping a folder instead of one file. Stripping the
Linux bundle removed 35 MB (22 % of the tarball) of debug information that the runners' Python
build carries (v0.2.0's bundle: 162.7 MB / 63.7 MB).

Launch times are with a warm page cache (dropping caches needs root, which the laboratory
authorisation does not cover); the first launch after boot is slower. The development host is
4 vCPU / 7.8 GiB and shared with other services. Raw files:
`benchmarks/results/client-qt-linux-{source,bundle,appimage}-20260926.json` and
`benchmarks/results/client-qt-windows-{exe-20260926,exe-20260926b,portable-20260926}.json` and
`benchmarks/results/client-qt-linux-ci-bundle-20260926.json`. The GUI itself is
inexpensive for the backend: it polls `health`, `resources`, `topologies` and deployed topologies
every 3 s (a few small JSON requests), telemetry once per second only while the Telemetry page
follows a running experiment, and never overlaps polls.

### v0.4.0: Russian UI and redesign

Measured by the packaged clients' `--smoke-start` on hosted runners at commit 04281ea (Build
Windows run 36294462584, Build Linux run 36294463788), against v0.3.0's numbers below:

| Item | v0.4.0 | v0.3.0 |
|---|---:|---:|
| Windows one-file EXE | 51,226,560 B | 51,027,301 B |
| Linux client tarball | 49,956,523 B | 49,768,161 B |
| Idle RSS after 10 s, Windows | 105.4–106.0 MiB (4 starts) | 92.9 MiB |
| Idle RSS after 10 s, Linux bundle | 103.0 MiB (3 starts) | 93.2 MiB |
| Largest minimum window size over all pages (Russian) | 1284×848 Windows, 1398×813 Linux | — |

The artifacts grew by about 0.2 MB (the Russian Qt translation `qtbase_ru.qm` and both
catalogs). Idle memory grew by 10–13 MiB (11–14 %); the growth has not been attributed to a
component yet (candidates: the richer widget tree, the painted stylesheet images, the catalogs
and the Qt translator).

## Self-contained backend (v0.3.0)

The backend is frozen separately and explicitly excludes PySide6 (the builds fail if any Qt file
is found in it). Measured on hosted runners at commit 07f07d7 — Build Windows run 36278743140,
Build Linux run 36278744673; raw files in `benchmarks/results/packaged-v0.3.0-20260926/`:

| Item | Windows (windows-latest) | Linux (ubuntu-22.04) |
|---|---:|---:|
| Backend artifact | `polmon-backend-0.3.0-windows-x64.exe` 16,433,265 B (one-file) | `polmon-backend-0.3.0-linux-x64.tar.gz` 15,740,585 B; 31,957,796 B extracted (one-folder) |
| Start to HTTP health, standalone | 2.03 s (one-file unpacks on every start) | 0.73 s (`env -i`) |
| Backend RSS after a full L0 workflow | 62.2 MiB (65,183,744 B, backend's own report) + 7.8 MiB one-file launcher | 56.7 MiB (59,437,056 B) |
| Client artifact | one-file EXE 51,027,301 B; portable zip 51,909,456 B | client tarball 49,768,161 B |
| Client launch to window (3 runs) | EXE 2.55 s median (2.26–2.84); portable 0.98 s median (0.93–2.32) | 0.58 s median (0.579–0.589) |
| Client idle RSS after 10 s | 92.9 MiB (EXE), 92.8 MiB (portable) | 93.2 MiB |

**Cost of the Local-backend flow** (Windows, `--local-backend-gui-probe`, three connects each):
pressing *Connect* to a connected, polled window takes 1.69–2.04 s (one-file) and 1.70–2.00 s
(portable), almost all of it the backend's own start. The flow adds one backend process of about
61 MiB (60.8 MiB reported at connect, 61.4–61.6 MiB after the L0 workflow) plus the 7.8 MiB
one-file launcher: roughly 69 MiB on top of the client's 93 MiB. Embedding the backend grows the
one-file client from 34.8 MB (v0.2.3) to 51.0 MB, and each one-file start (client or backend)
unpacks its runtime to a temporary directory; the portable build avoids both costs at start-up.

On Windows the backend reports its RSS itself: the PID a launcher sees is PyInstaller's one-file
bootloader (about 8 MiB), whose Python child does the work and exits with it (it watches the
launcher and shuts down gracefully if the launcher is killed). L0 endpoint allocations remain
governed by the admission and per-endpoint measurements above; the Windows local backend never
creates namespaces. v0.3.0's Windows backend reported no memory figures (procfs-only probes), so
its admission memory reserve could not refuse; from v0.3.1 it reports available physical memory
and enforces the reserve like Linux (swap remains unreported on Windows).
