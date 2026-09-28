"""Synthetic L0 lifecycle, idle, and controlled-traffic measurements (one run per process)."""

from __future__ import annotations

import time
import tracemalloc

from polmon.backends.synthetic.backend import SyntheticBackend
from polmon.backends.synthetic.engine import SyntheticEngineError
from polmon.backends.synthetic.protocols import SyntheticProtocolNetwork
from polmon.benchmarks.common import percentile, process_memory_status, reset_peak_rss
from polmon.core.diagnostics import resource_snapshot
from polmon.orchestration import Orchestrator
from polmon.topology.models import Interface, Network, Node, NodeClass, Topology

DEFAULT_COUNTS = (10, 25, 50)
LARGE_COUNTS = (100, 250)
MAX_COUNT = 250
FIDELITY = "L0 synthetic endpoints sharing one Python process"
LIMITATIONS = [
    "Synthetic L0 endpoints are lightweight protocol state in one shared process; they are not "
    "equivalent to Linux namespaces (L1) or virtual machines (L2) and are never compared as such.",
    "Latency is in-process protocol-engine time (frame encode, validate, dispatch) and excludes "
    "kernel, driver, and physical network latency.",
    "Each run executes in a fresh interpreter; incremental memory is RSS after deployment minus "
    "RSS before topology construction, and peak is VmHWM minus that baseline. Allocator page "
    "granularity makes very small deltas coarse.",
    "CPU utilisation is process CPU time divided by wall time for the whole run on a shared host.",
]


def build_topology(endpoint_count: int) -> Topology:
    if not 2 <= endpoint_count <= MAX_COUNT:
        raise ValueError(f"synthetic benchmark endpoint count must be between 2 and {MAX_COUNT}")
    nodes = [
        Node(
            id=f"node-{index:03d}",
            **{"class": NodeClass.L0},
            interfaces=[
                Interface(
                    id="eth0",
                    network="benchmark",
                    mac=f"02:00:00:01:{index // 256:02x}:{index % 256:02x}",
                    ipv4=f"192.168.239.{index + 1}",
                )
            ],
        )
        for index in range(endpoint_count)
    ]
    return Topology(
        id=f"benchmark-l0-{endpoint_count}",
        networks=[Network(id="benchmark", ipv4_subnet="192.168.239.0/24")],
        nodes=nodes,
    )


def _traffic_round(
    network: SyntheticProtocolNetwork, topology: Topology
) -> tuple[list[float], int, int, float, float]:
    """One ICMP echo from the first endpoint to every other endpoint."""
    source = topology.nodes[0].id
    latencies_ms: list[float] = []
    successes = 0
    attempts = 0
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    for target in topology.nodes[1:]:
        attempts += 1
        started = time.perf_counter()
        try:
            network.ping(source, target.interfaces[0].ipv4)
        except SyntheticEngineError:
            continue
        latencies_ms.append((time.perf_counter() - started) * 1_000)
        successes += 1
    return (
        latencies_ms,
        attempts,
        successes,
        time.perf_counter() - wall_start,
        time.process_time() - cpu_start,
    )


def traced_heap(endpoint_count: int) -> dict[str, int]:
    """Untimed second deployment under tracemalloc: exact Python-heap bytes for the topology."""
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        topology = build_topology(endpoint_count)
        backend = SyntheticBackend()
        control = Orchestrator(topology, backend)
        control.validate()
        control.create()
        control.start()
        deployed, peak = tracemalloc.get_traced_memory()
        control.destroy()
        del control, backend, topology
        after, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "python_heap_deployed_bytes": deployed - before,
        "python_heap_peak_bytes": peak - before,
        "python_heap_residual_bytes": after - before,
    }


