# Phase VI intermediate release handoff

VERSION: core 0.7.0rc1; addon distribution 0.1.0rc1; SemVer tag v0.7.0-rc.1.
STATUS: PARTIAL — bounded analytics delivered; VM runtime/acceptance unavailable.

## Authority, model and worktree

The October 22 intermediate-release mandate supersedes the operator file's older
handoff-only/no-publication boundary. This permits independently verifiable fixes,
local gates, coherent commits and an intermediate GitHub prerelease; it does not
permit VM installation/download/build/boot, TCG, a stable release or merging main.
No subagents or overlapping harness were used. No reset, clean, stash, rebase or
branch switch was performed. The fulfilled L0 large benchmark was not repeated.

Actual accepted model: `gpt-6.1-sol`, reasoning `high`, confirmed in the live
`polmon-rel:1.0` TUI and running CLI arguments. Accepted real provider response:
`POLMON_MODEL_ACCEPTED`. Supervisor notes are outside Git at
`/home/clawuser/.hermes/cache/scratch/POLMON-INTERMEDIATE-RUN-20261022.md`.
The operator accounting was not edited. No quota estimate is derived from tokens.
No repository/ancestor AGENTS.md was found; the supplied global test guidance
applies. Broad rootless/privileged gates are explicitly required by the mandate.

Initial branch: `frontier/2026-10-polmon`; initial HEAD:
`ac1bb6b59955983dad640b06250e944f5bb7ca2f`, nine commits ahead of main.
Canonical origin: `https://github.com/blindicide/polmon.git`, public repository;
default/main remote initially `225318b3a0383749cced6d064dfef4c144b56531`.
Initial file hashes/copies/diff and exact dirty inventory were captured before
editing in `/tmp/polmon-intermediate-20261022/`. Nothing was staged initially.

### Exact initial dirty/untracked inventory

```text
 M ARCHITECTURE.md
 M CHANGELOG.md
 M README.md
 M RESOURCE-BUDGET.md
 M SECURITY.md
 M docs/TOPOLOGY.md
 M pyproject.toml
 M src/polmon/resources/analytics.py
 M tests/unit/test_resource_analytics.py
?? CI-EXE-TASK.md
?? INSTRUCTION-PHASE-VI-ASTRA.md
?? RUN-ACCOUNTING-PHASE-VI-ASTRA.md
?? addons/l1-vm/README.md
?? addons/l1-vm/pyproject.toml
?? addons/l1-vm/src/polmon_l1_vm/__init__.py
?? addons/l1-vm/src/polmon_l1_vm/backend.py
?? addons/l1-vm/src/polmon_l1_vm/cli.py
?? addons/l1-vm/src/polmon_l1_vm/images.py
?? addons/l1-vm/src/polmon_l1_vm/recovery.py
?? addons/l1-vm/src/polmon_l1_vm/seed.py
?? benchmarks/results/l0-20261022T070800Z.csv
?? benchmarks/results/l0-20261022T070800Z.json
?? docs/PHASE-VI-BACKLOG.md
?? docs/evidence/phase-vi-astra/addon-build-final.txt
?? docs/evidence/phase-vi-astra/addon-build-offline.txt
?? docs/evidence/phase-vi-astra/addon-build.txt
?? docs/evidence/phase-vi-astra/analytics-live-rerun.txt
?? docs/evidence/phase-vi-astra/analytics-live.txt
?? docs/evidence/phase-vi-astra/analytics-rootless-rerun.txt
?? docs/evidence/phase-vi-astra/analytics-rootless.txt
?? docs/evidence/phase-vi-astra/bounds-focused.txt
?? docs/evidence/phase-vi-astra/final-privileged.txt
?? docs/evidence/phase-vi-astra/final-rootless-bounds.txt
?? docs/evidence/phase-vi-astra/final-rootless.txt
?? docs/evidence/phase-vi-astra/format-final.txt
?? docs/evidence/phase-vi-astra/format.txt
?? docs/evidence/phase-vi-astra/i18n-final.txt
?? docs/evidence/phase-vi-astra/i18n.txt
?? docs/evidence/phase-vi-astra/live-bounds.txt
?? docs/evidence/phase-vi-astra/vm-focused-rerun.txt
?? docs/evidence/phase-vi-astra/vm-focused.txt
?? docs/evidence/phase-vi-astra/vm-real-gate.txt
?? docs/milestones/phase-vi-astra.md
?? examples/topologies/l1-vm-addon.yml
?? scripts/vm-tests.sh
?? tests/integration/test_vm_guest.py
?? tests/unit/test_vm_addon.py
```

