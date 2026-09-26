### `target` — benchmarks/results/target-20260926T135121Z.json

- polmon 0.1.2 (commit 70477354a702), status **complete**, started 2026-09-26T13:51:21.093724+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "settle_seconds_between_runs": 0.0, "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.462 (0.277–0.581) | 0.191 (0.135–0.237) | 0.8 | 38.8 (38.8–38.9) | 39.7 (39.6–39.7) | 13.3 (-1.4–22.1) | 0.0 | 0.281 (0.170–0.323) | 0.088 (0.074–0.100) | 0.069 (0.061–0.105) | yes | yes | yes |

### `target` — benchmarks/results/target-20260926T140845Z.json

- polmon 0.1.3 (commit 8f290d2db32b), status **complete**, started 2026-09-26T14:08:45.373834+00:00
- host: AMD EPYC 9354 32-Core Processor, 4 logical CPUs, 7.8 GiB RAM, kernel 6.8.0-138-generic, Python 3.12.3
- workload: {"fidelity": "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP", "idle_seconds_per_run": 1.0, "isolation": "one fresh Python process per run", "l0_count": 50, "l1_count": 2, "repeats": 5, "services": "one built-in static HTTP service in every L1 namespace", "settle_seconds_between_runs": 0.0, "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)", "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per L0 endpoint, five kernel L1-to-L1 echoes"}

Median (min–max) across repeats.

| topology | runs | deploy s | teardown s | controller MiB | services MiB | attributed MiB | host ΔMemAvail MiB | L0→L1 loss % | L0→L1 p50 ms | L0→L0 p50 ms | L1→L1 RTT ms | ≤1 GiB (attributed) | ≤1 GiB (host Δ) | cleanup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 L0 + 2 L1 | 5 | 0.376 (0.284–0.474) | 0.133 (0.120–0.146) | 0.8 | 38.8 | 39.6 (39.6–39.7) | 23.1 (16.6–29.5) | 0.0 | 0.221 (0.177–0.334) | 0.104 (0.069–0.115) | 0.067 (0.061–0.077) | yes | yes | yes |
