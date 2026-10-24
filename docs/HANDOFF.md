# Handoff — VM-backed L1 after the merge (2026-10-24)

Supersedes the Phase VI closeout in [history/HANDOFF-PHASE-VI-ASTRA.md](history/HANDOFF-PHASE-VI-ASTRA.md).

## State

- `main` = `108c06a` (PR #3, the experimental QEMU/KVM L1 runtime, version `0.7.0rc3`). CI on `main` was green.
- Working branch `dev/no-kvm-hardening` = draft **PR #4**. Not merged. Its last CI run (head `d619316`) was still pending when this was written; check it first.
- Untracked operator files (`CI-EXE-TASK.md`, `INSTRUCTION-*.md`, `docs/evidence/intermediate-20261022/`, `docs/evidence/phase-vi-astra/`, `benchmarks/results/l0-20261022T070800Z.*`) are untouched and still protected.

## Key discovery: GitHub-hosted runners have working KVM

This server has no `/dev/kvm`, but `ubuntu-latest` does (`/dev/kvm` accessible, `readiness` ready in both `userns` and `netns`). The real VM gate can therefore run in CI.
`.github/workflows/vm-gate.yml` runs `scripts/vm-gate.py --mode both` and uploads `vm-gate-evidence` (summary.json, junit, full pytest output with the guest consoles). It triggers on PRs that touch VM code, and by hand.
`NOT_RUN` (exit 2) is a warning, never a pass.

### Where the real-VM gate stands: FAIL, cause not yet found

Both modes fail the same way: `vm.boot_timeout` in `wait_ready()` (tests/integration/test_vm_guest.py).

- Works: QEMU/KVM launches, TAPs and bridges come up, cleanup leaves the host network unchanged, no leaked resources.
- Works: both guests boot to a login prompt in about 1.6 s. The hostname is `alpha` / `bravo`, so cloud-init read the seed. The image's initramfs supports virtio, so a plain boot with this drive layout is fine.
- Fails: the lab-side HTTP probe never gets the identity page (`POLMON <id> <uuid>` on port 8080) within 90 s.

Open hypotheses, not yet tested:

1. `netns` mode: `sudo` strips `PYTHONPATH`, so `python -m polmon_l1_vm.cli probe-http` cannot import the addon inside the namespace. This would not explain `userns`.
2. The guest network or `runcmd` does not come up (cloud-init `network-config` v1 with `mac_address`, or `python3 -m http.server --bind <ip>` not starting).
3. The probe itself fails inside `nsenter` (python path or venv symlink).

**Next step.** Commit `d619316` makes the test print, on failure, the lab's `ip addr`, `ip neigh`, link counters, a `ping` to each guest and the raw `probe-http` output. Download the artifact from the latest `VM gate` run, then read `pytest-userns.txt` and `pytest-netns.txt`:

    gh run list --workflow=vm-gate.yml --branch dev/no-kvm-hardening --limit 1
    gh run download <run-id> -n vm-gate-evidence -D /tmp/gate

If `ping` works but the probe does not, it is hypothesis 1 or 3. If `ping` fails, look at the guest network.
After the gate passes: run it on `main`, store the evidence under `docs/evidence/`, and only then change `integration_verified` and the "experimental" wording.

## What PR #4 contains

| Commit | What |
|---|---|
| `ci: re-enable the Windows test job` | Windows unit/integration tests **pass** (the four known failures were already fixed). Keep the job on. |
| `test(vm): … fake QEMU` | `tests/fixtures/fake_qemu.py` plus `tests/unit/test_vm_fake_qemu.py`: real `VMBackend` start/stop/destroy against a stand-in QEMU. It validates the real command line (KVM only, sandbox, no user networking) and QMP shutdown, and covers ignore-quit, ignore-term and early exit. Runs on POSIX, no KVM needed. |
| `feat(vm): … gate harness` | `scripts/vm-gate.py` (PASS / FAIL / NOT_RUN plus evidence directory). `scripts/vm-tests.sh` forwards `POLMON_VM_PYTEST_ARGS`. |
| `fix(vm): stop every guest …` | See bugs below. |
| `fix(runner): write service output as it arrives` | See bugs below. |
| `docs: archive finished process documents` | `HANDOFF-PHASE-VI-ASTRA.md`, `INSTRUCTION-PHASE-V.md`, `PHASE-V-PROGRESS.md` moved to `docs/history/`. |
| `ci: … vm-gate`, `test(vm): print …` | The KVM workflow and failure diagnostics. |

### Real bugs found and fixed

1. `stop()` raised on the first guest it could not kill and never signalled the rest. It now tries all guests, then raises `vm.cleanup_failed`.
2. QEMU logs were never removed, so re-creating in the same directory failed with `vm.directory_not_empty`. `destroy()` removes them and the journal lists them. Recovery now accepts `-qemu.log` (the `OWNED_FILE` regex).
3. The base image was hashed only at `create()`. `start()` now re-checks its file identity (`vm.image_changed`; EN and RU messages added).
4. A comma in the QMP socket directory would inject QEMU options. It is now refused (`vm.path_invalid`).
5. `CommandRunner.start` log drain used `read(8192)`, which withholds output until 8 KiB arrive. Console and service logs lagged, and the end of a guest console was invisible. Fixed with `read1`; regression test added (it fails without the fix).

### Checked, not fixed (low severity)

- `acquire_image`'s 900 s deadline is only checked between 1 MiB reads, so a very slow server can exceed it.
- The pinned manifest URL uses `alpine/latest-stable/…`. If Alpine moves that path, the download fails (digest-pinned, so safe, but stale). `build-linux.yml` fetches the same image.
- `host.terminate` has a tiny pid-reuse window between the identity check and `kill`.
- QMP `readline` total time is not bounded against a trickling peer (QEMU's own socket).
- `ruff format --check` reports 76 files; only `ruff check` is enforced. Not touched.

## Not done / needs you

- **Branch pruning was denied by the auto-mode classifier**, so nothing was deleted. All of these are fully merged into `main`; SHAs are listed so any can be restored (`git push origin <sha>:refs/heads/<name>`):
  `ci/release-windows-test-waiver 98762da`, `ci/self-hosted-windows 6851611`, `feat/l1-vm-runtime f1bc912`, `frontier/2026-10-polmon 3764af0`, `phase-iii-self-contained 331ca65`, `phase-iv-ru-ui 099edd2`, `phase-v-studio 43f87a9`, `phase-vi-packaging-packet-lab ada84ad`, `wave/data-dir 4e855c3`, `wave/linux-local 4bcab53`, `wave/screenshots c1bd541`, `wave/windows-memory 422c7d3`.
  Local-only: `codex/test-minimization-20261022 ac1bb6b`, `integrate-v0.6.0 225318b` (has a worktree at `~/projects/polmon-phase-vi`), and a stale local `main`.
- The TCG smoke test was **not built**: the code is deliberately KVM-only. The hosted-runner KVM gate replaces it.
- **CHANGELOG.md** has no entries for the fixes above. Add them under `[Unreleased]`.
- PR #4 is still a draft: remove it from draft and merge once CI is green, the gate passes or is understood, and the CHANGELOG is updated.
- `docs/evidence/` has no VM-gate evidence yet.

## Done in this session, for reference

- Opened and merged PR #3; CI on `main` green.
- Fast-forwarding local `main` and deleting branches were attempted in the same command and denied; nothing ran. The `main` branch ref is therefore still stale.
