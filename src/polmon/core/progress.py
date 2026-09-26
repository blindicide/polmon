"""Info-dense CLI progress for long-running steps (stderr, TTY-aware, never on stdout)."""

from __future__ import annotations

import sys
import time
from typing import TextIO


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "?"
    if value >= 60:
        minutes, seconds = divmod(int(round(value)), 60)
        return f"{minutes}m{seconds:02d}s"
    return f"{value:.1f}s"


class Progress:
    """Percent / elapsed / ETA / step progress on stderr, degrading cleanly off-TTY."""

    def __init__(self, total: int, *, label: str = "benchmark", stream: TextIO | None = None):
        if total < 1:
            raise ValueError("progress total must be positive")
        self.total = total
        self.label = label
        self.stream = stream if stream is not None else sys.stderr
        isatty = getattr(self.stream, "isatty", None)
        self.interactive = bool(isatty and isatty())
        self.started = time.monotonic()
        self.completed = 0

    def line(self, completed: int, detail: str) -> str:
        elapsed = time.monotonic() - self.started
        eta = (elapsed / completed) * (self.total - completed) if completed else None
        percent = (completed / self.total) * 100
        return (
            f"[{self.label}] {percent:5.1f}% step {completed}/{self.total} "
            f"elapsed {_format_seconds(elapsed)} eta {_format_seconds(eta)} {detail}"
        ).rstrip()

    def update(self, completed: int, detail: str = "") -> None:
        self.completed = completed
        text = self.line(completed, detail)
        if self.interactive:
            end = "\n" if completed >= self.total else ""
            self.stream.write(f"\r\x1b[2K{text}{end}")
        else:
            self.stream.write(text + "\n")
        self.stream.flush()