The ignored operator brief `SUPERVISOR-BRIEF-POLMON-ASTRA.md` is also protected.
All six protected files (three untracked operator records, ignored brief and two
L0 outputs) were SHA-256 checked against that baseline after editing. CI-EXE-TASK
is included in those protected records; no protected file may enter Git/assets.
Historical raw evidence remains preserved locally and unstaged.

## Implementation and scope corrections

`ac1bb6b` introduced bounded, on-demand `/v1/resources/history`: timestamped node
UUID/deployment attribution, CPU-time/delta utilization, RSS, process disk I/O,
namespace network counters, host available-memory/swap context and JSON export.
The collector has interval/count/byte/subject bounds and no background worker.
This closeout finishes pending process-discovery/thread/child-read bounds and
returns unavailable process counters on platforms without POSIX `sysconf`.
Shared processes are charged once; RSS still includes shared pages and is not PSS
or kernel memory. Missing counters, incomplete trees and sampling gaps remain
explicit. History is volatile/on demand; transient unregistered costs can be lost.

The inherited addon draft advertised unvalidated runtime execution, acquisition
and recovery beyond the authorized scaffold. That was corrected: the optional
package now provides typed configuration, static validation, read-only clone/
network plans, image digest/size contracts and seed document generation.
`create/start/stop/destroy/wait_ready/sample/probe`, image acquisition, ISO creation
and recovery all raise `vm.scaffold_only` before mutation, even on capable hosts.
Readiness reports actual missing tools/KVM and permanent scaffold unavailability.
Storage-only verification/overlay helpers remain, distinctly tested using an empty
16 MiB QCOW2 disk. They are not Linux guests or proof of guest clone isolation.

Ordinary namespace L1/L0 behavior is preserved; local clients remain L0-only.
There is no VM GUI/API selection, mixed L0/namespace attachment, SSH/VNC/scenario
integration, runtime admission/global reservations, cgroups, recovery or guest
metrics. No VM execution/cleanup security claim is made. Documentation/backlog/
phase report/example describe the non-executing boundary and remaining work.

## Exact local verification and reproducibility

All commands run from this checkout, with Python 3.12 in `.venv`. Current raw logs
are under `docs/evidence/intermediate-20261022/`, retained locally. Historical raw
logs under `docs/evidence/phase-vi-astra/` remain byte-for-byte preserved.

| Command/check | Result and evidence |
|---|---|
| `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/unit/test_vm_addon.py tests/unit/test_resource_analytics.py tests/unit/test_foundation.py -q` | 29 passed, one existing warning; `/tmp/polmon-intermediate-20261022/focused.txt` |
| `QT_QPA_PLATFORM=offscreen scripts/check.sh` | PASS: 487 passed, 25 deselected, one warning (139.57 s); `rootless.txt` |
| `scripts/privileged-tests.sh -m privileged --ignore=tests/integration/test_vm_guest.py -s` | PASS: 23 passed, 488 deselected, one warning (31.61 s); host unchanged/no leftovers; `privileged.txt`; VM test excluded |
| `.venv/bin/python scripts/i18n-lint.py` | 0 hard-coded literals; `i18n.txt` |
| `.venv/bin/python scripts/i18n-completeness.py` | PASS, 1127 keys/0 problems; `i18n.txt` |
| `.venv/bin/ruff format --check addons/l1-vm/src scripts/release_metadata.py src/polmon/resources/analytics.py tests/unit/test_vm_addon.py tests/unit/test_resource_analytics.py tests/unit/test_foundation.py` | 11 files formatted; `format.txt` |
| `/home/clawuser/.local/bin/uv build --offline --python .venv/bin/python --wheel --out-dir build/intermediate-20261022 .` | PASS; `core-build.txt`; core 0.7.0rc1 wheel |
| Same build command with `addons/l1-vm` instead of `.` | PASS; `addon-build.txt`; addon 0.1.0rc1 wheel |
| Extract/import both built wheels with `.venv/bin/python`, assert imported paths and distribution versions | PASS; `wheel-smoke.txt`, `wheel-metadata.json`; addon pins `polmon==0.7.0rc1`; no protected files in wheels |
| `.venv/bin/python scripts/release_metadata.py v0.7.0-rc.1` | PASS; `release-metadata.json`; exact tag/source/project/lock/addon/changelog consistency |
| Bash syntax for `scripts/*.sh`, parsed workflow YAML/Bash steps and packaging spec ASTs | PASS; locally inspected; native runtime validation remains the release workflow's job |
| All six `.venv/bin/polmon-* --version` entry points | `polmon 0.7.0rc1` |
| `dpkg --compare-versions '0.7.0~rc1' lt '0.7.0'` | PASS; native preview ordering |
| `PYTHONPATH=addons/l1-vm/src .venv/bin/python -m polmon_l1_vm.cli readiness` | Expected exit 2; `vm-readiness.json` |
| `scripts/vm-tests.sh` / real guest integration | **NOT RUN**: unavailable KVM, forbidden runtime and unimplemented scaffold; no guest acceptance |

