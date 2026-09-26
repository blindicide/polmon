"""Classic PCAP writer with hard total-byte and per-frame limits."""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

from polmon.telemetry.models import CaptureSummary

GLOBAL_HEADER_SIZE = 24


class BoundedPcapWriter:
    def __init__(
        self,
        experiment_id: str,
        path: Path,
        *,
        max_bytes: int,
        snaplen: int = 65535,
    ) -> None:
        if max_bytes < GLOBAL_HEADER_SIZE:
            raise ValueError("capture limit is smaller than the PCAP header")
        if not 1 <= snaplen <= 65535:
            raise ValueError("snaplen must be between 1 and 65535")
        self.experiment_id = experiment_id
        self.path = path
        self.max_bytes = max_bytes
        self.snaplen = snaplen
        self._file = path.open("xb")
        self._file.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, snaplen, 1))
        self.frame_count = 0
        self.captured_bytes = GLOBAL_HEADER_SIZE
        self.dropped_frames = 0
        self.truncated_frames = 0

    def write(self, frame: bytes, *, timestamp: float | None = None) -> bool:
        timestamp = time.time() if timestamp is None else timestamp
        captured = bytes(frame[: self.snaplen])
        record_size = 16 + len(captured)
        if self.captured_bytes + record_size > self.max_bytes:
            self.dropped_frames += 1
            return False
        seconds = int(timestamp)
        microseconds = int((timestamp - seconds) * 1_000_000)
        self._file.write(struct.pack("<IIII", seconds, microseconds, len(captured), len(frame)))
        self._file.write(captured)
        self.frame_count += 1
        self.captured_bytes += record_size
        if len(captured) < len(frame):
            self.truncated_frames += 1
        return True

    def close(self) -> CaptureSummary:
        if not self._file.closed:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
        return CaptureSummary(
            self.experiment_id,
            self.path,
            self.frame_count,
            self.captured_bytes,
            self.dropped_frames,
            self.truncated_frames,
        )

    def __enter__(self) -> BoundedPcapWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
