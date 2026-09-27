"""Leave together with whatever owns this process.

A one-file executable is two processes: a small bootloader (the PID its parent sees) and the
Python child it extracts and starts. Terminating the bootloader (``Stop-Process``, a service
manager, ``TerminateProcess``) does not end that child on Windows, so the serving process watches
its launcher and shuts down gracefully once it is gone — no orphaned backend keeps the port.

A client that owns a backend holds the write end of a pipe on the backend's stdin. EOF on that
pipe — the client closing it to stop the backend, or the operating system closing it because the
client died, however abruptly — makes the backend shut down gracefully on every platform.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

SYNCHRONIZE = 0x00100000
INFINITE = 0xFFFFFFFF


def onefile_launcher_pid() -> int | None:
    """The bootloader's PID when running from a one-file bundle, otherwise ``None``."""
    bundle = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not bundle:
        return None
    # One-file bundles extract to a temporary ``_MEI<n>`` directory; one-folder bundles do not.
    return os.getppid() if Path(bundle).name.startswith("_MEI") else None


def _wait_for_exit(pid: int, poll_seconds: float) -> None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:  # already gone
            return
        try:
            kernel32.WaitForSingleObject(handle, INFINITE)
        finally:
            kernel32.CloseHandle(handle)
        return
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(poll_seconds)


def _watch(
    name: str,
    wait: Callable[[], None],
    message: str,
    event: str,
    on_exit: Callable[[], None],
    grace_seconds: float | None,
) -> threading.Thread:
    def watch() -> None:
        wait()
        logger.warning(message, extra={"event": event})
        on_exit()
        if grace_seconds is not None:
            time.sleep(grace_seconds)
            logger.error("graceful shutdown overran; exiting", extra={"event": "forced_exit"})
            os._exit(1)

    thread = threading.Thread(target=watch, name=name, daemon=True)
    thread.start()
    return thread


def watch_process(
    pid: int,
    on_exit: Callable[[], None],
    *,
    poll_seconds: float = 0.5,
    grace_seconds: float | None = 15.0,
) -> threading.Thread:
    """Call ``on_exit`` once ``pid`` ends; force this process out after ``grace_seconds``."""
    return _watch(
        "polmon-launcher-watch",
        lambda: _wait_for_exit(pid, poll_seconds),
        f"launcher process {pid} exited; shutting down",
        "launcher_exit",
        on_exit,
        grace_seconds,
    )


def _drain_until_eof(stream: BinaryIO) -> None:
    try:
        while stream.read(4096):
            pass
    except (OSError, ValueError):  # a closed or broken pipe counts as the owner leaving
        pass


def watch_stream_eof(
    stream: BinaryIO,
    on_exit: Callable[[], None],
    *,
    grace_seconds: float | None = 15.0,
) -> threading.Thread:
    """Call ``on_exit`` at EOF on ``stream`` (the owner's lifeline pipe); force exit after grace."""
    return _watch(
        "polmon-stdin-lifeline",
        lambda: _drain_until_eof(stream),
        "owner closed the stdin lifeline; shutting down",
        "owner_exit",
        on_exit,
        grace_seconds,
    )
