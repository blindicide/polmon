"""Bounded, on-demand host observations; never invent per-node shares of a process."""

from __future__ import annotations

import contextlib
import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from threading import RLock

from polmon.core.diagnostics import resource_snapshot
from polmon.version import __version__


@dataclass(frozen=True)
class Subject:
    deployment: str
    node_id: str
    node_uuid: str
    fidelity: str
    pids: tuple[int, ...] = ()
    configured_memory_bytes: int | None = None
    namespace: Path | None = None
    include_children: bool = True


def process_sample(pid: int, proc: Path = Path("/proc")) -> dict | None:
    """Read one process consistently across PID reuse, including names containing spaces."""
    if not hasattr(os, "sysconf"):
        return None
    try:
        path = proc / str(pid)
        raw = (path / "stat").read_text()
        fields = raw[raw.rindex(")") + 2 :].split()  # starts at field 3 (state)
        start = int(fields[19])
        cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        rss = int(fields[21]) * os.sysconf("SC_PAGE_SIZE")
        io = {}
        with contextlib.suppress(OSError, ValueError):
            io = dict(line.split(": ", 1) for line in (path / "io").read_text().splitlines())
        again = (path / "stat").read_text()
        if int(again[again.rindex(")") + 2 :].split()[19]) != start:
            return None
        return {
            "pid": pid,
            "start_ticks": start,
            "cpu_seconds": cpu,
            "rss_bytes": rss,
            "read_bytes": int(io["read_bytes"]) if "read_bytes" in io else None,
            "write_bytes": int(io["write_bytes"]) if "write_bytes" in io else None,
        }
    except (OSError, ValueError, IndexError):
        return None


def process_tree(
    roots: tuple[int, ...], *, limit: int = 128, proc: Path = Path("/proc")
) -> tuple[list[int], bool]:
    """Visit only registered roots and their descendants; no whole-host process scan."""
    seen: set[int] = set()
    pending = set(roots[:limit])
    complete = len(roots) <= limit
    while pending and len(seen) < limit:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        try:
            # Children can be forked by another thread; bound both tasks and descendants.
            tasks = list(islice((proc / str(pid) / "task").iterdir(), limit + 1))
            if len(tasks) > limit:
                complete = False
            for task in tasks[:limit]:
                with (task / "children").open() as stream:
                    raw = stream.read(8193)
                if len(raw) > 8192:
                    complete = False
                    raw = raw[:8192].rsplit(" ", 1)[0]
                for item in raw.split():
                    child = int(item)
                    if child in seen or child in pending:
                        continue
                    if len(seen) + len(pending) >= limit:
                        complete = False
                        break
                    pending.add(child)
        except (OSError, ValueError):
            complete = False
    return sorted(seen), complete and not pending


def network_sample(
    pids: list[int], namespace: Path | None, proc: Path = Path("/proc")
) -> dict | None:
    """One netns total, excluding loopback. Never attribute the host namespace to a node."""
    if namespace is None:
        return None
    try:
        expected = namespace.stat().st_ino
        if expected == (proc / "self/ns/net").stat().st_ino:
            return None
    except OSError:
        return None
    for pid in pids:
        try:
            path = proc / str(pid)
            if (path / "ns/net").stat().st_ino != expected:
                continue
            values = [
                line.split(":", 1)
                for line in (path / "net/dev").read_text().splitlines()
                if ":" in line
            ]
            counters = [raw.split() for name, raw in values if name.strip() != "lo"]
            if (path / "ns/net").stat().st_ino != expected:
                continue
            return {
                name: sum(int(row[index]) for row in counters)
                for name, index in (
                    ("rx_bytes", 0),
                    ("rx_packets", 1),
                    ("tx_bytes", 8),
                    ("tx_packets", 9),
                )
            }
        except (OSError, ValueError, IndexError):
            continue
    return None


