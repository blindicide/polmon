"""Phase I engineering target: 50 L0 endpoints plus two L1 service endpoints, one lab network."""

from __future__ import annotations

import time

from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.namespace.runner import CommandRunner
from polmon.backends.synthetic.engine import SyntheticEngineError
from polmon.backends.synthetic.protocols import SyntheticProtocolNetwork
from polmon.benchmarks.common import (
    available_memory_bytes,
    percentile,
    process_memory_status,
    process_tree_usage,
    reset_peak_rss,
)
from polmon.benchmarks.l1 import remaining_lab_resources, wait_for_service
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

TARGET_INCREMENTAL_BYTES = 1_073_741_824  # "approximately 1 GB" from the specification
FIDELITY = "hybrid: L0 synthetic endpoints and L1 namespaces bridged through one shared TAP"
LIMITATIONS = [
    "Attributed incremental memory = control-process RSS growth + L1 service process-tree RSS. "
    "Kernel memory for namespaces, veths, the bridge, and the TAP is not attributable to a "
    "process; the host MemAvailable delta is reported beside it as a noisy upper-bound "
    "indicator influenced by unrelated host activity.",
    "L0-to-L1 echoes cross the TAP boundary through the synthetic protocol engine; L0-to-L0 "
    "echoes stay in-process; L1-to-L1 echoes use the kernel. The three latencies measure "
    "different paths and are not equivalent.",
    "One measurement on one host is evidence for this host and configuration only.",
]


def build_topology(l0_count: int = 50, l1_count: int = 2) -> Topology:
    if not 1 <= l0_count <= 200:
        raise ValueError("target benchmark L0 count must be between 1 and 200")
    if not 2 <= l1_count <= 8:
        raise ValueError("target benchmark L1 count must be between 2 and 8")
    nodes = [
        Node(
            id=f"l0-{index:03d}",
            **{"class": NodeClass.L0},
            interfaces=[
                Interface(
                    id="eth0",
                    network="lab",
                    mac=f"02:00:00:03:00:{index:02x}",
                    ipv4=f"192.168.240.{index + 10}",
                )
            ],
        )
        for index in range(l0_count)
    ]
    nodes += [
        Node(
            id=f"l1-{index:02d}",
            **{"class": NodeClass.L1},
            interfaces=[
                Interface(
                    id="eth0",
                    network="lab",
                    mac=f"02:00:00:03:01:{index:02x}",
                    ipv4=f"192.168.240.{index + 220}",
                )
            ],
            services=[
                ServiceDefinition(
                    id="web", protocol="tcp", port=8080, implementation="static_http"
                )
            ],
        )
        for index in range(l1_count)
    ]
    return Topology(
        id=f"benchmark-target-{l0_count}-{l1_count}",
        networks=[Network(id="lab", ipv4_subnet="192.168.240.0/24")],
        nodes=nodes,
    )


def _timed(callback) -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        ok = bool(callback())
    except SyntheticEngineError:
        ok = False
    return ok, (time.perf_counter() - started) * 1_000


