# Changelog

All notable changes are documented here. Versions follow Semantic Versioning.

## [Unreleased]

### Security

- ICMP probes, ping statistics, and TCP probes inside lab namespaces ran as root; they now run as
  the invoking user through `setpriv` like the built-in services (`ping` keeps working through its
  `cap_net_raw` file capability), and the probe interpreter runs isolated (`-I -S`).
- SECURITY.md now states plainly that `sudo ip` is root-equivalent in the Phase I privilege model.

### Changed

- Hybrid TAP setup and teardown run as one privileged `ip` batch each; TAP names are owned before
  creation, and a pre-existing interface with a generated TAP name is refused instead of adopted.

### Added

- Rootless tests of the complete L0→L1 ARP/ICMP exchange across the TAP against a simulated L1
  peer (including unrelated frames on the bridge, timeouts, and unknown sources).

## [0.1.1] - 2026-09-26

Security and hardening release after the Phase I MVP.

### Added

- Optional bearer-token API authentication (`POLMON_API_TOKEN` / `--api-token-file`, owner-only
  file, ≥ 24 characters, constant-time comparison, checked before the body is read). The backend
  refuses to listen on a non-loopback address without a token. The Windows client gains an API
  token field (memory only), `ApiClient` a `token` argument, and `polmon-demo` authenticates every
  local run with a fresh random token.

### Changed

- L1 deployment runs one privileged `ip -batch` on the host plus one per namespace instead of about
  ten `sudo ip` calls per namespace; teardown is a single forced batch. Measured on the development
  host (5 repeats, `benchmarks/results/SUMMARY-wave4-batched-ip.md`): 2-namespace creation median
  1.321 s → 0.184 s, teardown 0.119 s → 0.087 s; 50 L0 + 2 L1 deployment 1.493 s → 0.453 s.

### Security

- The built-in L1 `static_http` service ran `python -m http.server` in the backend's working
  directory and listed it — including `.git/`, `.venv/`, reports, and telemetry — to every lab
  peer. It is now a standalone standard-library responder that returns a fixed body, never touches
  the filesystem, bounds request size, time, and concurrency, and runs in an isolated interpreter
  (`python -I -S`). `static_http` declared with a non-TCP protocol is rejected.
  Measured side effect (`benchmarks/results/SUMMARY-wave5-static-http.md`): service tree RSS
  26.6 → 19.4 MiB per service; 50 L0 + 2 L1 attributed memory 54.5 → 39.1 MiB.

### Fixed

- Rollback leaked a host veth pair whose peer had not yet moved into its namespace.
- Deployment now refuses when an object with a generated name already exists, instead of adopting
  it and deleting it on rollback.

- A hung privileged command raised `TimeoutExpired`, which could abort best-effort teardown midway
  or crash a probe; timeouts now return exit code 124 (or raise a clear error when checked).
- Oversized request bodies were read and parsed before model limits applied; bodies above 5 MiB,
  including chunked uploads, are now refused with HTTP 413 before parsing.
- The privileged host-network guard compared nft set contents, so fail2ban adding a ban during a
  run was reported as a host change; it now compares ruleset structure (`nft -s -t`).
- Client errors embedded the server's error document as a Python dict repr; `ApiClientError` now
  states the HTTP status, error code, and message, and exposes `status`, `code`, and `details`.

### Added

- Tests for the topology CLI, client error handling against a live backend, and UTF-8 JSON logs.

## [0.1.0] - 2026-09-26

Phase I MVP.

### Added

- `polmon-demo`: the Phase I target demonstration over the HTTP API — 50 L0 sensors and two L1
  service endpoints on one isolated network, a controlled reconnaissance experiment, telemetry and
  PCAP capture, JSON/Markdown report, reset, and independent kernel-level cleanup verification.
- `examples/topologies/mvp-demo.yml` and `examples/scenarios/mvp-recon.yml`.
- `docs/DEMO.md` and recorded demonstration evidence in `docs/demo/`.

### Fixed

- Telemetry resource samples reported zero active endpoints and namespaces during experiments; they
  now carry live counts and the topology deployment time (also in `GET /v1/resources` and
  deployment status).
- Reports rendered a failure condition that correctly did not fire as `MISMATCH`; comparisons now
  carry a role and outcome (`met`/`not_met`, `triggered`/`not_triggered`).

## [0.0.15] - 2026-09-26

Release candidate: feature freeze, audits, and corrections found by release testing.

### Added

- Experiments on hybrid L0/L1 deployments: L0→L0 and L0→L1 ICMP use the synthetic engine and the
  shared TAP, L1→L1 uses the kernel; L1→L0 and L0-sourced TCP are reported as `unsupported`.
  Boundary frames are written to the experiment capture. (Required by the v0.1.0 demonstration.)

### Fixed

- Path-like experiment/topology identifiers returned HTTP 500; they are now rejected with 422 at the
  API boundary, and the report writer and reader refuse them independently.
- Stopping the backend with SIGINT/SIGTERM left deployed namespaces, bridges, veths, and services
  behind; graceful shutdown now tears down every deployment and logs the result.
- A benchmark run that hit its time limit was SIGKILLed before its teardown; it now receives
  SIGTERM with a grace period. `lab-cleanup.sh` also stops processes inside leftover namespaces.
- Topology subnets outside RFC 1918 / RFC 2544 laboratory ranges were accepted; they are rejected.

### Removed

- The obsolete v0.0.2 privileged placeholder test that reported a misleading skip.
- `INSTRUCTION.md` from version control (operator instructions are not repository content; the
  file remains in history and on the operator's disk).

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