class ResourceAnalytics:
    """Thread-safe JSON ring: sample count AND encoded bytes are capped, with no worker."""

    def __init__(
        self,
        *,
        interval_seconds: float = 2,
        retention: int = 120,
        max_bytes: int = 2_097_152,
        max_subjects: int = 256,
        proc: Path = Path("/proc"),
    ) -> None:
        if not math.isfinite(interval_seconds) or not 0.25 <= interval_seconds <= 3600:
            raise ValueError("analytics interval must be between 0.25 and 3600 seconds")
        if not 1 <= retention <= 1000 or not 4096 <= max_bytes <= 16_777_216:
            raise ValueError("analytics retention/storage limit is invalid")
        if not 1 <= max_subjects <= 1000:
            raise ValueError("analytics subject limit is invalid")
        self.interval = interval_seconds
        self.retention, self.max_bytes, self.max_subjects = retention, max_bytes, max_subjects
        self.proc = proc
        self._history: deque[bytes] = deque()
        self._bytes = 0
        self._previous: dict[tuple, tuple[float, float]] = {}
        self._last: float | None = None
        self._sequence = 0
        self._dropped = 0
        self._lock = RLock()

    def sample(self, subjects: list[Subject], *, now: float | None = None) -> bool:
        with self._lock:
            now = time.monotonic() if now is None else now
            if not math.isfinite(now):
                raise ValueError("invalid sample time")
            if self._last is not None and now - self._last < self.interval:
                return False
            if len(subjects) > self.max_subjects:
                raise ValueError("analytics subject limit exceeded")
            identities = [(s.deployment, s.node_uuid) for s in subjects]
            if len(set(identities)) != len(identities):
                raise ValueError("duplicate analytics identity")
            gap = self._last is not None and now - self._last > self.interval * 3
            previous = {}
            owners: set[tuple[int, int]] = set()
            rows = []
            for subject in subjects:
                pids, complete = (
                    process_tree(subject.pids, proc=self.proc)
                    if subject.include_children
                    else (list(subject.pids), True)
                )
                processes = []
                duplicate = False
                for pid in pids:
                    item = process_sample(pid, self.proc)
                    if item is None:
                        complete = False
                        continue
                    identity = (pid, item["start_ticks"])
                    if identity in owners:
                        duplicate = True
                        continue
                    owners.add(identity)
                    key = (subject.deployment, subject.node_uuid, *identity)
                    old = self._previous.get(key)
                    item["cpu_percent"] = None
                    if old and not gap and item["cpu_seconds"] >= old[1]:
                        item["cpu_percent"] = 100 * (item["cpu_seconds"] - old[1]) / (now - old[0])
                    previous[key] = (now, item["cpu_seconds"])
                    processes.append(item)
                row = {
                    "deployment": subject.deployment,
                    "node_id": subject.node_id,
                    "node_uuid": subject.node_uuid,
                    "fidelity": subject.fidelity,
                    "configured_memory_bytes": subject.configured_memory_bytes,
                    "guest_memory_bytes": None,
                    "disk_virtual_bytes": None,
                    "disk_allocated_bytes": None,
                    "process_count": len(processes),
                    "process_tree_complete": complete and not duplicate and bool(subject.pids),
                    "shared_process_excluded": duplicate,
                    "network": network_sample(pids, subject.namespace, self.proc),
                }
                for metric in (
                    "cpu_seconds",
                    "cpu_percent",
                    "rss_bytes",
                    "read_bytes",
                    "write_bytes",
                ):
                    vals = [item[metric] for item in processes]
                    row[metric] = sum(vals) if vals and all(v is not None for v in vals) else None
                rows.append(row)
            host = resource_snapshot()
            deployments = []
            for deployment in sorted({s.deployment for s in subjects}):
                members = [row for row in rows if row["deployment"] == deployment]
                total = {
                    "deployment": deployment,
                    "node_count": len(members),
                    "complete": all(row["process_tree_complete"] for row in members),
                }
                for metric in (
                    "cpu_seconds",
                    "cpu_percent",
                    "rss_bytes",
                    "read_bytes",
                    "write_bytes",
                ):
                    vals = [row[metric] for row in members if row[metric] is not None]
                    total[metric] = sum(vals) if vals else None
                deployments.append(total)
            self._sequence += 1
            record = {
                "sequence": self._sequence,
                "timestamp": datetime.now(UTC).isoformat(),
                "monotonic_seconds": now,
                "sampling_gap": gap,
                "host": {
                    "available_memory_bytes": host.available_memory_bytes,
                    "swap_used_bytes": host.swap_used_bytes,
                },
                "nodes": rows,
                "deployments": deployments,
            }
            encoded = json.dumps(record, separators=(",", ":"), allow_nan=False).encode()
            if len(encoded) > self.max_bytes:
                raise ValueError("one analytics sample exceeds storage limit")
            while self._history and (
                len(self._history) >= self.retention or self._bytes + len(encoded) > self.max_bytes
            ):
                self._bytes -= len(self._history.popleft())
                self._dropped += 1
            self._history.append(encoded)
            self._bytes += len(encoded)
            self._previous, self._last = previous, now
            return True

    def export(self, *, limit: int = 120) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("analytics export limit must be between 1 and 1000")
        with self._lock:
            samples = [json.loads(item) for item in list(self._history)[-limit:]]
            return {
                "version": __version__,
                "schema_version": 1,
                "measurement": "host-procfs; configured fields are limits, null is unavailable",
                "rss_caveat": "RSS includes shared pages; totals are not PSS or kernel memory",
                "cpu_basis": "100 percent is one logical CPU; interval deltas, not lifetime load",
                "interval_seconds": self.interval,
                "retention": self.retention,
                "max_bytes": self.max_bytes,
                "stored_bytes": self._bytes,
                "dropped_samples": self._dropped,
                "samples": samples,
            }
