"""Stateful control-plane service behind the HTTP contract."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.synthetic.backend import SyntheticBackend
from polmon.core.diagnostics import resource_snapshot
from polmon.core.errors import ConfigurationError
from polmon.orchestration import Orchestrator
from polmon.reporting import write_experiment_report
from polmon.scenarios import ScenarioEngine, parse_scenario
from polmon.scenarios.engine import Observation
from polmon.scenarios.executors import NamespaceScenarioExecutor
from polmon.scenarios.models import ActionKind, ScenarioAction
from polmon.telemetry.models import EventCategory
from polmon.telemetry.store import TelemetrySession, TelemetryStore
from polmon.topology import dump_topology, parse_topology
from polmon.topology.models import NodeClass, Topology


class SyntheticScenarioExecutor:
    def __init__(self, backend: SyntheticBackend) -> None:
        from polmon.backends.synthetic.protocols import SyntheticProtocolNetwork

        self.network = SyntheticProtocolNetwork(backend.engine)

    def execute(
        self, action: ScenarioAction, topology: Topology, timeout_seconds: float
    ) -> Observation:
        del timeout_seconds
        if action.kind is not ActionKind.ICMP_PROBE:
            return Observation(action.id, False, "unsupported")
        target = next(node for node in topology.nodes if node.id == action.target)
        result = self.network.ping(action.source, target.interfaces[0].ipv4)
        return Observation(
            action.id,
            True,
            "reachable",
            {"sequence": result.sequence, "target": action.target},
        )


class ControlPlane:
    def __init__(self, data_directory: str | Path = "var") -> None:
        self.data_directory = Path(data_directory)
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.telemetry = TelemetryStore(self.data_directory / "telemetry.sqlite3")
        self.topologies: dict[str, Topology] = {}
        self.deployments: dict[str, Orchestrator] = {}
        self.experiments: dict[str, dict[str, object]] = {}
        self._lock = RLock()

    def validate_topology(self, source: str) -> dict[str, object]:
        topology = parse_topology(source)
        return {
            "valid": True,
            "topology_id": topology.id,
            "normalized_yaml": dump_topology(topology),
            "resources": topology.estimate_resources().model_dump(mode="json"),
        }

    def load_topology(self, source: str) -> dict[str, object]:
        topology = parse_topology(source)
        with self._lock:
            self.topologies[topology.id] = topology
        return self.validate_topology(source)

    def _backend(self, topology: Topology):
        classes = {node.node_class for node in topology.nodes}
        if classes == {NodeClass.L0}:
            return SyntheticBackend()
        if classes == {NodeClass.L1}:
            return NamespaceBackend()
        if classes <= {NodeClass.L0, NodeClass.L1}:
            return HybridBackend()
        raise ConfigurationError("topology contains an unsupported backend combination")

    def deploy(self, topology_id: str) -> dict[str, object]:
        with self._lock:
            if topology_id in self.deployments:
                return self.deployment(topology_id)
            topology = self._topology(topology_id)
            control = Orchestrator(topology, self._backend(topology))
            try:
                control.validate()
                control.create()
                control.start()
            except Exception:
                control.destroy()
                raise
            self.deployments[topology_id] = control
            return self.deployment(topology_id)

    def deployment(self, topology_id: str) -> dict[str, object]:
        control = self.deployments.get(topology_id)
        if control is None:
            raise ConfigurationError(f"topology '{topology_id}' is not deployed")
        inspection = control.inspect()
        return {
            "topology_id": topology_id,
            "state": inspection.state,
            "backend": inspection.backend.backend,
            "resources": sorted(inspection.owned_resources),
            "details": inspection.backend.details,
        }

    def destroy(self, topology_id: str) -> dict[str, object]:
        with self._lock:
            control = self.deployments.get(topology_id)
            if control is not None:
                control.destroy()
                self.deployments.pop(topology_id, None)
        return {"topology_id": topology_id, "state": "destroyed"}

    def reset_all(self) -> dict[str, object]:
        """Best-effort teardown of every owned deployment while preserving definitions."""
        failures: list[str] = []
        with self._lock:
            topology_ids = list(self.deployments)
        for topology_id in topology_ids:
            try:
                self.destroy(topology_id)
            except Exception as error:
                failures.append(f"{topology_id}: {type(error).__name__}")
        if failures:
            raise ConfigurationError(
                "environment reset did not clean every deployment",
                details={"failures": failures},
            )
        return {"state": "reset", "deployments_destroyed": len(topology_ids)}

    def run_experiment(
        self, experiment_id: str, topology_id: str, scenario_source: str
    ) -> dict[str, object]:
        scenario = parse_scenario(scenario_source)
        topology = self._topology(topology_id)
        control = self.deployments.get(topology_id)
        if control is None:
            raise ConfigurationError("topology must be deployed before an experiment")
        session = TelemetrySession(
            self.telemetry,
            experiment_id,
            topology_id,
            scenario.id,
            self.data_directory / "captures",
        )
        session.event(EventCategory.SCENARIO, "started")
        session.resources(resource_snapshot())
        backend = control.backend
        if isinstance(backend, NamespaceBackend):
            executor = NamespaceScenarioExecutor(backend)
        elif isinstance(backend, SyntheticBackend):
            executor = SyntheticScenarioExecutor(backend)
        else:
            try:
                session.close("failed")
            finally:
                self.destroy(topology_id)
            raise ConfigurationError("scenario execution is not yet supported for hybrid topology")

        def cleanup() -> None:
            self.destroy(topology_id)

        try:
            result = ScenarioEngine().run(scenario, topology, executor, cleanup)
        except Exception as error:
            session.event(
                EventCategory.EXECUTION_ERROR,
                "error",
                payload={"message": f"{type(error).__name__}: experiment aborted"},
            )
            session.resources(resource_snapshot())
            session.close("failed")
            self.destroy(topology_id)
            raise
        for observation in result.observations:
            session.event(
                EventCategory.NETWORK_OBSERVATION,
                observation.action_id,
                payload={
                    "success": observation.success,
                    "detail": observation.detail,
                    **observation.data,
                },
            )
        if isinstance(executor, SyntheticScenarioExecutor):
            for frame in executor.network.capture:
                session.packet(frame)
        for error in result.errors:
            session.event(EventCategory.EXECUTION_ERROR, "error", payload={"message": error})
        session.resources(resource_snapshot())
        summary = session.close(result.status)
        events = self.telemetry.events(experiment_id)
        artifacts = write_experiment_report(
            self.data_directory / "reports",
            experiment_id,
            topology,
            scenario,
            result,
            events,
            summary,
        )
        record = {
            **asdict(result),
            "status": result.status,
            "capture": asdict(summary),
            "reports": {
                "json": str(artifacts.json_path),
                "markdown": str(artifacts.markdown_path),
            },
        }
        self.experiments[experiment_id] = record
        return record

    def experiment(self, experiment_id: str) -> dict[str, object]:
        if experiment_id not in self.experiments:
            raise ConfigurationError(f"unknown experiment '{experiment_id}'")
        return self.experiments[experiment_id]

    def experiment_telemetry(self, experiment_id: str) -> list[dict[str, object]]:
        return [asdict(event) for event in self.telemetry.events(experiment_id)]

    def experiment_report(self, experiment_id: str) -> dict[str, object]:
        path = self.data_directory / "reports" / f"{experiment_id}.json"
        if not path.is_file():
            raise ConfigurationError(f"report for experiment '{experiment_id}' does not exist")
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ConfigurationError(f"report for experiment '{experiment_id}' is invalid")
        return document

    def _topology(self, topology_id: str) -> Topology:
        try:
            return self.topologies[topology_id]
        except KeyError as error:
            raise ConfigurationError(f"unknown topology '{topology_id}'") from error
