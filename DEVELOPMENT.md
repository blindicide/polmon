# Development

Use only Python 3.12 through the project environment:

```bash
uv venv --python /usr/bin/python3.12
uv pip install -e '.[dev,build]'
.venv/bin/ruff check .
.venv/bin/pytest -m 'not privileged and not performance'
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

GUI tests (`pytest -m gui`) drive the real Tk client and need a display; run them with
`xvfb-run -a .venv/bin/python -m pytest -m gui` on a headless Linux host. Without a display they
are reported as NOT RUN.
