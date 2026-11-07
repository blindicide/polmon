# PR #4 follow-up local results

These are **development-tree results**, collected after `ae31868`, before the final
implementation commit. They are not a clean-source expanded gate pass. Historical
release acceptance is unchanged, and `integration_verified` remains false.

- `faults-userns.xml` / `faults-netns.xml`: seven real-KVM fault cases passed per mode.
  Every case asserted cleanup; see `tests/integration/test_vm_failures.py`.
- `rootless.xml`: 546 passed, 11 skipped without a configured VM image. Temporary
  resources were isolated with `TMPDIR=/tmp/opencode` to avoid concurrent-test snapshots.
- `gui-ru.xml` / `gui-en.xml`: 67 passed per language, with unchanged layout assertions.
- `mixed-measurements.json`: guest/L0/namespace communication measurements extracted
  from an earlier four-test passing run in both modes. Its outer process guard failed
  because Firefox created unrelated sandbox processes. The original log remains local;
  this extracted file is not a passing guarded gate.
- `mixed-rerun.txt`: the subsequent expanded mixed rerun had four passing rollback/
  owner-recovery tests and two failed communication tests. Both failures were KVM entry
  errors during BIOS boot. Its host-network/cleanup guard passed. Kernel diagnostics
  coincided with VirtualBox activity; unrelated host applications were not stopped.

The final committed implementation subsequently passed the expanded hosted KVM gate:
see [`../vm-gate-20261107-pr4-expanded/`](../vm-gate-20261107-pr4-expanded/).
Do not replace that result with earlier partial successes or reinterpret this failed rerun as PASS.
Raw host/kernel diagnostics are intentionally not published with these test results.
