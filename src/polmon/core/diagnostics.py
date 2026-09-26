"""Secret-free platform and resource diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from polmon.version import __version__


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """Small resource sample using the standard library and Linux procfs."""

    process_rss_bytes: int
    process_cpu_seconds: float
    process_cpu_percent: float | None
    available_memory_bytes: int | None
    swap_used_bytes: int | None
    active_endpoints: int = 0
    active_namespaces: int = 0
    topology_deployment_seconds: float | None = None


def _proc_memory() -> tuple[int | None, int | None]:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None, None
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return None, None
    available = values.get("MemAvailable")
    swap_used = None
    if "SwapTotal" in values and "SwapFree" in values:
        swap_used = max(0, values["SwapTotal"] - values["SwapFree"])
    return available, swap_used


def _process_cpu_percent() -> float | None:
    """Calculate average CPU utilization over this process lifetime on Linux."""
    try:
        fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        ticks_per_second = os.sysconf("SC_CLK_TCK")
        cpu_seconds = (int(fields[13]) + int(fields[14])) / ticks_per_second
        elapsed = uptime - (int(fields[21]) / ticks_per_second)
        return round((cpu_seconds / elapsed) * 100, 3) if elapsed > 0 else 0.0
    except (OSError, ValueError, IndexError):
        return None


def resource_snapshot(**counts: int | float | None) -> ResourceSnapshot:
    """Capture the current process and host memory state without subprocesses."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # Linux reports KiB; macOS reports bytes. Python 3.12 exposes no portable discriminator.
    rss = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    available, swap_used = _proc_memory()
    return ResourceSnapshot(
        process_rss_bytes=rss,
        process_cpu_seconds=usage.ru_utime + usage.ru_stime,
        process_cpu_percent=_process_cpu_percent(),
        available_memory_bytes=available,
        swap_used_bytes=swap_used,
        active_endpoints=int(counts.get("active_endpoints") or 0),
        active_namespaces=int(counts.get("active_namespaces") or 0),
        topology_deployment_seconds=counts.get("topology_deployment_seconds"),
    )


def collect_diagnostics() -> dict[str, object]:
    """Return an allow-listed diagnostic document that cannot include environment secrets."""
    tool_names = ("ip", "ping", "tcpdump", "qemu-system-x86_64")
    tools = {name: shutil.which(name) is not None for name in tool_names}
    return {
        "polmon_version": __version__,
        "python_version": platform.python_version(),
        "python_supported": sys.version_info[:2] == (3, 12),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "capabilities": {
            "procfs": Path("/proc").is_dir(),
            "network_namespaces": Path("/proc/self/ns/net").exists(),
            "tools": tools,
        },
        "resources": asdict(resource_snapshot()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="display secret-free polmon diagnostics")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    parser.add_argument("--json", action="store_true", help="emit compact machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diagnostics = collect_diagnostics()
    print(json.dumps(diagnostics, indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
