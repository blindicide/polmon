#!/usr/bin/env bash
# Explicit real VM gate; exit 2 means environment unavailable, never a mock pass.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$root/addons/l1-vm/src${PYTHONPATH:+:$PYTHONPATH}"
"$root/.venv/bin/python" -m polmon_l1_vm.cli readiness || {
  echo 'NOT RUN — environment unavailable: see readiness reason codes above' >&2
  exit 2
}
if [[ -z "${POLMON_VM_TEST_IMAGE:-}" || -z "${POLMON_VM_TEST_MANIFEST:-}" ]]; then
  echo 'NOT RUN — environment unavailable: vm.pinned_image_unconfigured' >&2
  exit 2
fi
exec "$root/scripts/privileged-tests.sh" tests/integration/test_vm_guest.py -s
