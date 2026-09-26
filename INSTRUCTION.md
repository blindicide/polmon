# PROJECT SPECIFICATION
## Resource-Efficient Network Attack Simulation Platform
### Phase I — Foundation and MVP (v0.0.1 → v0.1.0)

**Execution mode:** Autonomous development with mandatory verification gates.  
**Target:** Functional, resource-efficient cybersecurity simulation MVP.  
**Primary development environment:** Linux, 2 CPU cores, 2 GB RAM, limited swap.  
**Heavy testing environment:** Separate workstation with 24 GB RAM.  
**Distribution:** Linux backend + standalone Windows x64 GUI executable.

---

# 1. MISSION

Develop the first functional version of a resource-efficient software/hardware platform for simulating attacks against isolated local computer networks.

The project is intended to support an engineering graduation thesis and may subsequently become a commercial cybersecurity training and experimentation product.

The distinguishing architectural principle is heterogeneous simulation fidelity.

Not every virtual network device requires a complete operating system. The platform must support three classes of nodes:

- L0: lightweight synthetic network endpoints;
- L1: isolated Linux networking environments;
- L2: conventional virtual machines.

Phase I concentrates on L0 and L1. L2 support must be represented architecturally but does not need a complete implementation before v0.1.0.

A separate Windows graphical client communicates with the Linux backend.

The platform must eventually support defining network topologies, deploying experimental environments, executing controlled scenarios, collecting telemetry, generating reports and restoring the environment.

Resource efficiency is a primary engineering requirement, not an optional optimisation.

# 2. OPERATING CONSTRAINTS

The development machine has:

- 2 CPU cores;
- 2 GB physical RAM;
- limited swap;
- Linux operating system;
- potentially other services running simultaneously.

Do not assume access to substantial computing resources.

The ordinary development workflow must not require:

- full Windows virtual machines;
- a local graphical desktop;
- Docker Desktop;
- Kubernetes;
- heavyweight monitoring stacks;
- Elasticsearch;
- a dedicated database server;
- continuous large-scale network simulations.

Prefer lightweight Python components, SQLite, Linux networking facilities and explicitly controlled subprocesses.

Swap is an emergency buffer, not additional working RAM.

Heavy benchmarks and L2 experiments must be separable from ordinary development.

The Windows executable must be built using GitHub-hosted Windows runners, not locally through Wine or Windows emulation.

## Resource-management requirements

Implement resource monitoring early.

Record at minimum:

- process RSS;
- process CPU utilisation;
- available system memory;
- swap consumption;
- active endpoint count;
- active network namespace count;
- topology deployment time.

The development server must not be subjected to uncontrolled stress tests.

Every scalability test must accept explicit limits for endpoint count, duration and resource consumption.

Default tests must use small topologies.

Large benchmarks must require explicit invocation.

The initial engineering target is to execute the backend with 50 L0 endpoints and two lightweight L1 endpoints within approximately 1 GB of incremental memory consumption.

This is a target to validate experimentally, not an assumed capability or a substitute for measurement.

The platform must refuse workloads that exceed configured resource limits rather than relying on the Linux OOM killer.

# 3. TECHNOLOGY BASELINE

Use the following preliminary stack unless investigation demonstrates a concrete technical reason to deviate.

| Component | Technology |
|---|---|
| Main language | Python 3.12 |
| Backend API | FastAPI |
| API server | Uvicorn |
| Configuration | YAML |
| Structured validation | Pydantic |
| Persistence | SQLite |
| Testing | pytest |
| Code quality | Ruff |
| Windows GUI | Tkinter |
| Windows packaging | PyInstaller |
| Linux networking | iproute2 and Linux networking APIs |
| L2 abstraction | QEMU/KVM-compatible interface |
| CI/CD | GitHub Actions |

Do not introduce a dependency merely because it is fashionable or convenient.

A new major dependency must have a documented purpose and resource cost.

Keep the control plane independent of the underlying execution backends.

