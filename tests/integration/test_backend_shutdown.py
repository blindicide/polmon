"""An interrupted backend (SIGTERM / Ctrl-C) must not leave laboratory resources behind."""

import json
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

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


def request(port: int, method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    call = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(call, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.mark.integration
@pytest.mark.privileged
@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
def test_backend_signal_tears_down_live_l1_deployment(tmp_path, stop_signal) -> None:
    if not available():
        pytest.skip("NOT RUN — environment unavailable: namespace privileges required")
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "polmon.backend", "--port", str(port), "--log-level", "INFO"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    namespaces: list[str] = []
    try:
        for _ in range(100):
            try:
                request(port, "GET", "/v1/health")
                break
            except OSError:
                time.sleep(0.1)
        topology = request(
            port, "POST", "/v1/topologies", {"yaml": TOPOLOGY.read_text(encoding="utf-8")}
        )
        deployment = request(port, "POST", f"/v1/deployments/{topology['topology_id']}")
        namespaces = [
            item.split(":", 1)[1] for item in deployment["resources"] if item.startswith("netns:")
        ]
        assert len(namespaces) == 2
        listed = subprocess.run(
            ["sudo", "-n", "ip", "netns", "list"], capture_output=True, text=True, check=True
        ).stdout
        assert all(name in listed for name in namespaces)
        server.send_signal(stop_signal)
        output, _ = server.communicate(timeout=30)
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate()
    listed = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, text=True, check=True
    ).stdout
    assert not [name for name in namespaces if name in listed], output
    assert "shutdown_cleanup" in output and "shutdown_cleanup_failed" not in output
