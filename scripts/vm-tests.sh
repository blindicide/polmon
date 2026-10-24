#!/usr/bin/env bash
# Явная проверка на настоящих гостях KVM; код 2 — среда недоступна, а не успешный прогон.
# Использование: scripts/vm-tests.sh [userns|netns]
#   userns (по умолчанию) — без sudo, в пользовательском и сетевом пространстве имён;
#   netns — именованное пространство через sudo, обёрнуто в scripts/privileged-tests.sh.
# Образ: POLMON_VM_TEST_IMAGE (получить: polmon-l1-vm acquire-image --manifest ... --image ...);
# манифест по умолчанию: examples/vm/alpine-3.24.1-manifest.json.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-userns}"
[[ "$mode" == userns || "$mode" == netns ]] || { echo "usage: $0 [userns|netns]" >&2; exit 64; }
export PYTHONPATH="$root/addons/l1-vm/src${PYTHONPATH:+:$PYTHONPATH}"
export POLMON_VM_TEST_MANIFEST="${POLMON_VM_TEST_MANIFEST:-$root/examples/vm/alpine-3.24.1-manifest.json}"
"$root/.venv/bin/python" -m polmon_l1_vm.cli readiness || {
  echo 'NOT RUN — environment unavailable: see readiness reason codes above' >&2
  exit 2
}
if [[ -z "${POLMON_VM_TEST_IMAGE:-}" ]]; then
  echo 'NOT RUN — environment unavailable: vm.pinned_image_unconfigured (set POLMON_VM_TEST_IMAGE)' >&2
  exit 2
fi
"$root/.venv/bin/python" -m polmon_l1_vm.cli verify-image \
  --manifest "$POLMON_VM_TEST_MANIFEST" --image "$POLMON_VM_TEST_IMAGE" >/dev/null || {
  echo 'NOT RUN — environment unavailable: image failed verification' >&2
  exit 2
}
if [[ "$mode" == netns ]]; then
  exec "$root/scripts/privileged-tests.sh" tests/integration/test_vm_guest.py -k netns -s
fi
cd "$root"
exec "$root/.venv/bin/python" -m pytest tests/integration/test_vm_guest.py -k userns -s
