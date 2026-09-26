### `l1` — benchmarks/results/l1-20260926T124743Z.json

- polmon 0.1.0 (commit e947d53629d1), status **complete**, started 2026-09-26T12:47:43.742196+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 1.321 (1.281–1.451) | 0.370 (0.348–0.444) | 0.119 (0.110–0.143) | 26.6 (26.3–26.6) | 16.9 (-13.0–26.8) | 0.0 (0.0–10.0) | 0.068 (0.065–0.072) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T130020Z.json

- polmon 0.1.0 (commit fe9290977c22), status **complete**, started 2026-09-26T13:00:20.768249+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.184 (0.169–0.210) | 0.432 (0.134–0.474) | 0.087 (0.080–0.090) | 26.6 (26.5–26.6) | 20.3 (-7.2–37.1) | 0.0 | 0.065 (0.062–0.174) | 0.0 | yes |

### `target` — benchmarks/results/target-20260926T124810Z.json

- polmon 0.1.0 (commit e947d53629d1), status **complete**, started 2026-09-26T12:48:10.375972+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 1.493 (1.276–1.520) | 0.149 (0.120–0.181) | 0.4 (0.3–0.4) | 53.2 (53.0–54.3) | 53.5 (53.4–54.6) | 8.2 (-11.3–31.1) | 0.0 | 0.080 (0.070–0.098) | 0.100 (0.086–0.115) | 0.068 (0.057–0.077) | yes | yes | yes |

### `target` — benchmarks/results/target-20260926T130041Z.json

- polmon 0.1.0 (commit fe9290977c22), status **complete**, started 2026-09-26T13:00:41.383425+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.453 (0.383–0.558) | 0.126 (0.118–0.131) | 0.3 | 54.2 (53.0–54.3) | 54.5 (53.4–54.7) | 13.9 (-0.2–25.3) | 0.0 | 0.068 (0.067–0.085) | 0.080 (0.074–0.083) | 0.064 (0.060–0.081) | yes | yes | yes |
