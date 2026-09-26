# Development

Use only Python 3.12 through the project environment:

```bash
uv venv --python /usr/bin/python3.12
uv pip install -e '.[dev,gui,build]'
.venv/bin/ruff check .
.venv/bin/pytest -m 'not privileged and not performance and not gui'
xvfb-run -a .venv/bin/pytest -m gui
```

Keep unit, integration, privileged, performance, and smoke tests explicitly marked. Default tests
must fit two CPU cores and 2 GB RAM. Add dependencies only with a documented purpose and resource
cost. Source, documentation, generated reports, and logs use UTF-8.

Use `pytest tests/unit` for the rootless unit gate, `pytest -m integration` for non-privileged
integration coverage, and select privileged tests explicitly with `pytest -m privileged` only in
an authorized isolated laboratory. CI excludes `privileged` and `performance`, publishes JUnit and
coverage XML artifacts, and writes a count summary to the workflow run.

`scripts/check.sh` runs the same lint and rootless gate as CI. `scripts/privileged-tests.sh` runs
the privileged selection and fails if the default route, the host's non-lab interfaces, iptables
rules, or the nft ruleset structure (counters and dynamic set elements such as fail2ban bans
omitted) changed, or if any platform-named namespace or
interface remains; `scripts/lab-cleanup.sh` lists such leftovers and removes them with `--apply`.
Performance tests live in `tests/performance/` and run only with `pytest -m performance`; they use
small sizes, and the 100/250-endpoint runs require `polmon-benchmark l0 --large`.

The desktop client is Qt (PySide6, the `gui` extra; see [docs/UI-PLAN.md](docs/UI-PLAN.md)). Its
tests live in `tests/gui/` and are marked `gui`: they build the real widgets with `pytest-qt` and
drive them against real in-process backends (connect, validate, deploy, run, cancel, telemetry,
reports, benchmarks, unreachable/slow/malformed/dying backends). CI runs them under `xvfb-run`
(platform `xcb`) on Linux and with `QT_QPA_PLATFORM=offscreen` on Windows; on a headless host
without Xvfb they select the offscreen platform automatically. Without PySide6 installed they are
reported as NOT RUN. The Qt system libraries needed for `xcb` on Ubuntu are listed in
[BUILD-LINUX.md](BUILD-LINUX.md).

`polmon-client --self-test` checks Qt, its platform plugins, the main window and the API client
off screen and never opens a window; `polmon-client --smoke-start 3` shows the real window on the
native platform for three seconds and reports the platform, launch-to-window time and idle RSS.
`scripts/measure-client.py --runs 5 -- .venv/bin/polmon-client` repeats that measurement.
