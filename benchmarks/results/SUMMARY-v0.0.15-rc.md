### `l0` — benchmarks/results/l0-20260926T123645Z.json

- polmon 0.0.15 (commit 883f8f1d1747), status **complete**, started 2026-09-26T12:36:45.781948+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"endpoint_counts": [10, 25, 50], "fidelity": "L0 synthetic endpoints sharing one Python process", "idle_seconds_per_run": 0.5, "isolation": "one fresh Python process per run", "repeats": 3, "traffic": "two rounds of one ICMP echo from the first endpoint to every other endpoint (round 1 resolves ARP, round 2 uses the ARP cache)"}

Median (min–max) across repeats.

| L0 endpoints | runs | create ms | teardown ms | incr. RSS MiB | peak incr. MiB | heap KiB | heap B/endpoint | idle CPU ms | µs CPU/echo | p50 ms | p95 ms | loss % | CPU % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 3 | 0.15 (0.13–0.18) | 0.08 (0.07–0.08) | 0.00 | 0.00 | 26.0 | 2662 | 0.06 (0.05–0.09) | 93.4 (79.7–111.4) | 0.069 (0.053–0.071) | 0.326 (0.293–0.432) | 0.0 | 0.7 (0.6–0.8) | yes |
| 25 | 3 | 0.29 (0.23–0.38) | 0.10 (0.09–0.14) | 0.00 | 0.00 | 66.6 | 2730 | 0.06 (0.05–0.07) | 74.9 (74.5–98.5) | 0.066 (0.065–0.098) | 0.166 (0.117–0.250) | 0.0 | 1.1 (1.1–1.4) | yes |
| 50 | 3 | 0.62 (0.61–0.64) | 0.10 (0.09–0.12) | 0.00 | 0.00 | 128.4 | 2629 | 0.05 (0.05–0.06) | 72.9 (69.0–82.5) | 0.068 (0.068–0.071) | 0.202 (0.120–0.221) | 0.0 | 1.9 (1.8–2.1) | yes |

### `l1` — benchmarks/results/l1-20260926T123653Z.json

- polmon 0.0.15 (commit 883f8f1d1747), status **complete**, started 2026-09-26T12:36:53.086085+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 3, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 3 | 1.331 (1.309–1.364) | 0.345 (0.324–0.385) | 0.116 (0.099–0.153) | 26.5 (26.4–26.6) | 14.9 (-3.7–17.6) | 0.0 | 0.073 (0.072–0.074) | 0.0 | yes |

### `target` — benchmarks/results/target-20260926T123709Z.json

- polmon 0.0.15 (commit 883f8f1d1747), status **complete**, started 2026-09-26T12:37:09.196218+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 3, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 3 | 1.451 (1.427–1.588) | 0.176 (0.142–0.181) | 0.4 | 53.1 | 53.4 (53.4–53.5) | -6.9 (-16.5–34.2) | 0.0 | 0.094 (0.084–0.098) | 0.107 (0.103–0.107) | 0.062 (0.057–0.065) | yes | yes | yes |