Package builds here are Python-wheel evidence. Windows executable/native Linux
package validation must come from the exact release workflow, never inferred from
source tests or the older v0.6.0 assets. No native Windows evidence is invented.

### Failures and corrections retained

Historical evidence: duplicate test-module basename collection failure in
`analytics-rootless.txt` was fixed by a unique integration module name; wrong API
response key in `analytics-live.txt` was corrected to `topology_id`; direct build
failed for missing Hatchling in `addon-build.txt`, followed by successful isolated
offline uv builds. Historical final bounds gate reported 491 passed/25 deselected;
privileged reported 23 passed/1 VM skip with host invariance. These are historical,
not final-candidate pass counts. The Starlette/httpx warning remains.

Closeout offline `uv lock --offline --python .venv/bin/python` failed because the
PyYAML artifact was not cached. `uv lock --python .venv/bin/python` succeeded;
only the project version changed in uv.lock. Initial Ruff findings were import
ordering/one long line, corrected before the final checks. No host packages were
installed. Runtime code was replaced rather than presented as accepted VM work.

## Resource measurement scope

Historical real namespace HTTP evidence (`analytics-live-rerun.txt`,
`live-bounds.txt`) reports around 19 MiB RSS across two registered processes and
0.02 CPU seconds. The specific earlier run recorded 19,660,800 RSS bytes, RX
573/8 to 659/9 bytes/packets, TX 595/7, unavailable process disk I/O, and 3,634
encoded bytes for two samples. These observations characterize that small run.
Fresh final privileged measurements are captured in `privileged.txt`.

Historical storage-only evidence used an empty 16 MiB QCOW2 disk: base allocation
200,704 bytes, modified clone 331,776, sibling 200,704, unchanged base hash and
removed overlays. Neither that nor the preserved L0 large benchmark measures
VM footprint. Two 256 MiB configured guests plus estimated 64 MiB overhead each
and a 256 MiB host reserve are planning estimates, not observed VM memory.
The preserved L0 benchmark outputs are unchanged and never repeated/published.

## Real VM blocker and exact next acceptance

`/dev/kvm` is absent and `/proc/cpuinfo` exposes neither vmx nor svm. The system
emulator and seed tool are absent (`vm.qemu_missing`, `vm.seed_tool_missing`,
`vm.kvm_unavailable`). Installation, module loads, guest downloads/build/boot,
TCG and VM launch are forbidden on this host. The added `vm.scaffold_only`
blocker also persists on capable hosts until implementation/acceptance.

On an explicitly authorized capable Linux x86_64 machine:

1. Record KVM/TUN/CPU/tool versions, lab privileges and memory/disk headroom;
   obtain separate authorization for any host provisioning.
2. Review an immutable guest image's publisher signature/digest and licensing;
   preserve provenance in a private pinned manifest. Never use the empty disk.
