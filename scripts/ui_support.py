"""Helpers for driving the real Qt client against a real backend process (dev tooling).

Used by ``scripts/ui_screenshots.py`` and ``scripts/ui_e2e.py``. The backend runs as a separate
``python -m polmon.backend`` process with a fresh random API token and its own data directory,
exactly as an operator would run it; the client is the unmodified ``MainWindow``.
"""

from __future__ import annotations

import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class BackendProcess:
    def __init__(self, data_directory: Path, *, extra_args: list[str] | None = None) -> None:
        self.data_directory = data_directory
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.token = secrets.token_urlsafe(32)
        self.log_path = data_directory / "backend.log"
        self.extra_args = extra_args or []
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, timeout: float = 20.0) -> BackendProcess:
        from polmon.client.api import ApiClient, ApiClientError

        self.data_directory.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("wb")
        environment = {**os.environ, "POLMON_API_TOKEN": self.token, "PYTHONUTF8": "1"}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "polmon.backend", "--port", str(self.port), *self.extra_args],
            cwd=self.data_directory,  # the backend keeps its data in ./var
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        client = ApiClient(self.url, timeout=1.0, token=self.token)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"backend exited early; see {self.log_path}")
            try:
                client.resources()
                return self
            except ApiClientError:
                time.sleep(0.1)
        raise RuntimeError(f"backend did not become ready within {timeout} s")

    def stop(self) -> int | None:
        if self.process is None or self.process.poll() is not None:
            return None if self.process is None else self.process.returncode
        if os.name == "posix":
            self.process.send_signal(signal.SIGTERM)  # graceful: the backend resets on shutdown
        else:
            self.process.terminate()
        try:
            return self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
            return self.process.wait(timeout=10)


def wait_until(app, predicate: Callable[[], bool], what: str, timeout: float = 30.0) -> float:  # noqa: ANN001
    """Pump the Qt event loop until ``predicate`` holds; returns the seconds waited."""
    from PySide6.QtCore import QEventLoop

    started = time.monotonic()
    while time.monotonic() - started < timeout:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if predicate():
            return time.monotonic() - started
        time.sleep(0.01)
    raise TimeoutError(f"timed out after {timeout:g} s waiting for: {what}")


def settle(app, seconds: float) -> None:  # noqa: ANN001
    """Keep the event loop running for ``seconds`` (lets polls and repaints happen)."""
    from PySide6.QtCore import QEventLoop

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.01)


def auto_confirm(log: Callable[[str], None]) -> None:
    """Answer confirmation dialogs with the accept action (recording the question by its
    catalog key) in unattended runs."""
    from polmon.client.widgets import set_confirm_handler

    def accept(title: str, text: str) -> bool:
        log(f"confirmation '{title}' accepted")
        return True

    set_confirm_handler(accept)
