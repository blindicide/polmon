# Phase V progress

Last updated: 2026-09-28 11:25Z (supervisor, at the dk credit wall)
Branch: `phase-v-studio`
Baseline: `main @ 634f49a` (`v0.4.1`)

**READ THIS FIRST IF YOU ARE RESUMING:** the phase stopped on a hard roadblock, not on completion.
The dk relay key pool ran out of credit and every request now returns
`Service Unavailable {"detail":"no usable openai upstream keys"}`. HEAD is
**`3e85a05`**, a WIP preservation commit — it is **not** milestone V.4 and its gates are **red**.
See "Exact next step" below.

## Verified

- Baseline facts from `INSTRUCTION-PHASE-V.md` accepted as directed: in-namespace SSH is feasible;
  GitHub Actions run `36314086429` was billing-blocked and is not release evidence.
- **V.1** (`287f6b0`) — machine identity (`name` / `uuid` / `id`), `lab-profile` address space,
  allocation helpers, `--migrate` CLI, docs, examples and fixture renumbering.
- **V.2** (`d8f42be`) — graphical topology studio (`client/studio.py`), persistent library
  (`src/polmon/library.py`), CRUD routes, layout persistence, `docs/TOPOLOGY-STUDIO.md`,
  `tests/gui/test_topology_studio.py`.
- **V.3** (`4686435 feat(console): add namespace SSH console access`) — **verified by the
  supervisor, all gates green:** `scripts/check.sh` = **423 passed / 16 deselected in 130 s**
  (exit 0, above the 409-test baseline; the earlier stale `Ctrl+1 … Ctrl+7` GUI failure is fixed);
  `scripts/privileged-tests.sh tests/integration/test_console_ssh.py` = **2 passed**, printing
  *"host network unchanged; no platform lab resources remain"*; i18n lint + completeness clean;
  live host probe showed no lab namespaces and `ens3`/`docker0`/`tailscale0` unchanged.
- `origin/phase-v-studio` is in sync with local HEAD (`git ls-remote` verified).

## In flight — V.4 (VNC), INCOMPLETE

Committed as **`3e85a05 wip(v4): namespace VNC relay and thin RFB client [INCOMPLETE - gates red]`**
plus the earlier partial `ad94225 feat(console): add VNC readiness and refusal path`.

**What is genuinely done and independently observed by the supervisor:**

- `x11vnc 0.9.16-10` **is installed** on this host (`sudo -n apt-get install -y x11vnc` succeeded;
  `dpkg -l` confirms). `Xvfb`, `xclock`, `sshd`, `ssh`, `ip netns` all present.
- The real lab stack was **seen running**: two namespaces, in-namespace `sshd`,
  `Xvfb :678 -screen 0 1024x768x24`, `xclock -digital` on `DISPLAY=:678`, and
  `x11vnc -display :678 -rfbport 5911 -listen 192.168.239.11`. A supervisor probe into that
  namespace received the real RFB banner **`RFB 003.008`**. Namespaces were cleaned up afterwards.
- `docs/evidence/phase-v/v4-vnc-readiness.txt` has been **corrected**: the earlier false claim
  *"this host lacks x11vnc and xterm"* is retracted and replaced with the real install transcript.
  It now states the gate is in progress and no limitation is claimed from prerequisite absence.
- A thin Qt RFB viewer (`src/polmon/client/vnc.py`, untracked→now committed) was being written with
  a standard-library WebSocket transport and RFB 3.8 Raw decoding into `QImage`.

**What is NOT done:**

- `ruff` is **RED**: `E501 src/polmon/backends/namespace/backend.py:335 (106 > 100)`.
- `scripts/check.sh` and `scripts/privileged-tests.sh tests/integration/test_console_ssh.py` were
  **not re-run** after the last edits, so V.4 has **no green gate**.
- The dedicated relay test (`test_vnc_api_relay_delivers_framebuffer_and_input`, proving
  framebuffer + keyboard/pointer through the authenticated backend relay into the Qt viewer) was
  written but its final green run was never captured.
- No `docs/evidence/phase-v/` capture of the V.4 end-to-end run.

## Exact next step

1. Fix the `E501` at `src/polmon/backends/namespace/backend.py:335` (the over-long line is inside a
   generated `python3 -c` string; split it).
2. Run `scripts/check.sh` and `scripts/privileged-tests.sh tests/integration/test_console_ssh.py`
   and get both green.
3. Capture the real V.4 evidence into `docs/evidence/phase-v/` (the framebuffer + input relay run).
4. Commit V.4 properly (conventional message, green gates) and push — superseding `3e85a05`.
5. Then proceed V.5 → V.6 → V.7 per the mandate.

Do not treat `3e85a05` as a completed milestone.

## Milestone status

| Milestone | State | Evidence |
|---|---|---|
| V.1 | committed + pushed (`287f6b0`) | `ruff` + i18n clean; full gate re-run by supervisor: 423 passed / 16 deselected |
| V.2 | committed + pushed (`d8f42be`) | `ruff` + i18n clean; `tests/gui/test_topology_studio.py` present |
| V.3 | committed + pushed (`4686435`), **verified green** | `check.sh` 423 passed / 16 deselected; privileged console tests 2 passed; host network unchanged; i18n clean |
| V.4 | **incomplete — WIP commit `3e85a05`, gates RED** | `x11vnc 0.9.16-10` installed; lab stack + `RFB 003.008` observed live; `E501` outstanding; no green gate |
| V.5 | not started | — |
| V.6 | not started | — |
| V.7 | not started | — |

## Hard roadblock

- `dk.credit_exhausted`: the dk relay key pool is out of credit. Every request, including a live
  probe from the supervisor, returns
  `Service Unavailable: {"detail":"no usable openai upstream keys"}`.
  **Work cannot continue on this rig until the pool is topped up or another route is provided.**
  Reported to the operator with the exact error. The session was left alive holding resume state.

## Known limitations

- `ci.billing_blocked`: GitHub-hosted Windows jobs are unavailable; no Windows artifact will be
  claimed unless an actual build becomes available.
- `v4.gate_incomplete`: V.4 has no green gate and no captured evidence yet. The previously recorded
  `vnc.prerequisite_missing` limitation was **false** and has been removed — `x11vnc` is installed
  and the stack demonstrably runs on this host.
