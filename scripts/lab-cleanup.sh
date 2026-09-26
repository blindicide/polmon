#!/usr/bin/env bash
# List (default) or remove (--apply) leftover platform-owned laboratory resources.
#
# Processes still running inside a platform namespace (for example a lab service left behind by a
# killed backend) are listed and, with --apply, sent SIGTERM (then SIGKILL) before the namespace
# is deleted; a namespace name alone would otherwise vanish while the process kept running.
# Only names the platform generates are touched: namespaces and bridges/TAPs matching
# polmon<8 hex><n|b|t> and veth pairs matching veth<8 hex><h|p>. Container runtimes' veths
# (e.g. veth + 7 hex) and every other interface are never matched.
# Usage: scripts/lab-cleanup.sh [--apply]
set -euo pipefail

apply=false
case "${1:-}" in
  "") ;;
  --apply) apply=true ;;
  *) echo "usage: $0 [--apply]" >&2; exit 64 ;;
esac

namespace_pattern='^polmon[0-9a-f]{8}n$'
link_pattern='^(polmon[0-9a-f]{8}[bt]|veth[0-9a-f]{8}[hp])$'

if ! sudo -n ip netns list >/dev/null 2>&1; then
  echo "NOT RUN — environment unavailable: passwordless sudo for 'ip netns' is required" >&2
  exit 2
fi

mapfile -t namespaces < <(sudo -n ip netns list | awk '{print $1}' | grep -E "$namespace_pattern" || true)
mapfile -t links < <(ip -o link show | awk -F': ' '{print $2}' | sed 's/@.*//' \
  | grep -E "$link_pattern" || true)

processes=()
for name in "${namespaces[@]}"; do
  mapfile -t found < <(sudo -n ip netns pids "$name" 2>/dev/null || true)
  processes+=("${found[@]}")
done

if [[ ${#namespaces[@]} -eq 0 && ${#links[@]} -eq 0 ]]; then
  echo "no platform lab resources found"
  exit 0
fi
for pid in "${processes[@]}"; do
  echo "process $pid $(ps -o user=,args= -p "$pid" 2>/dev/null | cut -c1-120)"
done
for name in "${namespaces[@]}"; do echo "namespace $name"; done
for name in "${links[@]}"; do echo "link $name"; done
if [[ "$apply" != true ]]; then
  echo "dry run: re-run with --apply to remove the resources listed above" >&2
  exit 1
fi
if [[ ${#processes[@]} -gt 0 ]]; then
  # Lab services run as the unprivileged owner; their privileged launcher exits with them.
  kill -TERM "${processes[@]}" 2>/dev/null || true
  sleep 1
  for pid in "${processes[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || true; fi
  done
fi
for name in "${namespaces[@]}"; do sudo -n ip netns del "$name"; done
for name in "${links[@]}"; do
  # Deleting one veth end removes its peer; tolerate the already-removed half.
  sudo -n ip link del dev "$name" 2>/dev/null || true
done
echo "stopped ${#processes[@]} process(es); removed ${#namespaces[@]} namespace(s) and up to" \
  "${#links[@]} link(s)"