The Windows GUI must not require the Linux simulation engine to run locally.

# 4. DEVELOPMENT RULES

Work autonomously through the milestones in the specified order.

For every version:

1. Inspect the existing repository and current implementation.
2. Define the version's deliverables.
3. Implement the required functionality.
4. Add or update tests.
5. Execute the relevant tests.
6. Correct discovered failures.
7. Update documentation.
8. Verify resource usage where applicable.
9. Commit the completed milestone.
10. Produce a concise milestone report.

Do not silently skip acceptance criteria.

Do not claim that tests passed unless they were actually executed.

Do not claim that a Windows executable works merely because PyInstaller returned exit code zero. Validate the generated executable.

If Windows execution is unavailable locally, use the GitHub Actions Windows runner.

If network privileges are unavailable, run unit tests normally and mark privileged integration tests as unavailable. Do not report skipped tests as successful integration tests.

Do not modify the host's production networking configuration.

Never modify the primary network interface, default route or production firewall rules as a shortcut.

Use isolated test bridges, network namespaces and explicitly managed virtual interfaces.

Ensure all experimental resources are removed after testing, including after exceptions or interrupted executions.

Use atomic operations where possible.

Do not introduce placeholder functions that silently return success.

Do not create fabricated benchmark results, screenshots, logs or reports.

Maintain readable English documentation and source code.

Check all text files, logs and generated reports for encoding problems. Use UTF-8 consistently. Do not allow mojibake to propagate into documentation, GUI strings or generated artifacts.

# 5. VERSION ROADMAP

## v0.0.1 — Repository and Build Infrastructure

**Priority: CRITICAL**

Create the repository foundation and establish the complete Windows executable build pipeline.

Required deliverables:

- Python project structure;
- initial Windows GUI;
- basic backend entry point;
- central version definition;
- dependency configuration;
- Git repository and .gitignore;
- initial unit tests;
- GitHub Actions workflows;
- PyInstaller packaging configuration;
- complete build and CI documentation.

The GUI may initially display project information, version information and a connection configuration screen.

It must launch successfully without a running Linux backend.

Provide command-line flags:

    --version
    --self-test

The self-test must validate the packaged application's essential imports and configuration without opening a graphical window.

### GitHub Actions requirements

Create:

    .github/workflows/ci.yml
    .github/workflows/build-windows.yml
    .github/workflows/release.yml

`ci.yml` must install dependencies, run linting and execute the unit-test suite.

`build-windows.yml` must:

- run on a GitHub-hosted Windows runner;
- install the selected Python version;
- install pinned build dependencies;
- execute the test suite;
- build the Windows executable using PyInstaller;
- verify the executable exists;
- invoke its --version and --self-test commands;
- verify the executable returns successful exit codes;
- upload the executable as a downloadable workflow artifact.

`release.yml` must build a versioned executable from release tags and attach the resulting artifact to the corresponding GitHub Release.

Use explicit workflow permissions. Release write permissions must be limited to the release job.

Pin third-party actions to reviewed immutable commit SHAs where practical.

Do not expose repository secrets to untrusted pull-request builds.

The Windows executable must use a predictable filename and include the project version.

### Mandatory documentation

Create:

    README.md
    ARCHITECTURE.md
    DEVELOPMENT.md
    BUILD-WINDOWS.md
    CI.md
    RELEASE.md
    RESOURCE-BUDGET.md
    SECURITY.md
    CONTRIBUTING.md
    CHANGELOG.md

Document:

- repository structure;
- installation requirements;
- development setup;
- local test execution;
- manual Windows build procedure;
- GitHub Actions build procedure;
- downloading workflow artifacts;
- creating versioned releases;
- verifying executable hashes;
- build troubleshooting;
- resource constraints;
- network-isolation policy;
- development conventions.

Provide a suitable license only after checking whether the repository already has a license or an explicit licensing decision exists. Do not silently relicense existing code.