def run_once(endpoint_count: int, repeat: int, idle_seconds: float) -> dict[str, object]:
    """Measure one lifecycle in the current process; call from a fresh worker process."""
    peak_tracked = reset_peak_rss()
    baseline = resource_snapshot()
    total_wall_start = time.perf_counter()
    total_cpu_start = time.process_time()

    topology = build_topology(endpoint_count)
    backend = SyntheticBackend()
    control = Orchestrator(topology, backend)
    create_start = time.perf_counter()
    control.validate()
    control.create()
    control.start()
    creation_seconds = time.perf_counter() - create_start
    deployed = resource_snapshot(active_endpoints=endpoint_count)

    idle_cpu_start = time.process_time()
    idle_start = time.perf_counter()
    time.sleep(idle_seconds)
    idle_wall_seconds = time.perf_counter() - idle_start
    idle_cpu_seconds = time.process_time() - idle_cpu_start

    network = SyntheticProtocolNetwork(backend.engine)
    cold = _traffic_round(network, topology)  # includes ARP resolution
    warm = _traffic_round(network, topology)  # ARP cache hits only
    after_traffic = resource_snapshot(active_endpoints=endpoint_count)

    teardown_start = time.perf_counter()
    control.destroy()
    teardown_seconds = time.perf_counter() - teardown_start
    finished = resource_snapshot()
    total_wall_seconds = time.perf_counter() - total_wall_start
    total_cpu_seconds = time.process_time() - total_cpu_start

    stats = backend.engine.stats()
    cleanup_complete = (
        not control.inspect().owned_resources
        and stats.endpoint_count == 0
        and stats.network_count == 0
        and stats.queued_packet_count == 0
        and stats.scheduled_event_count == 0
    )
    peak = process_memory_status().get("VmHWM") if peak_tracked else None
    attempts = cold[1] + warm[1]
    successes = cold[2] + warm[2]
    all_latencies = cold[0] + warm[0]
    heap = traced_heap(endpoint_count)
    return {
        "fidelity": "L0",
        "endpoint_count": endpoint_count,
        "repeat": repeat,
        "baseline_rss_bytes": baseline.process_rss_bytes,
        "incremental_memory_bytes": max(
            0, deployed.process_rss_bytes - baseline.process_rss_bytes
        ),
        "incremental_memory_after_traffic_bytes": max(
            0, after_traffic.process_rss_bytes - baseline.process_rss_bytes
        ),
        "peak_incremental_memory_bytes": (
            max(0, peak - baseline.process_rss_bytes) if peak is not None else None
        ),
        "residual_memory_after_teardown_bytes": max(
            0, finished.process_rss_bytes - baseline.process_rss_bytes
        ),
        **heap,
        "python_heap_bytes_per_endpoint": heap["python_heap_deployed_bytes"] / endpoint_count,
        "cpu_utilization_percent": (
            (total_cpu_seconds / total_wall_seconds) * 100 if total_wall_seconds else 0.0
        ),
        "creation_seconds": creation_seconds,
        "teardown_seconds": teardown_seconds,
        "idle_wall_seconds": idle_wall_seconds,
        "idle_cpu_seconds": idle_cpu_seconds,
        "traffic_attempts": attempts,
        "traffic_successes": successes,
        "packet_loss_percent": ((attempts - successes) / attempts) * 100 if attempts else 0.0,
        "traffic_wall_seconds": cold[3] + warm[3],
        "traffic_cpu_seconds": cold[4] + warm[4],
        "traffic_cpu_microseconds_per_echo": (
            ((cold[4] + warm[4]) / successes) * 1_000_000 if successes else None
        ),
        "latency_cold_mean_ms": sum(cold[0]) / len(cold[0]) if cold[0] else None,
        "latency_warm_mean_ms": sum(warm[0]) / len(warm[0]) if warm[0] else None,
        "latency_p50_ms": percentile(all_latencies, 0.5) if all_latencies else None,
        "latency_p95_ms": percentile(all_latencies, 0.95) if all_latencies else None,
        "latency_max_ms": max(all_latencies) if all_latencies else None,
        "cleanup_complete": cleanup_complete,
    }
