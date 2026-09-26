#!/usr/bin/env bash
# Run the recorded benchmark suite, retain raw JSON/CSV, and regenerate the Markdown summary.
#
# L0 sizes 10/25/50 always run; 100/250 only with --large. L1 and the Phase I target
# (50 L0 + 2 L1) run when the privileged lab is available and are recorded as NOT RUN otherwise.
# Usage: scripts/run-benchmarks.sh [--large] [--repeats N] [--output-dir DIR]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
benchmark="$root/.venv/bin/polmon-benchmark"
[[ -x "$benchmark" ]] || { echo "error: $benchmark not found; install the project" >&2; exit 1; }

large=()
repeats=5
output_dir="$root/benchmarks/results"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --large) large=(--large); shift ;;
    --repeats) repeats="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    *) echo "usage: $0 [--large] [--repeats N] [--output-dir DIR]" >&2; exit 64 ;;
  esac
done

mkdir -p "$output_dir"
marker="$(mktemp)"
trap 'rm -f "$marker"' EXIT
failures=0
"$benchmark" l0 "${large[@]}" --repeats "$repeats" --output-dir "$output_dir" || failures=$((failures + 1))
for kind in l1 target; do
  code=0
  "$benchmark" "$kind" --repeats "$repeats" --output-dir "$output_dir" || code=$?
  if [[ $code -eq 2 ]]; then
    echo "$kind: NOT RUN — environment unavailable (recorded in $output_dir)" >&2
  elif [[ $code -ne 0 ]]; then
    failures=$((failures + 1))
  fi
done

mapfile -t new_results < <(find "$output_dir" -maxdepth 1 -name '*.json' -newer "$marker" | sort)
# The marker was created before the runs; fall back to every result if the clock is coarse.
if [[ ${#new_results[@]} -eq 0 ]]; then
  mapfile -t new_results < <(find "$output_dir" -maxdepth 1 -name '*.json' | sort)
fi
"$benchmark" summarize "${new_results[@]}" --output "$output_dir/SUMMARY-latest.md"
echo "summary: $output_dir/SUMMARY-latest.md" >&2
exit $((failures > 0 ? 1 : 0))
