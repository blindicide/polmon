# Optional VM-backed L1 addon

Experimental implementation of L1 nodes as QEMU/KVM guests instead of namespaces. Core POLMON
stays namespace-backed; local clients stay L0-only; L2 is still refused. The addon is
a separate package (`polmon-l1-vm`) and the core backend never imports it: it runs
the addon's CLI as a subprocess job (see [docs/API.md](../../docs/API.md), `/v1/vm`).

## Implemented scope (experimental)

- Two Alpine guests on an isolated network, no route out, no NAT, no host shares.
- Per-guest QCOW2 overlays over a verified read-only base; the base is never written.
- Unprivileged QEMU with `-sandbox`, KVM only, bounded CPU, memory, logs and time.
- Service probes against both guests, then measurements: host CPU time, RSS, I/O,
  TAP bytes and packets, overlay allocation, boot time.
- Teardown paths for success, failure and cancellation; identity-checked recovery refuses
  ambiguous ownership and preserves failed cleanup journals. Legacy journals require inspection.
- Explicit mixed topology selection (`run --vm-node ID`, repeatable): selected L1 nodes become
  VMs, remaining L1 nodes use nested Linux namespaces, and L0 peers use isolated TAP responders.
  All links stay inside the owned lab; ordinary core L1 dispatch remains namespace-backed.
- Two lab modes:
  - `userns` — rootless, no sudo.
  - `netns` — named network namespace through passwordless `sudo -n`; QEMU drops to the
    owner uid. Needs authorized passwordless sudo and
    `POLMON_VM_TEST_IMAGE=<image> scripts/vm-tests.sh netns`.

The original two-guest lifecycle gate passed in both modes; retained evidence is under
[`docs/evidence/vm-gate-20261107-pr4/`](../../docs/evidence/vm-gate-20261107-pr4/).
Real fault tests also cover crashes, partial startup, probe timeout, API cancel/timeout,
command SIGKILL and backend death/successor recovery. `scripts/vm-tests.sh` now runs lifecycle,
fault and mixed suites; `scripts/vm-gate.py --mode both --image PATH` retains their evidence.
Specific passing tests do not establish comprehensive VM/security acceptance:
`integration_verified` remains **false**. Published historical release acceptance is unchanged.

## Image

The pinned Alpine 3.24.1 cloud image (`examples/vm/alpine-3.24.1-manifest.json`) ships
with the program. In a checkout it lives in `packaging/vm-image/` (git-ignored, about
175 MB); `scripts/fetch-vm-image.py` puts it there and checks the SHA-256. The frozen Linux
client includes it and the addon; Windows and Python wheels do not. If the bundled file is
absent the addon falls back to a copy in the
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

For a mixed lab, pass `--topology examples/topologies/l1-vm-mixed.yml --vm-node guest`
with the usual `--manifest`, `--image` and `--directory` arguments. `--hold-seconds` keeps
the ready lab alive for a bounded interval (up to 600 seconds), then destroys it. Namespace
peers expose only declared static HTTP services; L0 supports ARP/ICMP, not TCP emulation.

## Limits

Two guests, one vCPU and 256 MiB each, an estimated 64 MiB emulator allowance per guest,
a 768 MiB aggregate budget and a 256 MiB host reserve. Admission is rechecked at launch.
Disk needs the full overlay capacity plus a 512 MiB reserve.

## Not done

Guest scenarios, SSH/VNC to guests, guest-side metrics and a persistent VM time series.
