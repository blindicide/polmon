"""Concrete action executors that map closed scenario actions to backend methods."""

from __future__ import annotations

import time

from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.synthetic.engine import SyntheticEngineError
from polmon.backends.synthetic.protocols import SyntheticProtocolNetwork
from polmon.scenarios.catalog import command_argv
from polmon.scenarios.engine import Observation
from polmon.scenarios.models import ActionKind, ScenarioAction
from polmon.topology.models import NodeClass, Topology


class NamespaceScenarioExecutor:
    def __init__(self, backend: NamespaceBackend) -> None:
        self.backend = backend

    def execute(
        self, action: ScenarioAction, topology: Topology, timeout_seconds: float
    ) -> Observation:
        if action.kind is ActionKind.WAIT:
            seconds = action.seconds or 0
            if seconds > timeout_seconds:
                time.sleep(max(0.0, timeout_seconds))
                raise TimeoutError
            time.sleep(seconds)
            return Observation(
                action.id,
                True,
                "waited",
                {"duration_seconds": seconds},
            )
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
        if action.kind is ActionKind.SSH_EXEC:
            addresses = {node.id: str(node.interfaces[0].ipv4) for node in topology.nodes}
            argv = command_argv(action.command or "", action.parameters, addresses)
            result = self.backend.ssh_command(action.target, argv, timeout=min(timeout_seconds, 60))
            return Observation(
                action.id,
                result.returncode == action.expected_exit_status,
                f"exit_status={result.returncode}",
                {
                    "command": action.command,
                    "argv": argv,
                    "exit_status": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_seconds": result.duration_seconds,
                },
            )
        service = next(item for item in target.services if item.id == action.service)
        deadline = time.monotonic() + min(timeout_seconds, 5.0)
        success = False
        while time.monotonic() < deadline:
            if self.backend.probe_tcp(action.source, address, service.port):
                success = True
                break
            time.sleep(0.1)
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


class HybridScenarioExecutor:
    """Route closed actions over the path each endpoint-class pair actually supports.

    - L0 -> L0 ICMP: the synthetic protocol engine (in-process frames).
    - L0 -> L1 ICMP: ARP and ICMP echo across the shared TAP into the Linux bridge.
    - L1 -> L1 ICMP/TCP: the kernel, through the namespace executor.
    - L1 -> L0 ICMP: the kernel's ping; the TAP responder answers ARP and echo for L0 endpoints.
    TCP to or from an L0 endpoint is reported as ``unsupported``: the synthetic engine implements
    no TCP. Nothing is emulated.
    """

    def __init__(self, backend: HybridBackend) -> None:
        self.backend = backend
        self.namespace = NamespaceScenarioExecutor(backend.namespace)
        self.network = SyntheticProtocolNetwork(backend.synthetic.engine)
        # The experiment owns the boundary capture window from here on.
        self.backend.capture.clear()

    def captured_frames(self) -> list[bytes]:
        return [*self.network.capture, *self.backend.capture]

    def execute(
        self, action: ScenarioAction, topology: Topology, timeout_seconds: float
    ) -> Observation:
        if action.kind is ActionKind.WAIT:
            seconds = action.seconds or 0
            if seconds > timeout_seconds:
                time.sleep(max(0.0, timeout_seconds))
                raise TimeoutError
            time.sleep(seconds)
            return Observation(action.id, True, "waited", {"duration_seconds": seconds})
        nodes = {node.id: node for node in topology.nodes}
        if action.kind is ActionKind.SSH_EXEC:
            target = nodes[action.target]
            if target.node_class is not NodeClass.L1:
                return Observation(action.id, False, "unsupported")
            observation = self.namespace.execute(action, topology, timeout_seconds)
            return Observation(
                observation.action_id,
                observation.success,
                observation.detail,
                {**observation.data, "path": f"{target.node_class.value}"},
            )
        source = nodes[action.source]
        target = nodes[action.target]
        path = f"{source.node_class.value}->{target.node_class.value}"
        l1_icmp_to_l0 = (
            source.node_class is NodeClass.L1
            and target.node_class is NodeClass.L0
            and action.kind is ActionKind.ICMP_PROBE
        )
        if l1_icmp_to_l0 or (
            source.node_class is NodeClass.L1 and target.node_class is NodeClass.L1
        ):
            observation = self.namespace.execute(action, topology, timeout_seconds)
            return Observation(
                observation.action_id,
                observation.success,
                observation.detail,
                {**observation.data, "path": path},
            )
        if source.node_class is not NodeClass.L0 or action.kind is not ActionKind.ICMP_PROBE:
            return Observation(
                action.id,
                False,
                "unsupported",
                {"path": path, "protocol": action.kind.value, "target": action.target},
            )
        address = target.interfaces[0].ipv4
        try:
            if target.node_class is NodeClass.L1:
                success = self.backend.ping_l1(
                    source.id, address, timeout=max(0.1, min(timeout_seconds, 2.0))
                )
            else:
                success = self.network.ping(source.id, address) is not None
        except SyntheticEngineError:
            success = False
        return Observation(
            action.id,
            success,
            "reachable" if success else "unreachable",
            {"protocol": "icmp", "target": action.target, "path": path},
        )
