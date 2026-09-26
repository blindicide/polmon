# Continuous integration

`ci.yml` lints and tests every push to `main` and every pull request with read-only permissions.
`build-windows.yml` uses a GitHub-hosted Windows runner and uploads the verified executable. In a
workflow run, open **Artifacts** and download `polmon-windows-x64`. Test XML is uploaded even after
a failing Linux test so failures remain inspectable. Pull-request jobs receive no repository
secrets.

`build-windows.yml` accepts optional `ref` and `pytest-deselect` inputs. `release.yml` passes the
release tag as `ref`, so a manual `workflow_dispatch` repair of an older tag builds that tag's
source; see RELEASE.md for the repair procedure and its reporting rules.

CI also checks the syntax of every `scripts/*.sh`, runs each installed entry point with `--version`
and requires it to print the package version, and runs the small rootless benchmark test
(`pytest -m "performance and not privileged"`: 10 and 25 L0 endpoints) so benchmark code cannot
silently break. Privileged tests and large benchmarks never run in hosted CI.

