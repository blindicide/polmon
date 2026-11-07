# PR #4 fixes and validation — 2026-11-07

This replaces the October 24 investigation notes. PR #4 remains experimental and
draft; no merge, waiver, release or acceptance-flag change is authorized here.

## Diagnosed failures

The failing hosted checks at `1a99d08` are preserved:
[CI](https://github.com/blindicide/polmon/actions/runs/40130947922),
[VM gate](https://github.com/blindicide/polmon/actions/runs/40130948058).

1. **Windows:** `test_service_log_is_written_while_the_process_is_still_running`
   read its log before the background drain thread created it. The test now waits
   for creation and output, and still requires the child to be alive.
2. **Userns VM readiness:** the raw artifact already showed successful ping and
   HTTP identity responses from both guests. `probe-http` appended a newline to
   the body, so exact identity comparison failed. It now preserves the body,
   including empty, absent, single and multiple trailing newlines.
3. **Netns VM readiness:** `sudo` removed `PYTHONPATH`, and the source addon was not
   installed. The probe now supplies its known addon location explicitly inside
   the owner-privileged command. It does not preserve Python environment variables
   across sudo. Frozen dispatch remains `--run-vm probe-http`.
4. **Evidence reporting:** pytest can prefix `REAL-VM-EVIDENCE` with the test-file
   name on the same line. The gate now retains those measurements in its summary.

Regression tests first reproduced both probe bugs and the evidence-parser bug,
then passed after the fixes. Failure diagnostics use the same probe command as
readiness, including the netns import fix.

## Local validation

The current executor is a Linux laptop, not the earlier VM-hosted server. It has
Python 3.12, the project virtual environment, QEMU 8.2.2 and working KVM/userns/netns.
The existing guest image was copied to a read-only temporary base and verified
against the pinned manifest; the original image was not modified.

- Real-KVM gate: **PASS in both userns and netns**, with no skipped guest tests.
  Two guests per mode passed exact identity and wrong-identity rejection,
  guest-to-guest HTTP, host/egress isolation, process/network/disk measurements,
  guest-written overlay differences, unchanged base digest and deterministic cleanup.
  The final rerun at clean source commit `4a3f5fe` retained measurements for both
  modes; raw evidence is in [evidence/vm-gate-20261107-pr4/](evidence/vm-gate-20261107-pr4/).
- Final rootless unit/integration run: **494 passed, 1 skipped**. The VM test in
  that selection had no image configured; it ran separately in the real-KVM gate.
- Focused probe, runner and gate regression tests: **38 passed** after the final
  probe-dispatch refactor and evidence-parser fix.
- Ruff and both translation gates passed.
- Russian-default and English GUI runs: **64 passed, 3 failed each** in dashboard
  layout assertions.
  Both language variants of the standalone layout test reproduce unchanged on an
  archived `1a99d08` checkout (927 px required height versus the 900 px contract).
  This is a pre-existing local layout failure, not a VM-fix regression; no GUI code,
  assertion or test selection was changed to hide it.

Native Windows and updated hosted-KVM checks must be verified on the pushed PR
head. Local Linux results do not stand in for Windows execution.

## Other PR fixes retained

- Shutdown attempts every guest even if one cannot be stopped.
- Destroy/recovery removes owned QEMU logs, permitting run-directory reuse.
- Start rechecks base-image identity; QMP paths reject option separators.
- Service/guest output drains short chunks immediately instead of waiting for 8 KiB.
- Fake-QEMU lifecycle tests exercise real launch/shutdown code without claiming guest
  acceptance. Gate classification tests distinguish PASS, FAIL and NOT_RUN.
- Finished Phase V/VI records are archived under `docs/history/`.
- `CHANGELOG.md` and `CI.md` describe the fixes and re-enabled Windows matrix.

## Evidence boundaries and follow-up

- Keep `integration_verified: false` and experimental release wording. A successful
  two-guest lifecycle gate is not complete failure/recovery or security acceptance;
  real-guest crash/cancel/recovery and exhaustive hardening validation remain open.
- Mixed VM/L0/namespace topologies, guest scenarios, SSH/VNC integration, guest-side
  metrics and persistent VM time series remain unfinished. Ordinary local topology
  execution remains L0-only; namespace L1 needs an authorized Linux lab backend.
- No version bump, release, merge or waiver is part of these fixes. No branch pruning
  or unrelated operator-file cleanup was performed.
- Low-severity review notes remain: slow image reads can overrun the aggregate
  acquisition deadline; the pinned image URL uses `latest-stable`; process termination
  has a small PID-reuse window; QMP trickling responses lack a total read deadline.
- The old Phase VI closeout is historical:
  [history/HANDOFF-PHASE-VI-ASTRA.md](history/HANDOFF-PHASE-VI-ASTRA.md).
  Host-networking privileges remain root-equivalent; see [SECURITY.md](../SECURITY.md).
