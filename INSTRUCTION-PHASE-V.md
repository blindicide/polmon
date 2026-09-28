# INSTRUCTION-PHASE-V.md — polmon v0.5.0 "Topology studio & lab access"

**Operator:** Ruslan · **Issued:** 2026-09-28 · **Baseline:** `main @ 634f49a` (tag `v0.4.1`) · **Target:** `v0.5.0`
**Harness:** Claude Code (Opus 5.5 high) first; a second rig may take over the same tree mid-mandate (see §7).

This mandate is the operator's own complaint list, restated as an engineering spec. Implement it
completely and honestly. Where a decision is not fixed here, DECIDE, implement the strongest
defensible option, and document the decision in the phase report — do not stop to ask.

---

## 0. Standing rules (non-negotiable)

1. **A self-report is not evidence.** Every milestone is *verified* before it is claimed: gates run,
   real commands executed, real output captured. Failed hypotheses, unmet quality gates and partial
   work are reported plainly — never relabelled as done.
2. **No fake results, ever.** No mock/synthetic output presented as a real run, no hand-written
   "expected" numbers, no stubs presented as features. If something could not be done (hardware or
   host-package absent), it is skipped with a **reason code** and listed under KNOWN LIMITATIONS.
3. **Never delete** `.md`/`.csv`/`.json` results, reports, evidence or docs. Bulky regenerable
   artefacts (build dirs, checkpoints, generated code) may be pruned; whole-directory `rm -rf`
   needs the operator.
4. **Commit per milestone** (`V.1` … `V.7`), conventional-commit messages, each commit with green
   gates. Work on branch **`phase-v-studio`**, push it to `origin` (the repository is private).
   Leave `origin/main` at the last verified release until the phase completes; then merge `--no-ff`,
   tag `v0.5.0` (annotated), and publish.
5. **Gates before every milestone commit:** `scripts/check.sh` (ruff + rootless pytest) green and no
   regression against the 409-test baseline; privileged lab work additionally proven with
   `scripts/privileged-tests.sh` (which must keep proving the **host network was untouched**);
   i18n lint (`scripts/i18n-lint*`) and `scripts/i18n-completeness.py` green.
6. **The GUI matters, but the operator runs it on Windows himself.** Do not build elaborate
   screenshot/rendering pipelines for this phase; the existing `pytest-qt` GUI suite must stay
   green, screenshots are regenerated only if a page's layout materially changed, and Windows-side
   smoke testing is the operator's job. Prioritise substance (working features, honest gates).
7. **Resumability across rigs.** The phase may be interrupted by a quota wall and continued by
   another agent. Therefore: keep every milestone independently committed + pushed, keep a live
   `PHASE-V-PROGRESS.md` at the repo root with what is verified, what is in flight and the exact
   next step. Never leave uncommitted work as the only copy of anything.

---

## 1. Verified baseline facts (2026-09-28 — do not re-derive, but do re-verify what you rely on)

| Fact | Value |
|---|---|
| Repo state | `main @ 634f49a`, clean tree, tag `v0.4.1`, 10 tags, origin = private GitHub `blindicide/polmon` |
| Gate baseline | `scripts/check.sh` → `ruff` clean, **409 passed / 14 deselected in 120 s**, exit 0 |
| Host | EPYC lab host, 4 cores, root FS 63% used, **passwordless `sudo` works**, `ip netns` works |
| Binaries present | `/usr/sbin/sshd`, `/usr/bin/ssh`, `/usr/bin/Xvfb`, `/usr/bin/setpriv`, `/usr/sbin/ip` |
| Binaries **absent** | `x11vnc` (Ubuntu candidate `0.9.16-10`), `dropbear`, `xterm`, `tunctl` |
| Host addresses | `lo`, `ens3 45.88.174.157/32`, `docker0 172.17.0.1/16`, `br-… 172.21.0.1/16`, `tailscale0 100.104.115.40/32` — **nothing in 192.168.230.0/24 … 192.168.240.0/24** |
| **SSH-in-namespace: PROVEN WORKING** | A throwaway netns ran `/usr/sbin/sshd -f <cfg>` (ed25519 host key, `PasswordAuthentication no`, `AuthorizedKeysFile` in a temp dir, `ListenAddress 127.0.0.1:2222`); `ip netns exec <ns> ssh -i key … 'echo OK; ip -o -4 addr show lo; id -un'` returned `SSH-IN-NETNS-OK`, `127.0.0.1/8`, `clawuser`, exit 0. Teardown clean. **The console feature is feasible — build it for real, do not fake it.** |
| GitHub Actions | **BROKEN (billing).** Last run `36314086429`: every job failed to start — *"recent account payments have failed or your spending limit needs to be increased"*. **Do not make any deliverable depend on GitHub-hosted runners.** Keep workflow YAML valid and honest, but local gates are the source of truth this phase. |

