# Security and network isolation

polmon is only for explicitly designated laboratory networks. Defaults prohibit external routing,
production targets, automatic discovery, host firewall changes, and arbitrary user-supplied shell
commands. Privileged integration work may create only project-owned isolated bridges, namespaces,
and veth interfaces. Cleanup must be deterministic even after failure. Do not store credentials in
configuration, logs, telemetry, reports, or repository files. Report vulnerabilities privately to
the repository owner; do not include exploit details in a public issue.

Controls in the implementation:

- New topology subnets default to the explicit `192.168.230.0/24`–`192.168.240.0/24` laboratory
  profile. Narrowing the accepted space is a safety property: unexpected addresses are rejected
  before any privileged work and owned resources are easy to recognize. The broader RFC 1918 plus
  RFC 2544 policy is available only through an explicit `address_space: rfc1918` compatibility
  declaration. Scenario actions can only target nodes declared in the bound topology, never raw
  addresses or discovered hosts.
- Privileged operations go through one argv-only command runner (`sudo -n`, no shell) limited to
  `ip` namespace, bridge, veth, TAP, address, and in-namespace route operations on generated
  `polmon*`/`veth*` names. Every workload inside a lab namespace (built-in services, ICMP and TCP
  probes) is started through `setpriv` as the invoking user; only `ip` itself and `setpriv` run as
  root.
- Known limit of the Phase I privilege model: `sudo ip` is root-equivalent, because
  `ip netns exec` can run any program. A sudoers rule restricted to `ip` therefore does not confine
  a compromised backend. Run the backend only on a dedicated laboratory host under an account
  whose sudo rights are acceptable to lose; a narrowly scoped privileged helper with a fixed set of
  verbs is the planned replacement.
- The backend binds to `127.0.0.1` by default and refuses any non-loopback address unless an API
  token is configured; with a token, every non-health endpoint requires `Authorization: Bearer`.
  Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`, keep it in a
  mode-600 file passed with `--api-token-file` (or in `POLMON_API_TOKEN`), and never commit it.
  The token is not logged, reported, or shown by the client. Plain HTTP exposes the token on the
  wire: across untrusted networks, reach the backend through an SSH tunnel or a TLS proxy.
- L1 SSH consoles run a real `sshd` inside the node namespace with per-deployment Ed25519 keys,
  passwords/PAM/root login disabled, and the existing invoking unprivileged operator account.
  Interactive commands execute in that namespace, not on the host; sessions have bounded live
  buffers, timeouts, retained transcripts and authenticated API access. L0/L2 and missing host
  prerequisites are refused with stable reason codes. See `docs/CONSOLE.md`.
- API identifiers are pattern-checked before they reach file paths; request bodies are capped at
  2 MB per document and 5 MiB per request.
- Benchmark jobs (`POST /v1/benchmarks`) start only the fixed `polmon-benchmark` module with
  validated numeric arguments (argv, no shell) in their own process group; their limits cannot
  exceed the backend's admission limits or undercut its memory reserve, only one job runs at a
  time, and none runs while an experiment is active. Result names are pattern-checked before any
  file access.
- The desktop client keeps the API token in memory only (never in its settings file, logs,
  window title or reports; asserted by the GUI tests and the end-to-end driver), talks to the
  backend only through the documented HTTP API, and imports no backend or networking code.
  Its settings (`QSettings`: URL, recent URLs, timeout, theme, window layout) hold no secrets.
- The local preset binds its child to `127.0.0.1`, generates a fresh in-memory token and captures
  stdout/stderr in the user's state directory. The child has its own process group; on Windows it
  is also assigned to a kill-on-close Job Object, preventing an orphan after an abrupt client
  crash. Windows enforces L0-only fidelity in both UI and backend. Release EXEs are unsigned and
  may trigger SmartScreen; SHA-256 verification is the available authenticity check.
- Telemetry redacts secret-like keys; diagnostics use an allow-list and never read the environment.
- `scripts/privileged-tests.sh` proves each privileged run left the default route, host interfaces,
  iptables, and nft ruleset unchanged; `scripts/lab-cleanup.sh` lists or removes leftovers
  (including orphaned lab service processes) by generated name only.

Dependencies are pinned exactly in `pyproject.toml` and `uv.lock`; CI's `dependency-audit` job
runs `pip-audit` over the `dev`, `gui` (PySide6) and `build` sets on every push. Release artifacts
are built only on GitHub-hosted runners from the tagged source, with third-party actions pinned
to commit SHAs, and every published asset is listed in `SHA256SUMS.txt`. Audit them before a release with
`uvx pip-audit -r <(uv pip freeze --python .venv/bin/python | grep -v polmon)`; the 2026-09-26 audit
after the starlette 1.7.0 upgrade reported no known vulnerabilities.
