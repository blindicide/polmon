"""Задания виртуальных машин L1 за HTTP API.

Каждое задание запускает команду дополнения ``polmon-l1-vm`` отдельным процессом в собственной
группе процессов, поэтому ограничения, допуск и очистка самого дополнения действуют без
изменений, а API ничего не импортирует из ``polmon_l1_vm``. Образ гостя и топология зафиксированы
здесь: по сети скачивается только закреплённый образ с проверкой sha256, а не произвольный адрес
из запроса.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock, Thread, Timer
from typing import Literal

from polmon.core.errors import ConfigurationError
from polmon.topology.models import StrictModel

# Закреплённый образ; тест сверяет эти данные с examples/vm/alpine-3.24.1-manifest.json.
MANIFEST = {
    "sha256": "6e2e6fe0572b6632527f268d3659e8fccebda4e1ee470fafe2c4d7b85b6a4df6",
    "source_url": (
        "https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/cloud/"
        "generic_alpine-3.24.1-x86_64-bios-cloudinit-r0.qcow2"
    ),
    "distribution": "alpine-3.24.1-x86_64-bios-cloudinit",
    "license_notice": (
        "Alpine Linux cloud image; its components are distributed under their own open-source "
        "licenses, see https://alpinelinux.org/cloud/"
    ),
}
# Лаборатория из двух гостей; тест сверяет её с examples/topologies/l1-vm-addon.yml.
TOPOLOGY = """id: vm-clones
networks:
  - {id: lab, ipv4_subnet: 192.168.240.0/24}
nodes:
  - id: alpha
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:06:00:01', ipv4: 192.168.240.11}
    services:
      - {id: web, protocol: tcp, port: 8080, implementation: static_http}
  - id: bravo
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:06:00:02', ipv4: 192.168.240.12}
    services:
      - {id: web, protocol: tcp, port: 8080, implementation: static_http}
"""
IMAGE_NAME = MANIFEST["source_url"].rsplit("/", 1)[1]
JOB_SECONDS = {"acquire": 1_000.0, "verify": 300.0, "run": 900.0}
TERMINATION_GRACE_SECONDS = 30.0
MAX_RETAINED_JOBS = 20
READINESS_FIELDS = ("version", "ready", "modes", "missing", "integration_verified")
NO_MODES = {"userns": False, "netns": False}


class VMRequest(StrictModel):
    action: Literal["acquire", "verify", "run"]
    mode: Literal["userns", "netns"] = "userns"


def bundled_image() -> Path:
    """Образ, который поставляется вместе с программой (в сборке — рядом с исполняемым файлом)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "vm"
    else:
        base = Path(__file__).resolve().parents[3] / "packaging/vm-image"
    return base / IMAGE_NAME


def addon_source() -> Path | None:
    """Исходники дополнения в рабочей копии репозитория (в установленной системе их нет)."""
    candidate = Path(__file__).resolve().parents[3] / "addons/l1-vm/src"
    return candidate if (candidate / "polmon_l1_vm").is_dir() else None


def addon_importable() -> bool:
    return importlib.util.find_spec("polmon_l1_vm") is not None


def addon_available() -> bool:
    """Дополнение можно запустить: Linux, обычная установка и найденный пакет."""
    if sys.platform != "linux":
        return False
    return addon_importable() or addon_source() is not None


def addon_environment() -> dict[str, str]:
    environment = {**os.environ, "PYTHONUTF8": "1"}
    source = addon_source()
    if source is not None and not addon_importable():
        paths = [str(source), environment.get("PYTHONPATH", "")]
        environment["PYTHONPATH"] = os.pathsep.join(item for item in paths if item)
    return environment


