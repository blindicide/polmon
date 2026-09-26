"""Leave together with a PyInstaller one-file launcher.

A one-file executable is two processes: a small bootloader (the PID its parent sees) and the
Python child it extracts and starts. Terminating the bootloader (``Stop-Process``, a service
manager, ``TerminateProcess``) does not end that child on Windows, so the serving process watches
its launcher and shuts down gracefully once it is gone — no orphaned backend keeps the port.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

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


def watch_process(
    pid: int,
    on_exit: Callable[[], None],
    *,
    poll_seconds: float = 0.5,
    grace_seconds: float | None = 15.0,
) -> threading.Thread:
    """Call ``on_exit`` once ``pid`` ends; force this process out after ``grace_seconds``."""

    def watch() -> None:
        _wait_for_exit(pid, poll_seconds)
        logger.warning(
            "launcher process %s exited; shutting down", pid, extra={"event": "launcher_exit"}
        )
        on_exit()
        if grace_seconds is not None:
            time.sleep(grace_seconds)
            logger.error("graceful shutdown overran; exiting", extra={"event": "forced_exit"})
            os._exit(1)

    thread = threading.Thread(target=watch, name="polmon-launcher-watch", daemon=True)
    thread.start()
    return thread
