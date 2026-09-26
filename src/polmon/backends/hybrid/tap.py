"""Unprivileged file-descriptor access to a pre-created owned TAP interface."""

from __future__ import annotations

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
        return cls(name, descriptor)

    def write(self, frame: bytes) -> None:
        written = os.write(self.file_descriptor, frame)
        if written != len(frame):
            raise OSError("partial TAP frame write")

    def read(self, timeout: float) -> bytes | None:
        readable, _, _ = select.select([self.file_descriptor], [], [], timeout)
        return os.read(self.file_descriptor, 65535) if readable else None

    def close(self) -> None:
        if self.file_descriptor >= 0:
            os.close(self.file_descriptor)
            self.file_descriptor = -1

