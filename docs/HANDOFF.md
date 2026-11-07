# PR #4 fixes and validation — 2026-11-07

This replaces the October 24 investigation notes. PR #4 was merged to `main` on
2026-11-07 as `fd40fe265447a71742b303687a86bc24141193b4`. The runtime remains
experimental; no waiver or acceptance-flag change was made. The `v0.7.1` release is
being prepared separately and is not published by this handoff.

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

All six hosted checks at `ae31868` subsequently passed, including native Windows and
hosted KVM: [CI](https://github.com/blindicide/polmon/actions/runs/42346378937),
[VM gate](https://github.com/blindicide/polmon/actions/runs/42346378915).
Local Linux results do not stand in for the next pushed head's Windows execution.

## Follow-up implementation

- Dashboard cards/counter tiles trim vertical padding without reducing fonts, removing
  content or changing assertions; the original language/layout file now has **5 passing tests**.
  Both complete GUI selections passed: **67 Russian, 67 English**.
- Both userns and netns passed seven real fault cases each: guest SIGKILL, readiness
  probe outage/timeout, failed second QEMU launch, API cancel, API timeout, command
  SIGKILL and backend SIGKILL followed by startup recovery. Every scenario asserts
  process, namespace, socket and run-file cleanup and preserved host interfaces.
- A PID/start-time-pinned CLI parent guard handles backend death even after its stderr
  pipe closes. API source children receive an explicit known addon path.
- Explicit `--vm-node` selection on addon `plan`/`run` supports isolated mixed labs;
  API run requests accept bounded custom definitions, VM selection and hold time.
  Auxiliary processes/files and nested namespace identities are journaled for recovery.
- `scripts/vm-tests.sh` and hosted path filters now cover lifecycle, failures and mixed
  integration tests. Rootless: **546 passed, 11 skipped** without a VM image configured.
  Ruff, both translation gates and the Qt client self-test passed.
- The final rootless run used `TMPDIR=/tmp/opencode`; an earlier concurrent run hit two
  global temporary-directory snapshot races with the mixed worker's KVM tests. Every
  test assertion passed, and rerunning in a separate temporary root passed all teardowns.
  Test cleanup assertions were not relaxed.
- Mixed communication/rollback first passed in both modes (**4 passed**). The outer guard
  rejected newly created Firefox sandbox processes, not lab resources. A later expanded
  run passed rollback and nested-owner crash recovery in both modes (**4 passed**) but
  both communication reruns failed at BIOS boot with `KVM: entry failed, hardware error
  0x0`. Kernel VMREAD/VMWRITE warnings coincided with VirtualBox activity. The final outer
  cleanup/host-network guard passed. This failed rerun is not a gate pass or waiver.
- Final hosted verification at PR source head `baae249` passed **all six checks**:
  [native CI](https://github.com/blindicide/polmon/actions/runs/42349649584) and
  [expanded KVM gate](https://github.com/blindicide/polmon/actions/runs/42349649597).
  The KVM artifact reports **11 passed per mode, no skips**, with `git_dirty: false`.
  It tested GitHub's synthetic PR merge `2b1759c`; the later main merge is recorded above.
  Raw logs, JUnit, measurements and full parent provenance are retained in
  [evidence/vm-gate-20261107-pr4-expanded/](evidence/vm-gate-20261107-pr4-expanded/).
  This resolves final expanded verification without waiving or erasing the earlier
  local failure. Unrelated host VMs, browsers and kernel settings are left untouched.
  No release, tag or acceptance-flag promotion was part of this implementation work.

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

- Keep `integration_verified: false` and experimental addon wording. A successful
  lifecycle/fault gate is not comprehensive security acceptance; exhaustive hardening
  validation remains open.
- Guest scenarios, SSH/VNC integration, guest-side metrics and persistent VM time
  series remain unfinished. Ordinary local topology
  execution remains L0-only; namespace L1 needs an authorized Linux lab backend.
- Core/addon release metadata is `0.7.1`/`0.1.1`; publication is pending the gated tag
  workflow. No waiver was used. No branch pruning or unrelated operator-file cleanup was
  performed. All commits/version edits use the dedicated model in `AGENTS.md`.
- Low-severity review notes remain: slow image reads can overrun the aggregate
  acquisition deadline; the pinned image URL uses `latest-stable`; process termination
  has a small PID-reuse window; QMP trickling responses lack a total read deadline.
- The old Phase VI closeout is historical:
  [history/HANDOFF-PHASE-VI-ASTRA.md](history/HANDOFF-PHASE-VI-ASTRA.md).
  Host-networking privileges remain root-equivalent; see [SECURITY.md](../SECURITY.md).
