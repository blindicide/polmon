"""Owned local-backend process lifecycle; no backend implementation imports.

The desktop client talks to this process through the same HTTP contract as a remote backend.
Windows uses a kill-on-close Job Object so even an abrupt client exit cannot orphan the child.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from polmon.client.api import ApiClient, ApiClientError

LOCAL_LABEL = "Local backend — L0 only"
LOCAL_FIDELITY_MESSAGE = (
    "Local backend supports L0 synthetic nodes only; L1/L2 requires a polmon backend on a "
    "Linux host with network namespace privileges."
)
BACKEND_OVERRIDE_ENV = "POLMON_BACKEND_EXECUTABLE"
# Session directories hold one backend log each; older ones are pruned when a backend starts.
SESSION_LOGS_KEPT = 20

_L0_TOPOLOGY = """id: local-smoke
networks:
  - id: lab
    ipv4_subnet: 198.18.10.0/24
nodes:
  - id: probe
    class: l0
    interfaces:
      - {id: eth0, network: lab, mac: '02:10:00:00:00:01', ipv4: 198.18.10.2}
  - id: target
    class: l0
    interfaces:
      - {id: eth0, network: lab, mac: '02:10:00:00:00:02', ipv4: 198.18.10.3}
"""
_L0_SCENARIO = """id: local-smoke
required_topology: local-smoke
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
  - {id: ping, kind: icmp_probe, source: probe, target: target}
timeout_seconds: 5
success_conditions:
  - {action: ping, field: success, equals: true}
