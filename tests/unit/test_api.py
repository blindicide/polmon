from pathlib import Path

from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.version import __version__

TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/hybrid-small.yml"


def l0_source() -> str:
    source = TOPOLOGY.read_text(encoding="utf-8").replace("class: l1", "class: l0")
    return source.replace(
        """    services:
      - id: web
        protocol: tcp
        port: 8080
        implementation: static_http
""",
        "",
    )


def test_api_validates_loads_deploys_and_resets_l0(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path)))
    assert client.get("/v1/health").json()["version"] == __version__
    validated = client.post("/v1/topologies/validate", json={"yaml": l0_source()})
    assert validated.status_code == 200 and validated.json()["valid"] is True
    loaded = client.post("/v1/topologies", json={"yaml": l0_source()}).json()
    deployed = client.post(f"/v1/deployments/{loaded['topology_id']}")
    assert deployed.status_code == 200
    assert deployed.json()["state"] == "running"
    reset = client.delete(f"/v1/deployments/{loaded['topology_id']}")
    assert reset.json()["state"] == "destroyed"


def test_api_returns_consistent_validation_error(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path)))
    response = client.post("/v1/topologies/validate", json={"yaml": "nodes: nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "configuration_error"


def test_api_runs_synthetic_experiment_and_returns_telemetry(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path)))
    topology_id = client.post("/v1/topologies", json={"yaml": l0_source()}).json()["topology_id"]
    client.post(f"/v1/deployments/{topology_id}")
    scenario = f"""id: api-ping
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
    response = client.post(
        "/v1/experiments",
        json={"experiment_id": "api-test", "topology_id": topology_id, "scenario_yaml": scenario},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    telemetry = client.get("/v1/experiments/api-test/telemetry").json()
    categories = {item["category"] for item in telemetry}
    assert categories >= {"scenario", "network_observation", "resource"}
