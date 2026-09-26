# polmon

polmon is a resource-efficient platform for controlled network-security experiments in
explicitly isolated laboratories. Phase I combines shared-process synthetic endpoints (L0),
Linux network namespaces (L1), and a standalone Windows client. L2 virtual machines are an
architectural extension, not part of the initial implementation.

## Quick start

Requirements: Linux, `/usr/bin/python3.12`, `uv`, and `iproute2` for later privileged tests.

```bash
uv venv --python /usr/bin/python3.12
uv pip install -e '.[dev]'
scripts/check.sh              # lint + rootless tests
.venv/bin/polmon-backend
```

Helper scripts in `scripts/`: `check.sh` (ordinary gate), `privileged-tests.sh` (laboratory tests
with a before/after proof that the host network was untouched), `lab-cleanup.sh` (list or remove
leftover platform-named namespaces and interfaces), `run-benchmarks.sh` (recorded benchmark suite),
and `verify-release.sh` (download a release and check its SHA-256).

Benchmarks run only on explicit request: `.venv/bin/polmon-benchmark l0|l1|target|summarize`. See
[docs/BENCHMARKS.md](docs/BENCHMARKS.md) for limits, method, and the retained raw results.

Run `.venv/bin/polmon-client --version` or `--self-test` without a display. The GUI can be
opened with `.venv/bin/polmon-client`; it starts independently of the backend.

Use `.venv/bin/polmon-diagnostics --json` to inspect the Python version, host capabilities,
network-tool availability, and an allow-listed resource snapshot without exposing environment
variables or credentials. The backend emits structured JSON startup and shutdown logs.

See [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPMENT.md](DEVELOPMENT.md), and
[SECURITY.md](SECURITY.md). No license has been granted; a license file will be added only after
the repository owner makes an explicit licensing decision.
