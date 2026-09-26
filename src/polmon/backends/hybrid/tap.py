"""Unprivileged file-descriptor access to a pre-created owned TAP interface."""

from __future__ import annotations

import contextlib
import importlib
import os
import select
import struct
from dataclasses import dataclass

TUNSETIFF = 0x400454CA
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000


@dataclass(slots=True)
class TapPort:
    name: str
    file_descriptor: int
    # Self-pipe so interrupt() can wake a reader blocked in select() immediately.
    wake_read: int = -1
    wake_write: int = -1

    @classmethod
    def attach(cls, name: str) -> TapPort:
        descriptor = os.open("/dev/net/tun", os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl = importlib.import_module("fcntl")
            request = struct.pack("16sH", name.encode("ascii"), IFF_TAP | IFF_NO_PI)
            fcntl.ioctl(descriptor, TUNSETIFF, request)
        except Exception:
            os.close(descriptor)
            raise
        wake_read, wake_write = os.pipe()
        os.set_blocking(wake_read, False)
        os.set_blocking(wake_write, False)
        return cls(name, descriptor, wake_read, wake_write)

    def write(self, frame: bytes) -> None:
        written = os.write(self.file_descriptor, frame)
        if written != len(frame):
            raise OSError("partial TAP frame write")

    def read(self, timeout: float) -> bytes | None:
        watched = [self.file_descriptor] + ([self.wake_read] if self.wake_read >= 0 else [])
        readable, _, _ = select.select(watched, [], [], timeout)
        if self.wake_read >= 0 and self.wake_read in readable:
            with contextlib.suppress(BlockingIOError):
                os.read(self.wake_read, 64)
            return None
        return os.read(self.file_descriptor, 65535) if readable else None

    def interrupt(self) -> None:
        """Wake a concurrent ``read`` at once (used when stopping the TAP responder)."""
        if self.wake_write >= 0:
            with contextlib.suppress(BlockingIOError):  # a wake-up may already be pending
                os.write(self.wake_write, b"\0")

    def close(self) -> None:
        for attribute in ("file_descriptor", "wake_read", "wake_write"):
            descriptor = getattr(self, attribute)
            if descriptor >= 0:
                os.close(descriptor)
                setattr(self, attribute, -1)

