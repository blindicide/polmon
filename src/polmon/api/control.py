"""Stateful control-plane service behind the HTTP contract."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock, Thread

from polmon.api.benchmarks import BenchmarkJobs
from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.synthetic.backend import SyntheticBackend
from polmon.core.diagnostics import ResourceSnapshot, fidelity_readiness, resource_snapshot
from polmon.core.errors import ConfigurationError, PolmonError
from polmon.orchestration import Orchestrator
from polmon.orchestration.lifecycle import LifecycleState
from polmon.reporting import write_experiment_report
from polmon.resources import AdmissionController, ResourceLimits, ResourceMonitor
from polmon.resources.policy import ResourceLimitError, directory_size_bytes
from polmon.scenarios import ScenarioEngine, parse_scenario
from polmon.scenarios.engine import ActionExecutor, Observation, ScenarioError
from polmon.scenarios.executors import HybridScenarioExecutor, NamespaceScenarioExecutor
from polmon.scenarios.models import ActionKind, InitialCondition, Scenario, ScenarioAction
from polmon.telemetry.models import EventCategory
from polmon.telemetry.store import EXPERIMENT_ID, TelemetrySession, TelemetryStore
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


# Finished experiments kept in memory with full detail; older ones are served from SQLite.
MAX_EXPERIMENT_RECORDS = 256


class ControlPlane:
    def __init__(
        self,
        data_directory: str | Path = "var",
        *,
        limits: ResourceLimits | None = None,
        snapshot: Callable[[], ResourceSnapshot] = resource_snapshot,
        l0_only: bool = False,
    ) -> None:
        self.data_directory = Path(data_directory)
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.telemetry = TelemetryStore(self.data_directory / "telemetry.sqlite3")
        self.topologies: dict[str, Topology] = {}
        self.deployments: dict[str, Orchestrator] = {}
        self.experiments: dict[str, dict[str, object]] = {}
        self.active_experiments: dict[str, ScenarioEngine] = {}
        self.limits = limits or ResourceLimits()
        self.l0_only = l0_only
        self._snapshot = snapshot
        self.admission = AdmissionController(self.limits, snapshot=self._snapshot)
        self.deployment_seconds: dict[str, float] = {}
        self.progress: dict[str, dict[str, object]] = {}
        self.experiment_threads: dict[str, Thread] = {}
        self._lock = RLock()
        self.benchmarks = BenchmarkJobs(
            self.data_directory / "benchmarks", self.limits, busy=self._benchmark_conflicts
        )

    def capabilities(self) -> dict[str, object]:
        """Execution fidelity advertised through health/resources responses."""
        return {
            "fidelity": "l0_only" if self.l0_only else "linux_lab",
            "l0": True,
            "l1": not self.l0_only,
            "l2": False,
            "hybrid_tap": not self.l0_only,
        }

    def _benchmark_conflicts(self) -> dict[str, object]:
        with self._lock:
            active = len(self.active_experiments)
        return {"active_experiments": {"active": active, "limit": 0}} if active else {}

    def _sample(self, topology_id: str | None = None) -> ResourceSnapshot:
        """Resource sample annotated with live endpoint/namespace counts and deployment time."""
        with self._lock:
            estimates = [
                self.topologies[item].estimate_resources()
                for item in self.deployments
                if item in self.topologies
            ]
            seconds = self.deployment_seconds.get(topology_id) if topology_id else None
        return replace(
            self._snapshot(),
            active_endpoints=sum(item.endpoint_count for item in estimates),
            active_namespaces=sum(item.l1_namespaces for item in estimates),
            topology_deployment_seconds=seconds,
        )

    @staticmethod
    def _describe(topology: Topology) -> dict[str, object]:
        return {
            "valid": True,
            "topology_id": topology.id,
            "normalized_yaml": dump_topology(topology),
            "resources": topology.estimate_resources().model_dump(mode="json"),
            "topology": topology.model_dump(mode="json", by_alias=True, exclude_none=True),
        }

    def validate_topology(self, source: str) -> dict[str, object]:
        return self._describe(parse_topology(source))

    def load_topology(self, source: str) -> dict[str, object]:
        topology = parse_topology(source)
        with self._lock:
            self.topologies[topology.id] = topology
        return self._describe(topology)

    def list_topologies(self) -> list[dict[str, object]]:
        with self._lock:
            loaded = list(self.topologies.values())
            deployed = set(self.deployments)
        return [
            {
                "topology_id": topology.id,
                "deployed": topology.id in deployed,
                "node_count": len(topology.nodes),
                "network_count": len(topology.networks),
                "resources": topology.estimate_resources().model_dump(mode="json"),
            }
            for topology in sorted(loaded, key=lambda item: item.id)
        ]

    def unload_topology(self, topology_id: str) -> dict[str, object]:
        """Forget a loaded definition; a deployed topology must be destroyed first."""
        with self._lock:
            self._topology(topology_id)
            if topology_id in self.deployments:
                raise ConfigurationError(
                    f"topology '{topology_id}' is deployed; destroy the deployment first"
                )
            self.topologies.pop(topology_id, None)
        return {"topology_id": topology_id, "state": "unloaded"}

    def topology_detail(self, topology_id: str) -> dict[str, object]:
        with self._lock:
            topology = self._topology(topology_id)
            deployed = topology_id in self.deployments
        return {**self._describe(topology), "deployed": deployed}

    def validate_scenario(self, source: str) -> dict[str, object]:
        """Parse a scenario and, when its topology is loaded, check it against that topology."""
        scenario = parse_scenario(source)
        with self._lock:
            topology = self.topologies.get(scenario.required_topology)
            deployed = scenario.required_topology in self.deployments
        problems: list[str] = []
        if topology is not None:
            try:
                ScenarioEngine().validate_against(scenario, topology)
            except ScenarioError as error:
                problems.append(error.message)
        document = scenario.model_dump(mode="json")
        document["permitted_actions"] = sorted(document["permitted_actions"])
        return {
            "valid": True,
            "scenario_id": scenario.id,
            "scenario": document,
            "topology_check": {
                "topology_id": scenario.required_topology,
                "loaded": topology is not None,
                "deployed": deployed,
                "compatible": topology is not None and not problems,
                "problems": problems,
            },
        }

    def _backend(self, topology: Topology):
        classes = {node.node_class for node in topology.nodes}
        if classes == {NodeClass.L0}:
            return SyntheticBackend()
        if NodeClass.L2 in classes:
            raise ConfigurationError("L2 virtual-machine execution is not implemented")
        readiness = fidelity_readiness()
        needed = "l1_ready" if classes == {NodeClass.L1} else "hybrid_ready"
        if not readiness[needed]:
            unavailable = [
                name
                for name, result in readiness["checks"].items()  # type: ignore[union-attr]
                if not result["ok"]
                and (needed == "hybrid_ready" or name != "tun_device")
            ]
            raise ConfigurationError(
                "L1/hybrid deployment requires a Linux host with iproute2, unprivileged ping, "
                "and passwordless sudo restricted to network namespace operations.",
                details={
                    "requires": "linux_network_namespaces",
                    "unavailable_checks": unavailable,
                },
            )
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
            if self.l0_only and any(node.node_class is not NodeClass.L0 for node in topology.nodes):
                raise ConfigurationError(
                    "Local backend supports L0 synthetic nodes only; L1/L2 requires a polmon "
                    "backend on a Linux host with network namespace privileges.",
                    details={"fidelity": "l0_only", "requires": "linux_network_namespaces"},
                )
            deployed = [self._topology(item) for item in self.deployments]
            self.admission.admit_topology(topology, deployed)
            control = Orchestrator(topology, self._backend(topology))
            started = time.perf_counter()
            try:
                control.validate()
                control.create()
                control.start()
            except Exception:
                control.destroy()
                raise
            self.deployment_seconds[topology_id] = time.perf_counter() - started
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
            "deployment_seconds": self.deployment_seconds.get(topology_id),
            "details": inspection.backend.details,
        }

    def destroy(self, topology_id: str) -> dict[str, object]:
        with self._lock:
            control = self.deployments.get(topology_id)
            if control is not None:
                control.destroy()
                self.deployments.pop(topology_id, None)
                self.deployment_seconds.pop(topology_id, None)
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
        self,
        experiment_id: str,
        topology_id: str,
        scenario_source: str,
        *,
        wait: bool = True,
    ) -> dict[str, object]:
        """Run an experiment; with ``wait=False`` return once admitted and run in background.

        Validation, deployment checks and admission always happen before this returns, so
        rejections reach the caller directly in both modes.
        """
        if not EXPERIMENT_ID.fullmatch(experiment_id):
            raise ConfigurationError("invalid experiment identifier")
        scenario = parse_scenario(scenario_source)
        topology = self._topology(topology_id)
        control = self.deployments.get(topology_id)
        if control is None:
            raise ConfigurationError("topology must be deployed before an experiment")
        backend = control.backend
        executor: ActionExecutor
        if isinstance(backend, NamespaceBackend):
            executor = NamespaceScenarioExecutor(backend)
        elif isinstance(backend, SyntheticBackend):
            executor = SyntheticScenarioExecutor(backend)
        elif isinstance(backend, HybridBackend):
            executor = HybridScenarioExecutor(backend)
        else:
            self.destroy(topology_id)
            raise ConfigurationError("scenario execution is unsupported for this backend")
        try:
            ScenarioEngine().validate_against(scenario, topology)
        except ScenarioError:
            self.destroy(topology_id)  # documented contract: preflight failures clean up
            raise

        engine = ScenarioEngine()
        with self._lock:
            if (
                experiment_id in self.active_experiments
                or experiment_id in self.experiments
                or self.telemetry.exists(experiment_id)
            ):
                raise ConfigurationError(f"experiment '{experiment_id}' already exists")
            if self.benchmarks.running() is not None:
                raise ResourceLimitError(
                    "experiment refused while a benchmark job is running",
                    details={"benchmark_jobs": {"active": 1, "limit": 0}},
                )
            self.admission.admit_experiment(
                scenario, len(self.active_experiments), data_directory=self.data_directory
            )
            self.active_experiments[experiment_id] = engine
            self.progress[experiment_id] = {
                "experiment_id": experiment_id,
                "topology_id": topology_id,
                "scenario_id": scenario.id,
                "state": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "started": time.monotonic(),
                "timeout_seconds": scenario.timeout_seconds,
                "total_actions": len(scenario.sequence),
                "completed_actions": 0,
                "current_action": None,
            }

        if wait:
            try:
                return self._execute_experiment(experiment_id, topology, scenario, executor, engine)
            finally:
                self._finish_progress(experiment_id)

        thread = Thread(
            target=self._background_experiment,
            args=(experiment_id, topology, scenario, executor, engine),
            name=f"polmon-experiment-{experiment_id}",
            daemon=True,
        )
        with self._lock:
            self.experiment_threads[experiment_id] = thread
        thread.start()
        return self.experiment(experiment_id)

    def _finish_progress(self, experiment_id: str) -> None:
        with self._lock:
            self.active_experiments.pop(experiment_id, None)
            progress = self.progress.get(experiment_id)
            if progress is not None:
                progress["finished"] = time.monotonic()
                progress["current_action"] = None
            self._trim_finished()

    def _trim_finished(self) -> None:
        """Bound in-memory history; evicted experiments remain available from SQLite."""
        finished = [item for item in self.progress if item not in self.active_experiments]
        for experiment_id in finished[: max(0, len(finished) - MAX_EXPERIMENT_RECORDS)]:
            self.progress.pop(experiment_id, None)
            self.experiments.pop(experiment_id, None)
        excess = len(self.experiments) - MAX_EXPERIMENT_RECORDS
        for experiment_id in list(self.experiments)[: max(0, excess)]:
            self.experiments.pop(experiment_id, None)

    def _background_experiment(
        self,
        experiment_id: str,
        topology: Topology,
        scenario: Scenario,
        executor: ActionExecutor,
        engine: ScenarioEngine,
    ) -> None:
        try:
            self._execute_experiment(experiment_id, topology, scenario, executor, engine)
        except Exception as error:  # recorded for GET /experiments/{id}; never lost silently
            if isinstance(error, PolmonError):
                failure = {"code": error.code, "message": error.message, "details": error.details}
            else:
                failure = {
                    "code": "internal_error",
                    "message": f"{type(error).__name__}: experiment aborted",
                    "details": {},
                }
            with self._lock:
                self.experiments[experiment_id] = {
                    "experiment_id": experiment_id,
                    "topology_id": topology.id,
                    "scenario_id": scenario.id,
                    "status": "error",
                    "error": failure,
                }
        finally:
            self._finish_progress(experiment_id)
            with self._lock:
                self.experiment_threads.pop(experiment_id, None)

    def _progress_view(self, experiment_id: str) -> dict[str, object] | None:
        with self._lock:
            progress = self.progress.get(experiment_id)
            if progress is None:
                return None
            end = progress.get("finished") or time.monotonic()
            elapsed = float(end) - float(progress["started"])  # type: ignore[arg-type]
            return {
                "total_actions": progress["total_actions"],
                "completed_actions": progress["completed_actions"],
                "current_action": progress["current_action"],
                "started_at": progress["started_at"],
                "elapsed_seconds": round(elapsed, 3),
                "timeout_seconds": progress["timeout_seconds"],
            }

    def _execute_experiment(
        self,
        experiment_id: str,
        topology: Topology,
        scenario: Scenario,
        executor: ActionExecutor,
        engine: ScenarioEngine,
    ) -> dict[str, object]:
        topology_id = topology.id
        session = TelemetrySession(
            self.telemetry,
            experiment_id,
            topology_id,
            scenario.id,
            self.data_directory / "captures",
            max_capture_bytes=self.limits.max_capture_bytes,
        )
        session.event(EventCategory.SCENARIO, "started")
        session.resources(self._sample(topology_id))

        def cleanup() -> None:
            self.destroy(topology_id)

        def resource_limit(reason: str, sample: ResourceSnapshot) -> None:
            session.event(
                EventCategory.EXECUTION_ERROR,
                "resource_limit",
                payload={"message": reason},
            )
            engine.cancel()

        monitor = ResourceMonitor(
            self.limits,
            resource_limit,
            on_sample=session.resources,
            snapshot=lambda: self._sample(topology_id),
        )

        def action_started(index: int, action: ScenarioAction) -> None:
            with self._lock:
                progress = self.progress.get(experiment_id)
                if progress is not None:
                    progress["current_action"] = action.id

        def action_observed(index: int, action: ScenarioAction, observation: Observation) -> None:
            # Recorded as it happens, so telemetry pollers see a live stream.
            session.event(
                EventCategory.NETWORK_OBSERVATION,
                observation.action_id,
                payload={
                    "success": observation.success,
                    "detail": observation.detail,
                    **observation.data,
                },
            )
            with self._lock:
                progress = self.progress.get(experiment_id)
                if progress is not None:
                    progress["completed_actions"] = index + 1

        # The engine is created per experiment; never clear a cancel that arrived before the run
        # thread started.
        monitor.start()
        try:
            result = engine.run(
                scenario,
                topology,
                executor,
                cleanup,
                reset_cancellation=False,
                precondition=lambda condition: self._precondition(topology, condition),
                on_action=action_started,
                on_observation=action_observed,
            )
        except Exception as error:
            try:
                session.event(
                    EventCategory.EXECUTION_ERROR,
                    "error",
                    payload={"message": f"{type(error).__name__}: experiment aborted"},
                )
                session.resources(self._sample(topology_id))
                session.close("failed")
            finally:
                self.destroy(topology_id)
            raise
        finally:
            monitor.stop()
        if isinstance(executor, SyntheticScenarioExecutor):
            for frame in executor.network.capture:
                session.packet(frame)
        elif isinstance(executor, HybridScenarioExecutor):
            for frame in executor.captured_frames():
                session.packet(frame)
        for error in result.errors:
            session.event(EventCategory.EXECUTION_ERROR, "error", payload={"message": error})
        session.resources(self._sample(topology_id))
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
            "experiment_id": experiment_id,
            **asdict(result),
            "status": result.status,
            "capture": asdict(summary),
            "reports": {
                "json": str(artifacts.json_path),
                "markdown": str(artifacts.markdown_path),
            },
        }
        with self._lock:
            self.experiments[experiment_id] = record
        return record

    def _precondition(self, topology: Topology, condition: InitialCondition) -> bool:
        """Verify one declared initial condition against the live deployment."""
        with self._lock:
            control = self.deployments.get(topology.id)
        if control is None or control.inspect().state != LifecycleState.RUNNING:
            return False
        if condition is InitialCondition.TOPOLOGY_DEPLOYED:
            return True
        if condition is InitialCondition.SERVICES_STARTED:
            declared = [
                (node.id, service.id)
                for node in topology.nodes
                if node.node_class is NodeClass.L1
                for service in node.services
            ]
            backend = control.backend
            namespace = backend.namespace if isinstance(backend, HybridBackend) else backend
            if not declared:
                return True
            if not isinstance(namespace, NamespaceBackend):
                return False
            return all(
                key in namespace.services and namespace.services[key].poll() is None
                for key in declared
            )
        return False

    def cancel_experiment(self, experiment_id: str) -> dict[str, object]:
        with self._lock:
            engine = self.active_experiments.get(experiment_id)
            if engine is None:
                raise ConfigurationError(f"experiment '{experiment_id}' is not active")
            engine.cancel()
            if experiment_id in self.progress:
                self.progress[experiment_id]["state"] = "cancelling"
        return {"experiment_id": experiment_id, "state": "cancelling"}

    def shutdown(self, timeout: float = 15.0) -> dict[str, object]:
        """Cancel and join active experiments and benchmark jobs, then reset everything."""
        with self._lock:
            engines = list(self.active_experiments.values())
            threads = list(self.experiment_threads.values())
        for engine in engines:
            engine.cancel()
        for thread in threads:
            thread.join(timeout=timeout)
        self.benchmarks.shutdown()
        return self.reset_all()

    def close(self) -> None:
        """Release the telemetry database handle (Windows cannot delete open files)."""
        self.telemetry.close()

    def resource_status(self) -> dict[str, object]:
        snapshot = self._sample()
        return {
            "capabilities": self.capabilities(),
            "limits": self.limits.model_dump(mode="json"),
            "data_directory_bytes": directory_size_bytes(self.data_directory),
            "active_deployments": len(self.deployments),
            "active_experiments": len(self.active_experiments),
            "benchmark_running": self.benchmarks.running() is not None,
            "snapshot": asdict(snapshot),
        }

    def start_benchmark(self, request) -> dict[str, object]:  # noqa: ANN001
        """Start a benchmark allowed by this backend's fidelity policy."""
        if self.l0_only and request.kind != "l0":
            raise ConfigurationError(
                "Local backend supports L0 benchmarks only; L1 and target benchmarks require a "
                "polmon backend on a Linux host with network namespace privileges.",
                details={"fidelity": "l0_only", "requires": "linux_network_namespaces"},
            )
        return self.benchmarks.start(request)

    def experiment(self, experiment_id: str) -> dict[str, object]:
        """Live progress while running, the full record once finished (this process), or the
        persisted summary of an experiment run by an earlier backend process."""
        with self._lock:
            progress = self._progress_view(experiment_id)
            if experiment_id in self.active_experiments:
                state = self.progress[experiment_id]
                return {
                    "experiment_id": experiment_id,
                    "topology_id": state["topology_id"],
                    "scenario_id": state["scenario_id"],
                    "status": "cancelling" if state["state"] == "cancelling" else "running",
                    "progress": progress,
                }
            if experiment_id in self.experiments:
                return {**self.experiments[experiment_id], "progress": progress}
        if self.telemetry.exists(experiment_id):
            stored = self.telemetry.experiment(experiment_id)
            status = stored["status"]
            if status == "running":  # never finished: the process that ran it stopped
                status = "interrupted"
            return {
                "experiment_id": experiment_id,
                "topology_id": stored["topology_id"],
                "scenario_id": stored["scenario_id"],
                "status": status,
                "started_at": stored["started_at"],
                "finished_at": stored["finished_at"],
                "capture": stored["capture"],
                "persisted": True,
                "progress": None,
            }
        raise ConfigurationError(f"unknown experiment '{experiment_id}'")

    def list_experiments(self, limit: int = 200) -> list[dict[str, object]]:
        with self._lock:
            active = set(self.active_experiments)
        listed = []
        for row in self.telemetry.experiments(limit):
            status = row["status"]
            if status == "running" and row["id"] not in active:
                status = "interrupted"
            listed.append(
                {
                    "experiment_id": row["id"],
                    "topology_id": row["topology_id"],
                    "scenario_id": row["scenario_id"],
                    "status": status,
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "polmon_version": row["version"],
                    "capture": None
                    if row["frame_count"] is None
                    else {
                        "frame_count": row["frame_count"],
                        "captured_bytes": row["captured_bytes"],
                        "dropped_frames": row["dropped_frames"],
                        "truncated_frames": row["truncated_frames"],
                    },
                    "report_available": (
                        self.data_directory / "reports" / f"{row['id']}.json"
                    ).is_file(),
                }
            )
        return listed

    def experiment_telemetry(
        self, experiment_id: str, *, after: int = 0, limit: int | None = None
    ) -> list[dict[str, object]]:
        return [
            asdict(event)
            for event in self.telemetry.events(experiment_id, after=after, limit=limit)
        ]

    def experiment_capture_path(self, experiment_id: str) -> Path:
        """The finished experiment's bounded PCAP file (written when the experiment closes)."""
        if not EXPERIMENT_ID.fullmatch(experiment_id):
            raise ConfigurationError("invalid experiment identifier")
        with self._lock:
            if experiment_id in self.active_experiments:
                raise ConfigurationError(f"experiment '{experiment_id}' is still running")
        path = self.data_directory / "captures" / f"{experiment_id}.pcap"
        if not path.is_file():
            raise ConfigurationError(f"capture for experiment '{experiment_id}' does not exist")
        return path

    def experiment_report_markdown(self, experiment_id: str) -> dict[str, object]:
        if not EXPERIMENT_ID.fullmatch(experiment_id):
            raise ConfigurationError("invalid experiment identifier")
        path = self.data_directory / "reports" / f"{experiment_id}.md"
        if not path.is_file():
            raise ConfigurationError(f"report for experiment '{experiment_id}' does not exist")
        return {"experiment_id": experiment_id, "markdown": path.read_text(encoding="utf-8")}

    def experiment_report(self, experiment_id: str) -> dict[str, object]:
        if not EXPERIMENT_ID.fullmatch(experiment_id):
            raise ConfigurationError("invalid experiment identifier")
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
