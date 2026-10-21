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

Interrupted executions: stopping the backend with SIGINT or SIGTERM runs the same reset before the
process exits. A benchmark run that exceeds its time limit receives SIGTERM so its teardown still
executes, and is killed only after a 20-second grace period.

Crash recovery (uncatchable SIGKILL, OOM kill, power loss): before the privileged batch that
creates a namespace, bridge, veth or TAP, the backend writes the generated names to an ownership
journal (`<data-dir>/state/lab-ownership/*.json`, written atomically with mode 600) together with
its pid, process start time and boot id; once the objects exist it adds their kernel identities
(namespace inode, link ifindex). A clean teardown removes the record. The next backend on the
same data directory reclaims every record whose owner is gone, at startup and on `POST /v1/reset`
(and before redeploying the same topology):

- processes inside the reclaimed namespaces stop first: the operator's own processes directly,
  root `sshd` through its `sudo … ip netns exec` launcher, which relays the signal; a launcher is
  never SIGKILLed, because that would orphan its child;
- names are re-checked against the generated `polmon…`/`veth…` patterns, and an object whose
  kernel identity differs from the record (someone else reused the name) is reported as foreign
  and left alone; a record owned by another running backend is skipped;
- a record is dropped only after its objects are verifiably gone, so a failed delete is retried.

Outcomes appear as `lab.recovery.reclaimed`, `.foreign`, `.failed`, `.skipped_live_owner` and
`.processes_remaining` structured log events and in `lab_recovery` of `GET /v1/resources`; the
reset response counts them in `lab_reclaimed`. `scripts/lab-cleanup.sh` remains the manual tool
for objects with no journal (for example a lost data directory or a separate benchmark process).

Condition comparisons carry a `role` and an `outcome`: success requirements are `met` or `not_met`;
failure triggers are `triggered` or `not_triggered`. The Markdown report prints these labels, so a
failure condition that did not fire reads "not triggered" rather than as a mismatch.
