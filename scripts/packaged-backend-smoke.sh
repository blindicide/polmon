#!/usr/bin/env bash
# Drive a listening packaged backend through a real L0 workflow, then probe L1 honestly.
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 URL TOKEN READINESS_JSON OUTPUT_JSON" >&2
  exit 2
fi
url=$1
token=$2
readiness=$3
output=$4
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT

request() {
  local method=$1 path=$2 data=${3:-}
  local args=(-fsS -X "$method" -H "Authorization: Bearer $token" -H 'Accept: application/json')
  if [[ -n $data ]]; then
    # Body on stdin: no file path reaches curl, so Git Bash on Windows needs no path conversion.
    curl "${args[@]}" -H 'Content-Type: application/json' --data-binary @- "$url$path" < "$data"
  else
    curl "${args[@]}" "$url$path"
  fi
}

request GET /v1/health > "$scratch/health.json"
jq -e '.name == "polmon" and .status == "ok"' "$scratch/health.json" >/dev/null
jq -Rs '{yaml: .}' examples/topologies/l0-office.yml > "$scratch/topology-request.json"
request POST /v1/topologies "$scratch/topology-request.json" > "$scratch/topology.json"
request POST /v1/deployments/l0-office > "$scratch/deployment.json"
jq -e '.state == "running" and .backend == "synthetic"' "$scratch/deployment.json" >/dev/null
jq -n --rawfile scenario examples/scenarios/office-sweep.yml '{
  experiment_id: "packaged-linux-smoke",
  topology_id: "l0-office",
  scenario_yaml: $scenario
}' > "$scratch/experiment-request.json"
request POST /v1/experiments "$scratch/experiment-request.json" > "$scratch/experiment.json"
jq -e '.status == "succeeded"' "$scratch/experiment.json" >/dev/null
request GET /v1/experiments/packaged-linux-smoke/telemetry > "$scratch/telemetry.json"
jq -e 'length > 0' "$scratch/telemetry.json" >/dev/null
request GET /v1/experiments/packaged-linux-smoke/report > "$scratch/report.json"
jq -e '.status == "succeeded"' "$scratch/report.json" >/dev/null
request GET /v1/experiments/packaged-linux-smoke/report/markdown > "$scratch/markdown.json"
jq -e '.markdown | length > 0' "$scratch/markdown.json" >/dev/null
request GET /v1/resources > "$scratch/resources.json"
jq -e '.snapshot.process_rss_bytes > 0' "$scratch/resources.json" >/dev/null
request POST /v1/reset > "$scratch/reset.json"
jq -e '.state == "reset" and .deployments_destroyed == 1' "$scratch/reset.json" >/dev/null

jq -Rs '{yaml: .}' examples/topologies/l1-two-node.yml > "$scratch/l1-request.json"
request POST /v1/topologies "$scratch/l1-request.json" > "$scratch/l1-load.json"
if jq -e '.l1_ready' "$readiness" >/dev/null; then
  request POST /v1/deployments/l1-two-node > "$scratch/l1-result.json"
  jq -e '.state == "running" and .backend == "namespace"' "$scratch/l1-result.json" >/dev/null
  request DELETE /v1/deployments/l1-two-node > "$scratch/l1-cleanup.json"
  jq -e '.state == "destroyed"' "$scratch/l1-cleanup.json" >/dev/null
  l1_outcome=passed
else
  status=$(curl -sS -o "$scratch/l1-result.json" -w '%{http_code}' -X POST \
    -H "Authorization: Bearer $token" "$url/v1/deployments/l1-two-node")
  test "$status" = 422
  jq -e '.error.message | contains("Linux host")' "$scratch/l1-result.json" >/dev/null
  l1_outcome="NOT RUN - environment unavailable"
fi

jq -n \
  --slurpfile health "$scratch/health.json" \
  --slurpfile deployment "$scratch/deployment.json" \
  --slurpfile experiment "$scratch/experiment.json" \
  --slurpfile telemetry "$scratch/telemetry.json" \
  --slurpfile report "$scratch/report.json" \
  --slurpfile reset "$scratch/reset.json" \
  --slurpfile resources "$scratch/resources.json" \
  --slurpfile readiness "$readiness" \
  --slurpfile l1 "$scratch/l1-result.json" \
  --arg l1_outcome "$l1_outcome" '{
    health: $health[0],
    deployment: $deployment[0],
    experiment_status: $experiment[0].status,
    telemetry_events: ($telemetry[0] | length),
    report_status: $report[0].status,
    reset: $reset[0],
    backend_rss_bytes: $resources[0].snapshot.process_rss_bytes,
    capabilities: $resources[0].capabilities,
    readiness: $readiness[0],
    l1_outcome: $l1_outcome,
    l1_result: $l1[0]
  }' > "$output"
cat "$output"