---

## 2. The seven operator complaints (source of truth for "done")

1. *"There should be a topology builder similar to GNS3."*
2. *"There should be the option to connect to machines via SSH/VNC and issue basic commands."*
3. *"The machines should be in 192.168.230-240.x."*
4. *"There should be the option to create a topology and scenario yourself."*
5. *"There should be the option to view more detailed logs."*
6. *"There should be the option to rename machines with 'normal' names in addition to IDs."*
7. *"Machines should have UUIDs too."*

Every one of the seven must be visibly satisfied by a working feature, with evidence, by the end of
this mandate. If any cannot be, say so explicitly with the reason code.

---

## 3. Milestones

### V.1 — Machine identity and the lab address plan (complaints 3, 6, 7)

**Identity.** `src/polmon/topology/models.py` `Node` gains, all optional with sane defaults so
v0.4.x documents still validate:

- `name: str | None` — **human display name** ("normal name"): free-form UTF-8 label, 1–64 chars,
  no control characters, unique within a topology (case-insensitive). Defaults to `id` when absent.
  This is the name shown on the canvas, in tables, in console tabs, in reports and in logs.
- `uuid: UUID` — RFC 4122 **v4**, stable for the node's life, unique across a topology, generated
  when absent. Accepted from YAML as a string; normalized to canonical lowercase hyphenated form.
  Visible and copyable in the client (inspector + a "copy UUID" action) and present in exports,
  API documents, reports and logs. Node `id` remains the machine-readable key; `uuid` is the global
  identity; `name` is the label. Document the three-way distinction in `docs/TOPOLOGY.md`.

**Address plan (complaint 3).** Introduce an explicit laboratory profile:

```
LAB_ADDRESS_PROFILE = 192.168.230.0/24, 192.168.231.0/24, … , 192.168.240.0/24   (11 /24s)
```

- A topology may declare `address_space: lab-profile | rfc1918`. **Default is `lab-profile`**:
  every network's `ipv4_subnet` must lie inside one of the 11 profile /24s, so deployed machines are
  in `192.168.230.x … 192.168.240.x` exactly as the operator asked. `rfc1918` keeps the old
  RFC 1918 + `198.18.0.0/15` acceptance for compatibility and is documented as the explicit,
  non-default escape hatch (existing topologies that declare it keep working).
- **Migrate the repository's own content** to the profile: `examples/topologies/*`,
  `examples/scenarios/*`, docs snippets, and every test fixture that asserts an address. Keep a
  `polmon-topology --migrate <file>` helper (or an equivalent documented path) that rewrites a v0.4
  topology into a profile-compliant one (renumbering interfaces deterministically, preserving MACs).
- **Auto-allocation helpers** (used by the builder, the CLI and tests): next free `/24` in the
  profile, next free host address in a subnet (never network/broadcast, never an already-used
  address), next free unicast MAC in a lab-assigned locally-administered prefix, deterministic and
  documented. The builder must never require the operator to type an address by hand.
- Update `docs/SECURITY.md` + `docs/TOPOLOGY.md` to describe the profile, the escape hatch and why
  narrowing the space is a safety property; add unit tests for range enforcement, allocation
  exhaustion behaviour, and the migration helper.

