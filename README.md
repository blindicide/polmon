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
.venv/bin/pytest
.venv/bin/polmon-backend
```

Run `.venv/bin/polmon-client --version` or `--self-test` without a display. The GUI can be
opened with `.venv/bin/polmon-client`; it starts independently of the backend.

See [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPMENT.md](DEVELOPMENT.md), and
[SECURITY.md](SECURITY.md). No license has been granted; a license file will be added only after
the repository owner makes an explicit licensing decision.
