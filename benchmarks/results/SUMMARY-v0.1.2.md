### `l0` — benchmarks/results/l0-20260926T135041Z.json

- polmon 0.1.2 (commit 70477354a702), status **complete**, started 2026-09-26T13:50:41.325623+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"endpoint_counts": [10, 25, 50, 100, 250], "fidelity": "L0 synthetic endpoints sharing one Python process", "idle_seconds_per_run": 0.5, "isolation": "one fresh Python process per run", "repeats": 5, "settle_seconds_between_runs": 0.0, "traffic": "two rounds of one ICMP echo from the first endpoint to every other endpoint (round 1 resolves ARP, round 2 uses the ARP cache)"}

Median (min–max) across repeats.

| L0 endpoints | runs | create ms | teardown ms | incr. RSS MiB | peak incr. MiB | heap KiB | heap B/endpoint | idle CPU ms | µs CPU/echo | p50 ms | p95 ms | loss % | CPU % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 0.19 (0.16–0.27) | 0.07 (0.06–0.08) | 0.01 | 0.02 | 27.2 | 2782 | 0.06 (0.06–0.07) | 108.8 (102.9–115.2) | 0.082 (0.077–0.098) | 0.386 (0.334–0.476) | 0.0 | 0.7 (0.7–0.8) | yes |
| 25 | 5 | 0.42 (0.28–0.45) | 0.09 (0.07–0.11) | 0.02 (0.02–0.03) | 0.05 (0.04–0.05) | 69.1 | 2832 | 0.06 (0.06–0.07) | 86.6 (73.4–99.1) | 0.068 (0.063–0.096) | 0.203 (0.108–0.273) | 0.0 | 1.2 (1.1–1.4) | yes |
| 50 | 5 | 0.61 (0.51–0.70) | 0.13 (0.10–0.28) | 0.07 (0.06–0.07) | 0.11 | 131.5 | 2692 | 0.06 (0.05–0.07) | 95.1 (65.5–105.9) | 0.092 (0.068–0.099) | 0.143 (0.115–0.404) | 0.0 | 2.3 (1.8–2.7) | yes |
| 100 | 5 | 1.01 (0.93–1.15) | 0.13 (0.13–0.28) | 0.21 | 0.30 | 272.1 | 2787 (2786–2787) | 0.06 (0.04–0.08) | 88.7 (79.1–97.6) | 0.082 (0.074–0.097) | 0.151 (0.142–0.154) | 0.0 | 4.1 (3.8–4.3) | yes |
| 250 | 5 | 2.72 (2.32–2.84) | 0.28 (0.25–0.44) | 0.60 | 0.80 | 635.4 | 2603 | 0.05 (0.05–0.09) | 99.1 (86.4–101.8) | 0.095 (0.082–0.096) | 0.156 (0.138–0.178) | 0.0 | 10.2 (9.2–10.5) | yes |

### `l1` — benchmarks/results/l1-20260926T135101Z.json

- polmon 0.1.2 (commit 70477354a702), status **complete**, started 2026-09-26T13:51:01.046111+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "settle_seconds_between_runs": 0.0, "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.181 (0.165–0.228) | 0.222 (0.211–0.269) | 0.091 (0.086–0.102) | 19.4 (19.4–19.5) | 7.3 (-7.9–12.7) | 0.0 | 0.078 (0.068–0.092) | 0.0 | yes |

### `target` — benchmarks/results/target-20260926T135121Z.json

- polmon 0.1.2 (commit 70477354a702), status **complete**, started 2026-09-26T13:51:21.093724+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "settle_seconds_between_runs": 0.0, "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.462 (0.277–0.581) | 0.191 (0.135–0.237) | 0.8 | 38.8 (38.8–38.9) | 39.7 (39.6–39.7) | 13.3 (-1.4–22.1) | 0.0 | 0.281 (0.170–0.323) | 0.088 (0.074–0.100) | 0.069 (0.061–0.105) | yes | yes | yes |
