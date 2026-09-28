"""V.6 real deployment, console, experiment, and structured-log correlation gate."""

import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app

TOPOLOGY = """id: log-lab
networks:
  - {id: lab, ipv4_subnet: 192.168.239.0/24}
nodes:
  - id: alpha
    name: Log alpha
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:00:03:01', ipv4: 192.168.239.31}
    services:
      - {id: shell, protocol: tcp, port: 22, implementation: ssh}
  - id: bravo
    name: Log bravo
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:00:03:02', ipv4: 192.168.239.32}
    services:
      - {id: shell, protocol: tcp, port: 22, implementation: ssh}
"""

SCENARIO = """id: log-experiment
required_topology: log-lab
initial_conditions: [topology_deployed, services_started]
permitted_actions: [ssh_exec]
sequence:
  - {id: inspect-bravo, kind: ssh_exec, target: bravo, command: hostname}
timeout_seconds: 10
success_conditions:
  - {action: inspect-bravo, field: success, equals: true}
cleanup_policy: always
"""


def lab_available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv", "sshd", "ssh")):
        return False
    return (
        subprocess.run(
            ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
        ).returncode
        == 0
    )


@pytest.mark.integration
@pytest.mark.privileged
def test_real_lab_console_experiment_log_correlation(tmp_path) -> None:
    if not lab_available():
        pytest.skip("NOT RUN — environment unavailable: namespace privileges required")
    plane = ControlPlane(tmp_path)
    client = TestClient(create_app(plane))
    try:
        loaded = client.post("/v1/topologies", json={"yaml": TOPOLOGY})
        assert loaded.status_code == 200, loaded.text
        nodes = loaded.json()["topology"]["nodes"]
        bravo_uuid = next(item["uuid"] for item in nodes if item["id"] == "bravo")
        assert client.post("/v1/deployments/log-lab").status_code == 200

        created = client.post("/v1/deployments/log-lab/nodes/alpha/console/sessions")
        assert created.status_code == 200, created.text
        session_id = created.json()["session_id"]
        session_path = f"/v1/deployments/log-lab/nodes/alpha/console/sessions/{session_id}"
        client.post(session_path + "/input", json={"data": "echo LOG-COMMAND\n"})
        cursor = 0
        output = ""
        for _ in range(40):
            update = client.get(session_path + f"/stream?after={cursor}").json()
            output += update["output"]
            cursor = update["cursor"]
            if "LOG-COMMAND" in output:
                break
            time.sleep(0.1)
        assert "LOG-COMMAND" in output
        assert client.delete(session_path).status_code == 200
        print(f"LOG-CONSOLE-SESSION-OK session={session_id} marker=LOG-COMMAND")

        experiment = client.post(
            "/v1/experiments",
            json={
                "experiment_id": "log-experiment-run",
                "topology_id": "log-lab",
                "scenario_yaml": SCENARIO,
                "wait": True,
            },
        )
        assert experiment.status_code == 200, experiment.text
        assert experiment.json()["status"] == "succeeded"

        by_node = client.get(f"/v1/logs?node={bravo_uuid}&limit=200")
        assert by_node.status_code == 200
        records = by_node.json()["records"]
        events = {item["event"] for item in records}
        assert {
            "lab.provision.complete",
            "lab.service.start",
            "experiment.action.start",
            "experiment.action.end",
            "lab.teardown.complete",
        } <= events
        session_records = client.get(f"/v1/logs?session={session_id}&limit=100").json()["records"]
        assert any(item["event"] == "console.command" for item in session_records)
        files = client.get("/v1/logs/files").json()
        file_paths = [str(item["path"]) for item in files["files"]]
        assert any(path.endswith("polmon.jsonl") for path in file_paths)
        assert any("services" in path and path.endswith("shell.log") for path in file_paths)
        missing = client.get("/v1/experiments/does-not-exist/report")
        assert missing.status_code == 422 and "LOG-COMMAND" not in missing.text
        print(
            "LOG-CORRELATION-OK node=bravo uuid="
            f"{bravo_uuid} events=provision,service,console,experiment,teardown files=bounded"
        )
    finally:
        client.close()
        plane.shutdown()
        plane.close()
