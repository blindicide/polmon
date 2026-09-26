# Benchmarks

`polmon-benchmark` measures the platform under explicit limits and keeps every raw measurement.
Numbers quoted anywhere in this repository must come from a retained result file under
`benchmarks/results/`; the Markdown summaries there are generated from those files by
`polmon-benchmark summarize` and are never edited by hand.

## Commands

```bash
.venv/bin/polmon-benchmark l0                     # L0 sizes 10, 25, 50; rootless
.venv/bin/polmon-benchmark l0 --large             # adds the explicit 100 and 250 sizes
.venv/bin/polmon-benchmark l1                     # 2 L1 namespaces; privileged lab
.venv/bin/polmon-benchmark target                 # 50 L0 + 2 L1 service endpoints; privileged
.venv/bin/polmon-benchmark summarize benchmarks/results/*.json
scripts/run-benchmarks.sh [--large] [--repeats N] # the recorded suite plus SUMMARY-latest.md
```

Every command accepts `--repeats`, `--idle-seconds`, `--output-dir`, and `--json`. Progress goes to
stderr (percent, step, elapsed, ETA; one line per step off a TTY) so `--json` stdout stays a single
JSON document. Results are written as `<kind>-<UTC timestamp>.json` plus a flat `.csv`.

### Limits

Every run is admitted before anything is created and bounded while it runs:

| Option | Default | Effect |
|---|---|---|
| `--max-endpoints` | 50 for `l0` (250 with `--large`), 64 for `target` | Admission rejects larger topologies |
| `--max-namespaces` | 4 | Admission rejects more L1 namespaces |
| `--max-run-seconds` | 120 | A run that exceeds it is killed and the suite aborts |
| `--max-incremental-mb` | 512 | A run whose RSS or peak growth exceeds it aborts the suite |
| `--memory-reserve-mb` | 256 | Admission requires the estimate plus this reserve to be available |

An aborted suite still writes its JSON with `status: "aborted"`, the error, and every completed
row, and exits with code 3. A privileged benchmark without passwordless laboratory `sudo` writes
`status: "not_run"` with `NOT RUN — environment unavailable: <reason>` and exits with code 2.
Endpoint counts above 50 are refused unless `--large` is given.

## Method

- **Isolation.** Each run executes in a fresh Python interpreter
  (`python -m polmon.benchmarks.worker`), so one run's allocator state never becomes the next
  run's baseline. The peak-RSS counter (`VmHWM`) is reset through `/proc/self/clear_refs` before
  the baseline; if the reset is unavailable, peak memory is recorded as `null`.
- **Memory.** `incremental_memory_bytes` is RSS after deployment minus RSS before topology
  construction; CPython reuses memory freed during start-up, so small topologies often show zero
  RSS growth. For L0 the benchmark therefore also performs a second, untimed deployment under
  `tracemalloc` and records exact Python-heap bytes (`python_heap_*`). L1 kernel objects
  (namespaces, veths, bridges, TAPs) belong to no process: the service process tree RSS is measured
  exactly, and the host `MemAvailable` delta is reported separately as a noisy system-wide
  indicator that other host activity also moves — it can even be negative.
- **CPU.** Process CPU time over wall time for the whole run; idle overhead is CPU consumed during
  a fixed idle period with the topology deployed.
- **Traffic.** L0: two rounds of ICMP echo from the first endpoint to every other endpoint (round 1
  resolves ARP, round 2 hits the ARP cache). L1: iputils `ping` between two namespaces at 0.2 s
  intervals. Target: one L0-to-L1 echo per L0 endpoint across the shared TAP, one L0-to-L0 echo per
  endpoint, and five kernel L1-to-L1 echoes. Loss is `(attempts − successes) / attempts`.
- **Cleanup.** A run passes cleanup only when the orchestrator owns no resources and, for L1 and
  the target, no namespace, bridge, veth, or TAP created by the run is still reported by the
  kernel.

## Fidelity classes are not interchangeable

| Class | What one endpoint is | What latency means |
|---|---|---|
| L0 | Protocol state inside one shared Python process | In-process frame encode/validate/dispatch time |
| L1 | A Linux network namespace with a veth on an isolated bridge | Kernel ICMP round trip through the bridge |
| Hybrid | L0 state bridged to L1 through one shared TAP | Engine frame out through the TAP and back |
| L2 | A virtual machine | **NOT RUN** — L2 is an architectural extension in Phase I |

The per-class figures answer different questions and are never compared as equivalents. An L0
endpoint costing a few KiB of heap does not mean an L1 or L2 endpoint could be replaced by one.

## Recorded results

The results of each milestone's recorded run, with host description, workload, limits, source
commit, and limitations, are in `benchmarks/results/`; `benchmarks/results/SUMMARY-*.md` renders
them as tables. See the v0.0.14 milestone report for the run that established the Phase I
baseline.

Comparisons between runs are generated the same way, by passing several result files to
`summarize`; for example `SUMMARY-wave4-batched-ip.md` compares L1 and target runs before (commit
e947d53) and after (commit fe92909) batching the privileged `ip` commands.

