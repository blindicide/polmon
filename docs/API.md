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

The Windows client performs every HTTP call on one worker thread and polls completion through Tk's
event loop. It never imports Linux networking code and does not require a backend to launch or run
its headless smoke tests.

Identifiers are validated before any work: `topology_id` path and body values must match
`^[a-z][a-z0-9-]{0,31}$` and `experiment_id` values `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`; anything else
(for example a path-like `../x`) is rejected with HTTP 422 before files or telemetry are touched.

Experiments run on L0, L1, and hybrid deployments. On a hybrid deployment each action uses the path
its endpoint classes support: L0→L0 ICMP in the synthetic engine, L0→L1 ICMP across the shared
TAP, and L1→L1 ICMP/TCP in the kernel. L1→L0 actions and TCP from an L0 source return an
observation with `detail: "unsupported"` rather than an emulated result; observations carry a
`path` such as `l0->l1`. The experiment capture contains the synthetic and TAP boundary frames.

When the backend stops (SIGINT or SIGTERM through uvicorn's graceful shutdown) it tears down every
owned deployment before exiting and logs `shutdown_cleanup` (or `shutdown_cleanup_failed` with the
failures). A backend killed with SIGKILL cannot clean up; recover with `scripts/lab-cleanup.sh`.