### Acceptance gate

v0.0.1 passes only when:

- the project installs cleanly;
- unit tests pass;
- the GUI launches;
- the EXE builds successfully on Windows;
- the packaged EXE passes its smoke tests;
- GitHub Actions publishes the downloadable artifact;
- all mandatory documentation exists and matches the actual implementation.

Do not proceed to v0.0.2 with a broken packaging pipeline.

---

## v0.0.2 — Testing and Diagnostics

Implement a consistent testing and diagnostic framework.

Required:

- pytest configuration;
- unit/integration/performance test separation;
- coverage reporting;
- structured logging;
- consistent error handling;
- environment diagnostics;
- startup resource reporting;
- CI test result summaries.

Create a diagnostic command capable of displaying platform version, Python version, host capabilities and relevant network-tool availability.

The diagnostic system must not expose secrets.

Acceptance:

- Unit tests run without root.
- CI correctly reports failures.
- Privileged tests are explicitly marked.
- The ordinary test suite fits the development machine's memory budget.

---

## v0.0.3 — Topology Data Model

Implement a declarative topology representation.

Support:

- topology identifier;
- nodes;
- networks;
- interfaces;
- MAC addresses;
- IPv4 addresses;
- node classes;
- resource requirements;
- optional service definitions.

Use YAML as the primary human-readable format.

Provide schema validation and meaningful error messages.

Reject duplicate identifiers, invalid addresses, conflicting network assignments and unsupported node configurations.

Implement resource estimation without actually deploying the topology.

Acceptance:

A topology can be parsed, validated, serialised and inspected without privileged operations.

Malformed configurations fail predictably.

---

## v0.0.4 — Orchestration Abstraction

Implement the execution-backend interface.

Minimum operations:

    validate()
    create()
    start()
    stop()
    destroy()
    inspect()

Develop a mock backend for unit testing.

Define lifecycle states and legal transitions.

Implement idempotent cleanup, consistent error reporting and resource ownership tracking.

Acceptance:

The orchestration lifecycle is testable without creating real network resources.

Failed operations do not leave inconsistent internal state.

---

## v0.0.5 — L0 Engine Foundation

Create the synthetic endpoint engine.

Do not launch an operating system or container for each L0 endpoint.

Use a shared process and lightweight endpoint state.

Implement:

- endpoint creation;
- endpoint destruction;
- unique identities;
- endpoint registry;
- event scheduling;
- basic virtual network representation;
- resource accounting.

Initially, no complete TCP/IP stack is required.

Acceptance:

At least 50 logical endpoints can be created and destroyed repeatedly.

Endpoint identities remain unique.

Resource cleanup is verified.

Measure incremental memory consumption.

---

## v0.0.6 — L0 Networking

Implement the first useful synthetic network capabilities.

Required:

- Ethernet framing;
- MAC addressing;
- ARP;
- IPv4;
- ICMP echo request/reply;
- basic interface configuration;
- deterministic packet dispatch;
- basic connectivity diagnostics.

Implement protocol tests using known-valid packet fixtures.

Do not advertise unsupported protocol capabilities.

Do not attempt a complete TCP implementation at this stage.

Acceptance:

Synthetic endpoints can resolve addresses and exchange ICMP traffic within the virtual network.

Packet contents and checksums are validated.

---

## v0.0.7 — L1 Networking

Implement Linux network namespace support.

Required:

- namespace lifecycle;
- virtual Ethernet pairs;
- isolated Linux bridges;
- interface configuration;
- IPv4 addressing;
- routing within the experimental topology;
- lightweight service execution;
- deterministic teardown.

Separate privileged networking operations from the ordinary control-plane process where practical.

Never require root for unrelated unit tests or GUI development.

Acceptance:

Two isolated L1 endpoints can communicate over a virtual network.

A test service can be started and reached.

Destroying the topology removes its associated namespaces and interfaces.

---

## v0.0.8 — Hybrid L0/L1 Networking

