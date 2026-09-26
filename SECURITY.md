# Security and network isolation

polmon is only for explicitly designated laboratory networks. Defaults prohibit external routing,
production targets, automatic discovery, host firewall changes, and arbitrary user-supplied shell
commands. Privileged integration work may create only project-owned isolated bridges, namespaces,
and veth interfaces. Cleanup must be deterministic even after failure. Do not store credentials in
configuration, logs, telemetry, reports, or repository files. Report vulnerabilities privately to
the repository owner; do not include exploit details in a public issue.

