# Security and network isolation

polmon is only for explicitly designated laboratory networks. Defaults prohibit external routing,
production targets, automatic discovery, host firewall changes, and arbitrary user-supplied shell
commands. Privileged integration work may create only project-owned isolated bridges, namespaces,
and veth interfaces. Cleanup must be deterministic even after failure. Do not store credentials in
configuration, logs, telemetry, reports, or repository files. Report vulnerabilities privately to
the repository owner; do not include exploit details in a public issue.

Controls in the implementation:

- Topology subnets are restricted to RFC 1918 and RFC 2544 laboratory ranges; scenario actions can
  only target nodes declared in the bound topology, never raw addresses or discovered hosts.
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
- API identifiers are pattern-checked before they reach file paths; request bodies are capped at
  2 MB per document and 5 MiB per request.
- Telemetry redacts secret-like keys; diagnostics use an allow-list and never read the environment.
- `scripts/privileged-tests.sh` proves each privileged run left the default route, host interfaces,
  iptables, and nft ruleset unchanged; `scripts/lab-cleanup.sh` lists or removes leftovers
  (including orphaned lab service processes) by generated name only.

Dependencies are pinned exactly in `pyproject.toml` and `uv.lock`. Audit them before a release with
`uvx pip-audit -r <(uv pip freeze --python .venv/bin/python | grep -v polmon)`; the 2026-09-26 audit
after the starlette 1.7.0 upgrade reported no known vulnerabilities.

