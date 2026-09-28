from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.scenarios import dump_scenario, parse_scenario
from polmon.scenarios.engine import ExecutionStatus, Observation, ScenarioEngine
from polmon.topology import parse_topology

SCENARIO = """id: authored
required_topology: lab
initial_conditions: [topology_deployed]
permitted_actions: [ssh_exec, wait]
sequence:
  - id: get-hostname
    kind: ssh_exec
    target: server
    command: hostname
  - id: pause
    kind: wait
    seconds: 0.1
timeout_seconds: 5
success_conditions:
  - {action: get-hostname, field: stdout, pattern: 'server'}
cleanup:
  - {id: cleanup-wait, kind: wait, seconds: 0.1}
"""


def test_scenario_library_crud_survives_restart(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path)))
    created = client.post("/v1/scenarios", json={"yaml": SCENARIO})
    assert created.status_code == 200
    assert created.json()["scenario_id"] == "authored"
    assert client.get("/v1/scenarios").json()[0]["action_count"] == 2
    detail = client.get("/v1/scenarios/authored").json()
    assert "cleanup:" in detail["yaml"]

    restarted = TestClient(create_app(ControlPlane(tmp_path)))
    assert restarted.get("/v1/scenarios/authored").json()["scenario"]["id"] == "authored"
    changed = SCENARIO.replace("seconds: 0.1", "seconds: 0.2", 1)
    assert restarted.put("/v1/scenarios/authored", json={"yaml": changed}).status_code == 200
    assert restarted.delete("/v1/scenarios/authored").json()["state"] == "deleted"


def test_scenario_dump_preserves_catalogue_and_cleanup() -> None:
    scenario = parse_scenario(SCENARIO)
    restored = parse_scenario(dump_scenario(scenario))
    assert restored == scenario
    assert restored.sequence[0].command == "hostname"
    assert restored.cleanup_steps[0].kind.value == "wait"


def test_cleanup_steps_run_and_timing_output_is_assertable() -> None:
    scenario = parse_scenario(
        SCENARIO.replace(
            "field: stdout, pattern: 'server'",
            "field: duration_seconds, minimum: 0, maximum: 1",
        )
    )
    calls: list[str] = []

    class Executor:
        def execute(self, action, topology, timeout_seconds):
            calls.append(action.id)
            if action.id == "get-hostname":
                return Observation(
                    action.id,
                    True,
                    "exit_status=0",
                    {"stdout": "server\n", "duration_seconds": 0.01},
                )
            return Observation(action.id, True, "waited", {"duration_seconds": 0.1})

    topology = parse_topology(
        """id: lab
networks: [{id: net, ipv4_subnet: 192.168.230.0/24}]
nodes:
  - id: server
    class: l1
    interfaces: [{id: eth0, network: net, mac: '02:50:4f:00:01:01', ipv4: 192.168.230.10}]
    services: [{id: ssh, protocol: tcp, port: 22, implementation: ssh}]
"""
    )
    result = ScenarioEngine().run(
        scenario,
        topology,
        Executor(),
        lambda: calls.append("teardown"),
        precondition=lambda _: True,
    )
    assert result.status is ExecutionStatus.SUCCEEDED
    assert calls == ["get-hostname", "pause", "cleanup-wait", "teardown"]
