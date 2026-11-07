# Current state and PR #4 merge caveats

Last checked: 2026-11-07. This is a status snapshot, not a merge waiver or VM acceptance report.

## Baseline and releases

- Before this documentation change, local `main` was clean at `108c06a` and matched
  `origin/main` (verified against GitHub). Core version: `0.7.0rc3`.
- Latest stable release: `v0.6.0`. Experimental `v0.7.0-rc.3` was published on
  October 23 with ten assets: Windows/Linux clients, Debian/RPM packages, core/addon
  wheels, package metadata and checksum manifests. Its
  [release workflow](https://github.com/blindicide/polmon/actions/runs/39952638109)
  succeeded. Published artifacts and packaging checks do not establish VM acceptance.
- [CI for the baseline main commit](https://github.com/blindicide/polmon/actions/runs/40126273066)
  succeeded. Its test matrix includes Linux only: Windows unit/integration tests are
  temporarily suspended, although Windows screenshot checks still run. A green main
  check must not be described as full Windows test coverage.

## PR #4: separate failures, no waiver granted

[PR #4](https://github.com/blindicide/polmon/pull/4), `dev/no-kvm-hardening`, is open
and **draft**, with head `1a99d0851008931f823aee724f7e230c0e52ffed`. It adds Windows
testing, fake-QEMU lifecycle tests, VM hardening, a real-KVM gate and documentation.

| Latest check at that head | Result |
|---|---|
| Linux unit/integration and GUI test job | PASS |
| Linux and Windows screenshot jobs | PASS |
| Dependency audit | PASS |
| Windows test job, rootless unit/integration step | **FAIL** |
| Real KVM guests, userns + netns gate | **FAIL** |

Sources: [CI run](https://github.com/blindicide/polmon/actions/runs/40130947922) and
[VM-gate run](https://github.com/blindicide/polmon/actions/runs/40130948058).
GitHub annotations identify failing steps, not a diagnosed Windows root cause.

GitHub reports no merge conflicts. `main` has no branch protection or applicable
branch rules, so failing checks are not a technical merge barrier. That is not
evidence of correctness or authorization to bypass checks. The draft must also be
marked ready before merging. **Skipping Windows alone would leave the VM failure.**

The PR's own `docs/HANDOFF.md` reports that hosted runners have usable KVM, guests
reach login prompts, and both network modes then hit `vm.boot_timeout` while waiting
for the HTTP identity service. It also reports successful cleanup. These are the
earlier author's observations, not independently reproduced acceptance results.
Network configuration, guest service startup and namespace-side probing remain
investigation hypotheses. That document's earlier claim that Windows tests pass is
superseded by the failing latest check above.

## Runtime and evidence boundaries

- Ordinary local client topologies remain L0-only on Windows and Linux. Namespace
  L1/hybrid execution needs an authorized Linux lab backend; L2 remains unsupported.
- The optional Linux QEMU/KVM addon, `/v1/vm/*` jobs and VM page are experimental.
  Main/rc3 has no passing real-guest acceptance. PR #4 adds actual guest attempts,
  but its gate fails; do not relabel this as PASS or as merely unavailable hardware.
- Successful guest networking/services, guest-written clone isolation, measured VM
  costs and complete failure/recovery acceptance still need evidence in both modes.
  Fake QEMU, storage tests and frozen-bundle/image checks are not substitutes.
- Mixed VM/L0/namespace topologies, guest scenario and SSH/VNC integration, guest-side
  metrics and a persistent VM time series remain unfinished.
- The retained v0.6.0 benchmark reports about 38.5 MiB attributed memory for 50 L0 +
  2 namespace L1 nodes, zero packet loss and cleanup. It is historical, not a new
  measurement or a VM-footprint claim; see
  [the benchmark summary](benchmarks/results/SUMMARY-v0.6.0-frontier.md).
- No `.venv` exists in this checkout. Python 3.12 is available, but application and
  GUI/test dependencies are missing. The inspection parsed 214 Python files and
  passed the hard-coded UI-string check. Translation completeness stopped on missing
  `pydantic`; full local tests were not run. This is an environment limitation, not
  an established code regression. No privileged tests, guest boots or benchmarks
  were run during this inspection.
- [SECURITY.md](SECURITY.md) retains important limitations: `sudo ip` is
  root-equivalent and the backend belongs on a dedicated lab host. The project has
  no granted license yet; Windows executables are unsigned.

## Next operator actions

1. Recheck PR head, draft status and checks; this snapshot is not live state.
2. Diagnose the Windows failure and inspect the VM gate's `vm-gate-evidence`
   artifact, especially `pytest-userns.txt`, `pytest-netns.txt` and `summary.json`.
3. Prefer fixing both failures. If an experimental merge is chosen instead, obtain
   explicit approval covering **both** failures, record the waiver and follow-up
   work, preserve the failing checks, and keep VM acceptance claims unchanged.
   The discussion so far has not approved either waiver or a merge.
4. Reconcile this file with the PR's `docs/HANDOFF.md` when integrating it. The older
   [Phase VI handoff](HANDOFF-PHASE-VI-ASTRA.md) records the rc1 attempt; its
   scaffold-only/release-blocked claims are historical, not current rc3 status.
   Phase V progress is historical too. The PR proposes archiving these records.
5. Update the changelog for PR fixes when integrating them; obtain passing real-KVM
   evidence before changing `integration_verified` or claiming VM acceptance.

This handoff change is documentation only: no version bump, CI bypass, PR state
change, merge, tag, release or push is included.
