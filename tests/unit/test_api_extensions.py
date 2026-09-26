"""API additions that back the Qt client: inspection, async experiments, paging, benchmarks."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polmon.api import control as control_module
from polmon.api.benchmarks import BenchmarkRequest, benchmark_command
from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.core.errors import ConfigurationError
from polmon.resources import ResourceLimits

TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/hybrid-small.yml"
LIMITS = {
    "max_endpoints": 50,
    "max_namespaces": 0,
    "max_run_seconds": 60,
    "max_incremental_mb": 256,
    "memory_reserve_mb": 256,
}


def l0_source() -> str:
    source = TOPOLOGY.read_text(encoding="utf-8").replace("class: l1", "class: l0")
    return source.replace(
        "    services:\n      - id: web\n        protocol: tcp\n        port: 8080\n"
        "        implementation: static_http\n",
        "",
    )


def scenario(topology_id: str = "hybrid-small", actions: int = 1, timeout: float = 5) -> str:
    sequence = "".join(
        f"  - {{id: ping-{index}, kind: icmp_probe, source: sensor-1, target: service-1}}\n"
        for index in range(actions)
    )
    return f"""id: api-async
required_topology: {topology_id}
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
{sequence}timeout_seconds: {timeout}
success_conditions:
  - {{action: ping-0, field: success, equals: true}}