def addon_command(*arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-vm", *arguments]
    return [sys.executable, "-m", "polmon_l1_vm.cli", *arguments]


Launcher = Callable[[Sequence[str], object, dict[str, str]], subprocess.Popen[bytes]]


def _launch(
    command: Sequence[str], stdout: object, environment: dict[str, str]
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - фиксированный вызов модуля, проверенные аргументы
        list(command),
        stdout=stdout,  # type: ignore[arg-type]
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,  # своя группа процессов: отмена достаёт и дочерние процессы
    )


def _last_document(text: str) -> dict[str, object] | None:
    for line in reversed(text.splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class VMJob:
    def __init__(self, job_id: str, request: VMRequest, directory: Path | None) -> None:
        self.job_id = job_id
        self.request = request
        self.directory = directory
        self.state = "running"
        self.started_at = datetime.now(UTC)
        self.started = time.monotonic()
        self.finished: float | None = None
        self.exit_code: int | None = None
        self.result: dict[str, object] | None = None
        self.message: str | None = None
        self.message_code: str | None = None
        self.message_params: dict[str, object] = {}
        self.stderr_tail: list[str] = []
        self.process: subprocess.Popen[bytes] | None = None
        self.timer: Timer | None = None
        self.cancel_requested = False
        self.expired = False

    def view(self) -> dict[str, object]:
        end = self.finished if self.finished is not None else time.monotonic()
        return {
            "job_id": self.job_id,
            "action": self.request.action,
            "mode": self.request.mode,
            "state": self.state,
            "started_at": self.started_at.isoformat(),
            "elapsed_seconds": round(end - self.started, 3),
            "limit_seconds": JOB_SECONDS[self.request.action],
            "result": self.result,
            "message": self.message,
            "message_code": self.message_code,
            "message_params": dict(self.message_params),
            "exit_code": self.exit_code,
            "stderr_tail": list(self.stderr_tail[-20:]),
        }


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM группе процессов задания (команда сама всё удаляет), SIGKILL после паузы."""
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)

    def escalate() -> None:
        try:
            process.wait(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)

    Thread(target=escalate, name="polmon-vm-kill", daemon=True).start()


class VMJobs:
    """Не более одного задания ВМ одновременно; завершённые хранятся ограниченно."""

    def __init__(
        self,
        directory: Path,
        *,
        launcher: Launcher = _launch,
        command: Callable[..., list[str]] = addon_command,
        environment: Callable[[], dict[str, str]] = addon_environment,
        available: Callable[[], bool] | None = None,
        bundled: Callable[[], Path] = bundled_image,
    ) -> None:
        self.directory = directory
        self._bundled = bundled
        self._launcher = launcher
        self._command = command
        self._environment = environment
        self._available = available or (lambda: addon_available())
        self._jobs: dict[str, VMJob] = {}
        self._threads: dict[str, Thread] = {}
        self._recovering = False
        self._lock = RLock()

    @property
    def available(self) -> bool:
        return self._available()

    @property
    def image_path(self) -> Path:
        """Образ из состава программы; если его нет — копия в каталоге данных."""
        bundled = self._bundled()
        if bundled.is_file():
            return bundled
        return self.directory / "image" / IMAGE_NAME

    # -- состояние ----------------------------------------------------------------------------

    def _image_present(self) -> bool:
        path = self.image_path
        return path.is_file() and not path.is_symlink()

    def status(self) -> dict[str, object]:
        """Дешёвое состояние: доступность дополнения, образ и выполняющееся задание."""
        present = self._image_present()
        with self._lock:
            running = self.running()
            return {
                "available": self.available,
                "as_root": getattr(os, "geteuid", lambda: -1)() == 0,
                "image": {
                    "present": present,
                    "bundled": present and self.image_path == self._bundled(),
                    "name": IMAGE_NAME,
                    "size_bytes": self.image_path.stat().st_size if present else None,
                    "sha256": MANIFEST["sha256"],
                    "source_url": MANIFEST["source_url"],
                    "distribution": MANIFEST["distribution"],
                    "license_notice": MANIFEST["license_notice"],
                },
                "running": running.job_id if running else None,
            }

    def _call(self, *arguments: str, timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - фиксированный вызов модуля, проверенные аргументы
            self._command(*arguments),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=self._environment(),
            check=False,
        )

    def readiness(self) -> dict[str, object]:
        """Проверка хоста самим дополнением; от root режимы выключены (см. ``as_root``)."""
        base: dict[str, object] = {"available": self.available, "ready": False, "modes": NO_MODES}
        if not self.available:
            return {**base, "missing": ["vm.addon_missing"]}
        try:
            completed = self._call("readiness", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return {**base, "missing": ["vm.readiness_failed"]}
        document = _last_document(completed.stdout)
        if document is None:
            return {**base, "missing": ["vm.readiness_failed"]}
        report = {key: document[key] for key in READINESS_FIELDS if key in document}
        result = {**base, **report}
        if getattr(os, "geteuid", lambda: -1)() == 0:
            # Гость обязан работать от имени обычного пользователя, а не root.
            missing = result.get("missing")
            known = list(missing) if isinstance(missing, list) else []
            result.update(ready=False, modes=NO_MODES, missing=[*known, "vm.running_as_root"])
        return result

    # -- задания ------------------------------------------------------------------------------

    def running(self) -> VMJob | None:
        with self._lock:
            return next((job for job in self._jobs.values() if job.state == "running"), None)

    def start(self, request: VMRequest) -> dict[str, object]:
        if not self.available:
            raise ConfigurationError(
                "the VM runtime add-on is not available on this backend",
                message_code="vm.addon_missing",
            )
        if getattr(os, "geteuid", lambda: -1)() == 0:
            raise ConfigurationError(
                "VM jobs must not run as root: guests would run with root privileges",
                message_code="vm.running_as_root",
            )
        present = self._image_present()
        if request.action == "acquire" and (present or self.image_path.is_symlink()):
            raise ConfigurationError(
                "the pinned image is already present", message_code="vm.image_exists"
            )
        if request.action != "acquire" and not present:
            raise ConfigurationError(
                "the pinned image has not been downloaded", message_code="vm.image_missing"
            )
        if request.action == "run":
            modes = self.readiness().get("modes")
            if not isinstance(modes, dict) or not modes.get(request.mode):
                raise ConfigurationError(
                    f"VM network mode '{request.mode}' is unavailable on this host",
                    message_code="vm.mode_unavailable",
                    params={"mode": request.mode},
                )
        with self._lock:
            if self._recovering or self.running() is not None:
                raise ConfigurationError("another VM job is running", message_code="vm.job_running")
            job_id = uuid.uuid4().hex[:12]
            self._prepare()
            run_directory = None
            if request.action == "run":
                run_directory = self.directory / "runs" / job_id
                run_directory.mkdir(parents=True, mode=0o700)
            job = VMJob(job_id, request, run_directory)
            stdout = tempfile.TemporaryFile()  # noqa: SIM115 - закрывается потоком наблюдения
            try:
                process = self._launcher(self._arguments(job), stdout, self._environment())
            except OSError as error:
                stdout.close()
                if run_directory is not None:
                    with contextlib.suppress(OSError):
                        run_directory.rmdir()
                raise ConfigurationError(
                    "the VM process could not be started",
                    details={"reason": str(error)},
                    message_code="vm.start_failed",
                ) from error
            job.process = process
            self._jobs[job_id] = job
            self._trim()
            job.timer = Timer(JOB_SECONDS[request.action], self._expire, (job,))
            job.timer.daemon = True
            job.timer.start()
            thread = Thread(
                target=self._supervise, args=(job, stdout), name=f"polmon-vm-{job_id}", daemon=True
            )
            self._threads[job_id] = thread
            thread.start()
            return job.view()

    def _prepare(self) -> None:
        """Каталоги и закреплённые файлы задания; доступ только владельцу."""
        for path in (self.directory, self.directory / "image", self.directory / "runs"):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        (self.directory / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
        (self.directory / "topology.yml").write_text(TOPOLOGY, encoding="utf-8")

    def _arguments(self, job: VMJob) -> list[str]:
        manifest = ["--manifest", str(self.directory / "manifest.json")]
        image = ["--image", str(self.image_path)]
        action = job.request.action
        if action == "acquire":
            return self._command("acquire-image", *manifest, *image)
        if action == "verify":
            return self._command("verify-image", *manifest, *image)
        assert job.directory is not None
        return self._command(
            "run",
            "--topology",
            str(self.directory / "topology.yml"),
            "--directory",
            str(job.directory),
            *manifest,
            *image,
            "--mode",
            job.request.mode,
        )

    def _trim(self) -> None:
        finished = [job for job in self._jobs.values() if job.state != "running"]
        for job in finished[: max(0, len(self._jobs) - MAX_RETAINED_JOBS)]:
            self._jobs.pop(job.job_id, None)
            self._threads.pop(job.job_id, None)

    def _expire(self, job: VMJob) -> None:
        with self._lock:
            if job.state != "running" or job.process is None:
                return
            job.expired = job.cancel_requested = True
            _terminate_group(job.process)

    def _cleanup(self, directory: Path) -> bool:
        """Снимает записанное владение каталога запуска и удаляет его; True — каталога нет."""
        try:
            completed = self._call("recover", "--directory", str(directory), timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if completed.returncode != 0:
            return False
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return not directory.exists()

    def _supervise(self, job: VMJob, stdout) -> None:  # type: ignore[no-untyped-def]
        process = job.process
        assert process is not None and process.stderr is not None
        error_code: str | None = None
        try:
            for raw in process.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                with self._lock:
                    job.stderr_tail = [*job.stderr_tail[-49:], line]
                document = _last_document(line)
                if document and isinstance(document.get("error_code"), str):
                    error_code = str(document["error_code"])
            exit_code = process.wait()
            stdout.seek(0)
            document = _last_document(stdout.read().decode("utf-8", errors="replace"))
        finally:
            stdout.close()
            if job.timer is not None:
                job.timer.cancel()
        # Каталог запуска убирается до объявления конца: интерфейс видит завершённое задание
        # только когда после него ничего не осталось.
        left_behind = job.directory is not None and not self._cleanup(job.directory)
        with self._lock:
            job.exit_code = exit_code
            job.finished = time.monotonic()
            if left_behind:
                job.state, job.message_code = "failed", "vm.failed"
                job.message = "VM cleanup failed; recovery is required"
                job.message_params = {"detail": "cleanup failed"}
            elif job.expired:
                job.state, job.message_code = "failed", "vm.timeout"
                job.message = "the VM job exceeded its time limit and was stopped"
                job.message_params = {"seconds": JOB_SECONDS[job.request.action]}
            elif job.cancel_requested:
                job.state, job.message_code = "cancelled", "vm.cancelled"
                job.message = "cancelled by the operator"
            elif exit_code == 0 and document is not None:
                job.state, job.result = "succeeded", document
            else:
                job.state = "failed"
                if error_code and error_code.startswith("vm."):
                    job.message_code = error_code
                else:
                    job.message_code = "vm.failed"
                    job.message_params = {"detail": error_code or f"exit {exit_code}"}
                job.message = f"the VM job failed: {error_code or f'exit status {exit_code}'}"
            if left_behind:
                # Остаток виден оператору; восстановление уберёт его позже.
                job.message_params = {**job.message_params, "left_behind": True}

    def job(self, job_id: str) -> dict[str, object]:
        with self._lock:
            return self._known(job_id).view()

    def jobs(self) -> list[dict[str, object]]:
        with self._lock:
            return [job.view() for job in reversed(self._jobs.values())]

    def _known(self, job_id: str) -> VMJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise ConfigurationError(
                f"unknown VM job '{job_id}'",
                message_code="vm.unknown_job",
                params={"job_id": job_id},
            )
        return job

    def cancel(self, job_id: str) -> dict[str, object]:
        with self._lock:
            job = self._known(job_id)
            if job.state != "running" or job.process is None:
                raise ConfigurationError(
                    f"VM job '{job_id}' is not running",
                    message_code="vm.job_not_running",
                    params={"job_id": job_id},
                )
            job.cancel_requested = True
            _terminate_group(job.process)
            return job.view()

    # -- восстановление и завершение ----------------------------------------------------------

    def recover(self) -> dict[str, object]:
        """Убирает остатки прерванных запусков: процессы, пространства, диски, каталоги."""
        with self._lock:
            if self._recovering or self.running() is not None:
                raise ConfigurationError("another VM job is running", message_code="vm.job_running")
            self._recovering = True
        try:
            runs = self.directory / "runs"
            found = (
                [path for path in sorted(runs.iterdir()) if path.is_dir() and not path.is_symlink()]
                if runs.is_dir()
                else []
            )
            cleaned = sum(1 for path in found if self._cleanup(path))
            return {"directories": len(found), "recovered": cleaned, "failed": len(found) - cleaned}
        finally:
            with self._lock:
                self._recovering = False

    def recover_at_startup(self) -> None:
        """Остатки запусков предыдущего процесса убираются при старте; сбой не мешает запуску."""
        runs = self.directory / "runs"
        if self.available and runs.is_dir() and any(runs.iterdir()):
            with contextlib.suppress(Exception):
                self.recover()

    def shutdown(self, timeout: float = TERMINATION_GRACE_SECONDS + 5) -> None:
        with self._lock:
            job = self.running()
            if job is not None and job.process is not None:
                job.cancel_requested = True
                _terminate_group(job.process)
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=timeout)
