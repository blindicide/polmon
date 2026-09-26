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


def test_experiment_can_be_reported_reset_and_repeated(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path)))
    topology_id = client.post("/v1/topologies", json={"yaml": l0_source()}).json()["topology_id"]

    def run(experiment_id: str) -> dict[str, object]:
        deployed = client.post(f"/v1/deployments/{topology_id}")
        assert deployed.status_code == 200
        scenario = f"""id: report-ping
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
failure_conditions:
  - action: ping
    field: success
    equals: false
cleanup_policy: never
"""
        response = client.post(
            "/v1/experiments",
            json={
                "experiment_id": experiment_id,
                "topology_id": topology_id,
                "scenario_yaml": scenario,
            },
        )
        assert response.status_code == 200
        return response.json()

    first = run("repeat-one")
    report = client.get("/v1/experiments/repeat-one/report")
    assert report.status_code == 200
    document = report.json()
    assert document["polmon_version"] == __version__
    assert document["status"] == "succeeded"
    assert document["topology"]["id"] == topology_id
    assert document["scenario"]["id"] == "report-ping"
    assert document["expected_vs_actual"][0]["matched"] is True
    outcomes = [(item["role"], item["outcome"]) for item in document["expected_vs_actual"]]
    assert outcomes == [("success_requirement", "met"), ("failure_trigger", "not_triggered")]
    markdown = Path(first["reports"]["markdown"]).read_text(encoding="utf-8")
    assert "failure trigger `ping.success == False`: observed `True` — not triggered" in markdown
    assert "MISMATCH" not in markdown
    assert len(document["resource_statistics"]) >= 2
    samples = document["resource_statistics"]
    expected = client.get("/v1/resources").json()["snapshot"]["active_endpoints"]
    assert expected > 0 and all(item["active_endpoints"] == expected for item in samples)
    assert all(item["topology_deployment_seconds"] > 0 for item in samples)
    assert Path(first["reports"]["json"]).is_file()
    assert Path(first["reports"]["markdown"]).is_file()

    reset = client.post("/v1/reset")
    assert reset.json() == {"state": "reset", "deployments_destroyed": 1}
    second = run("repeat-two")
    assert second["status"] == "succeeded"
    assert client.post("/v1/reset").json()["deployments_destroyed"] == 1


def test_scenario_validation_failure_cleans_deployment(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path)))
    topology_id = client.post("/v1/topologies", json={"yaml": l0_source()}).json()["topology_id"]
    client.post(f"/v1/deployments/{topology_id}")
    scenario = f"""id: invalid-source
required_topology: {topology_id}
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
  - id: ping
    kind: icmp_probe
    source: outside-lab
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
        json={
            "experiment_id": "failed-validation",
            "topology_id": topology_id,
            "scenario_yaml": scenario,
        },
    )
    assert response.status_code == 422
    assert client.get(f"/v1/deployments/{topology_id}").status_code == 422


def test_reset_continues_after_failure_and_retains_failed_deployment(tmp_path) -> None:
    class Control:
        def __init__(self, fail: bool) -> None:
            self.fail = fail
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True
            if self.fail:
                raise RuntimeError("injected teardown failure")

    plane = ControlPlane(tmp_path)
    failed = Control(True)
    cleaned = Control(False)
    plane.deployments = {"failed": failed, "cleaned": cleaned}  # type: ignore[dict-item]
    try:
        plane.reset_all()
    except Exception as error:
        assert "did not clean every deployment" in str(error)
    else:
        raise AssertionError("reset should report incomplete cleanup")
    assert failed.destroyed is True and cleaned.destroyed is True
    assert set(plane.deployments) == {"failed"}


def test_api_rejects_path_like_identifiers_before_touching_files(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path)), raise_server_exceptions=False)
    topology_id = client.post("/v1/topologies", json={"yaml": l0_source()}).json()["topology_id"]
    for experiment_id in ("../escape", "a/b", ".hidden", "x" * 65):
        response = client.post(
            "/v1/experiments",
            json={"experiment_id": experiment_id, "topology_id": topology_id, "scenario_yaml": "x"},
        )
        assert response.status_code == 422, experiment_id
    for path in ("/v1/experiments/..escape/report", "/v1/deployments/Bad_Id"):
        assert client.get(path).status_code == 422, path
    assert not (tmp_path / "reports").exists() and not (tmp_path / "captures").exists()
    assert all(item.name.startswith("telemetry.sqlite3") for item in tmp_path.iterdir())


def test_report_writer_refuses_unsafe_identifiers(tmp_path) -> None:
    import pytest

    from polmon.reporting import write_experiment_report

    with pytest.raises(ValueError, match="invalid experiment identifier"):
        write_experiment_report(tmp_path, "../escape", None, None, None, [], None)  # type: ignore[arg-type]


def test_backend_shutdown_tears_down_every_deployment(tmp_path) -> None:
    control = ControlPlane(tmp_path)
    with TestClient(create_app(control)) as client:
        topology_id = client.post("/v1/topologies", json={"yaml": l0_source()}).json()[
            "topology_id"
        ]
        assert client.post(f"/v1/deployments/{topology_id}").status_code == 200
        assert control.deployments
    assert not control.deployments  # lifespan shutdown ran reset_all()
    assert topology_id in control.topologies  # definitions survive for a restart
