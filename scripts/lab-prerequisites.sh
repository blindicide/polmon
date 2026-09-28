#!/usr/bin/env bash
# Read-only prerequisite check for the L1 lab and SSH console.
set -euo pipefail

if [[ "${1:-}" == "--create-lab-account" ]]; then
  echo "NOT RUN — console.account_policy_existing_user: polmon uses the invoking unprivileged account" >&2
  echo "Run the backend as the dedicated unprivileged operator account; no host account is created." >&2
  exit 2
fi

status=0
for tool in ip sudo setpriv ping ssh sshd ssh-keygen; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "MISSING: $tool" >&2
    status=1
  else
    echo "OK: $tool=$(command -v "$tool")"
  fi
done
if [[ "$(id -u)" == 0 ]]; then
  echo "REFUSED: run the backend under a dedicated unprivileged account" >&2
  status=1
fi
if ! sudo -n ip netns list >/dev/null 2>&1; then
  echo "MISSING: passwordless sudo for ip netns" >&2
  status=1
fi
exit "$status"
