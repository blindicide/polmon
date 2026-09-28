from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app


def test_vnc_refuses_l0_with_a_stable_reason_code(tmp_path) -> None:
    plane = ControlPlane(tmp_path)
    client = TestClient(create_app(plane))
    source = """id: vnc-test
nodes:
  - id: sensor
    class: l0
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:00:01:01', ipv4: 192.168.230.10}
networks:
  - {id: lab, ipv4_subnet: 192.168.230.0/24}
"""
    assert client.post("/v1/topologies", json={"yaml": source}).status_code == 200
    readiness = client.get("/v1/deployments/vnc-test/nodes/sensor/console/readiness")
    assert readiness.status_code == 200
    assert "console.l1_required" in readiness.json()["vnc"]["reason_codes"]
    refused = client.post("/v1/deployments/vnc-test/nodes/sensor/console/vnc")
    assert refused.status_code == 422
    assert refused.json()["error"]["message_code"] == "console.l1_required"
    plane.shutdown()
