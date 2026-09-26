"""Privileged L1 (Linux network namespace) lifecycle, service, and ping measurements."""

from __future__ import annotations

import shutil
import subprocess
import time

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.namespace.runner import CommandRunner
from polmon.benchmarks.common import available_memory_bytes, process_tree_usage
from polmon.core.diagnostics import resource_snapshot
from polmon.orchestration import Orchestrator
from polmon.topology.models import (
    Interface,
    Network,
    Node,
    NodeClass,
    ServiceDefinition,
    Topology,
)

MAX_NAMESPACES = 8
FIDELITY = "L1 Linux network namespaces with veth pairs on an isolated bridge"
LIMITATIONS = [
    "L1 endpoints are real kernel network namespaces; their kernel memory (netns, veth, bridge, "
    "sockets) is not attributed to any process. It is approximated by the host MemAvailable "
    "delta, which also moves with unrelated host activity and is therefore reported separately "
    "and never used as a precise figure.",
    "Service memory is the summed RSS of the privileged launcher and service process tree "
    "(sudo, setpriv, Python http.server); it is dominated by the interpreter, not by networking.",
    "RTT is kernel ICMP echo round trip between namespaces through one Linux bridge on the same "
    "host, measured by iputils ping; it is not comparable to L0 in-process latency.",
    "Requires passwordless sudo restricted to laboratory networking; otherwise NOT RUN.",
]


def namespace_environment_available() -> tuple[bool, str]:
    for tool in ("ip", "sudo", "setpriv", "ping"):
        if shutil.which(tool) is None:
            return False, f"required tool '{tool}' is not installed"
    try:
        result = subprocess.run(
            ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"sudo probe failed: {error}"
    if result.returncode != 0:
        return False, "passwordless sudo for 'ip netns' is not available"
    return True, "available"


def build_topology(namespace_count: int, *, service_count: int = 1) -> Topology:
    if not 2 <= namespace_count <= MAX_NAMESPACES:
        raise ValueError(f"L1 benchmark namespace count must be between 2 and {MAX_NAMESPACES}")
    if not 0 <= service_count <= namespace_count - 1:
        raise ValueError("L1 benchmark needs one client namespace without a service")
    nodes = []
    for index in range(namespace_count):
        serves = index >= namespace_count - service_count
        nodes.append(
            Node(
                id=f"l1-{index:02d}",
                **{"class": NodeClass.L1},
                interfaces=[
                    Interface(
                        id="eth0",
                        network="bench",
                        mac=f"02:00:00:02:00:{index:02x}",
                        ipv4=f"10.241.0.{index + 10}",
                    )
                ],
                services=(
                    [
                        ServiceDefinition(
                            id="web", protocol="tcp", port=8080, implementation="static_http"
                        )
                    ]
                    if serves
                    else []
                ),
            )
        )
    return Topology(
        id=f"benchmark-l1-{namespace_count}",
        networks=[Network(id="bench", ipv4_subnet="10.241.0.0/24")],
        nodes=nodes,
    )


def remaining_lab_resources(backend: NamespaceBackend, runner: CommandRunner) -> list[str]:
    """Names this run created that the kernel still reports after teardown."""
    if backend.names is None:
        return []
    namespaces = runner.run(["ip", "netns", "list"], privileged=True).stdout
    links = runner.run(["ip", "-o", "link", "show"], check=False).stdout
    remaining = [name for name in backend.names.namespaces.values() if name in namespaces]
    remaining += [name for name in backend.names.bridges.values() if f" {name}:" in links]
    remaining += [
        name
        for name in [*backend.names.host_veths.values(), *backend.names.peer_veths.values()]
        if f" {name}@" in links or f" {name}:" in links
    ]
    return remaining


def wait_for_service(
    backend: NamespaceBackend, source: str, address: str, port: int, *, timeout: float = 10.0
) -> float | None:
    started = time.perf_counter()
    deadline = started + timeout
    while time.perf_counter() < deadline:
        if backend.probe_tcp(source, address, port):
            return time.perf_counter() - started
        time.sleep(0.05)
    return None


def run_once(
    namespace_count: int, repeat: int, idle_seconds: float, ping_count: int
) -> dict[str, object]:
    """Measure one L1 lifecycle; always tears down, even when a measurement fails."""
    topology = build_topology(namespace_count)
    runner = CommandRunner()
    backend = NamespaceBackend(runner=runner)
    control = Orchestrator(topology, backend)
    client = topology.nodes[0]
    servers = [node for node in topology.nodes if node.services]
    peer = topology.nodes[1]
    host_before = available_memory_bytes()
    baseline = resource_snapshot()
    row: dict[str, object] = {"fidelity": "L1", "namespace_count": namespace_count}
    row["repeat"] = repeat
    try:
        started = time.perf_counter()
        control.validate()
        control.create()
        row["creation_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        control.start()
        row["service_start_seconds"] = time.perf_counter() - started
        ready = [
            wait_for_service(backend, client.id, str(server.interfaces[0].ipv4), 8080)
            for server in servers
        ]
        row["service_ready_seconds"] = max(ready) if all(r is not None for r in ready) else None
        row["services_reachable"] = sum(item is not None for item in ready)
        row["services_declared"] = len(servers)
        roots = [process.pid for process in backend.services.values()]
        before_idle = process_tree_usage(roots)
        time.sleep(idle_seconds)
        after_idle = process_tree_usage(roots)
        row["service_process_count"] = after_idle["process_count"]
        row["service_tree_rss_bytes"] = after_idle["rss_bytes"]
        row["service_idle_cpu_seconds"] = max(
            0.0, float(after_idle["cpu_seconds"]) - float(before_idle["cpu_seconds"])
        )
        row["idle_seconds"] = idle_seconds
        host_deployed = available_memory_bytes()
        row["host_available_memory_delta_bytes"] = (
            host_before - host_deployed
            if host_before is not None and host_deployed is not None
            else None
        )
        row["controller_incremental_rss_bytes"] = max(
            0, resource_snapshot().process_rss_bytes - baseline.process_rss_bytes
        )
        stats = backend.ping_statistics(
            client.id, str(peer.interfaces[0].ipv4), count=ping_count, interval=0.2
        )
        row.update({f"ping_{key}": value for key, value in stats.items()})
    finally:
        started = time.perf_counter()
        control.destroy()
        row["teardown_seconds"] = time.perf_counter() - started
        leftovers = remaining_lab_resources(backend, runner)
        row["remaining_lab_resources"] = leftovers
        row["cleanup_complete"] = not leftovers and not control.inspect().owned_resources
    return row
