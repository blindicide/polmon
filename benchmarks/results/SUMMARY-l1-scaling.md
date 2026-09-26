### `l1` — benchmarks/results/l1-20260926T131236Z.json

- polmon 0.1.1 (commit 4d91416943a3), status **complete**, started 2026-09-26T13:12:36.314455+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.198 (0.181–0.204) | 0.352 (0.109–0.371) | 0.090 (0.082–0.095) | 19.4 | 4.8 (-18.2–12.5) | 0.0 | 0.067 (0.059–0.183) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T132956Z.json

- polmon 0.1.1 (commit 1c6a4c3e4392), status **complete**, started 2026-09-26T13:29:56.913612+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 4, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 5 | 1.324 (0.435–1.464) | 0.131 (0.092–0.272) | 0.132 (0.101–0.156) | 19.4 | 17.2 (-4.5–37.4) | 0.0 | 0.084 (0.071–0.143) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T133022Z.json

- polmon 0.1.1 (commit 1c6a4c3e4392), status **complete**, started 2026-09-26T13:30:22.189641+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 8, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 5 | 1.777 (1.614–2.937) | 0.198 (0.137–0.235) | 0.432 (0.187–1.277) | 19.4 (19.4–19.5) | 9.9 (2.8–28.3) | 0.0 (0.0–10.0) | 0.074 (0.065–0.074) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T133240Z.json

- polmon 0.1.1 (commit ba770669c13a), status **complete**, started 2026-09-26T13:32:40.805680+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 2, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "settle_seconds_between_runs": 5.0, "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 5 | 0.189 (0.168–0.208) | 0.225 (0.127–0.264) | 0.096 (0.084–0.104) | 19.4 (19.3–19.4) | 8.3 (5.3–25.2) | 0.0 | 0.070 (0.068–0.077) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T133320Z.json

- polmon 0.1.1 (commit ba770669c13a), status **complete**, started 2026-09-26T13:33:20.951781+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 4, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "settle_seconds_between_runs": 5.0, "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 5 | 1.154 (0.327–1.536) | 0.210 (0.183–0.256) | 0.129 (0.125–0.139) | 19.4 | 6.3 (-22.2–37.7) | 0.0 | 0.075 (0.071–0.084) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T133405Z.json

- polmon 0.1.1 (commit ba770669c13a, dirty tree), status **complete**, started 2026-09-26T13:34:05.182538+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 8, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "settle_seconds_between_runs": 5.0, "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 5 | 1.783 (1.689–1.894) | 0.209 (0.100–0.245) | 1.180 (0.748–2.064) | 19.4 | 32.6 (-3.5–81.5) | 0.0 | 0.074 (0.066–0.153) | 0.0 | yes |

### `l1` — benchmarks/results/l1-20260926T133645Z.json

- polmon 0.1.1 (commit ba770669c13a), status **complete**, started 2026-09-26T13:36:45.553930+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "L1 Linux network namespaces with veth pairs on an isolated bridge", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "namespace_count": 8, "repeats": 5, "services": "one built-in static HTTP service in the last namespace", "settle_seconds_between_runs": 5.0, "traffic": "10 kernel ICMP echoes at 0.2 s intervals, client to peer"}

Median (min–max) across repeats.

| namespaces | runs | create s | service ready s | teardown s | service tree MiB | host ΔMemAvail MiB | service idle CPU ms | RTT avg ms | loss % | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 5 | 1.766 (0.974–1.936) | 0.240 (0.106–0.291) | 0.948 (0.210–1.357) | 19.4 | 7.7 (-1.2–22.2) | 0.0 | 0.077 (0.074–0.083) | 0.0 | yes |