cleanup_policy: never
"""


PLANES: list[ControlPlane] = []


@pytest.fixture(autouse=True)
def shut_down_planes():
    """Deployments own process-wide resources: every plane is shut down after each test."""
    yield
    while PLANES:
        PLANES.pop().shutdown()


def app_client(tmp_path, **kwargs) -> TestClient:
    plane = ControlPlane(tmp_path, **kwargs)
    PLANES.append(plane)
    return TestClient(create_app(plane))


def deployed_client(tmp_path, **kwargs) -> TestClient:
    client = app_client(tmp_path, **kwargs)
    assert client.post("/v1/topologies", json={"yaml": l0_source()}).status_code == 200
    deployed = client.post("/v1/deployments/hybrid-small")
    assert deployed.status_code == 200, deployed.text
    return client


def wait_for(client: TestClient, path: str, done, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = client.get(path).json()
        if done(document):
            return document
        time.sleep(0.05)
    raise AssertionError(f"{path} did not reach the expected state: {document}")


def test_validation_returns_a_structured_topology_for_inspection(tmp_path) -> None:
    client = app_client(tmp_path)
    document = client.post("/v1/topologies/validate", json={"yaml": l0_source()}).json()
    nodes = {node["id"]: node for node in document["topology"]["nodes"]}
    interface = nodes["sensor-1"]["interfaces"][0]
    assert nodes["sensor-1"]["class"] == "l0"
    assert set(interface) >= {"id", "network", "mac", "ipv4"}
    assert document["topology"]["networks"][0]["ipv4_subnet"]
    assert document["resources"]["endpoint_count"] == len(nodes)


def test_loaded_topologies_are_listed_with_deployment_state(tmp_path) -> None:
    client = app_client(tmp_path)
    assert client.get("/v1/topologies").json() == []
    client.post("/v1/topologies", json={"yaml": l0_source()})
    listed = client.get("/v1/topologies").json()
    assert [item["topology_id"] for item in listed] == ["hybrid-small"]
    assert listed[0]["deployed"] is False and listed[0]["node_count"] >= 2
    client.post("/v1/deployments/hybrid-small")
    detail = client.get("/v1/topologies/hybrid-small").json()
    assert detail["deployed"] is True and detail["topology"]["id"] == "hybrid-small"
    assert client.get("/v1/topologies/missing").status_code == 422


def test_scenario_validation_reports_structure_and_topology_compatibility(tmp_path) -> None:
    client = app_client(tmp_path)
    unloaded = client.post("/v1/scenarios/validate", json={"yaml": scenario()}).json()
    assert unloaded["scenario"]["sequence"][0]["kind"] == "icmp_probe"
    assert unloaded["scenario"]["permitted_actions"] == ["icmp_probe"]
    assert unloaded["topology_check"] == {
        "topology_id": "hybrid-small",
        "loaded": False,
        "deployed": False,
        "compatible": False,
        "problems": [],
    }
    client.post("/v1/topologies", json={"yaml": l0_source()})
    compatible = client.post("/v1/scenarios/validate", json={"yaml": scenario()}).json()
    assert compatible["topology_check"]["compatible"] is True
    broken = scenario().replace("source: sensor-1", "source: nowhere")
    problems = client.post("/v1/scenarios/validate", json={"yaml": broken}).json()
    assert problems["topology_check"]["compatible"] is False
    assert "outside the designated topology" in problems["topology_check"]["problems"][0]
    invalid = client.post("/v1/scenarios/validate", json={"yaml": "id: x"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["details"]["errors"]


def test_async_experiment_reports_progress_live_telemetry_and_reports(tmp_path) -> None:
    client = deployed_client(tmp_path)
    started = client.post(
        "/v1/experiments",
        json={
            "experiment_id": "async-1",
            "topology_id": "hybrid-small",
            "scenario_yaml": scenario(actions=3),
            "wait": False,
        },
    )
    assert started.status_code == 202
    assert started.json()["status"] in {"running", "succeeded"}
    final = wait_for(
        client, "/v1/experiments/async-1", lambda item: item["status"] not in {"running"}
    )
    assert final["status"] == "succeeded"
    assert final["progress"]["completed_actions"] == final["progress"]["total_actions"] == 3
    events = client.get("/v1/experiments/async-1/telemetry").json()
    observations = [item for item in events if item["category"] == "network_observation"]
    assert [item["event"] for item in observations] == ["ping-0", "ping-1", "ping-2"]
    page = client.get(
        "/v1/experiments/async-1/telemetry", params={"after": events[1]["sequence"], "limit": 2}
    ).json()
    assert [item["sequence"] for item in page] == [item["sequence"] for item in events[2:4]]
    listed = client.get("/v1/experiments").json()
    assert listed[0]["experiment_id"] == "async-1" and listed[0]["report_available"] is True
    assert listed[0]["capture"]["frame_count"] >= 1
    markdown = client.get("/v1/experiments/async-1/report/markdown").json()["markdown"]
    assert "async-1" in markdown


def test_async_rejections_surface_on_the_post(tmp_path) -> None:
    client = deployed_client(tmp_path, limits=ResourceLimits(max_experiment_duration_seconds=10))
    response = client.post(
        "/v1/experiments",
        json={
            "experiment_id": "too-long",
            "topology_id": "hybrid-small",
            "scenario_yaml": scenario(timeout=60),
            "wait": False,
        },
    )
    assert response.status_code == 429
    details = response.json()["error"]["details"]
    assert details["duration_seconds"] == {"requested": 60.0, "limit": 10.0}


def test_async_experiment_can_be_cancelled(tmp_path, monkeypatch) -> None:
    original = control_module.SyntheticScenarioExecutor.execute

    def slow(self, action, topology, timeout_seconds):
        time.sleep(0.2)
        return original(self, action, topology, timeout_seconds)

    monkeypatch.setattr(control_module.SyntheticScenarioExecutor, "execute", slow)
    client = deployed_client(tmp_path)
    client.post(
        "/v1/experiments",
        json={
            "experiment_id": "cancel-me",
            "topology_id": "hybrid-small",
            "scenario_yaml": scenario(actions=20, timeout=60),
            "wait": False,
        },
    )
    running = client.get("/v1/experiments/cancel-me").json()
    assert running["status"] == "running" and running["progress"]["total_actions"] == 20
    assert client.post("/v1/experiments/cancel-me/cancel").json()["state"] == "cancelling"
    final = wait_for(
        client,
        "/v1/experiments/cancel-me",
        lambda item: item["status"] not in {"running", "cancelling"},
    )
    assert final["status"] == "cancelled"
    assert final["progress"]["completed_actions"] < 20


def test_background_failures_are_recorded_not_lost(tmp_path, monkeypatch) -> None:
    def explode(self, *args):
        raise ConfigurationError("simulated failure", details={"where": "test"})

    monkeypatch.setattr(ControlPlane, "_execute_experiment", explode)
    client = deployed_client(tmp_path)
    client.post(
        "/v1/experiments",
        json={
            "experiment_id": "broken",
            "topology_id": "hybrid-small",
            "scenario_yaml": scenario(),
            "wait": False,
        },
    )
    final = wait_for(client, "/v1/experiments/broken", lambda item: item["status"] == "error")
    assert final["error"]["message"] == "simulated failure"


def test_experiments_survive_a_backend_restart_and_ids_stay_unique(tmp_path) -> None:
    client = deployed_client(tmp_path)
    body = {"experiment_id": "persisted", "topology_id": "hybrid-small"}
    assert (
        client.post("/v1/experiments", json={**body, "scenario_yaml": scenario()}).json()["status"]
        == "succeeded"
    )
    PLANES.pop().shutdown()  # the first process stops before the second starts
    restarted = deployed_client(tmp_path)
    stored = restarted.get("/v1/experiments/persisted").json()
    assert stored["status"] == "succeeded" and stored["persisted"] is True
    again = restarted.post("/v1/experiments", json={**body, "scenario_yaml": scenario()})
    assert again.status_code == 422 and "already exists" in again.json()["error"]["message"]


def test_benchmark_requests_are_admitted_against_backend_limits(tmp_path) -> None:
    client = app_client(tmp_path)
    too_big = client.post(
        "/v1/benchmarks",
        json={"kind": "l0", "limits": {**LIMITS, "max_endpoints": 5000, "memory_reserve_mb": 1}},
    )
    assert too_big.status_code == 429
    details = too_big.json()["error"]["details"]
    assert details["max_endpoints"] == {"requested": 5000, "limit": 250}
    assert details["memory_reserve_mb"] == {"requested": 1, "minimum": 256}
    large = client.post("/v1/benchmarks", json={"kind": "l0", "counts": [100], "limits": LIMITS})
    assert large.status_code == 422
    missing = client.post("/v1/benchmarks", json={"kind": "l0"})
    assert missing.status_code == 422  # limits are always explicit


def test_benchmark_command_carries_every_limit(tmp_path) -> None:
    request = BenchmarkRequest.model_validate({"kind": "l0", "counts": [10], "limits": LIMITS})
    command = benchmark_command(request, tmp_path)
    for flag, value in (("--max-endpoints", "50"), ("--memory-reserve-mb", "256")):
        assert command[command.index(flag) + 1] == value
    assert command[-1] == "--json" and str(tmp_path) in command


def fake_launcher(command, stdout):
    script = (
        "import sys, time\n"
        "print('[benchmark l0]  33.3% step 1/3 elapsed 0.1s eta 0.2s endpoints=10 repeat=1',"
        " file=sys.stderr, flush=True)\n"
        "time.sleep(30)\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=stdout,
        stderr=subprocess.PIPE,
        start_new_session=sys.platform != "win32",
    )


def test_benchmark_jobs_report_progress_and_can_be_cancelled(tmp_path) -> None:
    plane = ControlPlane(tmp_path)
    PLANES.append(plane)
    plane.benchmarks._launcher = fake_launcher
    client = TestClient(create_app(plane))
    job = client.post("/v1/benchmarks", json={"kind": "l0", "limits": LIMITS})
    assert job.status_code == 202
    job_id = job.json()["job_id"]
    progressed = wait_for(
        client,
        f"/v1/benchmarks/jobs/{job_id}",
        lambda item: item["progress"]["completed_steps"] == 1,
    )
    assert progressed["progress"]["total_steps"] == 3
    assert progressed["progress"]["detail"] == "endpoints=10 repeat=1"
    second = client.post("/v1/benchmarks", json={"kind": "l0", "limits": LIMITS})
    assert second.status_code == 429
    assert "concurrent_benchmarks" in second.json()["error"]["details"]
    client.post("/v1/topologies", json={"yaml": l0_source()})
    client.post("/v1/deployments/hybrid-small")
    refused = client.post(
        "/v1/experiments",
        json={
            "experiment_id": "blocked",
            "topology_id": "hybrid-small",
            "scenario_yaml": scenario(),
        },
    )
    assert refused.status_code == 429
    assert client.post(f"/v1/benchmarks/jobs/{job_id}/cancel").status_code == 200
    final = wait_for(
        client, f"/v1/benchmarks/jobs/{job_id}", lambda item: item["state"] != "running"
    )
    assert final["state"] == "cancelled"
    assert client.get("/v1/benchmarks/jobs").json()[0]["job_id"] == job_id


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="benchmarks measure via procfs")
def test_real_l0_benchmark_job_retains_a_result(tmp_path) -> None:
    client = app_client(tmp_path)
    job = client.post(
        "/v1/benchmarks",
        json={"kind": "l0", "counts": [3], "idle_seconds": 0, "limits": LIMITS},
    ).json()
    final = wait_for(
        client,
        f"/v1/benchmarks/jobs/{job['job_id']}",
        lambda item: item["state"] != "running",
        timeout=90,
    )
    assert final["state"] == "succeeded", final
    assert final["progress"]["completed_steps"] == 1
    results = client.get("/v1/benchmarks/results").json()
    assert results[0]["name"] == final["result_name"] and results[0]["benchmark"] == "l0"
    detail = client.get(f"/v1/benchmarks/results/{final['result_name']}").json()
    assert detail["document"]["measurements"][0]["endpoint_count"] == 3
    assert "l0" in (detail["summary_markdown"] or "")
    assert client.get("/v1/benchmarks/results/..%2Fsecret.json").status_code in {404, 422}
