# Scenario studio

Scenarios are validated YAML documents that bind an experiment to one named topology. The
scenario library is stored beside the topology library under `library/scenarios/` and is exposed
through persistent `POST`, `GET`, `PUT`, and `DELETE` endpoints:

```text
POST /v1/scenarios          create or upsert a validated YAML document
GET  /v1/scenarios          list loaded documents
GET  /v1/scenarios/{id}     fetch normalized YAML and the parsed document
PUT  /v1/scenarios/{id}     replace an existing document
DELETE /v1/scenarios/{id}  remove a document
```

The client Scenarios page has a backend library picker, YAML editor, and a step-list editor. The
step editor supports adding, removing, reordering, and duplicating sequence actions; the YAML tab
remains the canonical way to edit topology binding, initial conditions, timeout, cleanup policy,
conditions, parameters, and cleanup steps. Both tabs operate on the same document and all writes
are validated before they reach the backend library.

## Closed actions and the safety boundary

Automated actions use a closed catalogue. They are deliberately different from the interactive SSH
console: the console lets an operator type a bounded command interactively, while an automated
scenario can only name one documented command and its bounded parameters. There is no shell string,
pipe, redirection, URL, or arbitrary executable in a scenario action.

The available actions are:

| Action | Required fields | Effect |
| --- | --- | --- |
| `icmp_probe` | `source`, `target` | Bounded ICMP reachability probe |
| `tcp_probe` | `source`, `target`, declared `service` | Probe the target service port |
| `ssh_exec` | `target`, `command` | Run one catalogue command through the target's SSH service |
| `wait` | `seconds` | Sleep for a positive, bounded duration |

The `ssh_exec` command catalogue is `hostname`, `cat_hostname`, `ip_addr`, `ip_route`, `ip_neigh`,
`ps`, `uptime`, `false`, `sleep`, `ping`, and `nc`. `sleep` accepts `seconds` from 1–30;
`ping` accepts a topology-node `host` and count from 1–4; `nc` accepts a topology-node `host`, a
port from 1–65535, and a boolean `listen` flag. Targets and command hosts must exist in the
required topology, and SSH execution is restricted to L1 nodes declaring an `ssh` service.

Actions can assert `success` or `detail`, and observations can assert bounded
`duration_seconds` (`minimum`, `maximum`, or `equals`) or `stdout` (`equals` or a regular-expression
`pattern` of at most 128 characters). Cleanup actions are executed from `finally` before the
declared deployment cleanup policy is applied, including when a step fails or times out.

## Worked example

The profile-addressed pair in [scenario-studio.yml](../examples/topologies/scenario-studio.yml)
declares an SSH service and a static HTTP service on `server`. The corresponding
[operator-authored.yml](../examples/scenarios/operator-authored.yml) mixes ICMP, a TCP service
probe, `ssh_exec`, a wait, output/timing assertions, and a cleanup wait:

```yaml
sequence:
  - {id: reach-server, kind: icmp_probe, source: client, target: server}
  - {id: inspect-web, kind: tcp_probe, source: client, target: server, service: web}
  - {id: inspect-address, kind: ssh_exec, target: server, command: ip_addr}
  - {id: pause, kind: wait, seconds: 0.1}
success_conditions:
  - {action: reach-server, field: success, equals: true}
  - {action: inspect-web, field: success, equals: true}
  - {action: inspect-address, field: stdout, pattern: '192\.168\.239\.22'}
  - {action: inspect-address, field: duration_seconds, minimum: 0, maximum: 10}
cleanup:
  - {id: cleanup-pause, kind: wait, seconds: 0.1}
```

Run it after loading and deploying the topology:

```bash
curl -X POST http://127.0.0.1:8080/v1/topologies \
  -H 'content-type: application/json' --data-binary @examples/topologies/scenario-studio.yml
curl -X POST http://127.0.0.1:8080/v1/scenarios \
  -H 'content-type: application/json' --data-binary @examples/scenarios/operator-authored.yml
curl -X POST http://127.0.0.1:8080/v1/deployments/scenario-studio
```

The V.5 integration gate runs this operator-authored document once with a matching output pattern
and once with an intentionally impossible pattern. It records both the successful and deliberately
failed results, then verifies that the scenario survives a fresh `ControlPlane` instance.
