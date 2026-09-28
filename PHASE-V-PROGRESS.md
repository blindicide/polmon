# Phase V progress

Last updated: 2026-09-28 09:15Z (resumed rig)
Branch: `phase-v-studio`
Baseline: `main @ 634f49a` (`v0.4.1`)

## Verified

The resumed rig re-ran the gates against the V.3 tree: `scripts/check.sh` is green at
**423 passed / 16 deselected in 132 s**, compared with the 409-test pre-Phase-V baseline.
The additional V.3 tests are included and there is no regression. The i18n lint and completeness
gates are also green.

- Baseline facts from `INSTRUCTION-PHASE-V.md` accepted as directed: in-namespace SSH is feasible;
  GitHub Actions run `36314086429` was billing-blocked and is not release evidence.
- **V.1** (`287f6b0`) — machine identity (`name` / `uuid` / `id`), `lab-profile` address space,
  allocation helpers, `--migrate` CLI, docs, examples and fixture renumbering. `ruff` clean;
  i18n lint + completeness clean; re-verified in the resumed V.3 gate run.
- **V.2** (`d8f42be`) — graphical topology studio (`client/studio.py`, 518 lines), persistent
  library (`src/polmon/library.py`), CRUD routes, layout persistence, `docs/TOPOLOGY-STUDIO.md`,
  `tests/gui/test_topology_studio.py`. `ruff` clean; i18n lint + completeness clean; re-verified
  in the resumed V.3 gate run.
- Both commits are **pushed** to `origin/phase-v-studio` — verified by the supervisor:
  `git ls-remote origin phase-v-studio` = local `HEAD`.

## In flight

**V.3 (console over SSH)** — implemented and staged:
`src/polmon/console.py` (session + bounded transcript manager), `src/polmon/client/pages/console.py`
(the 8th client page), `scripts/lab-prerequisites.sh`, `docs/CONSOLE.md`,
`examples/topologies/l1-console.yml`, `tests/integration/test_console_ssh.py`, plus edits to
`api/{control,routes}.py`, `backends/namespace/{backend,runner}.py`, `client/api.py`,
`core/diagnostics.py`, `locales/{en,ru}.py`, `mainwindow.py`.
 The resumed rig ran both required gates. `scripts/privileged-tests.sh tests/integration/test_console_ssh.py`
 passed both tests and proved the host network unchanged with no lab resources remaining.

## Exact next step

Commit V.3 with a conventional-commit message and push it. The next milestone after that is V.4.

## Milestone status

| Milestone | State | Evidence |
|---|---|---|
| V.1 | committed + pushed (`287f6b0`) | `ruff` + i18n clean; supervisor full-gate run on the V.3 tree: 422 passed / 1 failed (see above) |
| V.2 | committed + pushed (`d8f42be`) | `ruff` + i18n clean; `tests/gui/test_topology_studio.py` present |
| V.3 | **gates green, staged for commit** | `check.sh`: 423 passed / 16 deselected; privileged console tests: 2 passed; host network unchanged |
| V.4 | not started | — |
| V.5 | not started | — |
| V.6 | not started | — |
| V.7 | not started | — |

## Known limitations

- `ci.billing_blocked`: GitHub-hosted Windows jobs are unavailable; no Windows artifact will be
  claimed unless an actual build becomes available.
