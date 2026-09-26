"""Lifecycle adapter for all-L0 topologies."""

from __future__ import annotations

from dataclasses import asdict

from polmon.backends.synthetic.engine import SyntheticEngine
from polmon.orchestration.base import BackendInspection
from polmon.topology.models import NodeClass, Topology


class SyntheticBackend:
    name = "synthetic"

    def __init__(self, *, max_endpoints: int = 1_000) -> None:
        self.engine = SyntheticEngine(max_endpoints=max_endpoints)
        self.running = False

    def validate(self, topology: Topology) -> None:
        unsupported = [node.id for node in topology.nodes if node.node_class is not NodeClass.L0]
        if unsupported:
            raise ValueError(f"synthetic backend cannot create non-L0 nodes: {unsupported}")
        if len(topology.nodes) > self.engine.max_endpoints:
            raise ValueError("topology exceeds synthetic endpoint limit")

    def create(self, topology: Topology) -> set[str]:
        resources: set[str] = set()
        try:
            for node in topology.nodes:
                interface = node.interfaces[0]
                self.engine.create_endpoint(
                    node.id,
                    network=interface.network,
                    mac=interface.mac,
                    ipv4=interface.ipv4,
                )
                resources.add(f"synthetic:{topology.id}:{node.id}")
        except Exception:
            self.engine.destroy_all()
            raise
        return resources

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def destroy(self) -> None:
        self.running = False
        self.engine.destroy_all()

    def inspect(self) -> BackendInspection:
        stats = self.engine.stats()
        return BackendInspection(
            backend=self.name,
            resources=frozenset(f"endpoint:{item}" for item in self.engine.endpoints),
            details={"running": self.running, "stats": asdict(stats)},
        )
