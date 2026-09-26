#!/usr/bin/env bash
# Start an extracted packaged backend with a scrubbed environment (env -i: no venv, no Python on
# PATH), drive packaged-backend-smoke.sh against it, measure it, and stop it gracefully.
#
# Usage: scripts/packaged-backend-e2e.sh BACKEND PREFIX [SEARCH_PATH]
#   BACKEND      path to the extracted polmon-backend executable
#   PREFIX       output prefix: PREFIX-readiness.json, PREFIX-e2e.json, PREFIX.log,
#                PREFIX-measurements.json
#   SEARCH_PATH  PATH given to the backend (default /usr/bin:/bin). A directory without sudo is
#                the negative control: L1 must then be refused cleanly with HTTP 422.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 BACKEND PREFIX [SEARCH_PATH]" >&2
  exit 2
fi
backend=$(realpath "$1")
prefix=$(realpath -m "$2")
search_path=${3:-/usr/bin:/bin}
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data=$(mktemp -d)

set +e
env -i PATH="$search_path" LANG=C.UTF-8 HOME="$data" "$backend" --lab-readiness \
  > "$prefix-readiness.json"
readiness_status=$?
set -e
[[ $readiness_status == 0 || $readiness_status == 2 ]] || {
  echo "--lab-readiness failed with $readiness_status" >&2
  exit 1
}

port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
(cd "$data" && exec env -i PATH="$search_path" LANG=C.UTF-8 HOME="$data" \
  POLMON_API_TOKEN="$token" "$backend" --host 127.0.0.1 --port "$port") > "$prefix.log" 2>&1 &
pid=$!
trap 'kill -TERM "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -rf -- "$data"' EXIT
started=$(date +%s.%N)
for _ in $(seq 1 200); do
  curl -fsS "http://127.0.0.1:${port}/v1/health" >/dev/null 2>&1 && break
  kill -0 "$pid" 2>/dev/null || { cat "$prefix.log" >&2; exit 1; }
  sleep 0.05
done
ready=$(date +%s.%N)

(cd "$root" && scripts/packaged-backend-smoke.sh "http://127.0.0.1:${port}" "$token" \
  "$prefix-readiness.json" "$prefix-e2e.json") >/dev/null
rss_kib=$(ps -o rss= -p "$pid" | tr -d ' ')

kill -TERM "$pid"
set +e
wait "$pid"
stop_status=$?
set -e
trap 'rm -rf -- "$data"' EXIT
[[ $stop_status == 0 || $stop_status == 143 ]] || { echo "stop status $stop_status" >&2; exit 1; }
grep -q '"event":"shutdown_cleanup"' "$prefix.log"
if kill -0 "$pid" 2>/dev/null; then echo "backend $pid still running" >&2; exit 1; fi

jq -n \
  --argjson rss_kib "$rss_kib" \
  --argjson ready "$(python3 -c "print(round($ready - $started, 3))")" \
  --argjson bundle "$(du -sb "$(dirname "$backend")" | cut -f1)" \
  --arg search_path "$search_path" '{
    backend_rss_bytes_after_workflow: ($rss_kib * 1024),
    seconds_to_healthy: $ready,
    extracted_bundle_bytes: $bundle,
    search_path: $search_path
  }' > "$prefix-measurements.json"
jq '{readiness: {l1_ready: .readiness.l1_ready}, experiment_status, telemetry_events,
     report_status, l1_outcome, l1_state: .l1_result.state, l1_error: .l1_result.error}' \
  "$prefix-e2e.json"
cat "$prefix-measurements.json"
