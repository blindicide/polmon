"""Narrow subprocess boundary for authorized laboratory networking operations."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
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

    def start(self, command: list[str], *, privileged: bool = False) -> subprocess.Popen[bytes]:
        argv = ["sudo", "-n", *command] if privileged else command
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

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
