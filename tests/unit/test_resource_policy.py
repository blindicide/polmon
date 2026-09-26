from pathlib import Path

import pytest

from polmon.api.control import ControlPlane
from polmon.backends.mock import MockBackend
from polmon.core.diagnostics import ResourceSnapshot
from polmon.resources import (
    AdmissionController,
    ResourceLimitError,
    ResourceLimits,
    ResourceMonitor,
)
from polmon.scenarios import ScenarioEngine, load_scenario
from polmon.scenarios.engine import ExecutionStatus, Observation
from polmon.topology import load_topology

L1_TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"
HYBRID_TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/hybrid-small.yml"
SCENARIO = Path(__file__).parents[2] / "examples/scenarios/recon.yml"


def snapshot(available_mb: int = 2_048) -> ResourceSnapshot:
    return ResourceSnapshot(1, 0.1, 1.0, available_mb * 1_048_576, 0)


def l0_source() -> str:
    source = HYBRID_TOPOLOGY.read_text(encoding="utf-8").replace("class: l1", "class: l0")
    return source.replace(
        """    services:
      - id: web
        protocol: tcp
        port: 8080
        implementation: static_http
""",
        "",
    )


def test_admission_rejects_endpoint_namespace_memory_duration_and_concurrency() -> None:
    topology = load_topology(L1_TOPOLOGY)
    restrictive = ResourceLimits(
        max_endpoint_count=1,
        max_active_namespaces=1,
        max_concurrent_experiments=1,
        max_experiment_duration_seconds=5,
        memory_safety_threshold_mb=2_000,
    )
    admission = AdmissionController(restrictive, snapshot=lambda: snapshot())
    with pytest.raises(ResourceLimitError) as topology_error:
        admission.admit_topology(topology, [])
    assert set(topology_error.value.details) == {
        "endpoint_count",
        "active_namespaces",
        "available_memory",
    }
    with pytest.raises(ResourceLimitError) as experiment_error:
        admission.admit_experiment(load_scenario(SCENARIO), active_count=1)
    assert set(experiment_error.value.details) == {
        "concurrent_experiments",
        "duration_seconds",
    }


def test_resource_monitor_samples_and_requests_cancellation() -> None:
    samples = []
    cancellations = []
    limits = ResourceLimits(memory_safety_threshold_mb=256)
    monitor = ResourceMonitor(
        limits,
        lambda reason, sample: cancellations.append((reason, sample)),
        on_sample=samples.append,
        snapshot=lambda: snapshot(128),
    )
    assert monitor.sample_once() is False
    assert samples and cancellations
    assert "below" in cancellations[0][0]


def test_monitor_signal_cancels_scenario_before_next_action() -> None:
    engine = ScenarioEngine()
    actions = []

    class Executor:
        def execute(self, action, topology, timeout_seconds):
            actions.append(action.id)
            return Observation(action.id, True, "reachable")

    monitor = ResourceMonitor(
        ResourceLimits(memory_safety_threshold_mb=256),
        lambda reason, sample: engine.cancel(),
        snapshot=lambda: snapshot(128),
    )
    engine.reset_cancellation()
    assert monitor.sample_once() is False
    result = engine.run(
        load_scenario(SCENARIO),
        load_topology(L1_TOPOLOGY),
        Executor(),
        lambda: None,
        reset_cancellation=False,
        precondition=lambda condition: True,
    )
    assert result.status is ExecutionStatus.CANCELLED
    assert not actions


def test_control_plane_rejects_before_create_and_exposes_status(tmp_path) -> None:
    limits = ResourceLimits(max_endpoint_count=1, memory_safety_threshold_mb=0)
    plane = ControlPlane(tmp_path, limits=limits, snapshot=lambda: snapshot())
    source = L1_TOPOLOGY.read_text(encoding="utf-8")
    topology_id = str(plane.load_topology(source)["topology_id"])
    with pytest.raises(ResourceLimitError):
        plane.deploy(topology_id)
    assert not plane.deployments
    status = plane.resource_status()
    assert status["limits"]["max_endpoint_count"] == 1
    assert status["active_deployments"] == 0


def test_failed_deployment_is_recoverable(tmp_path) -> None:
    plane = ControlPlane(
        tmp_path,
        limits=ResourceLimits(memory_safety_threshold_mb=0),
        snapshot=lambda: snapshot(),
    )
    source = L1_TOPOLOGY.read_text(encoding="utf-8")
    topology_id = str(plane.load_topology(source)["topology_id"])
    backend = MockBackend(fail_on="start")
    plane._backend = lambda topology: backend  # type: ignore[method-assign]
    with pytest.raises(Exception, match="start"):
        plane.deploy(topology_id)
    assert not plane.deployments
    assert not backend.resources
    backend.fail_on = None
    assert plane.deploy(topology_id)["state"] == "running"
    assert plane.reset_all()["deployments_destroyed"] == 1


def test_control_plane_cancellation_and_capture_limit(tmp_path) -> None:
    limits = ResourceLimits(max_capture_bytes=24, memory_safety_threshold_mb=0)
    plane = ControlPlane(tmp_path, limits=limits, snapshot=lambda: snapshot())
    engine = ScenarioEngine()
    plane.active_experiments["running"] = engine
    assert plane.cancel_experiment("running")["state"] == "cancelling"
    plane.active_experiments.clear()

    topology_id = str(plane.load_topology(l0_source())["topology_id"])
    plane.deploy(topology_id)
    scenario = f"""id: bounded-capture
required_topology: {topology_id}
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
  - id: ping
    kind: icmp_probe
    source: sensor-1
    target: service-1
timeout_seconds: 5
success_conditions:
  - action: ping
    field: success
    equals: true
cleanup_policy: always
"""
    result = plane.run_experiment("bounded", topology_id, scenario)
    assert result["capture"]["captured_bytes"] == 24
    assert result["capture"]["dropped_frames"] > 0
