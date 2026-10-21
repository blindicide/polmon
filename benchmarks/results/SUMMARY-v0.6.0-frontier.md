### `l0` — benchmarks/results/l0-20261021T224848Z.json

- polmon 0.6.0 (commit 19736d9dd0fc), status **complete**, started 2026-10-21T22:48:48.099472+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-142-generic, Python 3.12.3
- workload: {"endpoint_counts": [10, 25, 50], "fidelity": "L0 synthetic endpoints sharing one Python process", "idle_seconds_per_run": 0.5, "isolation": "one fresh Python process per run", "repeats": 5, "settle_seconds_between_runs": 0.0, "traffic": "two rounds of one ICMP echo from the first endpoint to every other endpoint (round 1 resolves ARP, round 2 uses the ARP cache)"}

Median (min–max) across repeats.

| L0 endpoints | runs | create ms | teardown ms | incr. RSS MiB | peak incr. MiB | heap KiB | heap B/endpoint | idle CPU ms | µs CPU/echo | p50 ms | p95 ms | loss % | CPU % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 0.12 (0.11–0.12) | 0.06 (0.05–0.07) | 0.01 | 0.02 (0.02–0.03) | 29.1 | 2978 | 0.05 (0.04–0.07) | 79.2 (76.7–92.9) | 0.064 (0.051–0.071) | 0.280 (0.274–0.370) | 0.0 | 0.6 (0.5–0.6) | yes |
| 25 | 5 | 0.37 (0.35–0.41) | 0.07 (0.07–0.10) | 0.04 | 0.06 | 73.9 | 3028 | 0.06 (0.05–0.08) | 77.6 (70.6–101.2) | 0.069 (0.055–0.094) | 0.129 (0.110–0.151) | 0.0 | 1.1 (1.1–1.4) | yes |
| 50 | 5 | 0.46 (0.39–0.59) | 0.10 (0.08–0.15) | 0.08 | 0.13 (0.12–0.13) | 140.4 | 2876 | 0.07 (0.05–0.10) | 73.3 (65.0–80.0) | 0.070 (0.061–0.070) | 0.109 (0.100–0.158) | 0.0 | 2.1 (1.7–2.1) | yes |

### `l1` — benchmarks/results/l1-20261021T224859Z.json

- polmon 0.6.0 (commit 19736d9dd0fc), status **complete**, started 2026-10-21T22:48:59.087930+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-142-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "settle_seconds_between_runs": 0.0, "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.158 (0.136–0.195) | 0.173 (0.082–0.184) | 0.089 (0.075–0.095) | 19.0 (19.0–19.1) | -2.5 (-14.1–47.3) | 0.0 | 0.067 (0.062–0.083) | 0.0 | yes |

### `target` — benchmarks/results/target-20261021T224917Z.json

- polmon 0.6.0 (commit 19736d9dd0fc), status **complete**, started 2026-10-21T22:49:17.158300+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-142-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "settle_seconds_between_runs": 0.0, "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.198 (0.187–0.295) | 0.121 (0.103–0.132) | 0.4 | 38.0 (38.0–38.2) | 38.5 (38.4–38.6) | 14.3 (8.0–23.1) | 0.0 | 0.209 (0.158–0.318) | 0.072 (0.068–0.075) | 0.061 (0.049–0.061) | yes | yes | yes |
