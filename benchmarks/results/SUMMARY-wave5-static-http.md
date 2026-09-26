### `l1` — benchmarks/results/l1-20260926T130020Z.json

- polmon 0.1.0 (commit fe9290977c22), status **complete**, started 2026-09-26T13:00:20.768249+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.184 (0.169–0.210) | 0.432 (0.134–0.474) | 0.087 (0.080–0.090) | 26.6 (26.5–26.6) | 20.3 (-7.2–37.1) | 0.0 | 0.065 (0.062–0.174) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T130341Z.json

- polmon 0.1.0 (commit 748552f093ef), status **complete**, started 2026-09-26T13:03:41.940566+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.198 (0.174–0.219) | 0.349 (0.131–0.498) | 0.082 (0.075–0.090) | 19.4 | 8.3 (-14.7–32.6) | 0.0 | 0.067 (0.066–0.070) | 0.0 | yes |

### `target` — benchmarks/results/target-20260926T130041Z.json

- polmon 0.1.0 (commit fe9290977c22), status **complete**, started 2026-09-26T13:00:41.383425+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.453 (0.383–0.558) | 0.126 (0.118–0.131) | 0.3 | 54.2 (53.0–54.3) | 54.5 (53.4–54.7) | 13.9 (-0.2–25.3) | 0.0 | 0.068 (0.067–0.085) | 0.080 (0.074–0.083) | 0.064 (0.060–0.081) | yes | yes | yes |

### `target` — benchmarks/results/target-20260926T130402Z.json

- polmon 0.1.0 (commit 748552f093ef), status **complete**, started 2026-09-26T13:04:02.357762+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.457 (0.410–0.640) | 0.125 (0.122–0.159) | 0.3 (0.3–0.4) | 38.8 | 39.1 (39.1–39.2) | -8.8 (-34.1–24.1) | 0.0 | 0.072 (0.068–0.082) | 0.085 (0.069–0.102) | 0.062 (0.060–0.081) | yes | yes | yes |
