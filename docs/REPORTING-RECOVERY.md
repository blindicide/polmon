# Reporting and recovery

Each completed experiment produces `reports/<experiment-id>.json` and
`reports/<experiment-id>.md` beneath the configured backend data directory. Writes use a temporary
file, flush it to storage, and replace the destination atomically. Reports contain the polmon
version, complete normalized topology and scenario, UTC execution timestamps, ordered observed
events, expected-versus-actual condition results, errors, resource samples, capture statistics,
cleanup state, and final status.

`POST /v1/reset` performs best-effort teardown of every deployment owned by the process. A failure
to tear down one deployment does not prevent attempts on the others, and the response reports a
configuration error listing incomplete items. Loaded topology definitions and completed reports are
retained, allowing a topology to be deployed and an experiment to be repeated without manual file
reconstruction.

Scenario preflight or execution exceptions close telemetry and invoke deployment teardown before
the API returns an error. Normal scenario cleanup follows the scenario's declared cleanup policy;
the reset endpoint remains the explicit recovery boundary for deployments intentionally retained by
`cleanup_policy: never`.
