# Optional VM-backed L1 addon

Runs L1 nodes as real QEMU/KVM guests instead of network namespaces. Core POLMON
stays namespace-backed; local clients stay L0-only; L2 is still refused. The addon is
a separate package (`polmon-l1-vm`) and the core backend never imports it: it runs
the addon's CLI as a subprocess job (see [docs/API.md](../../docs/API.md), `/v1/vm`).

## What works

- Two Alpine guests on an isolated network, no route out, no NAT, no host shares.
- Per-guest QCOW2 overlays over a verified read-only base; the base is never written.
- Unprivileged QEMU with `-sandbox`, KVM only, bounded CPU, memory, logs and time.
- Service probes against both guests, then measurements: host CPU time, RSS, I/O,
  TAP bytes and packets, overlay allocation, boot time.
- Teardown on success, failure, cancellation and crash recovery; the lab is always
  destroyed at the end of a run.
- Two lab modes:
  - `userns` — rootless, no sudo. Verified end to end with two real guests on KVM.
  - `netns` — named network namespace through passwordless `sudo -n`; QEMU drops to the
    owner uid. Implemented, **not integration-verified** (needs `sudo -v` and
    `POLMON_VM_TEST_IMAGE=<image> scripts/vm-tests.sh netns`).

## Image

The pinned Alpine 3.24.1 cloud image (`examples/vm/alpine-3.24.1-manifest.json`) ships
with the program. In a checkout it lives in `packaging/vm-image/` (git-ignored, about
175 MB); `scripts/fetch-vm-image.py` puts it there and checks the SHA-256. The packaged
backend includes it. If the bundled file is absent the addon falls back to a copy in the
backend data directory.

## Host requirements

Linux x86-64 with accessible `/dev/kvm`, `qemu-system-x86_64`, `qemu-img` and an ISO
tool (`genisoimage`). Nothing is installed for you; `readiness` reports what is missing.
The backend refuses VM jobs when it runs as root (`vm.running_as_root`).

## CLI

For source use set `PYTHONPATH=addons/l1-vm/src` and run
`.venv/bin/python -m polmon_l1_vm.cli <command>`:

| Command | Purpose |
|---|---|
| `readiness` | JSON host report: modes available, missing prerequisites |
| `plan` | Print the clone and network plan; changes nothing |
| `run` | Boot two guests, probe, sample, destroy; prints one JSON document |
| `verify-image` / `acquire-image` | Check, or download, the pinned image |
| `recover` | Remove leftovers of an interrupted run |
| `inspect` | Describe a run directory |

Errors print `{"error_code": "vm.…"}` to stderr and exit 2.

## Limits

Two guests, one vCPU and 256 MiB each, an estimated 64 MiB emulator allowance per guest,
a 768 MiB aggregate budget and a 256 MiB host reserve. Admission is rechecked at launch.
Disk needs the full overlay capacity plus a 512 MiB reserve.

## Not done

Attaching guests to L0/namespace nodes in one topology, scenarios, SSH/VNC to guests,
guest-side metrics and a persistent VM time series.
