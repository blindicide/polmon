# Changelog

All notable changes are documented here. Versions follow Semantic Versioning.

## [0.0.14] - 2026-09-26

### Added

- `polmon-benchmark` with L0 (10/25/50, explicit `--large` 100/250), L1 namespace, and Phase I
  target (50 L0 + 2 L1) benchmarks, admission-checked and time/memory-bounded per run, each in a
  fresh worker process, retaining raw JSON/CSV with host, workload, limits, and source commit.
- Generated Markdown summaries, `tests/performance/`, and the first recorded results.
- Helper scripts: `check.sh`, `privileged-tests.sh`, `lab-cleanup.sh`, `run-benchmarks.sh`,
  `verify-release.sh`.

### Fixed

- Synthetic endpoints stopped answering after 256 received frames because delivered frames were
  never consumed from their bounded receive queues (latent since 0.0.6).

## [0.0.13] - 2026-09-26

### Added

- Pre-deployment endpoint, namespace, and available-memory admission with detailed HTTP 429 errors.
- Configurable concurrency, capture, duration, and host-memory reserve limits through API policy and
  backend CLI flags.
- Runtime resource sampling, cooperative automatic/manual cancellation, and resource status API.
- Release workflow `workflow_dispatch` repairs build the pinned tag's own source, reject a
  mismatched executable version, and attach `SHA256SUMS.txt`.

### Fixed

- Hybrid L0-to-L1 traffic could lose its first ARP frame while the TAP bridge port was still
  disabled after attach; deployment now waits for every bridge port to forward (latent since 0.0.8).

## [0.0.12] - 2026-09-26

### Added

- Atomic JSON and Markdown reports with normalized inputs, observations, condition comparisons,
  errors, resource samples, capture statistics, status, timestamps, and version.
- Process-wide reset API that preserves topology definitions for repeatable deployment.
- Exception-path telemetry closure and best-effort recovery that retains failed teardown state.

## [0.0.11] - 2026-09-26

### Added

- Versioned FastAPI contracts for topology, deployment, experiment, status, telemetry, and reset.
- Stateful Linux control plane connecting validated models to L0/L1/hybrid backends and telemetry.
- Responsive Tkinter client with background HTTP operations, explicit timeouts, and useful errors.

## [0.0.10] - 2026-09-26

Release note: the `v0.0.10` tag's own release run (36238266300) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36241102476, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36238264377). See `docs/milestones/v0.0.10.md`.

### Added

- SQLite experiment metadata and ordered structured events with secret-key redaction.
- Resource samples and bounded classic PCAP capture with drop/truncation accounting.
- Foreign-key association and tcpdump interoperability coverage.

## [0.0.9] - 2026-09-26

Release note: the `v0.0.9` tag's own release run (36238094325) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36241097856, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36238093059). See `docs/milestones/v0.0.9.md`.

### Added

- Strict topology-bound scenario YAML with closed ICMP/TCP probe actions and declared targets.
- Deterministic sequence execution, deadlines, cancellation, conditions, observations, and cleanup.
- Controlled reconnaissance example and invalid/preflight/failure-path tests.

## [0.0.8] - 2026-09-26

Release note: the `v0.0.8` tag's own release run (36237923759) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36241093673, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36237921993). See `docs/milestones/v0.0.8.md`.

### Added

- One shared TAP per hybrid network connecting the synthetic engine to isolated Linux bridges.
- Cross-boundary ARP and ICMP echo with bounded raw-frame capture and deterministic teardown.
- Unit command-plan and real privileged L0-to-L1 integration coverage.

## [0.0.7] - 2026-09-26

Release note: the `v0.0.7` tag's own release run (36237741029) failed on Windows because Linux-only unit
tests hit the namespace backend's Linux guard. The tag was not moved; the release was published
later by repair run 36240994208, built from the tag source with those tests deselected on Windows only
(they passed in Linux CI run 36237739216). See `docs/milestones/v0.0.7.md`.

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
