# Bounded resource analytics

`GET /v1/resources/history?limit=120` samples registered deployment services and the
shared control process, then returns JSON history. It uses the existing API auth
policy. Poll at the configured interval; polling faster does not collect faster.
No request means no new samples, and there is no background worker or database.
Export the response to retain evidence across backend restarts. Existing
`/v1/resources` and experiment snapshot formats remain unchanged.

`ResourceLimits.analytics_interval_seconds` defaults to 2 (range 0.25–3600),
`analytics_retention` to 120 (1–1000), and `analytics_max_bytes` to 2 MiB
(4 KiB–16 MiB). Both sample count and encoded UTF-8 storage are enforced. Old
samples are evicted with a `dropped_samples` count. A single oversized sample or
too many subjects returns the existing history with `sample_error`, not a partial
new sample. Export limits are 1–1000. Limits bound stored payload, not total Python
heap: decoded API responses and process observations add transient memory.

Each sample has UTC timestamp, monotonic time, sequence, host memory/swap, node
identity (deployment/id/UUID/fidelity), and deployment aggregates. Configured
memory is a declaration, not observed guest RAM. Host procfs provides CPU time,
RSS and disk read/write bytes for registered service roots and descendants (up to
128 processes and 128 tasks per process). Inaccessible counters are null.
CPU percent is a delta over the actual monotonic interval; 100% means one CPU.
The first observation, changed process identity, decreasing CPU counter or gap
longer than three configured intervals produces null CPU percent. A missed
interval is never silently interpolated. Retired identities leave the rate cache
on the next sample.

RSS sums include shared library pages and exclude namespace/kernel overhead;
these are **not** PSS or total physical memory charges. Read/write bytes count
kernel-accounted process storage I/O, not application bytes, guest disk capacity
or allocated image size. Process-tree changes and unreadable processes make
`process_tree_complete` false. Deployment sums include known values only; inspect
`complete` and node nulls before interpreting them as totals. Processes observed
under two subjects are counted only once and flagged `shared_process_excluded`.
The control process excludes descendants to avoid consuming node attribution.

L0 endpoints share the control process: their per-node CPU/RSS are unavailable,
not equal shares or zeros. Namespace nodes without a registered running service
also have no per-node process usage. Interactive sessions and transient commands
not descended from registered services are not included. Network totals are
read once from a process whose namespace inode matches the registered lab
namespace, excluding loopback; host namespace counters are never attributed to
nodes. Restricted procfs can make network/I/O counters unavailable. VM guest RAM,
virtual/allocated disk and boot time are not inferred from ordinary L1 snapshots.
The optional VM addon supplies its own explicit storage/lifecycle observations.

For reproducible observations, record topology and service workload, poll interval,
host description and raw JSON before and after traffic, and capture cleanup using
`scripts/privileged-tests.sh`. `tests/integration/test_live_resource_analytics.py`
collects actual HTTP-service process observations and prints the JSON evidence.
It does not run a scalability benchmark or claim VM measurements.
