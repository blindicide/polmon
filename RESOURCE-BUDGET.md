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

On Windows almost all of the start-up time is the one-file bootloader unpacking the bundled Qt
and Python runtime into a temporary directory on every launch; the client itself is on screen
0.47 s after its interpreter starts.

Launch times are with a warm page cache (dropping caches needs root, which the laboratory
authorisation does not cover); the first launch after boot is slower. The development host is
4 vCPU / 7.8 GiB and shared with other services. Raw files:
`benchmarks/results/client-qt-linux-{source,bundle,appimage}-20260926.json` and
`benchmarks/results/client-qt-windows-exe-20260926.json`. The GUI itself is
inexpensive for the backend: it polls `health`, `resources`, `topologies` and deployed topologies
every 3 s (a few small JSON requests), telemetry once per second only while the Telemetry page
follows a running experiment, and never overlaps polls.