3. Implement KVM-only unprivileged lifecycle, isolated namespace TAP/bridges,
   exclusive overlays/seeds, resource admission/rechecks, bounded diagnostics,
   identity-pinned ownership/recovery and fail-closed cleanup. Replace scaffold
   refusals only alongside actual integration evidence.
4. Complete the real integration test, boot two distinct clones and capture guest
   UUID/hostname/MAC/IP, ICMP and HTTP service responses plus bidirectional
   inter-guest traffic, deliberately failing services and host/egress isolation.
5. Write different data inside each guest and prove sibling/base isolation,
   unchanged base digest, restart/reset semantics and disposable overlay behavior.
6. Measure host process CPU/RSS/I/O, optional guest memory, base/overlay virtual/
   allocated bytes, TAP directions, boot/lifecycle time and host headroom with
   explicit count/duration/storage bounds. Keep unavailable counters null.
7. Run normal/failure/interrupt/crash/recovery cases under the privileged wrapper;
   prove unchanged host network and no owned process/TAP/bridge/netns/overlay/seed
   survivors. Retain all evidence and diagnostic reports.
8. Run `POLMON_VM_TEST_IMAGE=/lab/base.qcow2 POLMON_VM_TEST_MANIFEST=/lab/reviewed.json scripts/vm-tests.sh`
   only after the runtime and test are implemented and authorization exists.
   Then rerun rootless/localization/package gates before claiming VM acceptance.

## Release plan and publication verification

The remote tag/ref/release state and actual v0.6.0 assets were inspected; no
`v0.7.0-*` tag existed. Existing release run `38047468561` completed successfully,
so the old billing-blocked claim is not treated as current evidence. The current
candidate workflow adds real prerelease support without bypassing native builds.
SemVer `v0.7.0-rc.1` maps to Python `0.7.0rc1`, addon `0.1.0rc1`, and native Debian/
RPM metadata `0.7.0~rc1`; externally downloadable names use `0.7.0rc1`.

After final local review/gates, commit coherent analytics, scaffold, release and
handoff changes, excluding protected files and raw host logs. Push only the feature
branch and a new annotated prerelease tag; do not merge/update main or force-push.
The native workflow must build/test both client platforms, build both wheels and
Debian/RPM packages, verify recorded checksums, publish exact-version notes with
`--prerelease --latest=false`, redownload assets and smoke-test Windows/Linux.

Expected assets: Windows EXE and portable ZIP, Linux tarball, core wheel, separate
addon wheel, Debian/RPM clients, package-manifest.json, SHA256SUMS-packages.txt and
SHA256SUMS.txt (10 total). No guest image/operator record/L0 output is an asset.
Read back release metadata, annotated tag target/remote branch SHA and exact run;
download all assets and check both checksum manifests. Actions must reach terminal
success, including published-client verification. Billing/startup/workflow failure
means publication is blocked, even if a GitHub API request succeeded.

Publication status: local gates PASS; native publication/verification PENDING. Candidate/final commit SHAs, release
URL, workflow run/status and download checksums will be recorded here at closeout.

## Separate judgments and final inventory

- Implementation: bounded analytics and non-executing addon contracts delivered;
  full VM runtime is incomplete and unavailable.
- Real VM acceptance: BLOCKED / NOT RUN, never replaced by fakes or storage tests.
- Release readiness/publication: local gates PASS; native workflow PENDING.
- Limitations: no guest metrics/runtime/recovery/mixed-fidelity integration; volatile
  procfs history, incomplete counters and existing upstream warning as above.

Implementation/release commits after the initial analytics commit:

- `66814b3`: bounded discovery and unavailable platform counters;
- `0ba28c3`: optional non-executing L1 scaffold and contracts;
- `0d94094`: prerelease workflow, versions, package metadata and notes.

The candidate report commit follows these and will be the annotated tag target.
Final exact dirty/operator inventory and protected-file hash verification will be
recorded in the post-publication closeout. Operator files/results remain uncommitted;
historical and new raw gate logs remain local. Final supervisor shutdown observes
clean Codex exit and descendant termination outside this active harness, appending
its actual observation to the supervisor run notes; it must not modify this tree.
