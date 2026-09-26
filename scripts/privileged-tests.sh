#!/usr/bin/env bash
# Run the privileged laboratory tests and prove the host network was left untouched.
#
# Snapshots the default route, the host's non-lab interfaces, iptables rules and the nft ruleset
# (packet counters normalised) before and after pytest, then fails if anything differs or if any
# platform-owned namespace or interface remains. Requires passwordless sudo that is authorised for
# laboratory networking only (see SECURITY.md).
# Usage: scripts/privileged-tests.sh [pytest selection, default: -m privileged]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="$root/.venv/bin/python"
[[ -x "$python" ]] || { echo "error: $python not found" >&2; exit 1; }
if ! sudo -n ip netns list >/dev/null 2>&1; then
  echo "NOT RUN — environment unavailable: passwordless sudo for 'ip netns' is required" >&2
  exit 2
fi

lab_pattern='^(polmon[0-9a-f]{8}[nbt]|veth[0-9a-f]{8}[hp])$'

snapshot() {
  echo "# default route"
  ip route show default
  echo "# host interfaces (platform lab interfaces excluded)"
  ip -o link show | awk -F': ' '{print $2}' | sed 's/@.*//' | grep -Ev "$lab_pattern" | sort
  echo "# iptables"
  sudo -n iptables -S 2>/dev/null | sort || echo "iptables unavailable"
  echo "# nft (counters normalised)"
  sudo -n nft list ruleset 2>/dev/null \
    | sed -E 's/counter packets [0-9]+ bytes [0-9]+/counter/g' || echo "nft unavailable"
}

leftovers() {
  sudo -n ip netns list | awk '{print $1}' | grep -E '^polmon' || true
  ip -o link show | awk -F': ' '{print $2}' | sed 's/@.*//' | grep -E "$lab_pattern" || true
}

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
existing="$(leftovers)"
if [[ -n "$existing" ]]; then
  echo "error: platform lab resources already exist; inspect with scripts/lab-cleanup.sh:" >&2
  echo "$existing" >&2
  exit 1
fi

snapshot > "$workdir/before"
cd "$root"
status=0
if [[ $# -eq 0 ]]; then set -- -m privileged; fi
"$python" -m pytest "$@" || status=$?
snapshot > "$workdir/after"

if ! diff -u "$workdir/before" "$workdir/after"; then
  echo "FAIL: host network state changed during the privileged run" >&2
  exit 1
fi
remaining="$(leftovers)"
if [[ -n "$remaining" ]]; then
  echo "FAIL: platform lab resources remain after the run:" >&2
  echo "$remaining" >&2
  exit 1
fi
echo "host network unchanged; no platform lab resources remain" >&2
exit "$status"
