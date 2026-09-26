"""Narrow subprocess boundary for authorized laboratory networking operations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class CommandRunner:
    """Run argv-only commands with timeouts; shell interpretation is never used."""

    def run(
        self,
        command: list[str],
        *,
        privileged: bool = False,
        check: bool = True,
        timeout: float = 10,
    ) -> CommandResult:
        argv = ["sudo", "-n", *command] if privileged else command
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
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

