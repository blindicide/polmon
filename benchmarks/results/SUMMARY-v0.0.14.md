### `l0` — benchmarks/results/l0-20260926T122444Z.json

- polmon 0.0.14 (commit d80a09ad7f60), status **complete**, started 2026-09-26T12:24:44.901619+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"endpoint_counts": [10, 25, 50, 100, 250], "fidelity": "L0 synthetic endpoints sharing one Python process", "idle_seconds_per_run": 0.5, "isolation": "one fresh Python process per run", "repeats": 5, "traffic": "two rounds of one ICMP echo from the first endpoint to every other endpoint (round 1 resolves ARP, round 2 uses the ARP cache)"}

Median (min–max) across repeats.

| L0 endpoints | runs | create ms | teardown ms | incr. RSS MiB | peak incr. MiB | heap KiB | heap B/endpoint | idle CPU ms | µs CPU/echo | p50 ms | p95 ms | loss % | CPU % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 0.16 (0.15–0.17) | 0.06 (0.05–0.07) | 0.00 | 0.00 (0.00–0.01) | 25.9 | 2648 | 0.05 (0.04–0.07) | 96.1 (83.2–110.5) | 0.061 (0.043–0.079) | 0.375 (0.305–0.453) | 0.0 | 0.7 (0.6–1.0) | yes |
| 25 | 5 | 0.28 (0.24–0.34) | 0.09 (0.07–0.10) | 0.00 | 0.00 | 61.8 | 2533 | 0.06 (0.05–0.07) | 79.6 (66.9–89.2) | 0.067 (0.066–0.077) | 0.143 (0.097–0.165) | 0.0 | 1.1 (1.0–1.3) | yes |
| 50 | 5 | 0.40 (0.38–0.40) | 0.10 (0.09–0.15) | 0.00 | 0.01 (0.00–0.01) | 129.3 | 2648 | 0.05 (0.05–0.18) | 83.5 (66.0–87.8) | 0.071 (0.067–0.074) | 0.139 (0.103–0.158) | 0.0 | 2.1 (1.7–2.1) | yes |
| 100 | 5 | 0.95 (0.84–1.24) | 0.20 (0.14–0.24) | 0.05 | 0.08 (0.07–0.09) | 272.0 | 2785 | 0.05 (0.05–0.06) | 77.6 (73.5–110.0) | 0.072 (0.071–0.080) | 0.138 (0.126–0.282) | 0.0 | 3.8 (3.5–4.9) | yes |
| 250 | 5 | 2.27 (2.00–2.71) | 0.36 (0.35–0.42) | 0.35 (0.34–0.36) | 0.54 (0.53–0.54) | 635.3 (635.2–635.3) | 2602 | 0.06 (0.06–0.09) | 102.1 (88.7–107.7) | 0.092 (0.085–0.108) | 0.162 (0.141–0.186) | 0.0 | 10.4 (9.3–10.8) | yes |

### `l1` — benchmarks/results/l1-20260926T122505Z.json

- polmon 0.0.14 (commit d80a09ad7f60), status **complete**, started 2026-09-26T12:25:05.189708+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 1.261 (1.109–1.346) | 0.373 (0.370–0.393) | 0.116 (0.102–0.124) | 26.6 (26.4–26.6) | 18.3 (-1.7–55.8) | 0.0 | 0.068 (0.062–0.075) | 0.0 | yes |

### `target` — benchmarks/results/target-20260926T122531Z.json

- polmon 0.0.14 (commit d80a09ad7f60), status **complete**, started 2026-09-26T12:25:31.225214+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 1.406 (1.341–1.620) | 0.148 (0.132–0.172) | 0.3 (0.3–0.4) | 53.2 (53.1–54.2) | 53.5 (53.5–54.6) | 32.7 (5.3–43.4) | 0.0 | 0.076 (0.069–0.100) | 0.084 (0.072–0.105) | 0.068 (0.060–0.073) | yes | yes | yes |