Implement communication between synthetic and Linux-native endpoints.

Prefer a clearly defined virtual Ethernet boundary.

Investigate a TAP-based integration using the Linux bridge infrastructure.

Avoid allocating a separate heavyweight process or virtual interface for every synthetic node.

Acceptance:

An L0 endpoint communicates with an L1 endpoint using the implemented protocols.

Traffic can be captured and inspected with standard networking tools.

The platform must distinguish supported protocol behaviour from unsupported behaviour.

Document the design and measured overhead of the L0/L1 boundary.

---

## v0.0.9 — Scenario Engine

Implement declarative experimental scenarios.

A scenario defines:

- required topology;
- initial conditions;
- permitted actions;
- execution sequence;
- timeout;
- expected observations;
- success/failure conditions;
- cleanup policy.

Begin with a controlled network reconnaissance experiment against explicitly designated laboratory endpoints.

The engine must not execute arbitrary user-provided shell commands without an explicit privileged execution policy.

Acceptance:

A scenario can be loaded, validated, executed and terminated deterministically.

Invalid scenarios are rejected before deployment.

---

## v0.0.10 — Telemetry

Introduce structured experiment telemetry.

Collect:

- experiment identifiers;
- timestamps;
- scenario events;
- node lifecycle events;
- network observations;
- execution errors;
- resource consumption.

Support bounded packet capture.

Do not continuously record unlimited traffic.

Persist experiment metadata using SQLite.

Acceptance:

An experiment produces a structured event record and an inspectable packet capture.

Telemetry remains associated with the correct experiment.

---

## v0.0.11 — Windows Client Integration

Connect the Windows application to the Linux backend.

Required GUI capabilities:

- server configuration;
- connection status;
- topology loading;
- topology validation;
- deployment control;
- experiment execution;
- experiment status;
- basic telemetry display.

The backend must provide documented API contracts.

Use explicit timeouts and meaningful connection errors.

The application must remain responsive while communicating with the server.

Acceptance:

The Windows executable can control a real experimental topology hosted on Linux.

The EXE is generated using the existing GitHub Actions workflow.

---

## v0.0.12 — Reporting and Recovery

Implement experiment reports.

Minimum contents:

- experiment identifier;
- topology;
- scenario;
- execution timestamps;
- observed events;
- expected versus actual results;
- errors;
- resource statistics;
- overall execution status.

Provide machine-readable JSON and a human-readable report format.

Implement environment reset and recovery.

Acceptance:

An experiment can be run, reported, reset and repeated without manual reconstruction.

Failures trigger appropriate cleanup.

---

## v0.0.13 — Resource Management

Implement resource admission control.

The system must estimate resource requirements before deployment.

Reject workloads exceeding configured limits.

Support configurable:

- maximum endpoint count;
- maximum active namespaces;
- maximum concurrent experiments;
- maximum capture size;
- experiment duration;
- memory safety threshold.

Implement resource monitoring and cancellation.

Acceptance:

The system prevents clearly excessive workloads and remains recoverable following a failed deployment.

---

## v0.0.14 — Performance Benchmarking

Create a reproducible benchmark suite.

Suggested L0 endpoint counts:

    10
    25
    50
    100
    250

Larger tests must require explicit invocation.

Measure:

- incremental memory;
- CPU utilisation;
- creation time;
- teardown time;
- idle overhead;
- controlled traffic overhead;
- packet loss;
- latency;
- resource cleanup.

Perform repeated runs.

Report actual measurements, workload descriptions, hardware specifications and limitations.

Distinguish synthetic endpoints from Linux namespaces and full VMs.

Do not claim equivalence between different fidelity classes.

Acceptance:

Benchmarks can be reproduced, and raw measurements are retained.

---

## v0.0.15 — Release Candidate

Freeze new feature development.

Perform:

- complete documentation audit;
- regression testing;
- resource testing;
- security review;
- Windows packaging verification;
- clean installation verification;
- cleanup and recovery testing;
- repository hygiene checks.