**Gate for V.1:** all identity/allocation tests green; every example, scenario and doc reference is
inside the profile; `scripts/check.sh` green; the 409-test baseline is not reduced.

### V.2 — Topology studio: a GNS3-like builder (complaints 1, 4, 6, 7)

Replace the current form-driven topology editor (`src/polmon/client/pages/topologies.py`) with a real
**graphical builder** — a node-and-link canvas in the Qt client — while keeping a plain YAML tab for
direct editing. Required capabilities:

- **Canvas**: infinite-ish scene, pan (middle-drag/space-drag), zoom (wheel, ctrl+wheel, fit-to-view,
  zoom-to-selection, 25 %–400 %), grid with snap-to-grid toggle, alignment guides, marquee select,
  multi-select (ctrl/shift), move, delete, copy/paste/duplicate, undo/redo (a real command stack).
- **Palette ("similar to GNS3")**: a device palette with categories and distinct icons — `L0`
  synthetic endpoint, `L1` namespace container, `L2` VM (future), and **network/switch** objects
  (a link-level broadcast domain) — plus a **connection tool** (drag from a node's interface handle
  onto a network/switch, or from network to node) that creates the interface, allocates MAC + IPv4
  from the profile, and refuses invalid links with a coded message.
- **Live validation**: the canvas continuously posts to `POST /v1/topologies/validate` and renders
  errors/warnings per node and per link in a validation panel with a click-to-focus jump; the
  document may be edited while invalid, but deploy is blocked with the same coded errors.
- **Inspector**: name (rename with a "normal" name, inline on the canvas too — double-click to
  rename), id, **UUID (with copy action)**, class, resources, interfaces (network, MAC, IPv4),
  services, and the console/VNC entry points. Renaming never changes `id` or `uuid`.
- **Persistence**: the operator must be able to **create topologies from scratch and keep them**.
  Today `ControlPlane.topologies` is an in-memory dict — a backend restart loses everything. Add a
  **persistent library** under the backend data directory (`<data-dir>/library/topologies/*.yml`,
  `/library/scenarios/*.yml`), with atomic writes, CRUD endpoints (`PUT`/upsert for existing ids),
  list/get/delete, and `import`/`export` of YAML from the client. Saving is idempotent; deleting asks
  for confirmation in the UI.
- **Layout persistence**: node positions are part of the document (`layout: {x, y}` per node,
  optional) so a saved topology reopens exactly as drawn; a loaded document without layout gets a
  deterministic auto-layout. Keep this additive and backward compatible.
- **Offline-safe**: with no backend connected, the builder still edits, validates locally where
  possible, imports/exports YAML, and clearly shows what needs a backend.
- Full RU/EN localization for every new string (`locales/ru.py`, `locales/en.py`; the completeness
  and lint scripts must pass), consistent with the existing design tokens and dark/light themes.

**Gate for V.2:** a fresh topology can be drawn from an empty canvas — nodes placed, renamed,
connected, automagically addressed, validated, saved, exported, reopened identically, deployed, and
reset — with GUI tests covering the builder's model operations (create/move/link/undo/redo/validate/
save/load) and a written walkthrough in `docs/TOPOLOGY-STUDIO.md`.

### V.3 — Console access over SSH: connect to machines and issue commands (complaint 2, first half)

Make lab machines genuinely reachable and drivable. **This is L1 (Linux namespace) and, later, L2 —
it is refused with a coded message for L0**, because a shared-process synthetic endpoint has no
application stack and emulating a login would be a fake.

- **In-namespace SSH service**: a new built-in service implementation `ssh` for L1 nodes
  (`ServiceDefinition.implementation == "ssh"`, TCP, default port 22). The namespace backend starts
  an sshd **inside the node's namespace** on the node's own address (the probe in §1 shows the
  mechanism), with a per-deployment ed25519 host key, `PasswordAuthentication no`,
  `PermitRootLogin no`, `UsePAM no`, an `AuthorizedKeysFile` pointing at a deployment-private
  authorised-keys file, and a **dedicated unprivileged lab account** (created by the lab
  prerequisite script, `--create-lab-account`, or an existing unprivileged user with an explicit,
  documented policy — decide and document which). Host keys, the private key and the config live in
  the run directory with `0600`/`0700` and are never shipped in a release.
