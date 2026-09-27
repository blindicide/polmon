"""Configurable workload admission and cooperative memory monitoring."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from threading import Event, Thread

from pydantic import Field

from polmon.core.diagnostics import ResourceSnapshot, resource_snapshot
from polmon.core.errors import PolmonError
from polmon.scenarios.models import Scenario
from polmon.topology.models import StrictModel, Topology


class ResourceLimitError(PolmonError):
    code = "resource_limit"
    status_code = 429


class ResourceLimits(StrictModel):
    max_endpoint_count: int = Field(default=250, ge=1, le=10_000)
    max_active_namespaces: int = Field(default=16, ge=0, le=1_000)
    max_concurrent_experiments: int = Field(default=1, ge=1, le=100)
    max_capture_bytes: int = Field(default=1_048_576, ge=24, le=1_073_741_824)
    max_experiment_duration_seconds: float = Field(default=300, gt=0, le=86_400)
    memory_safety_threshold_mb: int = Field(default=256, ge=0, le=1_048_576)
    monitor_interval_seconds: float = Field(default=0.25, gt=0, le=60)
    # Experiment artefacts (telemetry, captures, reports) are never deleted automatically; new
    # experiments are refused instead once either storage bound would be crossed.
    max_data_directory_mb: int = Field(default=1_024, ge=1, le=10_485_760)
    disk_free_reserve_mb: int = Field(default=512, ge=0, le=10_485_760)


class AdmissionController:
    def __init__(
        self,
        limits: ResourceLimits,
        *,
        snapshot: Callable[[], ResourceSnapshot] = resource_snapshot,
    ) -> None:
        self.limits = limits
        self.snapshot = snapshot

    def admit_topology(self, topology: Topology, deployed: Iterable[Topology]) -> None:
        estimates = [item.estimate_resources() for item in deployed]
        requested = topology.estimate_resources()
        projected_endpoints = (
            sum(item.endpoint_count for item in estimates) + requested.endpoint_count
        )
        projected_namespaces = (
            sum(item.l1_namespaces for item in estimates) + requested.l1_namespaces
        )
        projected_memory_mb = sum(item.memory_mb for item in estimates) + requested.memory_mb
        violations: dict[str, object] = {}
        if projected_endpoints > self.limits.max_endpoint_count:
            violations["endpoint_count"] = {
                "projected": projected_endpoints,
                "limit": self.limits.max_endpoint_count,
            }
        if projected_namespaces > self.limits.max_active_namespaces:
            violations["active_namespaces"] = {
                "projected": projected_namespaces,
                "limit": self.limits.max_active_namespaces,
            }
        available = self.snapshot().available_memory_bytes
        required_memory_mb = projected_memory_mb + self.limits.memory_safety_threshold_mb
        if available is not None and required_memory_mb * 1_048_576 > available:
            violations["available_memory"] = {
                "required_mb_including_reserve": required_memory_mb,
                "available_mb": available // 1_048_576,
            }
        if violations:
            raise ResourceLimitError(
                "topology exceeds configured resource limits", details=violations,
                message_code="admission.topology_limits",
            )

    def admit_experiment(
        self, scenario: Scenario, active_count: int, *, data_directory: Path | None = None
    ) -> None:
        violations: dict[str, object] = {}
        if data_directory is not None:
            violations.update(self._storage_violations(data_directory))
        if active_count >= self.limits.max_concurrent_experiments:
            violations["concurrent_experiments"] = {
                "active": active_count,
                "limit": self.limits.max_concurrent_experiments,
            }
        if scenario.timeout_seconds > self.limits.max_experiment_duration_seconds:
            violations["duration_seconds"] = {
                "requested": scenario.timeout_seconds,
                "limit": self.limits.max_experiment_duration_seconds,
            }
        if violations:
            raise ResourceLimitError(
                "experiment exceeds configured resource limits", details=violations,
                message_code="admission.experiment_limits",
            )


    def _storage_violations(self, data_directory: Path) -> dict[str, object]:
        """Room for one more experiment: its capture ceiling fits both storage bounds."""
        violations: dict[str, object] = {}
        needed = self.limits.max_capture_bytes
        used = directory_size_bytes(data_directory)
        limit = self.limits.max_data_directory_mb * 1_048_576
        if used + needed > limit:
            violations["data_directory"] = {
                "used_mb": round(used / 1_048_576, 1),
                "next_experiment_capture_limit_mb": round(needed / 1_048_576, 1),
                "limit_mb": self.limits.max_data_directory_mb,
            }
        free = shutil.disk_usage(data_directory).free
        reserve = self.limits.disk_free_reserve_mb * 1_048_576
        if free - needed < reserve:
            violations["disk_free"] = {
                "free_mb": free // 1_048_576,
                "reserve_mb": self.limits.disk_free_reserve_mb,
            }
        return violations


def directory_size_bytes(path: Path) -> int:
    """Apparent size of all regular files below ``path`` (symlinks are not followed)."""
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                continue
    return total


class ResourceMonitor:
    """Sample available memory and invoke cooperative cancellation below reserve."""

    def __init__(
        self,
        limits: ResourceLimits,
        on_limit: Callable[[str, ResourceSnapshot], None],
        *,
        on_sample: Callable[[ResourceSnapshot], None] | None = None,
        snapshot: Callable[[], ResourceSnapshot] = resource_snapshot,
    ) -> None:
        self.limits = limits
        self.on_limit = on_limit
        self.on_sample = on_sample
        self.snapshot = snapshot
        self._stop = Event()
        self._thread: Thread | None = None

    def sample_once(self) -> bool:
        sample = self.snapshot()
        if self.on_sample is not None:
            self.on_sample(sample)
        available = sample.available_memory_bytes
        threshold = self.limits.memory_safety_threshold_mb * 1_048_576
        if available is not None and available < threshold:
            self.on_limit("available memory fell below the configured reserve", sample)
            return False
        return True

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("resource monitor is already running")
        self._stop.clear()
        self._thread = Thread(target=self._run, name="polmon-resource-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.limits.monitor_interval_seconds * 2))
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.sample_once():
                return
            self._stop.wait(self.limits.monitor_interval_seconds)
