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
Request documents are capped at 2 MB; client connection/ordinary calls default to 5 seconds,
deployment/reset to 30 seconds, and experiment execution to 120 seconds.

`GET /v1/resources` returns effective admission limits, active counts, and a resource sample.
`POST /v1/experiments/{experiment_id}/cancel` requests cooperative cancellation of an active
experiment. Limit rejections return HTTP 429 and the `resource_limit` error code.

The Windows client performs every HTTP call on one worker thread and polls completion through Tk's
event loop. It never imports Linux networking code and does not require a backend to launch or run
its headless smoke tests.