cleanup_policy: never
"""
_L1_TOPOLOGY = _L0_TOPOLOGY.replace("id: local-smoke", "id: needs-linux", 1).replace(
    "class: l0", "class: l1", 1
)


class LocalBackendError(RuntimeError):
    """The owned process could not be started, reached, or stopped safely."""


class LocalBackendCancelled(LocalBackendError):
    """Startup was cancelled; the partial child has already been reaped."""


def _executable_name() -> str:
    return "polmon-backend.exe" if sys.platform == "win32" else "polmon-backend"


def resolve_backend_command(override: str | Path | None = None) -> list[str]:
    """Resolve packaged, virtual-environment, and source-checkout layouts in that order."""
    selected = str(override or os.environ.get(BACKEND_OVERRIDE_ENV, "")).strip()
    if selected:
        candidate = Path(selected).expanduser()
        resolved = candidate if candidate.is_file() else None
        if resolved is None and not candidate.parent.name:
            found = shutil.which(selected)
            resolved = Path(found) if found else None
        if resolved is None:
            raise LocalBackendError(f"backend override does not exist: {selected}")
        return [str(resolved.resolve())]

    name = _executable_name()
    candidates = [Path(sys.executable).resolve().parent / name]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.insert(0, Path(bundle) / name)
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() != Path(sys.executable).resolve():
            return [str(candidate)]
    installed = shutil.which("polmon-backend")
    if installed:
        return [installed]
    if getattr(sys, "frozen", False):
        raise LocalBackendError(
            "this client bundle has no backend beside it; install/extract the self-contained "
            "backend or select Remote Linux backend"
        )
    # Source checkout / editable install fallback. The module name is intentionally a string:
    # the client keeps its enforced import boundary from backend implementation modules.
    return [sys.executable, "-m", "polmon.backend"]


def _free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def default_state_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        return base / "polmon"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "polmon"


def _pid_alive(pid: int) -> bool:
    """Whether a process with this PID exists (a reused PID only delays a prune)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def prune_session_logs(
    sessions: Path, *, keep: int = SESSION_LOGS_KEPT, current: Path | None = None
) -> list[Path]:
    """Remove the oldest log-only session directories beyond ``keep``; return what was removed.

    A directory is removed only if it holds nothing but ``polmon-backend.log`` (v0.3.0 sessions
    also held that backend's data; those are left alone) and the client that created it (the
    PID in its name) is no longer running.
    """
    if not sessions.is_dir():
        return []
    candidates = sorted(
        (path for path in sessions.iterdir() if path.is_dir() and path != current),
        key=lambda path: path.name,
        reverse=True,
    )
    removed: list[Path] = []
    for path in candidates[keep:]:
        try:
            owner = int(path.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        if owner != os.getpid() and _pid_alive(owner):
            continue
        try:
            entries = list(path.iterdir())
            if any(entry.name != "polmon-backend.log" or not entry.is_file() for entry in entries):
                continue
            for entry in entries:
                entry.unlink()
            path.rmdir()
        except OSError:
            continue  # e.g. a log still open elsewhere on Windows: retry at the next start
        removed.append(path)
    return removed


def _process_rss_bytes(process: subprocess.Popen[bytes]) -> int | None:
    """Sample a child working set using only platform APIs available in packaged builds."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        ok = psapi.GetProcessMemoryInfo(
            wintypes.HANDLE(process._handle), ctypes.byref(counters), counters.cb
        )
        return int(counters.WorkingSetSize) if ok else None
    try:
        for line in Path(f"/proc/{process.pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


class _WindowsKillJob:
    """Minimal kill-on-close Job Object wrapper (constructed only on Windows)."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )]

        class BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        information = EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(information), ctypes.sizeof(information)
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        if not kernel32.AssignProcessToJobObject(handle, wintypes.HANDLE(process._handle)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        self._kernel32 = kernel32
        self._handle = handle

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


class LocalBackendManager:
    """Start, monitor, log, and reap one loopback-only L0 backend."""

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        state_directory: Path | None = None,
    ) -> None:
        self._executable = executable
        self.command: list[str] | None = None
        self.state_directory = state_directory or default_state_directory()
        self.process: subprocess.Popen[bytes] | None = None
        self.token = ""
        self.port: int | None = None
        self.url = ""
        self.log_path: Path | None = None
        # Persistent across sessions: experiment history, reports and captures survive a
        # reconnect or restart and stay bounded by the backend's own --max-data-mb admission.
        self.data_directory = self.state_directory / "data"
        self._log = None
        self._job: _WindowsKillJob | None = None
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def exit_code(self) -> int | None:
        return None if self.process is None else self.process.poll()

    def start(
        self,
        *,
        timeout: float = 20.0,
        attempts: int = 5,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            if self.running:
                return self.connection()
            self.command = resolve_backend_command(self._executable)
            self.state_directory.mkdir(parents=True, exist_ok=True)
            sessions = self.state_directory / "sessions"
            sessions.mkdir(exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            session = sessions / f"{stamp}-{os.getpid()}-{secrets.token_hex(3)}"
            session.mkdir()
            prune_session_logs(sessions, current=session)
            self.data_directory.mkdir(exist_ok=True)
            self.log_path = session / "polmon-backend.log"
            self._log = self.log_path.open("ab", buffering=0)
            self.token = secrets.token_urlsafe(32)

        last = "backend did not start"
        for attempt in range(1, attempts + 1):
            if cancelled and cancelled():
                self.stop()
                raise LocalBackendCancelled("local backend startup cancelled")
            self.port = _free_loopback_port()
            self.url = f"http://127.0.0.1:{self.port}"
            environment = {
                **os.environ,
                "POLMON_API_TOKEN": self.token,
                "PYTHONUTF8": "1",
            }
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            try:
                self.process = subprocess.Popen(  # noqa: S603 - resolved executable, fixed args
                    [
                        *self.command,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(self.port),
                        "--local-l0-only",
                        "--data-dir",  # explicit; "var" keeps the v0.3.1 layout readable
                        str(self.data_directory / "var"),
                        # Lifeline: the backend leaves at EOF on this pipe, i.e. when we close
                        # it in stop() or when this client dies (the OS closes it for us).
                        "--exit-with-stdin",
                    ],
                    cwd=self.data_directory,
                    stdin=subprocess.PIPE,
                    stdout=self._log,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    start_new_session=os.name == "posix",
                    creationflags=flags,
                )
                if sys.platform == "win32":
                    self._job = _WindowsKillJob(self.process)
            except OSError as error:
                self.stop()
                raise LocalBackendError(f"could not start {self.command[0]}: {error}") from error

            client = ApiClient(self.url, timeout=1.0, token=self.token)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cancelled and cancelled():
                    self.stop()
                    raise LocalBackendCancelled("local backend startup cancelled")
                code = self.process.poll()
                if code is not None:
                    last = f"backend exited with code {code} on startup attempt {attempt}"
                    self._close_job()
                    break
                try:
                    resources = client.resources()
                    capabilities = resources.get("capabilities") or {}
                    if (
                        not isinstance(capabilities, dict)
                        or capabilities.get("fidelity") != "l0_only"
                    ):
                        raise LocalBackendError("local backend did not advertise L0-only fidelity")
                    return self.connection()
                except ApiClientError:
                    time.sleep(0.1)
            else:
                last = f"backend was not ready within {timeout:g} s on attempt {attempt}"
            self._terminate_child(timeout=3.0)

        detail = self.log_tail()
        self.stop()
        suffix = f"; log: {self.log_path}" if self.log_path else ""
        if detail:
            suffix += f"; last output: {detail}"
        raise LocalBackendError(last + suffix)

    def connection(self) -> dict[str, object]:
        return {
            "url": self.url,
            "token": self.token,
            "port": self.port,
            "pid": None if self.process is None else self.process.pid,
            "log_path": self.log_path,
            "data_directory": self.data_directory,
            "label": LOCAL_LABEL,
        }

    def stop(self, *, timeout: float = 10.0) -> int | None:
        with self._lock:
            process = self.process
            if process is None:
                self._close_log()
                self._close_job()
                return None
            if process.poll() is None and self.url:
                with contextlib.suppress(ApiClientError, OSError):
                    ApiClient(self.url, timeout=2.0, token=self.token).reset_all()
            code = self._terminate_child(timeout=timeout)
            self._close_job()
            self._close_log()
            return code

    def _terminate_child(self, *, timeout: float, graceful: float = 5.0) -> int | None:
        process = self.process
        if process is None:
            return None
        if process.stdin is not None and not process.stdin.closed:
            with contextlib.suppress(OSError):
                process.stdin.close()  # EOF on the lifeline: graceful shutdown on every platform
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=min(graceful, timeout))
        if process.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except (OSError, ProcessLookupError):
                pass
            try:
                return process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except (OSError, ProcessLookupError):
                    pass
                return process.wait(timeout=5)
        return process.returncode

    def _close_job(self) -> None:
        if self._job is not None:
            self._job.close()
            self._job = None

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None

    def log_tail(self, limit: int = 500) -> str:
        if self.log_path is None:
            return ""
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
        except OSError:
            return ""


def packaged_workflow_self_test(
    executable: str | Path | None = None, *, state_directory: Path | None = None
) -> dict[str, object]:
    """Run the acceptance workflow solely through an owned backend and its HTTP API.

    Without ``state_directory`` it runs in a temporary one: a self-test must neither read nor add
    to the operator's persistent local experiment history.
    """
    if state_directory is None:
        with tempfile.TemporaryDirectory(
            prefix="polmon-local-self-test-", ignore_cleanup_errors=True
        ) as scratch:
            return packaged_workflow_self_test(executable, state_directory=Path(scratch))
    manager = LocalBackendManager(executable, state_directory=state_directory)
    connection = manager.start()
    process = manager.process
    assert process is not None
    client = ApiClient(str(connection["url"]), token=str(connection["token"]))
    try:
        client.load_topology(_L0_TOPOLOGY)
        deployment = client.deploy("local-smoke")
        experiment = client.run_experiment(
            "packaged-local-smoke", "local-smoke", _L0_SCENARIO
        )
        telemetry = client.telemetry("packaged-local-smoke")
        report = client.report("packaged-local-smoke")
        markdown = client.report_markdown("packaged-local-smoke")
        # The backend's own figure: on Windows the one-file executable is a small bootloader
        # whose Python child does the work, so sampling the launched PID would under-report.
        snapshot = client.resources().get("snapshot") or {}
        reset = client.reset_all()
        client.load_topology(_L1_TOPOLOGY)
        refusal = ""
        try:
            client.deploy("needs-linux")
        except ApiClientError as error:
            refusal = str(error).split(": ", 1)[-1]
        if refusal != LOCAL_FIDELITY_MESSAGE:
            raise LocalBackendError(f"unexpected L1 refusal: {refusal or 'request succeeded'}")
        if deployment.get("state") != "running" or experiment.get("status") != "succeeded":
            raise LocalBackendError("L0 deployment or experiment did not succeed")
        if not telemetry or report.get("status") != "succeeded" or not markdown.strip():
            raise LocalBackendError("telemetry or reports were not produced")
        if reset.get("deployments_destroyed") != 1:
            raise LocalBackendError(f"reset did not destroy the deployment: {reset}")
        record = {
            "label": LOCAL_LABEL,
            "backend_pid": process.pid,
            "backend": deployment.get("backend"),
            "experiment_status": experiment.get("status"),
            "telemetry_events": len(telemetry),
            "report_status": report.get("status"),
            "markdown_bytes": len(markdown.encode("utf-8")),
            "reset": reset,
            "l1_refusal": refusal,
            "log_path": str(manager.log_path),
            "backend_rss_bytes": snapshot.get("process_rss_bytes")
            if isinstance(snapshot, dict)
            else None,
            "launcher_rss_bytes": _process_rss_bytes(process),
        }
    finally:
        manager.stop()
    if process.poll() is None:
        raise LocalBackendError(f"backend process {process.pid} remained after normal stop")
    record["normal_stop_exit_code"] = process.returncode
    if process.returncode != 0:  # closing the lifeline must end it gracefully, not by a kill
        raise LocalBackendError(f"backend did not shut down gracefully: {process.returncode}")
    killed_connection = manager.start()
    killed_process = manager.process
    assert killed_process is not None
    killed_process.kill()
    killed_process.wait(timeout=10)
    manager.stop()
    if killed_process.poll() is None:
        raise LocalBackendError(f"killed backend process {killed_process.pid} remained")
    record["backend_killed"] = {
        "pid": killed_process.pid,
        "exit_code": killed_process.returncode,
        "url": killed_connection["url"],
    }
    return record


def crash_cleanup_probe(
    output: Path, executable: str | Path | None = None, *, state_directory: Path | None = None
) -> None:
    """Start an owned child, publish its PID, then emulate an uncatchable client crash."""
    if state_directory is None:  # kept out of the operator's state; the crash leaves it behind
        state_directory = Path(tempfile.mkdtemp(prefix="polmon-local-crash-test-"))
    manager = LocalBackendManager(executable, state_directory=state_directory)
    manager.start()
    output.write_text(json.dumps(manager.connection(), default=str), encoding="utf-8")
    # Do not unwind or close the Job Object explicitly. Windows must close it as part of process
    # teardown and kill the backend; this is the acceptance proof for a crashed packaged client.
    os._exit(77)
