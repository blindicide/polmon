#!/usr/bin/env python3
"""Measure the Qt client's cold start and idle memory by launching it repeatedly.

Cold start is the wall time from process launch to the client's ``exposed after`` line (the
main window is on screen), so it includes interpreter start-up, imports and, for a one-file
executable, the bootloader's extraction. Idle RSS is reported by the client after it has been
idle for ``--idle`` seconds. Needs a display (xvfb-run on headless Linux).

Usage: scripts/measure-client.py [--runs 5] [--idle 10] -- COMMAND [ARGS...]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time

RSS = re.compile(r"idle-rss-after-\S+=([\d.]+)MiB")
PLATFORM = re.compile(r"platform=(\S+)")


def measure(command: list[str], idle: float) -> dict[str, object]:
    started = time.perf_counter()
    process = subprocess.Popen(
        [*command, "--smoke-start", str(idle)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    cold = None
    lines = []
    for line in process.stdout:
        lines.append(line.rstrip())
        if cold is None and line.startswith("exposed after"):
            cold = time.perf_counter() - started
    code = process.wait(timeout=idle + 120)
    summary = next((line for line in lines if "smoke-start:" in line), "")
    rss = RSS.search(summary)
    platform = PLATFORM.search(summary)
    return {
        "exit_code": code,
        "cold_start_seconds": None if cold is None else round(cold, 3),
        "idle_rss_mib": float(rss.group(1)) if rss else None,
        "platform": platform.group(1) if platform else None,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--idle", type=float, default=10.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = [item for item in args.command if item != "--"]
    if not command:
        parser.error("give the client command after --")
    runs = [measure(command, args.idle) for _ in range(args.runs)]
    cold = [run["cold_start_seconds"] for run in runs if run["cold_start_seconds"] is not None]
    rss = [run["idle_rss_mib"] for run in runs if run["idle_rss_mib"] is not None]
    result = {
        "command": command,
        "runs": runs,
        "cold_start_seconds": {
            "median": statistics.median(cold) if cold else None,
            "min": min(cold) if cold else None,
            "max": max(cold) if cold else None,
        },
        "idle_rss_mib": {
            "median": statistics.median(rss) if rss else None,
            "min": min(rss) if rss else None,
            "max": max(rss) if rss else None,
        },
    }
    print(json.dumps(result, indent=2))
    return 0 if all(run["exit_code"] == 0 for run in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
