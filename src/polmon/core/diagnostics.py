"""Secret-free platform and resource diagnostics."""

from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from polmon.version import __version__


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """Small resource sample: Linux procfs, or the Win32 API through ctypes on Windows."""

    process_rss_bytes: int
    process_cpu_seconds: float
    process_cpu_percent: float | None
    available_memory_bytes: int | None
    swap_used_bytes: int | None
    active_endpoints: int = 0
    active_namespaces: int = 0
    topology_deployment_seconds: float | None = None


def _windows_available_memory() -> int | None:
    """Physical memory available to new allocations (``GlobalMemoryStatusEx``)."""
    from ctypes import wintypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.DWORD),
            ("memory_load", wintypes.DWORD),
            ("total_phys", ctypes.c_uint64),
            ("avail_phys", ctypes.c_uint64),
            ("total_page_file", ctypes.c_uint64),
            ("avail_page_file", ctypes.c_uint64),
            ("total_virtual", ctypes.c_uint64),
            ("avail_virtual", ctypes.c_uint64),
            ("avail_extended_virtual", ctypes.c_uint64),
        ]

    status = MemoryStatusEx()
    status.length = ctypes.sizeof(status)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    return int(status.avail_phys) if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None


def _proc_memory() -> tuple[int | None, int | None]:
    if sys.platform == "win32":
        # Windows has no swap partition to report (the page file backs committed memory, which
        # is not the same figure), so only availability is given; admission then enforces its
        # memory reserve on Windows too.
        return _windows_available_memory(), None
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


def _windows_process_cpu_percent() -> float | None:
    """Average CPU utilization over this process lifetime (``GetProcessTimes``)."""
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetSystemTimeAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel32.GetProcessTimes(
        kernel32.GetCurrentProcess(), *[ctypes.byref(item) for item in times]
    ):
        return None
    now = wintypes.FILETIME()
    kernel32.GetSystemTimeAsFileTime(ctypes.byref(now))

    def ticks(value: wintypes.FILETIME) -> int:  # 100 ns units
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    creation, _exit, kernel, user = times
    elapsed = ticks(now) - ticks(creation)
    return round((ticks(kernel) + ticks(user)) / elapsed * 100, 3) if elapsed > 0 else 0.0


def _process_cpu_percent() -> float | None:
    """Calculate average CPU utilization over this process lifetime (Linux procfs, Windows)."""
    if sys.platform == "win32":
        return _windows_process_cpu_percent()
    try:
        fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        ticks_per_second = os.sysconf("SC_CLK_TCK")
        cpu_seconds = (int(fields[13]) + int(fields[14])) / ticks_per_second
        elapsed = uptime - (int(fields[21]) / ticks_per_second)
        return round((cpu_seconds / elapsed) * 100, 3) if elapsed > 0 else 0.0
    except (OSError, ValueError, IndexError):
        return None


def _process_rss_bytes() -> int:
    """Return current resident memory using a platform-native standard-library path."""
    if sys.platform.startswith("linux"):
        try:
            resident_pages = int(Path("/proc/self/statm").read_text(encoding="utf-8").split()[1])
            return resident_pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return 0
    if sys.platform == "win32":
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("page_fault_count", wintypes.DWORD),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        win_dll = ctypes.WinDLL  # type: ignore[attr-defined]
        kernel32 = win_dll("kernel32", use_last_error=True)
        psapi = win_dll("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        success = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return int(counters.working_set_size) if success else 0
    try:
        usage = importlib.import_module("resource").getrusage(0)
        return int(usage.ru_maxrss) if sys.platform == "darwin" else int(usage.ru_maxrss) * 1024
    except (ImportError, AttributeError, OSError):
        return 0


def resource_snapshot(**counts: int | float | None) -> ResourceSnapshot:
    """Capture the current process and host memory state without subprocesses."""
    available, swap_used = _proc_memory()
    return ResourceSnapshot(
        process_rss_bytes=_process_rss_bytes(),
        process_cpu_seconds=time.process_time(),
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


def _file_capabilities(path: str | None) -> str | None:
    """Read ``security.capability`` via getcap when available (e.g. ping's cap_net_raw)."""
    getcap = shutil.which("getcap")
    if path is None or getcap is None:
        return None
    try:
        output = subprocess.run(
            [getcap, path], capture_output=True, text=True, timeout=5, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return output.split(" ", 1)[1] if " " in output else ""


def lab_readiness(
    *, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> dict[str, object]:
    """Read-only checks that the privileged laboratory (L1/hybrid) can run on this host.

    Nothing is created: the only privileged call is ``sudo -n ip netns list``.
    """
    tools = {name: shutil.which(name) for name in ("ip", "sudo", "setpriv", "ping")}
    checks: dict[str, dict[str, object]] = {}
    for name, path in tools.items():
        checks[f"tool_{name}"] = {"ok": path is not None, "detail": path or "not installed"}
    checks["tun_device"] = {
        "ok": Path("/dev/net/tun").exists(),
        "detail": "/dev/net/tun (hybrid TAP boundary)",
    }
    capabilities = _file_capabilities(tools["ping"])
    ping_ok = capabilities is None or "cap_net_raw" in capabilities
    checks["ping_unprivileged"] = {
        "ok": ping_ok,
        "detail": capabilities if capabilities is not None else "getcap unavailable; not verified",
    }
    if tools["sudo"] and tools["ip"]:
        try:
            probe = run(
                ["sudo", "-n", "ip", "netns", "list"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            sudo_ok = probe.returncode == 0
            detail = "passwordless sudo for ip" if sudo_ok else "sudo -n ip netns list failed"
        except (OSError, subprocess.SubprocessError) as error:
            sudo_ok, detail = False, f"sudo probe failed: {type(error).__name__}"
    else:
        sudo_ok, detail = False, "sudo or ip missing"
    checks["passwordless_sudo_ip"] = {"ok": sudo_ok, "detail": detail}
    return {"ready": all(bool(item["ok"]) for item in checks.values()), "checks": checks}


def fidelity_readiness() -> dict[str, object]:
    """Summarize which privileged Linux fidelity levels the host can actually provide."""
    lab = lab_readiness()
    checks = lab["checks"]
    assert isinstance(checks, dict)
    l1_names = (
        "tool_ip",
        "tool_sudo",
        "tool_setpriv",
        "tool_ping",
        "ping_unprivileged",
        "passwordless_sudo_ip",
    )
    l1_ready = all(bool(checks[name]["ok"]) for name in l1_names)  # type: ignore[index]
    hybrid_ready = l1_ready and bool(checks["tun_device"]["ok"])  # type: ignore[index]
    return {"l1_ready": l1_ready, "hybrid_ready": hybrid_ready, "checks": checks}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="display secret-free polmon diagnostics")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    parser.add_argument("--json", action="store_true", help="emit compact machine-readable JSON")
    parser.add_argument(
        "--lab",
        action="store_true",
        help="also check privileged-lab readiness (read-only); exit 1 when not ready",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diagnostics = collect_diagnostics()
    status = 0
    if args.lab:
        readiness = lab_readiness()
        diagnostics["lab"] = readiness
        status = 0 if readiness["ready"] else 1
    print(json.dumps(diagnostics, indent=None if args.json else 2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
