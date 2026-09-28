"""Narrow subprocess boundary for authorized laboratory networking operations."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread

TIMEOUT_RETURNCODE = 124  # the convention of coreutils timeout(1)


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True, slots=True)
class BoundedCommandResult(CommandResult):
    duration_seconds: float
    truncated: bool
    timed_out: bool


class CommandRunner:
    """Run argv-only commands with timeouts; shell interpretation is never used."""

    def run(
        self,
        command: list[str],
        *,
        privileged: bool = False,
        check: bool = True,
        timeout: float = 10,
        input: str | None = None,
    ) -> CommandResult:
        argv = ["sudo", "-n", *command] if privileged else command
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input,
            )
        except subprocess.TimeoutExpired:
            # A hung command must not abort best-effort teardown or turn a probe into a crash.
            if check:
                raise RuntimeError(
                    f"command timed out after {timeout:g}s: {command[0]}"
                ) from None
            return CommandResult("", f"timed out after {timeout:g}s", TIMEOUT_RETURNCODE)
        if check and completed.returncode != 0:
            raise RuntimeError(
                f"command failed ({completed.returncode}): {command[0]}: "
                f"{completed.stderr.strip()[:500]}"
            )
        return CommandResult(completed.stdout, completed.stderr, completed.returncode)

    def start(
        self,
        command: list[str],
        *,
        privileged: bool = False,
        log_path: str | Path | None = None,
        max_output_bytes: int = 128 * 1024,
    ) -> subprocess.Popen[bytes]:
        argv = ["sudo", "-n", *command] if privileged else command
        if log_path is None:
            return subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        destination = Path(log_path)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        def drain() -> None:
            assert process.stdout is not None
            written = 0
            with destination.open("ab") as stream:
                while chunk := process.stdout.read(8192):
                    remaining = max_output_bytes - written
                    if remaining > 0:
                        stream.write(chunk[:remaining])
                        stream.flush()
                        written += min(len(chunk), remaining)

        Thread(target=drain, daemon=True, name=f"service-log-{process.pid}").start()
        return process

    def run_bounded(
        self,
        command: list[str],
        *,
        privileged: bool = False,
        timeout: float = 10,
        max_output_bytes: int = 262_144,
    ) -> BoundedCommandResult:
        """Run argv with a wall timeout while draining and retaining at most a hard byte cap."""
        argv = ["sudo", "-n", *command] if privileged else command
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        total = 0
        truncated = False
        buffer_lock = Lock()

        def drain(name: str, stream) -> None:  # noqa: ANN001
            nonlocal total, truncated
            while chunk := stream.read(8192):
                with buffer_lock:
                    remaining = max_output_bytes - total
                    if remaining > 0:
                        kept = chunk[:remaining]
                        buffers[name].extend(kept)
                        total += len(kept)
                    if len(chunk) > remaining:
                        truncated = True

        threads = [
            Thread(target=drain, args=("stdout", process.stdout), daemon=True),
            Thread(target=drain, args=("stderr", process.stderr), daemon=True),
        ]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=3)
        duration = time.monotonic() - started
        return BoundedCommandResult(
            stdout=buffers["stdout"].decode("utf-8", "replace"),
            stderr=buffers["stderr"].decode("utf-8", "replace"),
            returncode=TIMEOUT_RETURNCODE if timed_out else process.returncode,
            duration_seconds=round(duration, 6),
            truncated=truncated,
            timed_out=timed_out,
        )
