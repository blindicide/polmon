# Phase III plan: self-contained backend artifacts

Status: implementation plan, committed before Phase III product changes. Target release:
**v0.3.0**. `MANDATE-SELFCONTAINED.md` is the governing operator order; the Phase II Qt design and
the security, isolation, resource, and reporting rules remain in force.

## 1. Runtime contract

The packaged client gains two explicit connection types:

- **Local backend (L0 only)** starts an owned backend on `127.0.0.1` and a dynamically selected
  port, authenticates with an ephemeral token, waits for readiness off the GUI thread, connects,
  and stops it on disconnect or client exit. The label remains visible for the whole session.
- **Remote Linux backend** keeps the existing URL/token workflow and can provide L0, L1, and the
  hybrid L0/L1 TAP boundary when its host passes the laboratory capability checks.

The local process manager imports no backend modules. It resolves an explicit CLI/environment
override first, then a packaged `polmon-backend[.exe]` beside the client (or in the one-file
extraction directory), then the checkout's installed console script / `python -m polmon.backend`.
It owns a new process group, redirects stdout and stderr to a user-visible rotating session log,
and retries a fresh loopback port when startup loses the bind race. On Windows the backend is
assigned to a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so abrupt client death closes
the job and cannot orphan the backend. Normal disconnect and exit request graceful termination,
then use a bounded forced stop. A killed backend is detected by the health poll and reported with
its exit code and log path.

## 2. Fidelity boundary

`ControlPlane` has an explicit fidelity policy. Windows defaults to `l0_only`; the client-started
backend also passes `--local-l0-only`, making the boundary testable on Linux. Health and resource
responses publish the policy. Validation/loading remain useful for inspection, but deployment of
any L1 or L2 topology is refused with HTTP 422 and the exact actionable message:

> Local backend supports L0 synthetic nodes only; L1/L2 requires a polmon backend on a Linux host
> with network namespace privileges.

The client performs the same preflight from the topology resource estimate and refuses before an
HTTP deploy call, while the backend remains authoritative. No request is downgraded and no
namespace is simulated. Namespace backends also translate missing-platform/tool/privilege errors
into an actionable clean refusal rather than a traceback.

## 3. Backend executable and packaging

A Qt-free PyInstaller backend spec collects FastAPI/Starlette, Pydantic, YAML, the complete polmon
backend graph, and uvicorn's dynamic logging, loop, protocol, and lifespan modules. The console
executable supports the existing `--version`, `--host`, `--port`, and token-file contract plus
`--self-test`. Self-test constructs the real application and uvicorn configuration, verifies the
router/control-plane module graph, runs a rootless L0 topology through validate, deploy, scenario,
telemetry, report, and reset in a temporary directory, and exits without listening on a public
interface.

Windows produces the existing one-file client and portable zip. The one-file client embeds the
separately built `polmon-backend.exe` and resolves it from PyInstaller's extraction directory; the
portable directory contains `polmon-client.exe` and `polmon-backend.exe` side by side. Both forms
therefore need no Python install. The backend remains a console-subsystem executable and its build
explicitly excludes PySide6.

Linux additionally produces
`polmon-backend-<version>-linux-x64.tar.gz`, containing a one-folder backend bundle and no Qt. A
second systemd unit targets the extracted executable. The existing client tarball, wheel, and
console-script unit remain available.

## 4. Verification and evidence

Local tests cover command resolution, port retries, log capture, normal stop, backend death,
L0-only API refusal, UI preflight text, and client shutdown. A GUI test starts a real backend using
the client's manager and follows the same connection path as the Local preset. A real widget grab
is committed as `docs/ui/local-backend.png`.

Hosted Windows verification runs only packaged binaries. For the one-file and portable forms it
starts the backend through the client's own lifecycle path, executes a rootless L0 workflow
(deploy, scenario, telemetry, JSON/Markdown report, reset), verifies the refusal response and UI
text for L1/L2, exercises disconnect/backend-killed/client-killed paths, and uses `tasklist` /
process queries after each path to prove no `polmon-backend.exe` remains. `--self-test` must name
uvicorn, the application graph, and the completed L0 workflow.

Hosted Linux verification extracts the backend tarball and starts it with `env -i` (no activated
venv and no Python invocation), then drives the same real L0 workflow over HTTP. A read-only lab readiness probe
records whether L1 is available; when permitted, a bounded two-node L1 deploy/destroy is run, and
otherwise the exact clean refusal is recorded as `NOT RUN - environment unavailable`. The
downloaded artifact is rechecked on a fresh runner and its SHA-256 is published.

CI retains the cross-platform unit/GUI matrix. Build workflows upload logs, workflow JSON evidence,
measurements, hashes, and artifacts. Release verification downloads published assets and repeats
their self-tests and L0 smoke workflows. Release notes state, per artifact, that the bundled
Windows local backend is L0-only and that the Linux backend supports L0 plus privileged L1/hybrid
operation when the host permits it.

## 5. Documentation, measurement, and release sequence

1. Commit this plan before implementation.
2. Implement backend policy/self-test and the client-owned lifecycle with unit and GUI coverage.
3. Add Windows and Linux backend builds, packaged E2E/refusal/cleanup probes, and the bundled
   systemd unit.
4. Regenerate the real Local-backend screenshot and update README, client/operations/API docs,
   architecture, build/CI/release guides, security notes, changelog, and resource budget.
5. Run local lint and the complete rootless suite; build and smoke the Linux backend locally.
6. Push the implementation, exercise CI and both build workflows on hosted runners, repair until
   green, and record run IDs, artifact sizes, hashes, RSS/startup measurements, and any honest
   privileged-test limitation in `docs/milestones/v0.3.0.md`.
7. Prepare v0.3.0, create an annotated tag only after the gates pass, publish all assets with
   `SHA256SUMS.txt`, download and verify the release on both hosted platforms, then commit the
   final release evidence.
