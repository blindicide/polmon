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

## Current experimental runtime candidate

The scaffold-only closeout is historical. The current addon implements QEMU/KVM lifecycle,
image acquisition, isolated userns/netns networking, probes and recovery; core exposes
`/v1/vm/*` and the client has a VM page. Linux client bundles include the addon and pinned
read-only image. See [the addon README](../addons/l1-vm/README.md).

Real guest acceptance is **NOT RUN** in this executor: `/dev/kvm`, the QEMU system emulator
and ISO tools are absent, and user namespace creation is denied. Neither network mode is
accepted on the basis of source, fake, QCOW storage or packaging checks. Independent guest
boot, networking, guest-written clone isolation, measured costs and failure cleanup remain
required for VM functional/security claims. An honestly limited experimental prerelease is
permitted after runnable local/native gates pass (see RELEASE.md and SECURITY.md).

Still open: real guest acceptance in both modes, mixed L0/namespace attachment, scenarios,
SSH/VNC to guests, guest-side metrics and persistent VM time series. Resource history for
namespace deployments remains separate from addon VM measurements.

## Historical intermediate candidate

`v0.7.0-rc.1` points to `16b8f4ad7c7a446aad68acd509be09b88bac28df` and is immutable.
Its original run `39771278495` failed Windows test collection. A later repair run
`39931136601` uploaded release assets but ended cancelled; post-publication verification
was cancelled. Those assets are not a fully verified release. The current candidate uses a
new version/tag and fixes test-helper imports without deselecting runnable Windows tests.
The [Phase VI handoff](history/HANDOFF-PHASE-VI-ASTRA.md) preserves the earlier closeout record.
