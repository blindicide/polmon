"""A backend killed without cleanup (SIGKILL) is recovered by the next backend on its data dir."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[2] / "examples/topologies"


def available(*tools: str) -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv", *tools)):
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
    with urllib.request.urlopen(call, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def start_backend(directory: Path, port: int) -> subprocess.Popen[str]:
    server = subprocess.Popen(
        [sys.executable, "-m", "polmon.backend", "--port", str(port), "--log-level", "INFO"],
        cwd=directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for _ in range(150):
        try:
            request(port, "GET", "/v1/health")
            return server
        except OSError:
            time.sleep(0.1)
    server.kill()
    raise AssertionError(server.communicate()[0])


def namespaces() -> set[str]:
    listed = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, text=True, check=True
    ).stdout
    return {line.split()[0] for line in listed.splitlines() if line.strip()}


def links() -> set[str]:
    return set(os.listdir("/sys/class/net"))


def host_links() -> set[str]:
    return {name for name in links() if not name.startswith(("polmon", "veth"))}


def namespace_pids(name: str) -> set[int]:
    output = subprocess.run(
        ["sudo", "-n", "ip", "netns", "pids", name], capture_output=True, text=True, check=False
    ).stdout
    return {int(item) for item in output.split()}


def stop(server: subprocess.Popen[str]) -> str:
    if server.poll() is None:
        server.send_signal(signal.SIGTERM)
    try:
        return server.communicate(timeout=60)[0]
    except subprocess.TimeoutExpired:
        server.kill()
        return server.communicate()[0]


@pytest.mark.integration
@pytest.mark.privileged
@pytest.mark.parametrize(
    ("example", "tools", "vnc_node"),
    [
        ("l1-console.yml", ("sshd", "Xvfb", "x11vnc", "xclock"), "server"),
        ("hybrid-tap.yml", (), None),
    ],
)
def test_sigkilled_backend_is_reclaimed_by_its_successor(tmp_path, example, tools, vnc_node):
    needs_tun = example.startswith("hybrid")
    if not available(*tools) or (needs_tun and not Path("/dev/net/tun").exists()):
        pytest.skip("NOT RUN — environment unavailable: namespace privileges/tools required")
    source = (EXAMPLES / example).read_text(encoding="utf-8")
    host_links_before = host_links()
    port = free_port()
    first = start_backend(tmp_path, port)
    second: subprocess.Popen[str] | None = None
    try:
        topology = request(port, "POST", "/v1/topologies", {"yaml": source})["topology_id"]
        deployment = request(port, "POST", f"/v1/deployments/{topology}")
        owned_namespaces = {
            item.split(":", 1)[1] for item in deployment["resources"] if item.startswith("netns:")
        }
        owned_links = {
            item.split(":", 1)[1]
            for item in deployment["resources"]
            if item.split(":", 1)[0] in {"bridge", "link", "tap"}
        }
        if vnc_node is not None:
            request(port, "POST", f"/v1/deployments/{topology}/nodes/{vnc_node}/console/vnc")
            time.sleep(1.0)
        journal = list((tmp_path / "var" / "state" / "lab-ownership").glob("*.json"))
        assert len(journal) == 1 and json.loads(journal[0].read_text())["state"] == "created"

        first.send_signal(signal.SIGKILL)
        first.communicate(timeout=10)
        # The crash left everything behind, including processes inside the namespaces.
        assert owned_namespaces <= namespaces()
        assert owned_links <= links()
        leaked = set().union(*(namespace_pids(name) for name in owned_namespaces))
        if example == "l1-console.yml":
            assert len(leaked) >= 5  # 2 sshd + static_http + Xvfb/xclock/x11vnc

        second = start_backend(tmp_path, port)
        assert not owned_namespaces & namespaces()
        assert not owned_links & links()
        time.sleep(0.5)
        assert not [pid for pid in leaked if Path(f"/proc/{pid}").exists()]
        assert list((tmp_path / "var" / "state" / "lab-ownership").glob("*.json")) == []
        status = request(port, "GET", "/v1/resources")
        recovery = status["lab_recovery"]
        assert recovery["reason"] == "startup" and recovery["failures"] == []
        assert recovery["reclaimed"][0]["topology_id"] == topology
        assert recovery["processes_remaining"] == []
        logs = request(port, "GET", "/v1/logs?search=lab.recovery&limit=20")
        assert any(item["event"] == "lab.recovery.reclaimed" for item in logs["records"])

        # The same topology deploys again without manual root cleanup.
        again = request(port, "POST", f"/v1/deployments/{topology}")
        assert again["state"] == "running"
        assert request(port, "POST", "/v1/reset")["deployments_destroyed"] == 1
        output = stop(second)
        second = None
        assert "shutdown_cleanup_failed" not in output
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate()
        if second is not None:
            stop(second)
    assert not owned_namespaces & namespaces()
    assert not owned_links & links()
    assert host_links() == host_links_before
