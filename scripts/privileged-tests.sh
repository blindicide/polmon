#!/usr/bin/env bash
# Run the privileged laboratory tests and prove the host network was left untouched.
#
# Snapshots the default route, the host's non-lab interfaces, iptables rules and the nft ruleset
# structure (counters and set elements omitted) before and after pytest, then fails if anything
# differs, if any platform-owned namespace or interface remains, or if a new lab process outlived
# the run (a process of this user outside the host network namespace, or any
# `ip netns exec polmon…` launcher). Requires passwordless sudo that is authorised for laboratory
# networking only (see SECURITY.md).
# Usage: scripts/privileged-tests.sh [pytest selection, default: -m privileged]
#        scripts/privileged-tests.sh -- COMMAND [ARGS...]   (guard any command, e.g. a GUI demo)
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
  # Structure only: -s drops counters and -t drops set elements, so dynamic ban lists maintained
  # by host services (e.g. fail2ban) do not register, while any table, chain, or rule change does.
  echo "# nft ruleset structure"
  sudo -n nft -s -t list ruleset 2>/dev/null || echo "nft unavailable"
}

leftovers() {
  sudo -n ip netns list | awk '{print $1}' | grep -E '^polmon' || true
  ip -o link show | awk -F': ' '{print $2}' | sed 's/@.*//' | grep -E "$lab_pattern" || true
}

lab_processes() {
  local host dir args ns launcher='ip netns exec polmon[0-9a-f]{8}n'
  host="$(readlink /proc/self/ns/net)"
  for dir in /proc/[0-9]*; do
    args="$(tr '\0' ' ' < "$dir/cmdline" 2>/dev/null)" || continue
    # Skip empty (kernel) command lines and this script, whose arguments may name a launcher.
    [[ -n "$args" && "$args" != *privileged-tests.sh* ]] || continue
    # Another user's namespace link is unreadable; launchers are still found by command line.
    ns="$(readlink "$dir/ns/net" 2>/dev/null)" || ns=""
    if [[ ( -n "$ns" && "$ns" != "$host" ) || "$args" =~ $launcher ]]; then
      echo "${dir#/proc/} ${ns:-?} ${args:0:160}"
    fi
  done | sort
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
lab_processes > "$workdir/processes-before"
cd "$root"
status=0
if [[ "${1:-}" == "--" ]]; then
  shift
  "$@" || status=$?
else
  if [[ $# -eq 0 ]]; then set -- -m privileged; fi
  "$python" -m pytest "$@" || status=$?
fi
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
# Teardown signals are asynchronous: allow stragglers a moment before calling them leaked.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  leaked="$(lab_processes | comm -13 "$workdir/processes-before" -)"
  [[ -z "$leaked" ]] && break
  sleep 0.5
done
if [[ -n "$leaked" ]]; then
  echo "FAIL: lab processes outlived the run (pid netns command):" >&2
  echo "$leaked" >&2
  exit 1
fi
echo "host network unchanged; no platform lab resources or processes remain" >&2
exit "$status"