- **Backend console API** (auth as every other route; token mandatory off loopback):
  - `POST /v1/deployments/{topology_id}/nodes/{node}/console/exec` — run **one bounded command**,
    return exit status, stdout, stderr, duration, and the resolved node identity. Bounded output
    (hard byte cap), bounded time, argv-only dispatch through the existing `CommandRunner` — never
    shell interpolation, never a host-level command.
  - `POST …/console/sessions` + `GET/DELETE …/sessions/{sid}` + streaming (`/stream`, SSE with
    cursor, or documented polling) + `POST …/sessions/{sid}/input` — an **interactive session**
    (`ssh -tt` on a PTY) with a bounded ring buffer, idle timeout, and clean teardown.
  - `GET …/console/readiness` — reports whether SSH (and VNC, see V.4) is available on this host and
    for this node class, with the exact missing prerequisite when not.
- **Client Console page** (new page, the 8th): one tab per machine — tab title is the node's
  **normal name** (falling back to `id`), the inspector shows `id` and `uuid` — an output pane, an
  input line with history (up/down), Ctrl+C to interrupt, a clear-session action, a
  **basic-commands palette** (at minimum: `hostname`/`cat /etc/hostname`, `ip -o -4 addr`,
  `ip route`, `arp -n`/`ip neigh`, `ping -c 4 <target>`, `ss -tlnp`/`netstat`, `ps`, `uptime`,
  `nc -z <host> <port>`), and a per-session transcript that is written to the run directory and is
  fetchable later. **A custom command is allowed in the interactive console** — this is the operator's
  GNS3-like experience, it is a lab shell inside a namespace — but every command is audited (who,
  when, which node, exit status) and the transcript is retained.
- **Session/typewriter feel**: line-oriented is acceptable (no full VT100 emulator required), but
  output must stream as it is produced, ANSI escapes must not corrupt the view, and long output must
  not freeze the GUI (worker thread + bounded buffer), consistent with the client's existing
  "GUI thread never does I/O" rule.
- **Docs + security**: `docs/CONSOLE.md` (how to enable, prerequisites, threat model, what is
  recorded), `docs/SECURITY.md` update (lab shell is confined to a namespace, is not root, has no
  host-network reach by construction; tokens mandatory off loopback; audit trail), and
  `scripts/privileged-tests.sh` extended to prove: sshd runs in-namespace, a key-auth exec works,
  **and the host network is still untouched afterwards**.
- **Windows**: the bundled local backend is `l0_only`, so the console is refused there with the
  existing coded "Linux host required" path. The remote-Linux-backend flow must work end to end and
  be documented in `docs/CLIENT.md`.