Correct failures discovered during release testing.

Do not introduce major architectural changes without documenting their consequences.

Acceptance:

All mandatory MVP gates pass.

---

## v0.1.0 — Phase I MVP

Deliver the first complete MVP.

It must provide:

- a Linux backend;
- a standalone Windows client;
- declarative network topologies;
- functional L0 endpoints;
- functional L1 endpoints;
- hybrid L0/L1 communication;
- a basic scenario engine;
- telemetry and reporting;
- resource admission control;
- automated environment cleanup;
- reproducible benchmark results;
- documented build and release procedures.

Target demonstration:

- 50 synthetic L0 endpoints;
- at least two active L1 service endpoints;
- an isolated virtual network;
- one controlled security experiment;
- captured telemetry;
- generated report;
- complete environment reset.

Additional L1 endpoints may be demonstrated on more capable hardware.

L2 remains an architectural extension. Complete KVM orchestration is not a prerequisite for this release.

# 6. REPOSITORY STRUCTURE

Use a maintainable modular structure, approximately:

    .github/
      workflows/
        ci.yml
        build-windows.yml
        release.yml

    src/
      project/
        core/
        topology/
        orchestration/
        backends/
          mock/
          synthetic/
          namespace/
          kvm/
        networking/
        scenarios/
        telemetry/
        reporting/
        api/
        client/

    tests/
      unit/
      integration/
      performance/
      smoke/

    docs/

    examples/
      topologies/
      scenarios/

    packaging/
      windows/

    scripts/

    pyproject.toml
    README.md
    CHANGELOG.md

The actual Python package name may be selected during repository bootstrap.

Keep module boundaries explicit.

The synthetic engine must not import Windows GUI components.

The Windows GUI must not directly depend on Linux networking modules.

The API must not assume that all execution backends are local.

# 7. SECURITY AND ISOLATION

All experiments must operate inside explicitly designated laboratory environments.

By default:

- no external routing;
- no unrestricted internet access;
- no host-network modifications;
- no production-network targets;
- no automatic execution against discovered real devices.

Network tests must use dedicated interfaces and controlled address ranges.

Reject external target addresses unless an explicitly authorised laboratory configuration allows them.

Avoid granting the entire backend unnecessary root privileges.

Do not store credentials in repository files, logs or generated reports.

No real-world attack execution is required for the early milestones.

# 8. VERSION CONTROL

Use SemVer.

The initial version is v0.0.1.

Each milestone must produce:

- a coherent implementation;
- tests;
- documentation;
- CHANGELOG entry;
- milestone report;
- Git commit.

Create a release tag only after its acceptance gate passes.

Do not tag incomplete work as a passing release.

Follow existing repository conventions where they are already established.

Do not force-push, delete unrelated branches or overwrite existing user work.

# 9. VALIDATION

Every version must be validated at the appropriate level.

Unit tests must be runnable on the 2-core/2-GB machine.

Privileged networking tests must be isolated and individually selectable.

Windows packaging must be validated on Windows.

Performance claims must be backed by recorded measurements.

Where a test cannot run because the necessary environment is unavailable, explicitly report:

    NOT RUN — environment unavailable

Do not substitute a mocked test for a real integration test while reporting equivalent coverage.

# 10. REPORTING FORMAT

After each milestone, produce:

    VERSION:
    STATUS: PASS / PARTIAL / BLOCKED

    IMPLEMENTED:
    TESTS EXECUTED:
    TEST RESULTS:
    RESOURCE OBSERVATIONS:
    KNOWN LIMITATIONS:
    FILES CHANGED:
    COMMIT:
    NEXT MILESTONE:

Provide exact test commands and meaningful results.

For Windows releases, include the GitHub Actions workflow run and artifact information where available.

If a milestone fails, identify the blocker and preserve a reproducible state.

Do not silently advance to the next milestone.

# 11. EXECUTION PRIORITY