def run_once(l0_count: int, l1_count: int, repeat: int, idle_seconds: float) -> dict[str, object]:
    topology = build_topology(l0_count, l1_count)
    runner = CommandRunner()
    backend = HybridBackend(runner=runner)
    control = Orchestrator(topology, backend)
    l0 = [node for node in topology.nodes if node.node_class is NodeClass.L0]
    l1 = [node for node in topology.nodes if node.node_class is NodeClass.L1]
    host_before = available_memory_bytes()
    peak_tracked = reset_peak_rss()
    baseline = resource_snapshot()
    row: dict[str, object] = {
        "fidelity": "hybrid",
        "l0_count": l0_count,
        "l1_count": l1_count,
        "repeat": repeat,
    }
    tap_names: list[str] = []
    try:
        started = time.perf_counter()
        control.validate()
        control.create()
        tap_names = list(backend.tap_names.values())
        control.start()
        row["deployment_seconds"] = time.perf_counter() - started
        # Probe every L1 service from the next L1 namespace over the lab bridge.
        ready = [
            wait_for_service(
                backend.namespace,
                l1[(index + 1) % len(l1)].id,
                str(node.interfaces[0].ipv4),
                8080,
                timeout=10,
            )
            for index, node in enumerate(l1)
        ]
        row["l1_services_reachable"] = sum(item is not None for item in ready)
        row["l1_services_declared"] = len(l1)
        row["service_ready_seconds"] = (
            max(ready) if all(item is not None for item in ready) else None
        )

        roots = [process.pid for process in backend.namespace.services.values()]
        before_idle = process_tree_usage(roots)
        cpu_before = time.process_time()
        time.sleep(idle_seconds)
        row["idle_seconds"] = idle_seconds
        row["controller_idle_cpu_seconds"] = time.process_time() - cpu_before
        after_idle = process_tree_usage(roots)
        row["service_idle_cpu_seconds"] = max(
            0.0, float(after_idle["cpu_seconds"]) - float(before_idle["cpu_seconds"])
        )

        # L0 -> L1 across the TAP boundary, from every L0 endpoint to alternating L1 targets.
        hybrid_latencies: list[float] = []
        hybrid_ok = 0
        for index, node in enumerate(l0):
            target = str(l1[index % len(l1)].interfaces[0].ipv4)
            ok, elapsed = _timed(lambda n=node, t=target: backend.ping_l1(n.id, t, timeout=2.0))
            hybrid_ok += int(ok)
            if ok:
                hybrid_latencies.append(elapsed)
        row["l0_to_l1_attempts"] = len(l0)
        row["l0_to_l1_successes"] = hybrid_ok
        row["l0_to_l1_loss_percent"] = ((len(l0) - hybrid_ok) / len(l0)) * 100
        row["l0_to_l1_latency_p50_ms"] = (
            percentile(hybrid_latencies, 0.5) if hybrid_latencies else None
        )
        row["l0_to_l1_latency_p95_ms"] = (
            percentile(hybrid_latencies, 0.95) if hybrid_latencies else None
        )

        # L0 -> L0 inside the synthetic engine.
        network = SyntheticProtocolNetwork(backend.synthetic.engine)
        synthetic_latencies: list[float] = []
        synthetic_ok = 0
        for node in l0[1:]:
            ok, elapsed = _timed(
                lambda n=node: network.ping(l0[0].id, n.interfaces[0].ipv4) is not None
            )
            synthetic_ok += int(ok)
            if ok:
                synthetic_latencies.append(elapsed)
        attempts = max(1, len(l0) - 1)
        row["l0_to_l0_attempts"] = len(l0) - 1
        row["l0_to_l0_successes"] = synthetic_ok
        row["l0_to_l0_loss_percent"] = ((len(l0) - 1 - synthetic_ok) / attempts) * 100
        row["l0_to_l0_latency_p50_ms"] = (
            percentile(synthetic_latencies, 0.5) if synthetic_latencies else None
        )

        # L1 -> L1 through the kernel bridge.
        stats = backend.namespace.ping_statistics(
            l1[0].id, str(l1[1].interfaces[0].ipv4), count=5, interval=0.2
        )
        row.update({f"l1_to_l1_{key}": value for key, value in stats.items()})

        deployed = resource_snapshot()
        peak = process_memory_status().get("VmHWM") if peak_tracked else None
        host_deployed = available_memory_bytes()
        controller = max(0, deployed.process_rss_bytes - baseline.process_rss_bytes)
        services = int(after_idle["rss_bytes"])
        row["controller_incremental_rss_bytes"] = controller
        row["controller_peak_incremental_bytes"] = (
            max(0, peak - baseline.process_rss_bytes) if peak is not None else None
        )
        row["service_process_count"] = after_idle["process_count"]
        row["service_tree_rss_bytes"] = services
        row["attributed_incremental_memory_bytes"] = controller + services
        row["host_available_memory_delta_bytes"] = (
            host_before - host_deployed
            if host_before is not None and host_deployed is not None
            else None
        )
        row["target_incremental_bytes"] = TARGET_INCREMENTAL_BYTES
        row["within_target_attributed"] = controller + services <= TARGET_INCREMENTAL_BYTES
        row["within_target_host_delta"] = (
            row["host_available_memory_delta_bytes"] <= TARGET_INCREMENTAL_BYTES
            if isinstance(row["host_available_memory_delta_bytes"], int)
            else None
        )
    finally:
        started = time.perf_counter()
        control.destroy()
        row["teardown_seconds"] = time.perf_counter() - started
        leftovers = remaining_lab_resources(backend.namespace, runner)
        links = runner.run(["ip", "-o", "link", "show"], check=False).stdout
        leftovers += [name for name in tap_names if f" {name}:" in links]
        row["remaining_lab_resources"] = leftovers
        row["cleanup_complete"] = not leftovers and not control.inspect().owned_resources
    return row
