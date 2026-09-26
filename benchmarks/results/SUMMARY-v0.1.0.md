### `l0` — benchmarks/results/l0-20260926T124723Z.json

- polmon 0.1.0 (commit e947d53629d1), status **complete**, started 2026-09-26T12:47:23.411122+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"endpoint_counts": [10, 25, 50, 100, 250], "fidelity": "L0 synthetic endpoints sharing one Python process", "idle_seconds_per_run": 0.5, "isolation": "one fresh Python process per run", "repeats": 5, "traffic": "two rounds of one ICMP echo from the first endpoint to every other endpoint (round 1 resolves ARP, round 2 uses the ARP cache)"}

Median (min–max) across repeats.

| L0 endpoints | runs | create ms | teardown ms | incr. RSS MiB | peak incr. MiB | heap KiB | heap B/endpoint | idle CPU ms | µs CPU/echo | p50 ms | p95 ms | loss % | CPU % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 0.17 (0.13–0.19) | 0.06 (0.06–0.07) | 0.00 | 0.00 | 26.0 | 2662 | 0.06 (0.05–0.06) | 100.7 (99.6–105.2) | 0.074 (0.059–0.086) | 0.391 (0.351–0.456) | 0.0 | 0.7 (0.6–0.7) | yes |
| 25 | 5 | 0.31 (0.23–0.32) | 0.10 (0.09–0.10) | 0.00 | 0.00 | 67.0 | 2742 | 0.06 (0.05–0.06) | 79.1 (71.6–95.1) | 0.068 (0.063–0.091) | 0.168 (0.119–0.188) | 0.0 | 1.2 (1.0–1.3) | yes |
| 50 | 5 | 0.56 (0.51–0.65) | 0.14 (0.12–0.18) | 0.00 | 0.00 (0.00–0.02) | 128.4 | 2629 | 0.07 (0.05–0.07) | 86.5 (72.0–97.1) | 0.071 (0.066–0.079) | 0.175 (0.132–0.179) | 0.0 | 2.1 (1.9–2.4) | yes |
| 100 | 5 | 1.01 (0.85–1.11) | 0.18 (0.16–0.22) | 0.05 | 0.07 (0.05–0.07) | 272.1 | 2787 | 0.07 (0.06–0.12) | 81.5 (76.9–89.7) | 0.074 (0.071–0.081) | 0.146 (0.128–0.179) | 0.0 | 3.8 (3.7–4.2) | yes |
| 250 | 5 | 2.25 (1.90–2.56) | 0.26 (0.24–0.29) | 0.30 (0.29–0.30) | 0.49 (0.48–0.50) | 635.4 | 2603 | 0.06 (0.05–0.15) | 95.8 (83.0–100.7) | 0.086 (0.079–0.094) | 0.159 (0.143–0.167) | 0.0 | 9.8 (8.9–10.5) | yes |

### `l1` — benchmarks/results/l1-20260926T124743Z.json

- polmon 0.1.0 (commit e947d53629d1), status **complete**, started 2026-09-26T12:47:43.742196+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 1.321 (1.281–1.451) | 0.370 (0.348–0.444) | 0.119 (0.110–0.143) | 26.6 (26.3–26.6) | 16.9 (-13.0–26.8) | 0.0 (0.0–10.0) | 0.068 (0.065–0.072) | 0.0 | yes |

### `target` — benchmarks/results/target-20260926T124810Z.json

- polmon 0.1.0 (commit e947d53629d1), status **complete**, started 2026-09-26T12:48:10.375972+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 1.493 (1.276–1.520) | 0.149 (0.120–0.181) | 0.4 (0.3–0.4) | 53.2 (53.0–54.3) | 53.5 (53.4–54.6) | 8.2 (-11.3–31.1) | 0.0 | 0.080 (0.070–0.098) | 0.100 (0.086–0.115) | 0.068 (0.057–0.077) | yes | yes | yes |
