# Phase VI continuation backlog

Baseline: `a307802`, `frontier/2026-10-polmon`, tracked/staged clean. Operator
instructions, accounting, brief, CI task and October 22 L0 results are excluded
from implementation commits. The prior Phase V report closes its seven milestones;
`SUMMARY-v0.6.0-frontier.md` records small L0/L1/target measurements. No separate
implementation backlog was found. The completed L0 large run will not be repeated.

1. **Bounded resource attribution and history.** Existing snapshots measure only the
   control process and host memory. Add timestamped node/deployment observations,
   process identity checks, CPU deltas, RSS, disk I/O, network counters where safely
   observable, explicit unavailable fields and bounded history/export. Acceptance:
   counter resets/PID reuse/missing data/gaps/shared ownership tests; actual Linux
   process observations; full rootless and localization gates. Keep configured
   memory separate from consumption; shared L0 process cost must never be charged
   independently to every endpoint.
2. **Optional standalone VM-backed L1 addon.** Separate installable Python package
   implementing the existing execution-backend lifecycle, explicitly selected by
   its CLI. Ordinary topology/API L1 semantics remain namespaces; L2 remains refused.
   Use QCOW2 overlays, verified operator-pinned base, bounded admission, an entirely
   isolated network namespace containing TAPs/bridges, unprivileged QEMU, static
   NoCloud configuration and deterministic teardown. Start with Alpine x86_64 BIOS
   cloud-init images: smaller distribution, standard Linux network stack; actual
   footprint remains unmeasured until a real guest can run. No bundled guest image,
   no automatic host installs, no guest package download/egress. Acceptance: image
   verification/refusal, real qemu-img clone isolation, failure cleanup, command
   containment, bounded limits; real VM boot + protocol/service/clone/cleanup gate
   only on a capable host. No mock qualifies as that gate.
3. **Operations, recovery and evidence.** Document installation, pinned image
   acquisition, costs/measurement provenance, supported lifecycle/API boundaries,
   bounded sampling/export and exact remaining integration gaps. Preserve raw gate
   logs. Commit only coherent code with passing applicable local gates.

## Status update: VM runtime implemented

The scaffold-only state described below is historical. The addon now boots two real Alpine
guests on KVM in rootless (`userns`) mode and the integration test passes; the `netns` mode
is implemented but not integration-verified. Core exposes `/v1/vm/*`, the client has a
Virtual machines page, and the guest image ships with the program. See
[the addon README](../addons/l1-vm/README.md). Still open: `netns` verification, attaching
guests to L0/namespace nodes, scenarios and SSH/VNC to guests, guest-side metrics.

## Host and scope decisions

Rechecked: `qemu-img` and `qemu-io` exist; `qemu-system-x86_64`, `/dev/kvm`, and
CPU vmx/svm flags are absent. No host install is authorized. Cloud environment
status tool and policy snapshot are unavailable in this executor. No credentials
were inspected. Existing unrelated Claude sessions have different working trees;
the POLMON pane is the active Codex harness, not the fulfilled old Claude draft.

The addon is a full OS VM with higher costs than namespace L1. Its separate CLI
makes the fidelity explicit and avoids exposing an unvalidated VM action through
existing namespace console/scenario APIs. Cross-addon L0/namespace attachment and
GUI VM controls are deferred until real VM integration can validate the boundary.
They must be reported as limitations, never implied by ordinary L1 support.

## Closeout correction and remaining backlog

The previous draft exceeded the scaffold-only instruction by providing unvalidated
VM runtime/acquisition/recovery code. Intermediate closeout removed those paths;
all VM lifecycle calls now fail explicitly with `vm.scaffold_only`, even if host
prerequisites exist. Pure configuration/clone/network/seed plans and storage-only
utilities remain. Historical logs are retained, without treating fake coverage or
empty-disk QCOW2 tests as guest evidence.

Resource history is implemented and measured on a real namespace HTTP service;
discovery, task enumeration, child-list reads and retention are bounded. Non-POSIX
process counters return unavailable rather than failing on Windows.

Remaining work, in order: implement and accept real KVM lifecycle/isolation/
admission/recovery on an authorized capable host; validate guest networking,
services and guest-written clone isolation; measure full VM resource costs and
failure cleanup; then consider mixed-fidelity attachment and UI integration.
Exact current gates/publication status: [handoff](../HANDOFF-PHASE-VI-ASTRA.md).

## Intermediate release blocker

`v0.7.0-rc.1` / candidate `16b8f4a` reached native workflow `39771278495` but
Windows pytest collection failed: `test_live_resource_analytics.py` imports
`tests.integration`, unavailable under that entry-point invocation. Publication
stopped under the mandate; no GitHub prerelease/assets exist. Before another
release, fix helper import portability, reproduce the actual pytest entry point,
rerun affected full/native gates and use a fresh version/tag. The failed tag is
immutable. Real VM work remains separately blocked as above.
