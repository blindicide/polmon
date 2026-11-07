# Current state and PR #4 fixes

Last checked: 2026-11-07. This is a status snapshot, not a merge waiver or a
complete VM functional/security acceptance report.

## PR #4

[PR #4](https://github.com/blindicide/polmon/pull/4), `dev/no-kvm-hardening`, remains
draft and unmerged. The previous failing head was `1a99d08`:
[CI](https://github.com/blindicide/polmon/actions/runs/40130947922),
[VM gate](https://github.com/blindicide/polmon/actions/runs/40130948058).
Those failures were diagnosed and fixed, not waived:

- Windows log-streaming test raced asynchronous log-file creation.
- Userns HTTP probes appended an extra newline, rejecting valid guest identities.
- Netns source probes could not import the addon after sudo removed `PYTHONPATH`.
- Gate summaries lost measurements when pytest prefixed evidence with progress text.

The real-KVM lifecycle gate passed locally in **both userns and netns**, with two
guests per mode and no skips; see [the retained evidence](docs/evidence/vm-gate-20261107-pr4/).
All six GitHub checks at implementation head `baae249` passed: Linux, Windows, both
screenshot jobs, dependency audit and expanded two-mode KVM gate. These changes add
real fault/recovery and mixed-topology coverage and fix the pre-existing local dashboard
layout failure. [Hosted evidence](docs/evidence/vm-gate-20261107-pr4-expanded/) retains
the clean checkout's logs, JUnit, measurements and synthetic-merge provenance.

- Seven real-KVM fault cases passed in **each** of userns and netns: guest crash,
  readiness timeout, partial startup, API cancel/timeout, command SIGKILL, and backend
  death with successor recovery. Every case checked deterministic cleanup.
- Dashboard `test_language.py`: **5 passed** with unchanged 1440×900 assertions.
  Padding was reduced, not font size or visible content.
- Full GUI suites: **67 passed in Russian, 67 passed in English**.
- Rootless unit/integration: **546 passed, 11 skipped** (unconfigured real-VM tests).
  A separate temporary root avoids global socket-directory snapshots racing concurrent
  KVM tests; no assertion was weakened. Ruff, translation gates and client self-test passed.
- Mixed communication and rollback initially passed in both modes (**4 tests**); an outer
  process guard flagged unrelated Firefox sandbox processes. The expanded rerun passed
  rollback and pre-VM-start owner recovery in both modes (**4 passed**) but failed both
  communication tests during BIOS boot with KVM entry errors while VirtualBox was active.
  Its cleanup/host-network guard passed. This rerun is **not** passing guest acceptance.
- The hosted expanded gate passed **11 tests per mode, zero skips**, including lifecycle,
  seven fault cases and three mixed-network/rollback/recovery cases. It ran from a clean
  synthetic PR-merge checkout; PR #4 itself remains unmerged. Local host applications
  were not stopped and kernel settings were not changed.

See [docs/HANDOFF.md](docs/HANDOFF.md) for causes, fixes, validation and remaining
acceptance work. No check bypass, waiver or PR merge is authorized by this snapshot.

## Releases and runtime boundaries

- Core development metadata is `0.7.1`, with optional addon `0.1.1` pinned to that core;
  this is not a release. Stable release remains `v0.6.0`; published experimental
  `v0.7.0-rc.3` artifacts and their acceptance status are unchanged.
- Ordinary local client topologies remain L0-only on Windows and Linux. Namespace
  L1/hybrid execution needs an authorized Linux lab backend; L2 remains unsupported.
- The optional QEMU/KVM addon, `/v1/vm/*` jobs and VM page remain experimental, with
  `integration_verified: false`. Passing the two-guest lifecycle gate does not prove
  comprehensive VM or security acceptance.
- Mixed VM/L0/namespace labs are explicit addon selections, not changes to ordinary L1
  semantics. Guest scenarios, SSH/VNC integration, guest-side metrics and persistent VM
  time series remain unfinished.
- The v0.6.0 benchmark's 38.5 MiB for 50 L0 + 2 namespace L1 nodes is historical,
  not a VM cost claim; see [the summary](benchmarks/results/SUMMARY-v0.6.0-frontier.md).
- The executor is now a KVM-capable Linux laptop with the project virtual environment,
  not the earlier dependency-limited VM-hosted server. Local VM tests use isolated
  lab namespaces and verify host-network preservation and cleanup.
- [SECURITY.md](SECURITY.md) still applies: `sudo ip` is root-equivalent; production
  operation belongs on a dedicated lab host. No license has been granted, and
  Windows executables are unsigned.

## Next actions

1. Verify checks at the updated PR head; do not substitute this snapshot for live CI.
2. Preserve and review expanded raw VM evidence before broadening acceptance claims;
   selected fault tests do not establish comprehensive security acceptance.
3. Keep the 1440×900 layout contract and verify both GUI language suites on native CI.
4. The archived [Phase VI handoff](docs/history/HANDOFF-PHASE-VI-ASTRA.md) and Phase V
   progress are historical; their scaffold-only claims do not describe this runtime.
