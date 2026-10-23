# Optional VM-backed L1 scaffold

**Status: non-executing scaffold. Real VM acceptance: NOT RUN.** Core POLMON
0.7.0rc1 and addon distribution 0.1.0rc1 are intermediate prereleases. Ordinary
L1 remains namespace-backed, local clients remain L0-only, and L2 stays refused.
The addon is separate from the core wheel and has no GUI/API dispatch.

The scaffold implements typed configuration, topology validation, clone/network
plans, capability detection, image digest/size contracts, and offline NoCloud
configuration generation. Every VM lifecycle operation, image acquisition,
seed ISO creation and recovery raises `vm.scaffold_only` before mutation.
Even on a capable host `readiness` remains false until a runtime is implemented
and independently accepted. No VM boot, networking, services, guest-written clone
isolation, guest footprint or VM cleanup is claimed.

## Installation and read-only planning

Use Python 3.12 and matching core/addon wheels, or install the checkout and
`pip install --no-deps ./addons/l1-vm` in a project virtual environment. No VM
runtime, image or heavy dependency is installed by either package.

`polmon-l1-vm --version` reports the core version. `polmon-l1-vm readiness` prints
JSON and exits 2 with stable missing capability codes and `vm.scaffold_only`.
For source use, set `PYTHONPATH=addons/l1-vm/src` and invoke
`.venv/bin/python -m polmon_l1_vm.cli`.

An operator-reviewed image manifest is required for a read-only plan:

- `schema_version`: 1;
- `sha256`: reviewed lowercase SHA-256, 64 characters;
- `source_url`: exact immutable HTTPS artifact URL;
- `distribution`: `alpine-<actual-version>-x86_64-bios-cloudinit`;
- `license_notice`: publisher/package licensing and source notice;
- `max_file_bytes`: default 512 MiB, maximum 1 GiB;
- `max_virtual_bytes`: default 2 GiB, maximum 4 GiB.

No guest image, approved URL or digest is provided. The distribution is an
operator assertion; a matching digest alone establishes neither OS identity nor
trust. The historical storage fixture is an empty disk, never a Linux guest.

```sh
polmon-l1-vm plan --manifest /lab/reviewed-image.json --image /lab/base.qcow2 \
  --topology examples/topologies/l1-vm-addon.yml --directory /lab/runs/planned
```

This only parses a small manifest/topology and prints a plan; it does not read or
create the image/run directory. Prototype `run`, `recover`, `acquire-image`,
`verify-image` and `inspect` CLI commands explicitly refuse execution.

## Resource and isolation contracts to implement

Full OS VMs have different costs and fidelity from namespaces. Default planning
limits are two guests, one vCPU and 256 MiB configured RAM per guest, an **estimated**
64 MiB emulator allowance each, a 768 MiB aggregate memory budget and a 256 MiB
host memory reserve. There is no measured VM overhead, runtime admission,
cgroup enforcement or global reservation. Never treat swap as guest RAM.

A future runtime must reserve full overlay virtual capacity, metadata/seed margin
and a 512 MiB disk reserve. It must recheck memory/disk availability at launch
and during observation. Shared base allocation must be counted once; configured
RAM must remain separate from host RSS and guest-reported consumption.

Clone contracts require exclusive per-node QCOW2 overlays, stable UUID/MAC/IP,
independent hostnames and seed identities, and a verified read-only base without
backing chains or external data. The existing bounded `verify_image` and
`OverlayStore` utilities cover storage plumbing only. `seed_documents` produces
configuration text with static lab addresses, no gateway/DNS/package installation,
and a proposed BusyBox HTTP identity page. ISO construction is unavailable.

All future TAPs and bridges must live within a dedicated lab namespace, with
no host uplink, NAT, firewall changes, helper scripts, user networking or host
shares. QEMU must be unprivileged and KVM-only with bounded CPU/RAM/logs/time.
Guest runtime, namespace attachment and recovery remain unimplemented. No
namespace/container/mock or TCG substitute qualifies as VM acceptance.

Future recovery must journal ownership before mutation, pin boot/PID-start/netns
identities, refuse uncertain ownership and live owners, and preserve evidence.
Cleanup must prove no VM process, TAP, bridge, namespace, overlay or seed remains
following success, failure, interruption or crash. Do not infer this from the
existing namespace backend's separate recovery implementation.

## Current evidence and remaining acceptance

This host has no `/dev/kvm` or vmx/svm CPU flags, no system emulator and no seed
ISO tool. Runtime installation, module loading, image downloads/builds, TCG and
VM launches are forbidden here. No such operation was attempted in closeout.
The explicit `scripts/vm-tests.sh` gate is NOT RUN; readiness checks and unit
contracts are not guest integration. Historical raw logs are preserved under
`docs/evidence/phase-vi-astra/`; current exact commands/results are in
[the handoff](../../HANDOFF-PHASE-VI-ASTRA.md).

On a separately authorized capable Linux x86_64 lab:

1. Verify accessible KVM/TUN and reviewed emulator/seed-tool prerequisites,
   hardware virtualization, lab privileges and resource headroom. Record versions.
2. Independently review a pinned guest image, publisher signature/digest and
   licensing. Retain provenance; never use the empty storage-test disk as a guest.
3. Implement the runtime and remove scaffold refusals only with real lifecycle,
   admission, ownership/recovery and bounded-output evidence. Implement the real
   integration test; its present guard cannot pass the missing runtime.
4. Boot two clones under isolated TAP/bridge networking. Capture guest-written
   identities, ICMP, declared TCP/HTTP services, bidirectional inter-guest traffic,
   route/DNS/host isolation and deliberate failure behavior.
5. Write different data inside each guest; verify sibling/base independence and
   unchanged base hash, then restart/reset and verify disposable state semantics.
6. Measure per-process host CPU/RSS/I/O, guest memory if available, disk virtual/
   allocated/base/overlay costs, TAP bytes/packets, boot/lifecycle timings and host
   headroom under bounded duration/count. Label unavailable data as null.
7. Exercise normal teardown, failed launch/boot/service, cancellation, crash and
   recovery under `scripts/privileged-tests.sh -- COMMAND`. Prove host-network
   invariance and no owned process/network/disk leftovers; preserve raw reports.
8. Run the completed `scripts/vm-tests.sh` with reviewed image/manifest paths,
   plus rootless/localization/package gates. Only then claim VM acceptance.

Cross-addon L0/namespace attachment, GUI/scenario/SSH/VNC integration, guest metrics
and a persistent VM time series remain additional work. Core resource history is
volatile/on demand, bounded by count/bytes/interval; procfs RSS is not PSS or kernel
memory, and absent/unregistered counters remain unavailable.
