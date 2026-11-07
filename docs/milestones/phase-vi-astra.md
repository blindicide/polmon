# Phase VI intermediate closeout

VERSION: core 0.7.0rc1; optional addon 0.1.0rc1; planned SemVer tag v0.7.0-rc.1.
STATUS: PARTIAL / RELEASE BLOCKED — resource analytics implemented; VM runtime/acceptance unavailable.

IMPLEMENTED: bounded on-demand node/deployment CPU/RSS/I/O and namespace counters,
identity attribution, missing/shared/gap metadata and JSON export. Discovery queues,
thread enumeration and child reads are bounded. Non-POSIX counters fail unavailable.
The separate VM package provides typed models, validation, read-only clone/network
plans and static seed documents. Runtime lifecycle, acquisition, ISO creation and
recovery all refuse with `vm.scaffold_only`, including on capable hosts.

TESTS EXECUTED / TEST RESULTS: exact final commands, exit codes, local evidence,
commit/tag/Actions results and full inventories are maintained in the authoritative
[handoff](../history/HANDOFF-PHASE-VI-ASTRA.md). Historical raw evidence remains in
`docs/evidence/phase-vi-astra/`; the previous 491 rootless and 23 privileged passes
are historical, not final-candidate evidence. VM integration is NOT RUN.

FAILURES AND CORRECTIONS: prior collection filename collision and wrong API key
were corrected; direct Hatchling was absent and an offline isolated wheel build
succeeded. During closeout, offline lock refresh lacked a cached PyYAML wheel;
normal metadata resolution succeeded without dependency changes beyond the project
version. The prior unvalidated VM runtime exceeded the scaffold instruction and
was replaced with explicit refusals; fake runtime tests were replaced by boundary
contracts. Existing storage-only QCOW2 coverage remains distinct from guest tests.

RESOURCE OBSERVATIONS: historical real namespace service logs report about 19 MiB
RSS across two processes and 0.02 CPU seconds, with readable namespace network
counters and unavailable disk I/O. Historical 16 MiB empty-disk QCOW2 tests prove
storage isolation only. Fresh small namespace observations appear in the final
privileged gate. No large L0 run was repeated. VM RAM/emulator allowances are
configuration estimates; no guest footprint was measured. RSS is not PSS/kernel
memory; core history is volatile/on demand and counters may be incomplete.

KNOWN LIMITATIONS: no `/dev/kvm` or vmx/svm flags, emulator or seed tool. Runtime
installation/module loads/downloads/image builds/TCG/VM launches are forbidden on
this host. No real guest, networking/services, guest-written clone isolation,
VM resource or cleanup acceptance. Runtime/admission/recovery and guest metrics
remain unimplemented, as do mixed-fidelity/GUI/scenario/SSH/VNC VM integration.
Full capable-machine acceptance steps are in the addon README and handoff.

FILES CHANGED / COMMIT: see the handoff and `git log` on
`frontier/2026-10-polmon`; analytics began at `ac1bb6b`. Operator mandates,
accounting/brief, CI task and preserved October 22 L0 CSV/JSON remain untouched,
uncommitted and excluded from release assets. Historical raw logs remain local.

NEXT MILESTONE: implement and independently accept real KVM functionality on an
explicitly authorized capable machine. An intermediate prerelease is not VM
acceptance; its native release workflow must finish successfully before publication
can be reported as verified. No quota is inferred from tokens or old ledgers.

Release attempt: annotated `v0.7.0-rc.1` points to
`16b8f4ad7c7a446aad68acd509be09b88bac28df`. Native workflow `39771278495`
passed candidate metadata, then Windows collection failed on the `tests.integration`
import in `test_live_resource_analytics.py`. Remaining builds and downstream release/verification were cancelled; final run
state is completed/cancelled after the Windows failure. Zero artifacts were produced;
the handoff records terminal results. No GitHub prerelease/assets
were created. Fix portability on a fresh candidate and rerun native gates;
never move the failed tag or bypass verification. Main is unchanged.
