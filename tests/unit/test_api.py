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


def test_l0_only_backend_advertises_and_enforces_fidelity(tmp_path) -> None:
    plane = ControlPlane(tmp_path, l0_only=True)
    client = TestClient(create_app(plane))
    health = client.get("/v1/health").json()
    assert health["capabilities"] == {
        "fidelity": "l0_only",
        "l0": True,
        "l1": False,
        "l2": False,
        "hybrid_tap": False,
    }
    hybrid = TOPOLOGY.read_text(encoding="utf-8")
    assert client.post("/v1/topologies", json={"yaml": hybrid}).status_code == 200
    refused = client.post("/v1/deployments/hybrid-small")
    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == (
        "Local backend supports L0 synthetic nodes only; L1/L2 requires a polmon backend on a "
        "Linux host with network namespace privileges."
    )
    l2 = l0_source().replace("id: hybrid-small", "id: needs-l2").replace(
        "class: l0", "class: l2", 1
    )
    assert client.post("/v1/topologies", json={"yaml": l2}).status_code == 200
    l2_refused = client.post("/v1/deployments/needs-l2")
    assert l2_refused.status_code == 422
    assert l2_refused.json()["error"]["message"] == refused.json()["error"]["message"]
    assert plane.deployments == {}


def test_linux_backend_cleanly_refuses_l1_when_host_is_not_ready(tmp_path, monkeypatch) -> None:
    from polmon.api import control as control_module

    checks = {
        "tool_ip": {"ok": False},
        "tool_sudo": {"ok": True},
        "tool_setpriv": {"ok": True},
        "tool_ping": {"ok": True},
        "ping_unprivileged": {"ok": True},
        "passwordless_sudo_ip": {"ok": False},
        "tun_device": {"ok": False},
    }
    monkeypatch.setattr(
        control_module,
        "fidelity_readiness",
        lambda: {"l1_ready": False, "hybrid_ready": False, "checks": checks},
    )
    plane = ControlPlane(tmp_path)
    client = TestClient(create_app(plane))
    l1 = l0_source().replace("id: hybrid-small", "id: needs-l1").replace(
        "class: l0", "class: l1"
    )
    assert client.post("/v1/topologies", json={"yaml": l1}).status_code == 200
    refused = client.post("/v1/deployments/needs-l1")
    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == (
        "L1/hybrid deployment requires a Linux host with iproute2, unprivileged ping, and "
        "passwordless sudo restricted to network namespace operations."
    )
    assert refused.json()["error"]["details"]["unavailable_checks"] == [
        "tool_ip",
        "passwordless_sudo_ip",
    ]
    assert plane.deployments == {}


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


def test_oversized_bodies_are_rejected_before_parsing(tmp_path) -> None:
    from polmon.api.limits import MAX_REQUEST_BYTES

    client = TestClient(create_app(ControlPlane(tmp_path)))
    oversized = b"{" + b" " * MAX_REQUEST_BYTES + b"}"
    declared = client.post(
        "/v1/topologies/validate", content=oversized, headers={"content-type": "application/json"}
    )
    assert declared.status_code == 413
    assert declared.json()["error"]["code"] == "request_too_large"

    def chunks():
        for _ in range(6):
            yield b" " * 1_048_576

    chunked = client.post(
        "/v1/topologies/validate", content=chunks(), headers={"content-type": "application/json"}
    )
    assert chunked.status_code == 413
    assert client.get("/v1/health").status_code == 200  # the server keeps serving


def test_experiments_are_refused_when_storage_bounds_would_be_crossed(tmp_path) -> None:
    from polmon.resources import ResourceLimits

    scenario = """id: storage
required_topology: hybrid-small
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
  - {id: ping, kind: icmp_probe, source: sensor-1, target: service-1}
timeout_seconds: 5
success_conditions:
  - {action: ping, field: success, equals: true}
"""
    cases = {
        "data_directory": ResourceLimits(max_data_directory_mb=1),
        "disk_free": ResourceLimits(disk_free_reserve_mb=10_485_760),
    }
    for violation, limits in cases.items():
        directory = tmp_path / violation
        control = ControlPlane(directory, limits=limits)
        (directory / "earlier-artifacts.bin").write_bytes(b"\0" * 600_000)
        client = TestClient(create_app(control))
        topology_id = client.post("/v1/topologies", json={"yaml": l0_source()}).json()[
            "topology_id"
        ]
        client.post(f"/v1/deployments/{topology_id}")
        response = client.post(
            "/v1/experiments",
            json={
                "experiment_id": "blocked",
                "topology_id": topology_id,
                "scenario_yaml": scenario,
            },
        )
        assert response.status_code == 429, violation
        assert violation in response.json()["error"]["details"]
        assert not (directory / "reports").exists() and not (directory / "captures").exists()
        assert client.get("/v1/resources").json()["data_directory_bytes"] >= 600_000
        client.post("/v1/reset")
