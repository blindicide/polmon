"""Stateful control-plane service behind the HTTP contract."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
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
from polmon.console import ConsoleSessions
from polmon.core.diagnostics import ResourceSnapshot, fidelity_readiness, resource_snapshot
from polmon.core.errors import ConfigurationError, PolmonError
from polmon.core.logstore import StructuredLogStore
from polmon.library import YamlLibrary
from polmon.orchestration import Orchestrator
from polmon.orchestration.lifecycle import LifecycleState
from polmon.reporting import write_experiment_report
from polmon.resources import AdmissionController, ResourceLimits, ResourceMonitor
from polmon.resources.policy import ResourceLimitError, directory_size_bytes
from polmon.scenarios import ScenarioEngine, dump_scenario, parse_scenario
from polmon.scenarios.engine import ActionExecutor, Observation, ScenarioError
from polmon.scenarios.executors import HybridScenarioExecutor, NamespaceScenarioExecutor
from polmon.scenarios.models import ActionKind, InitialCondition, Scenario, ScenarioAction
from polmon.telemetry.models import EventCategory
from polmon.telemetry.store import EXPERIMENT_ID, TelemetrySession, TelemetryStore
from polmon.topology import dump_topology, parse_topology
from polmon.topology.models import NodeClass, Topology

CONSOLE_ARGUMENT = re.compile(r"^[A-Za-z0-9_./:@%+=,-]{1,256}$")
CONSOLE_COMMANDS = {
    "hostname",
    "cat",
    "ip",
    "arp",
    "ping",
    "ss",
    "netstat",
    "ps",
    "uptime",
    "nc",
    "false",
    "sleep",
}


class SyntheticScenarioExecutor:
    def __init__(self, backend: SyntheticBackend) -> None:
        from polmon.backends.synthetic.protocols import SyntheticProtocolNetwork

        self.network = SyntheticProtocolNetwork(backend.engine)

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
        self.logs = StructuredLogStore(self.data_directory / "logs")
        self.telemetry = TelemetryStore(self.data_directory / "telemetry.sqlite3")
        self.console_sessions = ConsoleSessions(self.data_directory / "logs" / "console")
        self.vnc_sessions: dict[str, tuple[str, str]] = {}
        self.topology_library = YamlLibrary(
            self.data_directory / "library" / "topologies",
            parse=parse_topology,
            dump=dump_topology,
            identity=lambda topology: topology.id,
        )
        self.topologies: dict[str, Topology] = self.topology_library.load_all()
        self.scenario_library = YamlLibrary(
            self.data_directory / "library" / "scenarios",
            parse=parse_scenario,
            dump=dump_scenario,
            identity=lambda scenario: scenario.id,
        )
        self.scenarios: dict[str, Scenario] = self.scenario_library.load_all()
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

    def _node_context(self, topology_id: str, node_id: str | None) -> dict[str, object] | None:
        if node_id is None:
            return None
        topology = self.topologies.get(topology_id)
        node = (
            next((item for item in topology.nodes if item.id == node_id), None)
            if topology
            else None
        )
        if node is None:
            return {"id": node_id}
        return {"id": node.id, "name": node.name, "uuid": str(node.uuid)}

    def _log(
        self,
        level: str,
        event: str,
        message: str,
        *,
        topology_id: str | None = None,
        node_id: str | None = None,
        experiment_id: str | None = None,
        session_id: str | None = None,
        params: dict[str, object] | None = None,
    ) -> None:
        self.logs.emit(
            level,
            event,
            message,
            params=params,
            deployment=topology_id,
            topology=topology_id,
            node=self._node_context(topology_id, node_id) if topology_id else None,
            experiment=experiment_id,
            session=session_id,
        )

    def logs_query(self, **filters: object) -> dict[str, object]:
        return self.logs.query(**filters)  # type: ignore[arg-type]

    def logs_files(self) -> dict[str, object]:
        return self.logs.files()

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

    def load_topology(self, source: str, topology_id: str | None = None) -> dict[str, object]:
        topology = parse_topology(source)
        requested_id = topology_id or topology.id
        self.topology_library.put(requested_id, topology)
        with self._lock:
            self.topologies[topology.id] = topology
        return {**self._describe(topology), "persisted": True}

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
                    f"topology '{topology_id}' is deployed; destroy the deployment first",
                    message_code="topology.deployed_destroy_first",
                    params={"topology_id": topology_id},
                )
            self.topologies.pop(topology_id, None)
            self.topology_library.delete(topology_id)
        return {"topology_id": topology_id, "state": "deleted"}

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

    @staticmethod
    def _describe_scenario(scenario: Scenario) -> dict[str, object]:
        return {
            "valid": True,
            "scenario_id": scenario.id,
            "yaml": dump_scenario(scenario),
            "scenario": scenario.model_dump(mode="json", by_alias=True, exclude_none=True),
        }

    def load_scenario(self, source: str, scenario_id: str | None = None) -> dict[str, object]:
        scenario = parse_scenario(source)
        requested_id = scenario_id or scenario.id
        self.scenario_library.put(requested_id, scenario)
        with self._lock:
            self.scenarios[scenario.id] = scenario
        return {**self._describe_scenario(scenario), "persisted": True}

    def list_scenarios(self) -> list[dict[str, object]]:
        with self._lock:
            scenarios = list(self.scenarios.values())
        return [
            {
                "scenario_id": scenario.id,
                "required_topology": scenario.required_topology,
                "action_count": len(scenario.sequence),
                "cleanup_action_count": len(scenario.cleanup_steps),
                "permitted_actions": sorted(action.value for action in scenario.permitted_actions),
            }
            for scenario in sorted(scenarios, key=lambda item: item.id)
        ]

    def scenario_detail(self, scenario_id: str) -> dict[str, object]:
        with self._lock:
            scenario = self.scenarios.get(scenario_id)
        if scenario is None:
            raise ConfigurationError(
                f"unknown scenario '{scenario_id}'",
                message_code="scenario.unknown",
                params={"scenario_id": scenario_id},
            )
        return self._describe_scenario(scenario)

    def unload_scenario(self, scenario_id: str) -> dict[str, object]:
        with self._lock:
            if scenario_id not in self.scenarios:
                raise ConfigurationError(
                    f"unknown scenario '{scenario_id}'",
                    message_code="scenario.unknown",
                    params={"scenario_id": scenario_id},
                )
            self.scenarios.pop(scenario_id)
            self.scenario_library.delete(scenario_id)
        return {"scenario_id": scenario_id, "state": "deleted"}

    def _backend(self, topology: Topology):
        classes = {node.node_class for node in topology.nodes}
        if classes == {NodeClass.L0}:
            return SyntheticBackend()
        if NodeClass.L2 in classes:
            raise ConfigurationError(
                "L2 virtual-machine execution is not implemented",
                message_code="fidelity.l2_not_implemented",
            )
        readiness = fidelity_readiness()
        needed = "l1_ready" if classes == {NodeClass.L1} else "hybrid_ready"
        if not readiness[needed]:
            unavailable = [
                name
                for name, result in readiness["checks"].items()  # type: ignore[union-attr]
                if not result["ok"] and (needed == "hybrid_ready" or name != "tun_device")
            ]
            raise ConfigurationError(
                "L1/hybrid deployment requires a Linux host with iproute2, unprivileged ping, "
                "and passwordless sudo restricted to network namespace operations.",
                details={
                    "requires": "linux_network_namespaces",
                    "unavailable_checks": unavailable,
                },
                message_code="fidelity.linux_lab_unavailable",
                params={"checks": unavailable},
            )
        if classes == {NodeClass.L1}:
            hostless_pair = (
                len(topology.networks) == 1
                and len(topology.nodes) == 2
                and all(
                    len(node.interfaces) == 1
                    and node.interfaces[0].network == topology.networks[0].id
                    for node in topology.nodes
                )
            )
            return NamespaceBackend(
                run_directory=self.data_directory
                / "runs"
                / "deployments"
                / topology.id
                / secrets.token_hex(6),
                log_directory=self.data_directory / "logs" / "services",
                hostless_pair=hostless_pair,
            )
        if classes <= {NodeClass.L0, NodeClass.L1}:
            return HybridBackend()
        raise ConfigurationError(
            "topology contains an unsupported backend combination",
            message_code="topology.unsupported_backend_combination",
        )

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
                    message_code="fidelity.l0_only",
                )
            deployed = [self._topology(item) for item in self.deployments]
            self.admission.admit_topology(topology, deployed)
            self._log(
                "INFO",
                "lab.provision.start",
                "provisioning topology",
                topology_id=topology.id,
                params={"node_count": len(topology.nodes), "network_count": len(topology.networks)},
            )
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
            for node in topology.nodes:
                self._log(
                    "INFO",
                    "lab.provision.complete",
                    "node provisioned",
                    topology_id=topology_id,
                    node_id=node.id,
                )
                for interface in node.interfaces:
                    self._log(
                        "INFO",
                        "lab.interface.up",
                        "interface is up",
                        topology_id=topology_id,
                        node_id=node.id,
                        params={"interface": interface.id, "network": interface.network},
                    )
                for service in node.services:
                    self._log(
                        "INFO",
                        "lab.service.start",
                        "service started",
                        topology_id=topology_id,
                        node_id=node.id,
                        params={
                            "service": service.id,
                            "implementation": service.implementation,
                            "port": service.port,
                        },
                    )
            return self.deployment(topology_id)

    def deployment(self, topology_id: str) -> dict[str, object]:
        control = self.deployments.get(topology_id)
        if control is None:
            raise ConfigurationError(
                f"topology '{topology_id}' is not deployed",
                message_code="topology.not_deployed",
                params={"topology_id": topology_id},
            )
        inspection = control.inspect()
        return {
            "topology_id": topology_id,
            "state": inspection.state,
            "backend": inspection.backend.backend,
            "resources": sorted(inspection.owned_resources),
            "deployment_seconds": self.deployment_seconds.get(topology_id),
            "details": inspection.backend.details,
        }

    def send_packet(
        self, topology_id: str, node_id: str, interface_id: str, frame_hex: str
    ) -> dict[str, object]:
        """Audit a bounded, one-shot send through an isolated namespace pair."""
        operation_id = secrets.token_hex(8)
        with self._lock:
            try:
                control = self.deployments.get(topology_id)
                if control is None:
                    raise ConfigurationError(
                        "topology is not deployed", message_code="packet.not_deployed"
                    )
                backend = control.backend
                if not isinstance(backend, NamespaceBackend) or not backend.hostless_pair:
                    raise ConfigurationError(
                        "packet workbench requires a hostless isolated namespace pair",
                        message_code="packet.hostless_pair_required",
                    )
                result = backend.send_packet(node_id, interface_id, frame_hex)
            except ConfigurationError as error:
                result = {
                    "state": "refused",
                    "message_code": error.message_code,
                    "message": error.message,
                }
            except Exception:
                result = {
                    "state": "error",
                    "message_code": "packet.backend_error",
                    "message": "packet transmission could not be completed",
                }
            self._log(
                {"sent": "INFO", "refused": "WARNING", "error": "ERROR"}[result["state"]],
                "packet.send",
                f"packet {result['state']}",
                topology_id=topology_id,
                node_id=node_id,
                params={
                    "operation_id": operation_id,
                    "state": result["state"],
                    "interface_id": interface_id,
                    "byte_count": result.get("byte_count", 0),
                    "message_code": result.get("message_code", ""),
                },
            )
            return {
                "operation_id": operation_id,
                "topology_id": topology_id,
                "node_id": node_id,
                **result,
            }

    def destroy(self, topology_id: str) -> dict[str, object]:
        topology = self.topologies.get(topology_id)
        self._log("INFO", "lab.teardown.start", "tearing down topology", topology_id=topology_id)
        self.console_sessions.close_topology(topology_id)
        with self._lock:
            control = self.deployments.get(topology_id)
            if control is not None:
                control.destroy()
                self.deployments.pop(topology_id, None)
                self.deployment_seconds.pop(topology_id, None)
        if topology is not None:
            for node in topology.nodes:
                self._log(
                    "INFO",
                    "lab.teardown.complete",
                    "node torn down",
                    topology_id=topology_id,
                    node_id=node.id,
                )
        return {"topology_id": topology_id, "state": "destroyed"}

    def console_readiness(self, topology_id: str, node_id: str) -> dict[str, object]:
        topology = self._topology(topology_id)
        node = next((item for item in topology.nodes if item.id == node_id), None)
        if node is None:
            raise ConfigurationError(
                "unknown topology node",
                message_code="console.node_unknown",
                params={"node": node_id},
            )
        sshd = shutil.which("sshd")
        ssh = shutil.which("ssh")
        node_supported = node.node_class is NodeClass.L1
        service = next((item for item in node.services if item.implementation == "ssh"), None)
        reasons = []
        if not node_supported:
            reasons.append("console.l1_required")
        if sshd is None:
            reasons.append("console.sshd_missing")
        if ssh is None:
            reasons.append("console.ssh_client_missing")
        if service is None:
            reasons.append("console.ssh_service_missing")
        checks = fidelity_readiness()["checks"]
        vnc_reasons = [
            f"console.{name}_missing"
            for name in ("Xvfb", "x11vnc", "xclock")
            if not bool(checks[f"tool_{name}"]["ok"])  # type: ignore[index]
        ]
        if not node_supported:
            vnc_reasons.insert(0, "console.l1_required")
        return {
            "topology_id": topology_id,
            "node": {"id": node.id, "name": node.name, "uuid": str(node.uuid)},
            "ssh": {"available": not reasons, "port": service.port if service else None},
            "vnc": {
                "available": not vnc_reasons,
                "display_stack": "Xvfb + x11vnc + xclock",
                "reason_codes": vnc_reasons,
            },
            "reason_codes": reasons,
        }

    def console_vnc_start(self, topology_id: str, node_id: str) -> dict[str, object]:
        readiness = self.console_readiness(topology_id, node_id)
        reasons = readiness["vnc"]["reason_codes"]
        if reasons:
            messages = {
                "console.l1_required": "VNC requires an L1 node",
                "console.Xvfb_missing": "Xvfb is missing",
                "console.x11vnc_missing": "x11vnc is missing; install package x11vnc",
                "console.xclock_missing": "xclock is missing; install package x11-apps",
            }
            reason = str(reasons[0])
            raise ConfigurationError(
                messages.get(reason, "VNC prerequisites are unavailable"), message_code=reason
            )
        control = self.deployments.get(topology_id)
        if control is None or not isinstance(control.backend, NamespaceBackend):
            raise ConfigurationError(
                "topology must be deployed on the namespace backend",
                message_code="console.not_deployed",
            )
        session = secrets.token_urlsafe(24)
        display = control.backend.start_vnc(node_id)
        self.vnc_sessions[session] = (topology_id, node_id)
        return {
            "session_id": session,
            "node": readiness["node"],
            "display": display,
            "relay_path": f"/v1/deployments/{topology_id}/nodes/{node_id}/console/vnc/{session}",
        }

    async def console_vnc_relay(self, session_id: str, websocket) -> None:  # noqa: ANN001
        session = self.vnc_sessions.get(session_id)
        if session is None:
            await websocket.close(code=4404)
            return
        topology_id, node_id = session
        control = self.deployments.get(topology_id)
        if control is None or not isinstance(control.backend, NamespaceBackend):
            await websocket.close(code=4409)
            return
        process = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",
            *control.backend.vnc_proxy_argv(node_id),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        async def from_client() -> None:
            while True:
                data = await websocket.receive_bytes()
                process.stdin.write(data)
                await process.stdin.drain()

        async def from_vnc() -> None:
            while True:
                data = await process.stdout.read(65536)
                if not data:
                    return
                await websocket.send_bytes(data)

        client_task = asyncio.create_task(from_client())
        vnc_task = asyncio.create_task(from_vnc())
        try:
            await asyncio.wait((client_task, vnc_task), return_when=asyncio.FIRST_COMPLETED)
        except Exception:
            pass
        finally:
            client_task.cancel()
            vnc_task.cancel()
            await asyncio.gather(client_task, vnc_task, return_exceptions=True)
            if process.stdin is not None:
                process.stdin.close()
            if process.returncode is None:
                process.terminate()
            await process.wait()
            process._transport.close()  # type: ignore[attr-defined]
            await asyncio.sleep(0)

    @staticmethod
    def _raise_console_reason(reason: str) -> None:
        if reason == "console.l1_required":
            raise ConfigurationError(
                "SSH console access requires an L1 node", message_code="console.l1_required"
            )
        if reason == "console.sshd_missing":
            raise ConfigurationError(
                "OpenSSH server is missing", message_code="console.sshd_missing"
            )
        if reason == "console.ssh_client_missing":
            raise ConfigurationError(
                "OpenSSH client is missing", message_code="console.ssh_client_missing"
            )
        if reason == "console.ssh_service_missing":
            raise ConfigurationError(
                "the node has no ssh service", message_code="console.ssh_service_missing"
            )
        raise ConfigurationError(
            "the deployment has no SSH run directory", message_code="console.ssh_unavailable"
        )

    def console_exec(
        self, topology_id: str, node_id: str, argv: list[str], timeout_seconds: float
    ) -> dict[str, object]:
        if not argv or argv[0] not in CONSOLE_COMMANDS:
            raise ConfigurationError(
                "command is outside the bounded console catalogue",
                message_code="console.command_not_allowed",
            )
        if any(not CONSOLE_ARGUMENT.fullmatch(argument) for argument in argv):
            raise ConfigurationError(
                "console arguments contain unsupported characters",
                message_code="console.argument_invalid",
            )
        readiness = self.console_readiness(topology_id, node_id)
        reasons = readiness["reason_codes"]
        if reasons:
            self._raise_console_reason(str(reasons[0]))
        control = self.deployments.get(topology_id)
        if control is None or not isinstance(control.backend, NamespaceBackend):
            raise ConfigurationError(
                "topology must be deployed on the namespace backend",
                message_code="console.not_deployed",
            )
        result = control.backend.ssh_command(node_id, argv, timeout=timeout_seconds)
        node = next(item for item in self.topologies[topology_id].nodes if item.id == node_id)
        self._log(
            "INFO",
            "console.command",
            "console command completed",
            topology_id=topology_id,
            node_id=node_id,
            params={
                "argv": argv,
                "exit_status": result.returncode,
                "duration_seconds": result.duration_seconds,
                "stderr_excerpt": result.stderr[:1_000],
            },
        )
        return {
            "node": {"id": node.id, "name": node.name, "uuid": str(node.uuid)},
            "argv": argv,
            "exit_status": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "truncated": result.truncated,
            "timed_out": result.timed_out,
        }

    def console_session_create(self, topology_id: str, node_id: str) -> dict[str, object]:
        readiness = self.console_readiness(topology_id, node_id)
        reasons = readiness["reason_codes"]
        if reasons:
            self._raise_console_reason(str(reasons[0]))
        control = self.deployments.get(topology_id)
        if control is None or not isinstance(control.backend, NamespaceBackend):
            raise ConfigurationError(
                "topology must be deployed on the namespace backend",
                message_code="console.not_deployed",
            )
        result = self.console_sessions.create(topology_id, node_id, control.backend)
        result["node"] = readiness["node"]
        self._log(
            "INFO",
            "console.session.start",
            "interactive console session started",
            topology_id=topology_id,
            node_id=node_id,
            session_id=str(result["session_id"]),
        )
        return result

    def console_session(self, session_id: str, after: int = 0) -> dict[str, object]:
        return self.console_sessions.get(session_id, after)

    def console_session_input(self, session_id: str, data: str) -> dict[str, object]:
        current = self.console_sessions.get(session_id)
        result = self.console_sessions.input(session_id, data)
        self._log(
            "INFO",
            "console.command",
            "interactive console input sent",
            topology_id=str(current["topology_id"]),
            node_id=str(current["node_id"]),
            session_id=session_id,
            params={"input_excerpt": data[:1_000]},
        )
        return result

    def console_session_delete(self, session_id: str) -> dict[str, object]:
        current = self.console_sessions.get(session_id)
        result = self.console_sessions.delete(session_id)
        self._log(
            "INFO",
            "console.session.end",
            "interactive console session closed",
            topology_id=str(current["topology_id"]),
            node_id=str(current["node_id"]),
            session_id=session_id,
        )
        return result

    def console_transcript(self, session_id: str) -> dict[str, object]:
        return self.console_sessions.transcript(session_id)

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
                message_code="reset.incomplete",
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
            raise ConfigurationError(
                "invalid experiment identifier",
                message_code="experiment.invalid_id",
            )
        scenario = parse_scenario(scenario_source)
        topology = self._topology(topology_id)
        control = self.deployments.get(topology_id)
        if control is None:
            raise ConfigurationError(
                "topology must be deployed before an experiment",
                message_code="experiment.topology_not_deployed",
                params={"topology_id": topology_id},
            )
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
            raise ConfigurationError(
                "scenario execution is unsupported for this backend",
                message_code="experiment.unsupported_backend",
            )
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
                raise ConfigurationError(
                    f"experiment '{experiment_id}' already exists",
                    message_code="experiment.exists",
                    params={"experiment_id": experiment_id},
                )
            if self.benchmarks.running() is not None:
                raise ResourceLimitError(
                    "experiment refused while a benchmark job is running",
                    details={"benchmark_jobs": {"active": 1, "limit": 0}},
                    message_code="experiment.benchmark_running",
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
                failure = error.document()
            else:
                failure = {
                    "code": "internal_error",
                    "message": f"{type(error).__name__}: experiment aborted",
                    "message_code": "experiment.aborted",
                    "params": {"cause": type(error).__name__},
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
            self._log(
                "INFO",
                "experiment.action.start",
                "scenario action started",
                topology_id=topology_id,
                node_id=action.target,
                experiment_id=experiment_id,
                params={
                    "action": action.id,
                    "kind": action.kind.value,
                    "resolved_target": action.target,
                },
            )
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
            self._log(
                "INFO" if observation.success else "WARNING",
                "experiment.action.end",
                "scenario action completed",
                topology_id=topology_id,
                node_id=action.target,
                experiment_id=experiment_id,
                params={
                    "action": action.id,
                    "kind": action.kind.value,
                    "success": observation.success,
                    "detail": observation.detail,
                    "duration_seconds": observation.data.get("duration_seconds"),
                    "exit_status": observation.data.get("exit_status"),
                    "stderr_excerpt": str(observation.data.get("stderr", ""))[:1_000],
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
        for error, detail in zip(
            result.errors, result.error_details or [{}] * len(result.errors), strict=False
        ):
            session.event(
                EventCategory.EXECUTION_ERROR,
                "error",
                payload={
                    "message": error,
                    "message_code": detail.get("message_code"),
                    "params": detail.get("params") or {},
                },
            )
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
                raise ConfigurationError(
                    f"experiment '{experiment_id}' is not active",
                    message_code="experiment.not_active",
                    params={"experiment_id": experiment_id},
                )
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
        self.console_sessions.close()
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
                message_code="fidelity.l0_benchmarks_only",
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
        raise ConfigurationError(
            f"unknown experiment '{experiment_id}'",
            message_code="experiment.unknown",
            params={"experiment_id": experiment_id},
        )

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
            raise ConfigurationError(
                "invalid experiment identifier",
                message_code="experiment.invalid_id",
            )
        with self._lock:
            if experiment_id in self.active_experiments:
                raise ConfigurationError(
                    f"experiment '{experiment_id}' is still running",
                    message_code="experiment.still_running",
                    params={"experiment_id": experiment_id},
                )
        path = self.data_directory / "captures" / f"{experiment_id}.pcap"
        if not path.is_file():
            raise ConfigurationError(
                f"capture for experiment '{experiment_id}' does not exist",
                message_code="experiment.capture_missing",
                params={"experiment_id": experiment_id},
            )
        return path

    def experiment_report_markdown(self, experiment_id: str) -> dict[str, object]:
        if not EXPERIMENT_ID.fullmatch(experiment_id):
            raise ConfigurationError(
                "invalid experiment identifier",
                message_code="experiment.invalid_id",
            )
        path = self.data_directory / "reports" / f"{experiment_id}.md"
        if not path.is_file():
            raise ConfigurationError(
                f"report for experiment '{experiment_id}' does not exist",
                message_code="experiment.report_missing",
                params={"experiment_id": experiment_id},
            )
        return {"experiment_id": experiment_id, "markdown": path.read_text(encoding="utf-8")}

    def experiment_report(self, experiment_id: str) -> dict[str, object]:
        if not EXPERIMENT_ID.fullmatch(experiment_id):
            raise ConfigurationError(
                "invalid experiment identifier",
                message_code="experiment.invalid_id",
            )
        path = self.data_directory / "reports" / f"{experiment_id}.json"
        if not path.is_file():
            raise ConfigurationError(
                f"report for experiment '{experiment_id}' does not exist",
                message_code="experiment.report_missing",
                params={"experiment_id": experiment_id},
            )
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ConfigurationError(
                f"report for experiment '{experiment_id}' is invalid",
                message_code="experiment.report_invalid",
                params={"experiment_id": experiment_id},
            )
        return document

    def _topology(self, topology_id: str) -> Topology:
        try:
            return self.topologies[topology_id]
        except KeyError as error:
            raise ConfigurationError(
                f"unknown topology '{topology_id}'",
                message_code="topology.unknown",
                params={"topology_id": topology_id},
            ) from error
