"""Concrete action executors that map closed scenario actions to backend methods."""

from __future__ import annotations

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.scenarios.engine import Observation
from polmon.scenarios.models import ActionKind, ScenarioAction
from polmon.topology.models import Topology


class NamespaceScenarioExecutor:
    def __init__(self, backend: NamespaceBackend) -> None:
        self.backend = backend

    def execute(
        self, action: ScenarioAction, topology: Topology, timeout_seconds: float
    ) -> Observation:
        del timeout_seconds  # Backend probes have stricter internal limits.
        nodes = {node.id: node for node in topology.nodes}
        target = nodes[action.target]
        address = str(target.interfaces[0].ipv4)
        if action.kind is ActionKind.ICMP_PROBE:
            success = self.backend.ping(action.source, address)
            return Observation(
                action.id,
                success,
                "reachable" if success else "unreachable",
                {"protocol": "icmp", "target": action.target},
            )
        service = next(item for item in target.services if item.id == action.service)
        success = self.backend.probe_tcp(action.source, address, service.port)
        return Observation(
            action.id,
            success,
            "reachable" if success else "unreachable",
            {
                "protocol": "tcp",
                "target": action.target,
                "service": service.id,
                "port": service.port,
            },
        )