Begin with v0.0.1 immediately.

Inspect the repository before making changes.

Establish the build pipeline, tests, documentation and Windows executable first.

Then implement subsequent milestones sequentially.

Do not spend Phase I implementing a large GUI, distributed orchestration, Kubernetes integration, an enterprise SIEM or a complete TCP/IP stack.

Prioritise correctness, reproducibility, resource efficiency and maintainability.

The primary measure of success is not how many features are implemented.

It is whether the resulting platform provides a working, repeatable and resource-efficient network-security experimentation environment that can be developed on modest hardware and expanded onto dedicated infrastructure later.

---

## 12. EXECUTION ENVIRONMENT (operator-set, binding)

This section is set by the operator and has the same authority as the rest of
this document. Where it constrains the stack, it wins.

- **Host:** `theta-gryphonis` running Linux, 4 cores / 8 GB RAM visible. The
  specification's *2 cores / 2 GB* figure is the ENGINEERING BUDGET the platform
  must be built and validated against — not a description of this host. Default
  tests stay small; admission control enforces the configured limits; the
  larger L0 counts (100, 250) run only on explicit invocation.
- **Python:** the system interpreter is Python 3.14 and MUST NOT be used.
  Use `/usr/bin/python3.12` through `uv` (`~/.local/bin/uv`), i.e.
  `uv venv --python 3.12` for the project virtual environment. Every python
  invocation for this project goes through that `.venv`. Pin the interpreter
  requirement in `pyproject.toml` (`requires-python = ">=3.12,<3.13"`).
- **Git remote:** `origin` is the PRIVATE repository
  `https://github.com/blindicide/polmon` (the `gh` CLI is authenticated with
  `repo` and `workflow` scopes). Push every milestone commit and release tag
  there. Do not create a second remote, do not make it public, do not
  force-push, and do not rewrite history.
- **Windows packaging:** the EXE is built by GitHub-hosted Windows runners via
  the workflows in this specification. Building Windows binaries locally with
  Wine, QEMU or any emulation layer is OUT OF SCOPE and must not be attempted.
  Validate the EXE on the runner (`--version`, `--self-test`, artifact upload).
- **Privileges:** passwordless `sudo` is available. It is authorised ONLY for
  laboratory networking: network-namespace lifecycle and the creation/removal
  of the platform's own isolated bridges, veth pairs and lab interfaces
  (names prefixed `polmon*`, `lab*`, `veth*`), plus addressing and routes
  INSIDE those namespaces. It is FORBIDDEN to touch the primary network
  interface, the default route, host `iptables`/`nft` rules, the `tailscale*`
  interfaces, firewall or DNS configuration, or any credential path
  (`~/.ssh`, `~/.codex`, `~/.config/gh`, `.env` files). Never modify the
  host's production networking configuration.
- **Interface conventions observed on this host:** the primary NIC is managed
  by the host and by Tailscale; assume no hairpin NAT (self-probes to the
  host's own public address fail). Do not verify reachability by curling the
  host's own public IP from the host.
- **Version visibility (standing requirement):** the project version appears in
  `--version` for every CLI entry point, in the GUI title/window, in the API
  (health/root response), in generated reports and in log banners. Create an
  **annotated** git tag for each completed milestone whose acceptance gate
  passed (e.g. `v0.0.1`), and tag nothing whose gate failed.
- **Progress output (standing requirement):** any CLI command that can run
  longer than ~10 seconds — deployment, scenario execution, benchmark runs,
  teardown — prints info-dense progress: percent complete, elapsed time, ETA,
  current/total steps. Progress goes to stderr and degrades cleanly when not
  attached to a TTY; it must never corrupt `--json` output.
- **Reporting:** milestone reports follow section 10 exactly. A gate that could
  not be run is reported as `NOT RUN — environment unavailable` with the reason;
  never substitute a mocked result for a real integration test, and never
  fabricate measurements, logs or screenshots.
