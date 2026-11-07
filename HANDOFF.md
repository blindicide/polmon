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
Linux rootless unit/integration tests: **494 passed,
1 skipped** (the unconfigured VM test ran separately in the KVM gate). Ruff and
translation gates passed. Three local GUI dashboard-layout assertions failed;
the same layout failure reproduces on the unchanged PR head. Native Windows and
updated hosted-KVM results must still be checked on the pushed PR head.

See [docs/HANDOFF.md](docs/HANDOFF.md) for causes, fixes, validation and remaining
acceptance work. No check bypass, waiver or PR merge is authorized by this snapshot.

## Releases and runtime boundaries

- Core remains `0.7.0rc3`; stable release remains `v0.6.0`. Published experimental
  `v0.7.0-rc.3` artifacts are unchanged. No version bump, tag or release is included.
- Ordinary local client topologies remain L0-only on Windows and Linux. Namespace
  L1/hybrid execution needs an authorized Linux lab backend; L2 remains unsupported.
- The optional QEMU/KVM addon, `/v1/vm/*` jobs and VM page remain experimental, with
  `integration_verified: false`. Passing the two-guest lifecycle gate does not prove
  complete real-guest failure/recovery or security acceptance.
- Mixed VM/L0/namespace topologies, guest scenario and SSH/VNC integration, guest-side
  metrics and persistent VM time series remain unfinished.
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
2. Preserve and review raw VM evidence before broadening acceptance claims. Keep
   complete real-guest failure/recovery acceptance separate from lifecycle success.
3. Investigate the existing local GUI layout issue separately unless hosted checks
   expose a merge-blocking portability failure. Do not weaken the 1440x900 contract.
4. The archived [Phase VI handoff](docs/history/HANDOFF-PHASE-VI-ASTRA.md) and Phase V
   progress are historical; their scaffold-only claims do not describe this runtime.
