# Backend API v1

All endpoints use JSON and live under `/v1`. `GET /v1/health` returns name, version, and status.
Topology YAML is validated with `POST /v1/topologies/validate` and loaded with
`POST /v1/topologies`, both using `{"yaml":"..."}`. Deployment creation/status/removal use
`POST`, `GET`, and `DELETE /v1/deployments/{topology_id}`.

Run an experiment with `POST /v1/experiments` and fields `experiment_id`, `topology_id`, and
`scenario_yaml`. Read its result at `GET /v1/experiments/{experiment_id}` and ordered telemetry at
`GET /v1/experiments/{experiment_id}/telemetry`. The durable machine-readable report is returned by
`GET /v1/experiments/{experiment_id}/report`; the backend also writes atomic JSON and Markdown
artifacts beneath its data directory. `POST /v1/reset` tears down every owned deployment while
preserving loaded topology definitions so they can be redeployed. Application errors use
`{"error":{"code":"...","message":"...","details":{...}}}` and an appropriate HTTP status.
Request documents are capped at 2 MB, and any request body above 5 MiB (declared or chunked)
is refused with HTTP 413 `request_too_large` before it is parsed; client connection/ordinary calls default to 5 seconds,
deployment/reset to 30 seconds, and experiment execution to 120 seconds.

`GET /v1/resources` returns effective admission limits, active counts, and a resource sample.
`POST /v1/experiments/{experiment_id}/cancel` requests cooperative cancellation of an active
experiment. Limit rejections return HTTP 429 and the `resource_limit` error code.

The Qt desktop client performs every HTTP call on a bounded worker-thread pool and applies results
on the GUI thread (see [UI-PLAN.md](UI-PLAN.md)). It never imports Linux networking code and does
not require a backend to launch or to run its headless self-test.

## Inspection, live progress and benchmarks (v0.2.0)

These routes back the desktop client; all are additive and existing clients are unaffected.

| Route | Purpose |
|---|---|
| `POST /v1/topologies/validate`, `POST /v1/topologies` | Responses also carry `topology`: the structured, normalized definition (nodes with `class`, interfaces with `network`, `mac`, `ipv4`; networks; services). |
| `GET /v1/topologies` | Loaded definitions with `deployed`, `node_count`, `network_count` and the resource estimate. |
| `GET /v1/topologies/{topology_id}` | One loaded definition (`normalized_yaml`, `topology`, `resources`, `deployed`). |
| `POST /v1/scenarios/validate` | `{"yaml": ...}` → the structured scenario (`permitted_actions` sorted) and `topology_check` (`loaded`, `deployed`, `compatible`, `problems`) against the loaded required topology. |
| `POST /v1/experiments` with `"wait": false` | Validation, deployment checks and admission run first (errors are returned directly); the experiment then runs on a backend thread and the call returns HTTP 202 with `status: running`. |
| `GET /v1/experiments/{experiment_id}` | While active: `status` `running`/`cancelling` and `progress` (`total_actions`, `completed_actions`, `current_action`, `elapsed_seconds`, `timeout_seconds`). When finished: the full record plus final `progress`; a background failure is `status: error` with an `error` document. Experiments run by an earlier backend process are returned from SQLite with `persisted: true` (a run that never finished reads `interrupted`). |
| `GET /v1/experiments?limit=N` | Persisted experiments, newest first (default 200, maximum 1000), with capture summary and `report_available`. |
| `GET /v1/experiments/{experiment_id}/telemetry?after=S&limit=N` | Events with `sequence > S`, at most `N` (≤ 5000) per page, for incremental live polling. Network observations are recorded as each action finishes. |
| `GET /v1/experiments/{experiment_id}/report/markdown` | `{"experiment_id", "markdown"}`: the human-readable report. |
| `POST /v1/benchmarks` | Starts one bounded benchmark job (HTTP 202). Body: `kind` (`l0`, `l1`, `target`), workload fields (`counts`/`large`, `namespaces`, `l0`/`l1`, `repeats`, `idle_seconds`, `settle_seconds`) and a **required** `limits` object (`max_endpoints`, `max_namespaces`, `max_run_seconds`, `max_incremental_mb`, `memory_reserve_mb`). Limits above the backend's own admission limits, a reserve below its reserve, a second concurrent job, or an active experiment are refused with HTTP 429 `resource_limit` naming each violation; L0 counts above 50 need `large: true`. |
| `GET /v1/benchmarks/jobs`, `GET /v1/benchmarks/jobs/{job_id}` | Job state (`running`, `succeeded`, `not_run`, `aborted`, `failed`, `cancelled`), `progress` (`completed_steps`, `total_steps`, `percent`, `eta_seconds`, `detail`), `result_name`, `message`, stderr tail. |
| `POST /v1/benchmarks/jobs/{job_id}/cancel` | SIGTERM to the job's process group (workers tear down), SIGKILL after a 20 s grace. |
| `GET /v1/benchmarks/results`, `GET /v1/benchmarks/results/{name}` | Retained raw result files in `<data>/benchmarks/`, and one document with its Markdown summary. |

Jobs run the unchanged `polmon-benchmark` command in a subprocess, so every run keeps its fresh
worker process and limit checks. An experiment is refused while a job runs, and vice versa.
Experiment identifiers are unique across backend restarts (the SQLite record is checked). On
shutdown the backend cancels and joins active experiments and terminates a running job before its
final reset.

Identifiers are validated before any work: `topology_id` path and body values must match
`^[a-z][a-z0-9-]{0,31}$` and `experiment_id` values `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`; anything else
(for example a path-like `../x`) is rejected with HTTP 422 before files or telemetry are touched.

Experiments run on L0, L1, and hybrid deployments. On a hybrid deployment each action uses the path
its endpoint classes support: L0→L0 ICMP in the synthetic engine, L0→L1 ICMP across the shared
TAP, L1→L0 ICMP from the kernel answered by the TAP responder, and L1→L1 ICMP/TCP in the kernel.
TCP to or from an L0 endpoint returns an observation with `detail: "unsupported"` rather than an
emulated result; observations carry a `path` such as `l0->l1`. The experiment capture contains the synthetic and TAP boundary frames.

When the backend stops (SIGINT or SIGTERM through uvicorn's graceful shutdown) it tears down every
owned deployment before exiting and logs `shutdown_cleanup` (or `shutdown_cleanup_failed` with the
failures). A backend killed with SIGKILL cannot clean up; recover with `scripts/lab-cleanup.sh`.

Authentication: when the backend has an API token (`POLMON_API_TOKEN`, or `--api-token-file` for
a file readable only by its owner; at least 24 characters), every path except `GET /` and
`GET /v1/health` requires `Authorization: Bearer <token>` and otherwise returns HTTP 401
`unauthorized`. The check runs before the request body is read and compares in constant time. The
backend refuses to listen on a non-loopback address without a token. Clients pass the token with
`ApiClient(url, token=...)`; the Windows client has an *API token* field that is kept in memory
only, and `polmon-demo --url` reads `POLMON_API_TOKEN` or `--token-file`.
