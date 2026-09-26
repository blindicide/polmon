### `l0` — benchmarks/results/l0-20260926T131215Z.json

- polmon 0.1.1 (commit 4d91416943a3), status **complete**, started 2026-09-26T13:12:15.747038+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"endpoint_counts": [10, 25, 50, 100, 250], "fidelity": "L0 synthetic endpoints sharing one Python process", "idle_seconds_per_run": 0.5, "isolation": "one fresh Python process per run", "repeats": 5, "traffic": "two rounds of one ICMP echo from the first endpoint to every other endpoint (round 1 resolves ARP, round 2 uses the ARP cache)"}

Median (min–max) across repeats.

| L0 endpoints | runs | create ms | teardown ms | incr. RSS MiB | peak incr. MiB | heap KiB | heap B/endpoint | idle CPU ms | µs CPU/echo | p50 ms | p95 ms | loss % | CPU % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 0.17 (0.13–0.19) | 0.08 (0.06–0.15) | 0.00 | 0.00 | 26.0 | 2662 | 0.06 (0.05–0.08) | 96.1 (79.7–117.3) | 0.066 (0.057–0.096) | 0.417 (0.318–0.488) | 0.0 | 0.7 (0.6–0.8) | yes |
| 25 | 5 | 0.27 (0.24–0.32) | 0.10 (0.09–0.11) | 0.00 | 0.00 (0.00–0.03) | 67.0 | 2742 | 0.05 (0.05–0.07) | 81.9 (71.5–99.0) | 0.069 (0.066–0.098) | 0.162 (0.115–0.259) | 0.0 | 1.2 (1.1–1.3) | yes |
| 50 | 5 | 0.64 (0.53–0.74) | 0.14 (0.13–0.27) | 0.00 | 0.00 | 128.4 | 2629 | 0.06 (0.06–0.09) | 96.0 (74.0–115.0) | 0.086 (0.068–0.105) | 0.171 (0.122–0.970) | 0.0 | 2.4 (1.9–2.7) | yes |
| 100 | 5 | 0.98 (0.88–1.18) | 0.21 (0.14–0.22) | 0.05 | 0.06 (0.05–0.07) | 272.1 | 2787 (2786–2787) | 0.06 (0.05–0.10) | 89.5 (75.2–102.7) | 0.096 (0.072–0.109) | 0.146 (0.120–0.180) | 0.0 | 4.1 (3.6–4.6) | yes |
| 250 | 5 | 2.32 (2.11–2.84) | 0.36 (0.26–0.51) | 0.29 (0.22–0.30) | 0.48 (0.41–0.49) | 635.4 (635.4–635.5) | 2603 | 0.05 (0.05–0.06) | 96.1 (88.3–105.7) | 0.090 (0.085–0.095) | 0.156 (0.139–0.171) | 0.0 | 9.8 (9.3–10.8) | yes |

### `l1` — benchmarks/results/l1-20260926T131236Z.json

- polmon 0.1.1 (commit 4d91416943a3), status **complete**, started 2026-09-26T13:12:36.314455+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.198 (0.181–0.204) | 0.352 (0.109–0.371) | 0.090 (0.082–0.095) | 19.4 | 4.8 (-18.2–12.5) | 0.0 | 0.067 (0.059–0.183) | 0.0 | yes |

### `target` — benchmarks/results/target-20260926T131256Z.json

- polmon 0.1.1 (commit 4d91416943a3), status **complete**, started 2026-09-26T13:12:56.547271+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.471 (0.258–0.559) | 0.129 (0.118–0.136) | 0.3 | 38.8 (38.8–38.9) | 39.2 (39.1–39.2) | 10.8 (-6.2–23.0) | 0.0 | 0.070 (0.062–0.076) | 0.076 (0.071–0.101) | 0.074 (0.059–0.089) | yes | yes | yes |
