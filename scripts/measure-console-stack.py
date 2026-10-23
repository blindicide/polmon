#!/usr/bin/env python3
"""Measure the memory of the interactive console stack with a real backend and a real lab.

Starts the backend on a fresh data directory, deploys `examples/topologies/l1-console.yml` (two
L1 nodes with sshd, one with the built-in HTTP service), then starts a VNC display on every node.
The processes inside each namespace are sampled after deployment and again with the displays
running: RSS for every process, PSS where /proc allows it (processes running as this user; root
`sshd` is RSS only). Writes one raw JSON document. Privileged lab: run it through
`scripts/privileged-tests.sh -- .venv/bin/python scripts/measure-console-stack.py`.

Usage: scripts/measure-console-stack.py [--output-dir benchmarks/results] [--settle 3]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples/topologies/l1-console.yml"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def status_bytes(pid: int, name: str, field: str) -> int | None:
    try:
        lines = Path(f"/proc/{pid}/{name}").read_text().splitlines()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    return next((int(line.split()[1]) * 1024 for line in lines if line.startswith(field)), None)


def process(pid: int) -> dict[str, object]:
    try:
        command = Path(f"/proc/{pid}/comm").read_text().strip()
    except FileNotFoundError:
        command = None
    return {
        "pid": pid,
        "command": command,
        "rss_bytes": status_bytes(pid, "status", "VmRSS:"),
        "pss_bytes": status_bytes(pid, "smaps_rollup", "Pss:"),
    }


def namespace_processes(namespace: str) -> list[dict[str, object]]:
    listed = subprocess.run(
        ["sudo", "-n", "ip", "netns", "pids", namespace],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted((process(int(pid)) for pid in listed.split()), key=lambda item: str(item))


def host() -> dict[str, object]:
    memory = Path("/proc/meminfo").read_text().splitlines()
    cpu = next(
        (line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
         if line.startswith("model name")),
        None,
    )
    return {
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "memory_total_bytes": int(memory[0].split()[1]) * 1024,
        "kernel": platform.release(),
        "python": platform.python_version(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "benchmarks/results")
    parser.add_argument("--settle", type=float, default=3.0)
    args = parser.parse_args()
    port = free_port()

    def call(method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    started = datetime.now(UTC)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        ).stdout.strip()
    )
    with tempfile.TemporaryDirectory(prefix="polmon-console-stack-") as directory:
        backend = subprocess.Popen(
            [sys.executable, "-m", "polmon.backend", "--port", str(port)],
            cwd=directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(150):
                try:
                    call("GET", "/v1/health")
                    break
                except OSError:
                    time.sleep(0.1)
            idle = process(backend.pid)
            topology = call("POST", "/v1/topologies", {"yaml": TOPOLOGY.read_text()})
            deployment = call("POST", f"/v1/deployments/{topology['topology_id']}")
            namespaces = {
                item.split(":", 1)[1]
                for item in deployment["resources"]
                if item.startswith("netns:")
            }
            time.sleep(args.settle)
            deployed = {name: namespace_processes(name) for name in sorted(namespaces)}
            nodes = [node["id"] for node in topology["topology"]["nodes"]]
            for node in nodes:
                call("POST", f"/v1/deployments/{topology['topology_id']}/nodes/{node}/console/vnc")
            time.sleep(args.settle)
            with_vnc = {name: namespace_processes(name) for name in sorted(namespaces)}
            backend_vnc = process(backend.pid)
            call("POST", "/v1/reset")
        finally:
            backend.terminate()
            backend.wait(timeout=60)
    result = {
        "kind": "console-stack",
        "polmon_commit": commit,
        "dirty_tree": dirty,
        "started": started.isoformat(),
        "host": host(),
        "workload": {
            "topology": str(TOPOLOGY.relative_to(ROOT)),
            "vnc_displays": len(nodes),
            "settle_seconds": args.settle,
            "display": "Xvfb 1024x768x24 + x11vnc + xclock per node",
        },
        "backend_idle": idle,
        "backend_with_vnc": backend_vnc,
        "namespaces_deployed": deployed,
        "namespaces_with_vnc": with_vnc,
        "limitations": [
            "RSS counts shared library pages in every process; PSS splits them, but is "
            "unreadable for processes running as root (sshd), whose PSS is null.",
            "One measurement on one host is evidence for this host and configuration only.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"console-stack-{started:%Y%m%dT%H%M%SZ}.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"JSON: {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
