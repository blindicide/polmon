# Phase V progress

Last updated: 2026-09-28 (Europe/Amsterdam)
Branch: `phase-v-studio`
Baseline: `main @ 634f49a` (`v0.4.1`)

## Verified

- Baseline facts from `INSTRUCTION-PHASE-V.md` accepted as directed: in-namespace SSH is feasible;
  GitHub Actions run `36314086429` was billing-blocked and is not release evidence.
- V.1 verified locally: `scripts/check.sh` passed with 417 tests (14 deselected), above the
  409-test baseline; i18n lint and completeness both passed; all five repository topology examples
  loaded under `lab-profile` and were scanned inside `192.168.230.0/24`–`192.168.240.0/24`.
- V.2 verified locally: `scripts/check.sh` passed with 421 tests (14 deselected); i18n lint and
  completeness passed. The studio operation suite covers create/move/connect/rename/duplicate/
  delete/undo/redo/round-trip, and API tests prove atomic persistence, upsert, restart reload and
  deletion.

## In flight

- V.2 commit preparation and push.

## Exact next step

Stage V.2 through the conventional-commit safety gate, commit and push it, then begin V.3 by adding
the in-namespace SSH service lifecycle and bounded backend console execution API.

## Milestone status

| Milestone | State | Evidence |
|---|---|---|
| V.1 | committed and pushed (`287f6b0`) | `scripts/check.sh`: 417 passed; i18n gates passed |
| V.2 | verified, awaiting commit | `scripts/check.sh`: 421 passed; i18n gates passed |
| V.3 | not started | — |
| V.4 | not started | — |
| V.5 | not started | — |
| V.6 | not started | — |
| V.7 | not started | — |

## Known limitations

- `ci.billing_blocked`: GitHub-hosted Windows jobs are unavailable; no Windows artifact will be
  claimed unless an actual build becomes available.
