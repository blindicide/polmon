# Scenarios

Scenario YAML binds to one named topology and lists initial conditions, a permitted-action allowlist,
an ordered sequence, timeout, expected success/failure conditions, and cleanup policy. Actions name
source and target nodes already present in the topology. TCP probes must reference a service declared
on the target. The only current actions are ICMP reachability and declared TCP service probes; there
is intentionally no command, script, executable, URL, or discovered-target field.

The engine validates the full document and its topology relationships before calling an executor.
Executors receive the remaining deadline and must use bounded I/O. Cancellation and timeout stop the
sequence, errors expose exception types rather than arbitrary text, and `always` cleanup runs from a
`finally` path. Results preserve timestamps, action observations, status, safe errors, and whether
cleanup completed.

Initial conditions are verified, never assumed. Before the first action the control plane checks
each declared condition against the live deployment: `topology_deployed` requires the deployment
to be running; `services_started` additionally requires every service declared on an L1 node to
have a live process. An unmet condition fails the experiment with
`initial conditions not satisfied: ...` before any action runs, and the cleanup policy still
applies. Callers of `ScenarioEngine.run` that pass no `precondition` checker get the same failure.

