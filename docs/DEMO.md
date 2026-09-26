# Phase I MVP demonstration

`polmon-demo` runs the Phase I target demonstration end to end through the backend's HTTP API — the
same contract the Windows client uses — and checks every outcome:

| Step | What is verified |
|---|---|
| 1 health | Backend reachable; its version is recorded |
| 2 topology | `examples/topologies/mvp-demo.yml` validated and loaded: 50 L0 sensors, 2 L1 servers with a built-in HTTP service, one isolated `10.70.0.0/24` network |
| 3 deploy | Admission passes; hybrid deployment running with 50 synthetic endpoints, 2 namespaces, 1 bridge, 1 shared TAP |
| 4 experiment | `examples/scenarios/mvp-recon.yml` (controlled reconnaissance of declared lab nodes only) succeeds: L0→L1 ICMP across the TAP, L0→L0 ICMP in the engine, L1→L1 ICMP and HTTP service probes in the kernel |
| 5 telemetry | Structured events recorded and boundary frames captured to PCAP |
| 6 report | JSON report retrievable with status `succeeded`; Markdown report written |
| 7 reset | `POST /v1/reset` destroys the deployment |
| 8 verify | No active deployments; the kernel no longer lists any namespace, bridge, veth, or TAP the deployment created |

```bash
.venv/bin/polmon-demo                             # disposable local backend (privileged lab)
.venv/bin/polmon-demo --url http://127.0.0.1:8080 # an already running backend
.venv/bin/polmon-demo --output-dir docs/demo      # keep the JSON record and Markdown report
```

With no `--url`, the demo starts a backend on a free loopback port with a temporary data directory,
stops it with SIGTERM afterwards, and records whether the shutdown cleanup ran. Against `--url`, a
failed run destroys only its own deployment and never resets other work on that backend. Progress
(percent, step, elapsed, ETA) goes to stderr; `--json` prints only the record on stdout. The exit
code is 0 only when every step passed.

The demonstration needs the privileged laboratory described in SECURITY.md (passwordless `sudo`
for `ip` namespace/link operations and `/dev/net/tun`). Without it the deployment is refused and the
demo reports `failed` — it never substitutes a mocked run.

Recorded runs are kept in `docs/demo/`: `<experiment-id>.json` (steps, deployment counts, backend
RSS and host memory before/after deployment, observations with their network path, telemetry and
capture counts, the full report document, reset and cleanup verification, shutdown result) and
`<experiment-id>-report.md` (the backend's human-readable report).
