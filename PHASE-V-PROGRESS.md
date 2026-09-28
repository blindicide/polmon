# Phase V progress

Last updated: 2026-09-28 (Codex, headless V.7 release gate complete)
Branch: `phase-v-studio`
Baseline: `main @ 634f49a` (`v0.4.1`)

**READ THIS FIRST IF YOU ARE RESUMING:** V.4, V.5, V.6 and V.7 are green. V.4 evidence is in
`docs/evidence/phase-v/v4-vnc-headless-gate.txt`; V.5 evidence is in
`docs/evidence/phase-v/v5-scenario-studio-gate.txt`; V.6 evidence is in
`docs/evidence/phase-v/v6-logs-gate.txt`; V.7 evidence is in
`docs/evidence/phase-v/v7-release-gate.txt`. Phase V is complete on this branch.

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
- **V.4** — namespace VNC is complete: the generated relay uses non-blocking pipe reads and
  explicit socket writes; the Qt client speaks RFB 3.8 with Raw + Hextile decoding; readiness and
  L0/refusal paths remain coded; the real raw TCP probe and authenticated WebSocket relay delivered
  a 1024x768 framebuffer and pointer event. `scripts/check.sh` = **424 passed / 18 deselected**;
  the privileged console/VNC suite = **4 passed**, with the wrapper proving host network unchanged
  and no platform lab resources remaining; i18n lint/completeness are clean.
- **V.5** — scenario studio is complete: persistent scenario CRUD and restart-safe YAML library,
  bounded `ssh_exec`/wait/catalogue parameters, timing/stdout assertions, cleanup steps, localized
  step-list editor, and documented examples. The real L1 gate created the scenario through the API,
  reloaded it after a fresh control-plane instance, passed the mixed ICMP/TCP/SSH/wait run, and
  failed the deliberately wrong stdout assertion as designed; both runs cleaned up.

## Complete — V.7 (release v0.5.0)

V.7 is complete with headless-runnable evidence, local Linux packaging, the release report and
green rootless/privileged gates. Windows artifacts are explicitly not claimed because the recorded
GitHub Actions workflow was billing-blocked.

**V.4 evidence retained:**

- `x11vnc 0.9.16-10` **is installed** on this host (`sudo -n apt-get install -y x11vnc` succeeded;
  `dpkg -l` confirms). `Xvfb`, `xclock`, `sshd`, `ssh`, `ip netns` all present.
- The real lab stack was **seen running**: two namespaces, in-namespace `sshd`,
  `Xvfb :678 -screen 0 1024x768x24`, `xclock -digital` on `DISPLAY=:678`, and
  `x11vnc -display :678 -rfbport 5911 -listen 192.168.239.11`. A supervisor probe into that
  namespace received the real RFB banner **`RFB 003.008`**. Namespaces were cleaned up afterwards.
- `v4-vnc-readiness.txt` retains the real package/tool transcript and the corrected prerequisite
  status.
- `v4-vnc-headless-gate.txt` retains the raw TCP and authenticated relay markers, gate summaries,
  host-network proof, i18n results, and the explicit headless visual limitation.

## Exact next step

1. Commit and push the V.7 release commit, then create the annotated `v0.5.0` tag on that green
   commit. No further Phase V implementation step remains on `phase-v-studio`.

## Milestone status

| Milestone | State | Evidence |
|---|---|---|
| V.1 | committed + pushed (`287f6b0`) | `ruff` + i18n clean; full gate re-run by supervisor: 423 passed / 16 deselected |
| V.2 | committed + pushed (`d8f42be`) | `ruff` + i18n clean; `tests/gui/test_topology_studio.py` present |
| V.3 | committed + pushed (`4686435`), **verified green** | `check.sh` 423 passed / 16 deselected; privileged console tests 2 passed; host network unchanged; i18n clean |
| V.4 | committed + pushed (`2decb06`), **green** | `v4-vnc-headless-gate.txt`: raw TCP + authenticated relay framebuffer/input, 424/18 rootless gate, 4 privileged tests, host network unchanged |
| V.5 | committed + pushed (`f6af8fb`), **green** | `v5-scenario-studio-gate.txt`: API/UI authoring, restart reload, real L1 pass/fail experiment, 428/19 rootless gate, host network unchanged |
| V.6 | committed + pushed (`4f9431a`), **green** | `v6-logs-gate.txt`: 431/20 rootless gate, real UUID correlation, Logs UI, bounded rotation, diagnostics, host network unchanged |
| V.7 | **green; release commit pending** | `v7-release-gate.txt` and `docs/milestones/v0.5.0.md`: version contract, local Linux bundles, full gates, honest CI/Windows limitation |

## Known limitations

- `ci.billing_blocked`: GitHub-hosted Windows jobs are unavailable; no Windows artifact will be
  claimed unless an actual build becomes available.
- `v4.no_visual_validation_on_headless_server`: no visual/interactive Qt validation was attempted
  on this server; the operator owns the Windows desktop acceptance check. The real xclock stack,
  RFB wire handshake, framebuffer bytes, and pointer relay were validated headlessly.
- The earlier `dk.credit_exhausted` pause was an infrastructure interruption, not a feature result;
  it is retained in the prior commits' history but is no longer blocking this continuation.
- `v7.ci.billing_blocked`: the recorded workflow run `36314086429` could not start hosted jobs;
  no Windows artifact is claimed.
- `v7.windows_build_unavailable_on_headless_linux_host`: Windows PyInstaller specs remain valid
  and version-driven, but were not run on this Linux server.
