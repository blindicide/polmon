import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.client.api import ApiClient

SCENARIO = Path(__file__).parents[2] / "examples/scenarios/recon.yml"
TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"


def available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv")):
        return False
    return subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    ).returncode == 0


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.mark.integration
@pytest.mark.privileged
def test_client_controls_real_l1_over_live_http(tmp_path) -> None:
    if not available():
        pytest.skip("NOT RUN — environment unavailable: namespace privileges required")
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(ControlPlane(tmp_path)),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.05)
    client = ApiClient(f"http://127.0.0.1:{port}")
    topology_id = "l1-two-node"
    try:
        assert client.health()["status"] == "ok"
        client.load_topology(TOPOLOGY.read_text(encoding="utf-8"))
        deployment = client.deploy(topology_id)
        assert deployment["state"] == "running"
        result = client.run_experiment(
            "client-real-l1", topology_id, SCENARIO.read_text(encoding="utf-8")
        )
        assert result["status"] == "succeeded"
        assert len(client.telemetry("client-real-l1")) >= 4
    finally:
        try:
            client.destroy(topology_id)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
