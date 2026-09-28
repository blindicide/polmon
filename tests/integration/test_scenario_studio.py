"""V.5 scenario-library and real L1 execution gate."""

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app

TOPOLOGY = """id: scenario-studio
networks:
  - {id: lab, ipv4_subnet: 192.168.239.0/24}
nodes:
  - id: client
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:00:02:01', ipv4: 192.168.239.21}
  - id: server
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:00:02:02', ipv4: 192.168.239.22}
    services:
      - {id: web, protocol: tcp, port: 8080, implementation: static_http}
      - {id: shell, protocol: tcp, port: 22, implementation: ssh}
"""

SCENARIO = r"""id: operator-authored
required_topology: scenario-studio
initial_conditions: [topology_deployed, services_started]
permitted_actions: [icmp_probe, tcp_probe, ssh_exec, wait]
sequence:
  - {id: reach-server, kind: icmp_probe, source: client, target: server}
  - {id: inspect-web, kind: tcp_probe, source: client, target: server, service: web}
  - id: inspect-address
    kind: ssh_exec
    target: server
    command: ip_addr
  - {id: pause, kind: wait, seconds: 0.1}
timeout_seconds: 20
success_conditions:
  - {action: reach-server, field: success, equals: true}
  - {action: inspect-web, field: success, equals: true}
  - {action: inspect-address, field: success, equals: true}
  - {action: inspect-address, field: stdout, pattern: '192\.168\.239\.22'}
  - {action: inspect-address, field: duration_seconds, minimum: 0, maximum: 10}
  - {action: pause, field: duration_seconds, minimum: 0, maximum: 1}
cleanup:
  - {id: cleanup-pause, kind: wait, seconds: 0.1}
cleanup_policy: always
"""


def lab_available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv", "sshd", "ssh")):
        return False
    result = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    )
    return result.returncode == 0


@pytest.mark.integration
@pytest.mark.privileged
def test_operator_authored_scenario_pass_fail_and_restart(tmp_path) -> None:
    if not lab_available():
        pytest.skip("NOT RUN — environment unavailable: namespace privileges required")

    first_plane = ControlPlane(tmp_path)
    first_client = TestClient(create_app(first_plane))
    try:
        assert first_client.post("/v1/topologies", json={"yaml": TOPOLOGY}).status_code == 200
        created = first_client.post("/v1/scenarios", json={"yaml": SCENARIO})
        assert created.status_code == 200, created.text
        assert created.json()["scenario_id"] == "operator-authored"
        assert first_client.get("/v1/scenarios").json()[0]["action_count"] == 4
        print("SCENARIO-API-CREATED operator-authored ICMP TCP SSH WAIT CLEANUP")
    finally:
        first_client.close()
        first_plane.close()

    second_plane = ControlPlane(tmp_path)
    second_client = TestClient(create_app(second_plane))
    try:
        restored = second_client.get("/v1/scenarios/operator-authored")
        assert restored.status_code == 200
        assert "cleanup:" in restored.json()["yaml"]
        print("SCENARIO-LIBRARY-RESTART-OK operator-authored")

        assert second_client.post("/v1/deployments/scenario-studio").status_code == 200
        passed = second_client.post(
            "/v1/experiments",
            json={
                "experiment_id": "scenario-pass",
                "topology_id": "scenario-studio",
                "scenario_yaml": restored.json()["yaml"],
                "wait": True,
            },
        )
        assert passed.status_code == 200, passed.text
        passing_record = passed.json()
        assert passing_record["status"] == "succeeded"
        assert [item["success"] for item in passing_record["observations"]] == [
            True,
            True,
            True,
            True,
        ]
        assert passing_record["cleanup_performed"] is True
        assert second_plane.deployments == {}
        print(
            "SCENARIO-PASS status=succeeded actions=4 observations=4 "
            "stdout=192.168.239.22 timing=bounded cleanup=true"
        )

        failing_source = SCENARIO.replace(r"192\.168\.239\.22", r"198\.51\.100\.77")
        assert second_client.post("/v1/deployments/scenario-studio").status_code == 200
        failed = second_client.post(
            "/v1/experiments",
            json={
                "experiment_id": "scenario-fail",
                "topology_id": "scenario-studio",
                "scenario_yaml": failing_source,
                "wait": True,
            },
        )
        assert failed.status_code == 200, failed.text
        failed_record = failed.json()
        assert failed_record["status"] == "failed"
        assert failed_record["cleanup_performed"] is True
        assert second_plane.deployments == {}
        print("SCENARIO-FAIL status=failed output-assertion=false cleanup=true")
    finally:
        second_plane.shutdown()
        second_plane.close()
        second_client.close()
