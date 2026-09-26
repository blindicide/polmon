# Changelog

All notable changes are documented here. Versions follow Semantic Versioning.

## [0.0.8] - 2026-09-26

### Added

- One shared TAP per hybrid network connecting the synthetic engine to isolated Linux bridges.
- Cross-boundary ARP and ICMP echo with bounded raw-frame capture and deterministic teardown.
- Unit command-plan and real privileged L0-to-L1 integration coverage.

## [0.0.7] - 2026-09-26

### Added

- Linux namespace backend with isolated bridges, veth interfaces, addressing, and direct routing.
- Predefined lightweight HTTP service lifecycle and connectivity probes.
- Narrow privileged command boundary, deterministic teardown, unit command-plan checks, and opt-in
  real namespace integration coverage.

## [0.0.6] - 2026-09-26

### Added

- Validated Ethernet II, ARP, minimal IPv4, and ICMP echo packet codecs.
- Deterministic synthetic address resolution and ping exchange with bounded frame capture.
- Known-byte fixtures for Internet, IPv4, and ICMP checksum validation.

## [0.0.5] - 2026-09-26

### Added

- Shared-process L0 endpoint registry with unique instance, MAC, and IPv4 identities.
- Bounded virtual networks, packet queues, deterministic event scheduling, and resource accounting.
- Synthetic orchestration backend and repeated 50-endpoint lifecycle coverage.

## [0.0.4] - 2026-09-26

### Added

- Backend-neutral execution interface and explicit topology lifecycle state machine.
- Process-wide resource ownership tracking, atomic create rollback, and idempotent cleanup.
- Failure-injectable mock backend and comprehensive transition/failure tests.

## [0.0.3] - 2026-09-26

### Added

- Strict YAML topology model with nodes, networks, interfaces, resources, and safe service metadata.
- Duplicate, overlap, address-conflict, and unsupported-configuration validation.
- Stable serialization, privilege-free resource estimation, inspection CLI, and hybrid example.

## [0.0.2] - 2026-09-26

### Added

- Secret-free environment diagnostics and process/system resource snapshots.
- Structured JSON logging, backend startup resource events, and consistent public API errors.
- Explicit integration and privileged markers, coverage XML, JUnit artifacts, and CI summaries.

## [0.0.1] - 2026-09-26

### Added

- Python project foundation with FastAPI backend and standalone Tkinter client.
- Headless `--version` and `--self-test` client commands.
- Linux CI, GitHub-hosted Windows packaging, executable smoke validation, and release automation.
- Initial test suite and development, architecture, security, resource, build, CI, and release docs.