**Gate for V.3:** a real end-to-end run on this host — deploy an L1 topology with `ssh` services,
open a console from the backend API, execute at least three different basic commands on at least two
different machines, capture real output (including a failing command's non-zero exit), interrupt a
running command, tear the session down, reset the deployment, and prove no lab namespace/interface
survives. Evidence into `docs/evidence/phase-v/`; raw transcripts retained.

### V.4 — VNC: a graphical console (complaint 2, second half)

Deliver VNC as a **real** capability with an honest readiness gate:

- **Server side**: inside an L1 namespace, start `Xvfb` (present) on a private display plus
  `x11vnc` (absent today — installable from Ubuntu as candidate `0.9.16-10`), bound to the node's
  lab address, with an access password (or key-only path) generated per deployment. Add the
  prerequisite to the lab prerequisite script and to `polmon-diagnostics --lab`, and report absence
  as a **coded, actionable** refusal (`vnc.vnc_server_missing` naming the exact package) rather than
  a generic error. Choose and document what runs inside the display (a minimal X client stack —
  `xterm`/`xclock`/a small Qt-free tool — must be documented as a prerequisite too; if no X client
  is available, say so instead of showing an empty grey screen and calling it done).
- **Client side**: the Qt client renders the remote framebuffer itself (a minimal RFB client:
  protocol 3.8, `Raw` + `Hextile` encodings, framebuffer updates into a `QImage`, keyboard and mouse
  events back), fed by a backend relay endpoint
  (`…/console/vnc` — chunked/WebSocket byte stream, token-authenticated). The client must stay a thin
  HTTP consumer: no VNC library in the client, no direct unauthenticated socket to the lab.
- **Scope honesty**: VNC is for L1 nodes where the host provides the stack; L0 and any host without
  the prerequisites are refused with a coded message. Do not manufacture a fake framebuffer.

**Gate for V.4:** the code, the API surface, the readiness/refusal path, and the documented
prerequisites are honest and green, backed by evidence that is **headless-runnable on this server**:
an API call through the authenticated relay, a TCP handshake, `RFB 003.008` observed on the wire, and
unit/integration tests. **Do NOT attempt a visual/interactive validation on this host — it is a
headless server with no display, and the client GUI is validated by the operator on his own Windows
desktop.** A rendered framebuffer watched by a human (or a screenshot pipeline built to fake one) is
explicitly NOT required and must not block the phase: if it is the only thing missing, record
`v4.no_visual_validation_on_headless_server` as a reason-coded limitation and move to V.5.

### V.5 — Scenario studio: author your own scenarios (complaint 4)

- **Scenario library**: today only `POST /v1/scenarios/validate` exists and scenarios are not stored.
  Add persistent CRUD (`/v1/scenarios` list/get/put/delete + upsert), a library on disk beside
  topologies, and import/export YAML.
- **Extend the action catalogue** so a user-authored scenario can actually exercise the new console
  capability while keeping the existing safety posture (named, bounded actions — no arbitrary shell
  in an automated step):
  - keep `icmp` reachability and declared TCP `service` probes;
  - add **`ssh_exec`**: run a **named** command from a documented catalogue (parameters allowed:
    target host, count, port, listen flag, etc.) on a node, with expected exit status;
  - add **timing/observation assertions**: expected latency bounds, expected success/failure,
    expected output match on a bounded pattern (from the catalogue), so a scenario can *assert*
    rather than just probe;
  - add **`wait`/`sleep`** with bounds and **cleanup steps** that run from `finally` regardless;
  - every new action validates statically against the topology before execution (unknown node,
    unknown target, port outside the catalogue, etc.) and has a stable code.
- **Scenario builder UI**: step list editor (add/remove/reorder/duplicate), per-step form with
  validation, initial conditions, timeout, cleanup policy, expected outcomes, run with live progress
  and cancellation (existing machinery), save/load/export, and a "run on this topology" flow from the
  topology builder. Full RU/EN localization.
- `docs/SCENARIOS.md` rewritten to document the catalogue, the closed-vs-closed design rationale
  (automated = bounded catalogue; interactive = free console), and worked examples in
  `examples/scenarios/`.

**Gate for V.5:** an operator-authored scenario (created through the API and through the UI) that
mixes ICMP, a TCP probe, an `ssh_exec` command and a timing assertion runs to completion on a real
deployment with real observations, passes and fails as designed (show both a passing and a
deliberately failing run), and is reloaded from the library after a backend restart.

### V.6 — Detailed logs (complaint 5)

- **Structured logging in the backend**: JSON-line records with level, timestamp, logger, event code,
  human message, parameters, and correlation ids (`deployment`, `topology`, `node` **name + id +
  uuid**, `experiment`, `session`); a bounded in-process ring buffer plus rotating files under the
  data directory; every lab-level operation (provision, service start, interface up, rule applied,
  command executed, teardown) emits a record.
- **Capture what is thrown away today**: in-namespace service/console processes are started with
  `stdout=stderr=DEVNULL` (`backends/namespace/runner.py`). Pipe them to per-node, per-session log
  files with size caps and surface them — this is the single most valuable source of "more detailed
  logs" and it is currently discarded.
- **API**: `GET /v1/logs` with filters (level ≥, source/logger, deployment, node, session, free-text
  search, `since`/cursor, limit) and paging; `GET /v1/logs/stream` for live following (SSE with
  cursor, documented); `GET /v1/logs/files` for the on-disk log index. Bounded responses, no
  unbounded scans, no log content in error messages.
- **Detail beyond events**: expose per-action experiment traces to the detail level this phase
  produces (action start/end, resolved target, timing, packets/observations counters, exit status
  and safe stderr excerpt) and per-node service output; add a verbose/raw view distinct from the
  existing event telemetry stream. Keep the telemetry page as the *event* view and make the new
  **Logs page** the detailed view (level chips, source filter, node/deployment filter, search,
  follow toggle, row detail with the full JSON record, copy row, export selection to a file, and the
  path of the on-disk log for the operator).
- Diagnostics: `polmon-diagnostics --logs` (or equivalent) prints the log directory, sizes and the
  last N errors; `docs/LOGS.md` documents levels, codes, retention and how to read a bundle.

**Gate for V.6:** a real deployment + console session + experiment produces a traceable log stream
where a single correlation id (e.g. one node's UUID) retrieves its provision, service start, console
command and teardown records; the Logs page shows, filters, follows and exports them; on-disk files
rotate and stay size-bounded; log content is absent from API error payloads.

### V.7 — Release v0.5.0

- Version `0.5.0` visible everywhere: client About/header, `--version` for every CLI, `/v1/health`,
  report headers, artefacts and the packaged bundles.
- Docs: README phase summary, `CHANGELOG.md` complete, `ARCHITECTURE.md` (builder, console relay,
  log pipeline, persistent library), `docs/TOPOLOGY-STUDIO.md`, `docs/CONSOLE.md`, `docs/LOGS.md`,
  `docs/API.md` (every new route + code), `docs/CLIENT.md` (new pages), `docs/SECURITY.md`,
  `docs/UI-GUIDE.md` refresh, `docs/evidence/phase-v/` with the real captured evidence.
- `examples/` updated: a profile-addressed topology that includes `ssh` services and a scenario that
  uses the new actions.
- Packaging: keep `PyInstaller` specs valid and build what can be built locally; **GitHub Actions is
  billing-blocked** (§1) so Windows artefacts may be impossible — if so, record it honestly as a
  reason-coded limitation with the exact workflow evidence, and keep the workflow files correct so a
  future run works. Do not claim a Windows build that did not run.
- Phase report `docs/milestones/v0.5.0.md`: what was delivered per complaint, the real evidence, the
  measured resource cost, and an explicit KNOWN LIMITATIONS section (including anything skipped with
  a reason code). Annotated tag `v0.5.0` on the merge commit; `origin/main` updated only when gates
  are green.

---

## 4. Definition of done

1. All seven complaints are satisfied by working, demonstrated features — with the evidence paths
   recorded in the phase report.
2. `scripts/check.sh` green (≥ 409 tests, no regressions), `scripts/privileged-tests.sh` green with
   the host-network-untouched proof, i18n scripts green.
3. A real end-to-end demonstration on this host exists as raw captured output in
   `docs/evidence/phase-v/`: build a topology in the studio, deploy it, SSH into two machines and run
   commands, run an operator-authored scenario, and pull the detailed logs for one node by UUID. All
   evidence must be **headless-runnable** (API calls, wire traces, test output). **No visual or
   interactive GUI validation on this server** — the client GUI is the operator's own acceptance test
   on his Windows desktop; VNC may be closed with `v4.no_visual_validation_on_headless_server`.
4. `PHASE-V-PROGRESS.md` reflects reality, and every commit is pushed on `phase-v-studio`.
5. Honest KNOWN LIMITATIONS: no fabricated passes; CI/billing blocker stated; anything not
   installable named with its package.

## 5. Explicitly out of scope

L2/KVM virtual machines (still an architectural extension — but the builder must not pretend they
work: `l2` nodes stay validated-but-refused exactly as today), arbitrary host-level command
execution, any change to the host's own networking, and elaborate CI/screenshot pipelines for this
phase.
