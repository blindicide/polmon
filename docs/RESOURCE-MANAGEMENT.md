# Resource management

The backend performs admission before creating any operating-system resources. It projects the
requested topology together with active deployments and rejects endpoint or Linux-namespace totals
above policy. It also compares estimated topology memory plus a configurable host-memory reserve to
currently available memory. Rejections use HTTP 429 with the stable `resource_limit` error code and
per-limit projected/allowed values.

Default limits are 250 endpoints, 16 active namespaces, one concurrent experiment, a 1 MiB capture,
300 seconds per experiment, and a 256 MiB available-memory reserve. They can be changed through
`ControlPlane(limits=ResourceLimits(...))` or backend flags `--max-endpoints`, `--max-namespaces`,
`--max-concurrent-experiments`, `--max-capture-bytes`, `--max-experiment-seconds`, and
`--memory-reserve-mb`. `GET /v1/resources` returns active counts, the effective policy, and a current
resource sample.

During execution a daemon monitor samples resources at a bounded interval. If available memory
falls below the reserve, it records a resource-limit event and cooperatively cancels the scenario.
`POST /v1/experiments/{experiment_id}/cancel` uses the same cooperative cancellation signal. The
scenario engine checks cancellation between declared actions, so an in-flight bounded probe is
allowed to return before teardown. Capture writers enforce the configured byte cap and account for
dropped frames.

Admission failure occurs before backend validation or resource creation. Deployment failures invoke
orchestrator rollback. Reset continues across independent deployments and retains any teardown that
failed so an operator can correct the cause and retry.

Storage is bounded the same way. Experiment artefacts (telemetry database, captures, reports) are
never deleted automatically; instead a new experiment is refused with HTTP 429 when its capture
ceiling would push the data directory above `--max-data-mb` (default 1024) or leave less free disk
than `--disk-reserve-mb` (default 512). `GET /v1/resources` reports `data_directory_bytes`. Archive
or remove old artefacts deliberately to make room.
