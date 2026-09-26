"""Shared benchmark plumbing: limits, progress, process isolation, and raw result files."""

from __future__ import annotations

import csv
import json
import math
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from polmon.core.errors import PolmonError
from polmon.resources import AdmissionController, ResourceLimits
from polmon.topology.models import Topology
from polmon.version import __version__

SCHEMA_VERSION = 2
DEFAULT_OUTPUT_DIR = Path("benchmarks/results")


class BenchmarkLimitError(PolmonError):
    code = "benchmark_limit"
    status_code = 429


@dataclass(frozen=True, slots=True)
class BenchmarkLimits:
    """Explicit ceilings every benchmark invocation runs under.

    Defaults fit the 2-core / 2 GB engineering budget; larger values must be requested.
    """

    max_endpoints: int = 50
    max_namespaces: int = 4
    max_run_seconds: float = 120.0
    max_incremental_memory_mb: int = 512
    memory_reserve_mb: int = 256

    def admit(self, topology: Topology) -> None:
        """Reject a benchmark topology before anything is created."""
        AdmissionController(
            ResourceLimits(
                max_endpoint_count=self.max_endpoints,
                max_active_namespaces=self.max_namespaces,
                memory_safety_threshold_mb=self.memory_reserve_mb,
            )
        ).admit_topology(topology, [])

    def check_memory(self, row: dict[str, object]) -> None:
        """Stop a suite whose measured growth exceeded the configured ceiling."""
        measured = max(
            int(row.get("incremental_memory_bytes") or 0),
            int(row.get("peak_incremental_memory_bytes") or 0),
        )
        if measured > self.max_incremental_memory_mb * 1_048_576:
            raise BenchmarkLimitError(
                "benchmark run exceeded the incremental memory ceiling",
                details={
                    "measured_mb": round(measured / 1_048_576, 3),
                    "limit_mb": self.max_incremental_memory_mb,
                },
            )


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; ``values`` must not be empty."""
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {}
    return values


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def hardware() -> dict[str, object]:
    """Describe the measuring host without identifying it (no hostname, users, or addresses)."""
    memory = _meminfo()
    return {
        "platform": platform.platform(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu_model": _cpu_model(),
        "python": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "total_memory_bytes": memory.get("MemTotal"),
        "total_swap_bytes": memory.get("SwapTotal"),
        "available_memory_bytes_at_start": memory.get("MemAvailable"),
        "swap_used_bytes_at_start": (
            memory["SwapTotal"] - memory["SwapFree"]
            if "SwapTotal" in memory and "SwapFree" in memory
            else None
        ),
    }


def process_memory_status(pid: int | str = "self") -> dict[str, int]:
    """Return VmRSS / VmHWM for a process in bytes (Linux procfs; empty elsewhere)."""
    result: dict[str, int] = {}
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return result
    for line in text.splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            key, raw = line.split(":", 1)
            result[key] = int(raw.split()[0]) * 1024
    return result


def reset_peak_rss() -> bool:
    """Reset this process's VmHWM so peak memory excludes interpreter start-up (Linux 4.0+)."""
    try:
        Path("/proc/self/clear_refs").write_text("5", encoding="ascii")
    except OSError:
        return False
    return True


def available_memory_bytes() -> int | None:
    return _meminfo().get("MemAvailable")


TERMINATION_GRACE_SECONDS = 20.0


def run_worker(kind: str, params: dict[str, object], *, timeout: float) -> dict[str, object]:
    """Run one measurement in a fresh interpreter so every run starts from a clean baseline.

    A run that exceeds ``timeout`` receives SIGTERM first so its teardown still executes, and is
    killed only if it does not exit within the grace period.
    """
    command = [sys.executable, "-m", "polmon.benchmarks.worker", kind, json.dumps(params)]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            _, stderr = process.communicate(timeout=TERMINATION_GRACE_SECONDS)
            killed = False
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate()
            killed = True
        raise BenchmarkLimitError(
            "benchmark run exceeded its duration limit",
            details={
                "kind": kind,
                "limit_seconds": timeout,
                "terminated_gracefully": not killed,
                "stderr": (stderr or "").strip()[-2_000:],
            },
        ) from None
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        raise BenchmarkLimitError(
            "benchmark worker failed",
            details={
                "kind": kind,
                "returncode": completed.returncode,
                "stderr": completed.stderr.strip()[-2_000:],
            },
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise BenchmarkLimitError("benchmark worker produced no result", details={"kind": kind})
    row = json.loads(lines[-1])
    if not isinstance(row, dict):
        raise BenchmarkLimitError("benchmark worker returned a non-object", details={"kind": kind})
    return row


def source_revision() -> dict[str, object]:
    """Git commit and dirty flag of the measured source tree, when it is a checkout."""
    root = Path(__file__).resolve().parents[3]
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": bool(dirty)}


def document(
    kind: str,
    *,
    workload: dict[str, object],
    limits: BenchmarkLimits,
    limitations: list[str],
    measurements: list[dict[str, object]],
    started_at: datetime,
    status: str = "complete",
    error: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": kind,
        "polmon_version": __version__,
        "source": source_revision(),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "status": status,
        "error": error,
        "workload": workload,
        "limits": asdict(limits),
        "hardware": hardware(),
        "limitations": limitations,
        "measurements": measurements,
    }


def result_prefix(output_dir: Path, kind: str, started_at: datetime) -> Path:
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return output_dir / f"{kind}-{stamp}"


def write_results(prefix: Path, payload: dict[str, object]) -> tuple[Path, Path | None]:
    """Write the raw JSON document and, when rows exist, a flat CSV next to it."""
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(json_path)
    rows = payload.get("measurements")
    if not isinstance(rows, list) or not rows:
        return json_path, None
    csv_path = prefix.with_suffix(".csv")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, dict | list)
                    else value
                    for key, value in row.items()
                }
            )
    return json_path, csv_path


def _proc_stat(pid: int) -> tuple[int, float] | None:
    """Return (parent pid, user+system CPU seconds) for ``pid`` from procfs."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # The command name may contain spaces; fields after the closing parenthesis are fixed.
    fields = raw[raw.rindex(")") + 2 :].split()
    ticks = os.sysconf("SC_CLK_TCK")
    return int(fields[1]), (int(fields[11]) + int(fields[12])) / ticks


def process_tree(roots: list[int]) -> list[int]:
    """Return ``roots`` and all of their live descendants (Linux procfs scan)."""
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            stat = _proc_stat(int(entry.name))
            if stat is not None:
                parents[int(entry.name)] = stat[0]
    tree = [pid for pid in roots if pid in parents]
    index = 0
    while index < len(tree):
        tree.extend(pid for pid, parent in parents.items() if parent == tree[index])
        index += 1
    return tree


def process_tree_usage(roots: list[int]) -> dict[str, float | int]:
    """Sum RSS and CPU seconds over a process tree (e.g. privileged L1 service processes)."""
    pids = process_tree(roots)
    rss = 0
    cpu = 0.0
    for pid in pids:
        rss += process_memory_status(pid).get("VmRSS", 0)
        stat = _proc_stat(pid)
        cpu += stat[1] if stat else 0.0
    return {"process_count": len(pids), "rss_bytes": rss, "cpu_seconds": cpu}
