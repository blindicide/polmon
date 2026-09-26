"""Bounded benchmark jobs behind the HTTP API.

A job runs the existing ``polmon-benchmark`` command in its own process group, so the per-run
worker isolation, admission and memory ceilings of the CLI apply unchanged, and nothing in the
API imports ``polmon.benchmarks``. Progress is parsed from the CLI's ``step n/N`` lines; results
are the CLI's retained raw JSON files.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock, Thread
from typing import Literal

from pydantic import Field

from polmon.core.errors import ConfigurationError
from polmon.resources import ResourceLimits
from polmon.resources.policy import ResourceLimitError
from polmon.topology.models import StrictModel

RESULT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$")
PROGRESS_LINE = re.compile(r"step (\d+)/(\d+) elapsed \S+ eta \S+ ?(.*)$")
TERMINATION_GRACE_SECONDS = 20.0
MAX_RETAINED_JOBS = 20
EXIT_STATES = {0: "succeeded", 2: "not_run", 3: "aborted"}


class BenchmarkJobLimits(StrictModel):
    """Explicit ceilings a caller must send with every benchmark request."""

    max_endpoints: int = Field(ge=1, le=10_000)
    max_namespaces: int = Field(ge=0, le=1_000)
    max_run_seconds: float = Field(gt=0, le=3_600)
    max_incremental_mb: int = Field(ge=1, le=65_536)
    memory_reserve_mb: int = Field(ge=0, le=1_048_576)


class BenchmarkRequest(StrictModel):
    kind: Literal["l0", "l1", "target"]
    counts: list[int] = Field(default_factory=lambda: [10, 25], min_length=1, max_length=8)
    large: bool = False
    namespaces: int = Field(default=2, ge=1, le=64)
    l0: int = Field(default=50, ge=1, le=10_000)
    l1: int = Field(default=2, ge=1, le=64)
    repeats: int = Field(default=1, ge=1, le=10)
    idle_seconds: float = Field(default=0.5, ge=0, le=60)
    settle_seconds: float = Field(default=0.0, ge=0, le=60)
    limits: BenchmarkJobLimits


def benchmark_command(request: BenchmarkRequest, output_dir: Path) -> list[str]:
    """The exact ``polmon-benchmark`` invocation for a request (every limit explicit)."""
    limits = request.limits
    command = [sys.executable, "-m", "polmon.benchmarks.cli", request.kind]
    if request.kind == "l0":
        command += ["--counts", *(str(count) for count in request.counts)]
        if request.large:
            command.append("--large")
    elif request.kind == "l1":
        command += ["--namespaces", str(request.namespaces)]
    else:
        command += ["--l0", str(request.l0), "--l1", str(request.l1)]
    return [
        *command,
        "--repeats",
        str(request.repeats),
        "--idle-seconds",
        str(request.idle_seconds),
        "--settle-seconds",
        str(request.settle_seconds),
        "--max-endpoints",
        str(limits.max_endpoints),
        "--max-namespaces",
        str(limits.max_namespaces),
        "--max-run-seconds",
        str(limits.max_run_seconds),
        "--max-incremental-mb",
        str(limits.max_incremental_mb),
        "--memory-reserve-mb",
        str(limits.memory_reserve_mb),
        "--output-dir",
        str(output_dir),
        "--json",
    ]


def planned_steps(request: BenchmarkRequest) -> int:
    runs = len(dict.fromkeys(request.counts)) if request.kind == "l0" else 1
    return runs * request.repeats


class BenchmarkJob:
    def __init__(self, job_id: str, request: BenchmarkRequest, command: list[str]) -> None:
        self.job_id = job_id
        self.request = request
        self.command = command
        self.state = "running"
        self.started_at = datetime.now(UTC)
        self.started = time.monotonic()
        self.finished: float | None = None
        self.completed_steps = 0
        self.total_steps = planned_steps(request)
        self.detail = "starting"
        self.stderr_tail: list[str] = []
        self.result_name: str | None = None
        self.message: str | None = None
        self.exit_code: int | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.cancel_requested = False

    def view(self) -> dict[str, object]:
        end = self.finished if self.finished is not None else time.monotonic()
        elapsed = end - self.started
        done = self.completed_steps
        running = self.state == "running"
        eta = (elapsed / done) * (self.total_steps - done) if done and running else None
        return {
            "job_id": self.job_id,
            "kind": self.request.kind,
            "state": self.state,
            "started_at": self.started_at.isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "progress": {
                "completed_steps": done,
                "total_steps": self.total_steps,
                "percent": round(100 * done / self.total_steps, 1),
                "eta_seconds": None if eta is None else round(eta, 1),
                "detail": self.detail,
            },
            "request": self.request.model_dump(mode="json"),
            "result_name": self.result_name,
            "message": self.message,
            "exit_code": self.exit_code,
            "stderr_tail": list(self.stderr_tail[-20:]),
        }


Launcher = Callable[[Sequence[str], object], subprocess.Popen[bytes]]


def _launch(command: Sequence[str], stdout: object) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - fixed module invocation, validated arguments
        list(command),
        stdout=stdout,  # type: ignore[arg-type]
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        start_new_session=os.name == "posix",  # own process group: cancel reaches the worker
    )


class BenchmarkJobs:
    """At most one running benchmark job; finished jobs are kept for inspection (bounded)."""

    def __init__(
        self,
        output_dir: Path,
        backend_limits: ResourceLimits,
        *,
        busy: Callable[[], dict[str, object]] | None = None,
        launcher: Launcher = _launch,
    ) -> None:
        self.output_dir = output_dir
        self.backend_limits = backend_limits
        self._busy = busy or (lambda: {})
        self._launcher = launcher
        self._jobs: dict[str, BenchmarkJob] = {}
        self._threads: dict[str, Thread] = {}
        self._lock = RLock()

    # -- admission -------------------------------------------------------------------------

    def _admit(self, request: BenchmarkRequest) -> None:
        limits = request.limits
        backend = self.backend_limits
        violations: dict[str, object] = {}
        if limits.max_endpoints > backend.max_endpoint_count:
            violations["max_endpoints"] = {
                "requested": limits.max_endpoints,
                "limit": backend.max_endpoint_count,
            }
        if limits.max_namespaces > backend.max_active_namespaces:
            violations["max_namespaces"] = {
                "requested": limits.max_namespaces,
                "limit": backend.max_active_namespaces,
            }
        if limits.memory_reserve_mb < backend.memory_safety_threshold_mb:
            violations["memory_reserve_mb"] = {
                "requested": limits.memory_reserve_mb,
                "minimum": backend.memory_safety_threshold_mb,
            }
        if limits.max_run_seconds > backend.max_experiment_duration_seconds:
            violations["max_run_seconds"] = {
                "requested": limits.max_run_seconds,
                "limit": backend.max_experiment_duration_seconds,
            }
        if self.running() is not None:
            violations["concurrent_benchmarks"] = {"active": 1, "limit": 1}
        violations.update(self._busy())
        if violations:
            raise ResourceLimitError(
                "benchmark request exceeds configured resource limits", details=violations
            )
        oversized = any(count > 50 for count in request.counts)
        if request.kind == "l0" and oversized and not request.large:
            raise ConfigurationError(
                "L0 endpoint counts above 50 require an explicit large benchmark",
                details={"counts": request.counts},
            )

    # -- lifecycle -------------------------------------------------------------------------

    def running(self) -> BenchmarkJob | None:
        with self._lock:
            return next((job for job in self._jobs.values() if job.state == "running"), None)

    def start(self, request: BenchmarkRequest) -> dict[str, object]:
        with self._lock:
            self._admit(request)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            job = BenchmarkJob(uuid.uuid4().hex[:12], request, [])
            job.command = benchmark_command(request, self.output_dir)
            stdout = tempfile.TemporaryFile()  # noqa: SIM115 - closed by the supervisor thread
            try:
                job.process = self._launcher(job.command, stdout)
            except OSError as error:
                stdout.close()
                raise ConfigurationError(
                    "benchmark process could not be started", details={"reason": str(error)}
                ) from error
            self._jobs[job.job_id] = job
            self._trim()
            thread = Thread(
                target=self._supervise,
                args=(job, stdout),
                name=f"polmon-benchmark-{job.job_id}",
                daemon=True,
            )
            self._threads[job.job_id] = thread
            thread.start()
            return job.view()

    def _trim(self) -> None:
        finished = [job for job in self._jobs.values() if job.state != "running"]
        for job in finished[: max(0, len(self._jobs) - MAX_RETAINED_JOBS)]:
            self._jobs.pop(job.job_id, None)
            self._threads.pop(job.job_id, None)

    def _supervise(self, job: BenchmarkJob, stdout) -> None:  # type: ignore[no-untyped-def]
        process = job.process
        assert process is not None and process.stderr is not None
        try:
            for raw in process.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                with self._lock:
                    job.stderr_tail = [*job.stderr_tail[-49:], line]
                    match = PROGRESS_LINE.search(line)
                    if match:
                        job.completed_steps = int(match.group(1))
                        job.total_steps = max(1, int(match.group(2)))
                        job.detail = match.group(3) or job.detail
            exit_code = process.wait()
            stdout.seek(0)
            output = stdout.read().decode("utf-8", errors="replace")
        finally:
            stdout.close()
        document: dict[str, object] | None = None
        for line in reversed(output.splitlines()):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                document = parsed
                break
        with self._lock:
            job.exit_code = exit_code
            job.finished = time.monotonic()
            if job.cancel_requested:
                job.state = "cancelled"
                job.message = "cancelled by the operator"
            else:
                job.state = EXIT_STATES.get(exit_code, "failed")
                error = document.get("error") if document else None
                if isinstance(error, dict):
                    job.message = str(error.get("message") or "")
                elif job.state == "failed":
                    job.message = f"benchmark process exited with status {exit_code}"
            if document is not None:
                job.result_name = self._result_name_for(document)

    def _result_name_for(self, document: dict[str, object]) -> str | None:
        kind = str(document.get("benchmark") or "")
        started = str(document.get("started_at") or "")
        try:
            stamp = datetime.fromisoformat(started).strftime("%Y%m%dT%H%M%SZ")
        except ValueError:
            return None
        name = f"{kind}-{stamp}.json"
        return name if (self.output_dir / name).is_file() else None

    def job(self, job_id: str) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ConfigurationError(f"unknown benchmark job '{job_id}'")
            return job.view()

    def jobs(self) -> list[dict[str, object]]:
        with self._lock:
            return [job.view() for job in reversed(self._jobs.values())]

    def cancel(self, job_id: str) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ConfigurationError(f"unknown benchmark job '{job_id}'")
            if job.state != "running" or job.process is None:
                raise ConfigurationError(f"benchmark job '{job_id}' is not running")
            job.cancel_requested = True
            job.detail = "cancelling"
            self._terminate(job.process)
            return job.view()

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        """SIGTERM the job's process group (workers tear down), SIGKILL after the grace."""
        if process.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        else:
            process.terminate()

        def escalate() -> None:
            try:
                process.wait(timeout=TERMINATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()

        Thread(target=escalate, name="polmon-benchmark-kill", daemon=True).start()

    def shutdown(self, timeout: float = TERMINATION_GRACE_SECONDS + 5) -> None:
        with self._lock:
            job = self.running()
            if job is not None and job.process is not None:
                job.cancel_requested = True
                self._terminate(job.process)
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=timeout)

    # -- retained results ------------------------------------------------------------------

    def results(self, limit: int = 200) -> list[dict[str, object]]:
        if not self.output_dir.is_dir():
            return []
        paths = sorted(
            (path for path in self.output_dir.glob("*.json") if RESULT_NAME.fullmatch(path.name)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]
        listed: list[dict[str, object]] = []
        for path in paths:
            entry: dict[str, object] = {"name": path.name, "size_bytes": path.stat().st_size}
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                entry["status"] = "unreadable"
                listed.append(entry)
                continue
            if isinstance(document, dict):
                measurements = document.get("measurements")
                entry.update(
                    benchmark=document.get("benchmark"),
                    status=document.get("status"),
                    started_at=document.get("started_at"),
                    polmon_version=document.get("polmon_version"),
                    measurement_count=len(measurements) if isinstance(measurements, list) else 0,
                )
            listed.append(entry)
        return listed

    def _result_path(self, name: str) -> Path:
        if not RESULT_NAME.fullmatch(name):
            raise ConfigurationError("invalid benchmark result name")
        path = self.output_dir / name
        if not path.is_file():
            raise ConfigurationError(f"benchmark result '{name}' does not exist")
        return path

    def result(self, name: str) -> dict[str, object]:
        path = self._result_path(name)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"benchmark result '{name}' is unreadable") from error
        if not isinstance(document, dict):
            raise ConfigurationError(f"benchmark result '{name}' is invalid")
        summary = subprocess.run(  # noqa: S603 - fixed module invocation on a validated path
            [sys.executable, "-m", "polmon.benchmarks.cli", "summarize", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        return {
            "name": name,
            "document": document,
            "summary_markdown": summary.stdout if summary.returncode == 0 else None,
        }
