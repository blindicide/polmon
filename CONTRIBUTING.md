# Contributing

Use English, UTF-8, Conventional Commits, and focused changes. Add tests and documentation with
behavior changes. Run Ruff and the non-privileged test suite before committing. Privileged tests
must be isolated, marked, opt-in, and clean up all project-owned network resources. Do not modify
host interfaces, default routes, DNS, or firewall state.

Run `scripts/check.sh` (the same lint and rootless gate as CI) before committing. Privileged work
is verified with `scripts/privileged-tests.sh`, which fails if the host network changed or any
platform-named laboratory resource remains.
