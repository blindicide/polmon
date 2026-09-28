import shutil
import struct
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.backends.namespace.backend import NamespaceBackend
from polmon.orchestration import Orchestrator
from polmon.topology import parse_topology


def console_topology() -> str:
    return """id: console-two
networks:
  - {id: lab, ipv4_subnet: 192.168.239.0/24}
nodes:
  - id: alpha
    name: Alpha terminal
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:00:01:01', ipv4: 192.168.239.11}
    services:
      - {id: shell, protocol: tcp, port: 22, implementation: ssh}
  - id: bravo
    name: Bravo terminal
    class: l1
    interfaces:
      - {id: eth0, network: lab, mac: '02:50:4f:00:01:02', ipv4: 192.168.239.12}
    services:
      - {id: shell, protocol: tcp, port: 22, implementation: ssh}
"""


def ssh_lab_available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv", "sshd", "ssh")):
        return False
    result = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    )
    return result.returncode == 0


def vnc_lab_available() -> bool:
    return ssh_lab_available() and all(shutil.which(tool) for tool in ("Xvfb", "x11vnc", "xclock"))


@pytest.mark.integration
@pytest.mark.privileged
def test_real_ssh_exec_on_two_nodes_interrupt_and_teardown(tmp_path) -> None:
    if not ssh_lab_available():
        pytest.skip("NOT RUN — console.ssh_prerequisite_missing")
    topology = parse_topology(console_topology())
    backend = NamespaceBackend(run_directory=tmp_path / "run")
    control = Orchestrator(topology, backend)
    try:
        control.validate()
        control.create()
        control.start()
        for node in ("alpha", "bravo"):
            for _ in range(30):
                result = backend.ssh_command(node, ["hostname"], timeout=3)
                if result.returncode == 0:
                    break
                time.sleep(0.1)
            assert result.returncode == 0, result.stderr
            addresses = backend.ssh_command(node, ["ip", "-o", "-4", "addr"], timeout=5)
            assert addresses.returncode == 0 and "192.168.239." in addresses.stdout
            uptime = backend.ssh_command(node, ["uptime"], timeout=5)
            assert uptime.returncode == 0 and uptime.stdout.strip()
        failed = backend.ssh_command("alpha", ["false"], timeout=3)
        assert failed.returncode != 0
        interrupted = backend.ssh_command("bravo", ["sleep", "30"], timeout=0.2)
        assert interrupted.timed_out and interrupted.returncode == 124
    finally:
        control.destroy()
    assert not backend.created_namespaces and not backend.created_veths
    listed = backend.runner.run(["ip", "netns", "list"], privileged=True).stdout
    assert all(name not in listed for name in backend.names.namespaces.values())


@pytest.mark.integration
@pytest.mark.privileged
def test_console_api_exec_interactive_stream_interrupt_and_transcript(tmp_path) -> None:
    if not ssh_lab_available():
        pytest.skip("NOT RUN — console.ssh_prerequisite_missing")
    plane = ControlPlane(tmp_path)
    client = TestClient(create_app(plane))
    try:
        loaded = client.post("/v1/topologies", json={"yaml": console_topology()})
        assert loaded.status_code == 200
        assert client.post("/v1/deployments/console-two").status_code == 200
        for node in ("alpha", "bravo"):
            path = f"/v1/deployments/console-two/nodes/{node}/console"
            for _ in range(30):
                executed = client.post(path + "/exec", json={"argv": ["hostname"]})
                if executed.status_code == 200 and executed.json()["exit_status"] == 0:
                    break
                time.sleep(0.1)
            assert executed.json()["node"]["name"].endswith("terminal")
            address = client.post(path + "/exec", json={"argv": ["ip", "-o", "-4", "addr"]})
            assert address.json()["exit_status"] == 0
            assert "192.168.239." in address.json()["stdout"]
            uptime = client.post(path + "/exec", json={"argv": ["uptime"]})
            assert uptime.json()["exit_status"] == 0 and uptime.json()["stdout"].strip()
        failed = client.post(
            "/v1/deployments/console-two/nodes/alpha/console/exec",
            json={"argv": ["false"]},
        )
        assert failed.json()["exit_status"] != 0

        root = "/v1/deployments/console-two/nodes/alpha/console/sessions"
        opened = client.post(root).json()
        session_id = opened["session_id"]
        session = f"{root}/{session_id}"
        client.post(session + "/input", json={"data": "echo INTERACTIVE-OK\n"})
        cursor = 0
        output = ""
        for _ in range(40):
            update = client.get(session + f"/stream?after={cursor}").json()
            output += update["output"]
            cursor = update["cursor"]
            if "INTERACTIVE-OK" in output:
                break
            time.sleep(0.1)
        assert "INTERACTIVE-OK" in output
        client.post(session + "/input", json={"data": "sleep 30\n"})
        time.sleep(0.2)
        client.post(session + "/input", json={"data": "\u0003"})
        client.post(session + "/input", json={"data": "echo AFTER-INTERRUPT\n"})
        for _ in range(40):
            update = client.get(session + f"/stream?after={cursor}").json()
            output += update["output"]
            cursor = update["cursor"]
            if "AFTER-INTERRUPT" in output:
                break
            time.sleep(0.1)
        assert "AFTER-INTERRUPT" in output
        assert client.delete(session).json()["state"] == "closed"
        transcript = client.get(session + "/transcript").json()
        assert "INTERACTIVE-OK" in transcript["text"]
        assert client.delete("/v1/deployments/console-two").status_code == 200
    finally:
        plane.shutdown()


@pytest.mark.integration
@pytest.mark.privileged
def test_real_vnc_stack_has_framebuffer_and_tears_down(tmp_path) -> None:
    if not vnc_lab_available():
        pytest.skip("NOT RUN — console.vnc_prerequisite_missing")
    source = console_topology().replace("console-two", "vnc-one").replace("bravo", "clock")
    topology = parse_topology(source)
    backend = NamespaceBackend(run_directory=tmp_path / "run")
    control = Orchestrator(topology, backend)
    try:
        control.validate()
        control.create()
        control.start()
        display = backend.start_vnc("alpha")
        address, port = display["address"], display["port"]
        probe = """import socket,sys,struct
s=socket.create_connection((sys.argv[1],int(sys.argv[2])),5)
assert s.recv(12) == b'RFB 003.008\\n'
s.sendall(b'RFB 003.008\\n'); count=s.recv(1)[0]; types=s.recv(count); assert 1 in types
s.sendall(b'\\x01'); assert s.recv(4) == b'\\x00\\x00\\x00\\x00'
s.sendall(b'\\x01'); init=s.recv(24); width,height=struct.unpack('>HH',init[:4])
assert width == 1024
assert height == 768
s.sendall(b'\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00')
s.sendall(b'\\x02\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01')
s.sendall(b'\\x03\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00')
s.sendall(b'\\x05\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00')
pixel=s.recv(16); assert len(pixel) == 16
s.sendall(b'\\x05'+struct.pack('>xHH',400,300))
print(f'RFB-OK {width}x{height} PIXEL-BYTES={len(pixel)} POINTER-SENT')
"""
        command = [
            "sudo", "-n", "ip", "netns", "exec", backend.names.namespaces["alpha"],
            "python3", "-c", probe, str(address), str(port),
        ]
        for _ in range(30):
            result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
            if result.returncode == 0:
                break
            time.sleep(0.2)
        assert result.returncode == 0, result.stderr
        assert "RFB-OK 1024x768" in result.stdout
    finally:
        control.destroy()
    assert not backend.created_namespaces and not backend.created_veths
    assert not backend.vnc_processes


@pytest.mark.integration
@pytest.mark.privileged
def test_vnc_api_relay_delivers_framebuffer_and_input(tmp_path) -> None:
    if not vnc_lab_available():
        pytest.skip("NOT RUN — console.vnc_prerequisite_missing")
    plane = ControlPlane(tmp_path)
    client = TestClient(create_app(plane))
    try:
        assert client.post("/v1/topologies", json={"yaml": console_topology()}).status_code == 200
        assert client.post("/v1/deployments/console-two").status_code == 200
        started = client.post(
            "/v1/deployments/console-two/nodes/alpha/console/vnc"
        )
        assert started.status_code == 200, started.text
        relay = started.json()["relay_path"]
        with client.websocket_connect(relay) as socket:
            assert socket.receive_bytes() == b"RFB 003.008\n"
            socket.send_bytes(b"RFB 003.008\n")
            security = socket.receive_bytes()
            assert security[0] == 1 and security[1:5] == b"\x00\x00\x00\x00"
            socket.send_bytes(b"\x01")
            assert socket.receive_bytes() == b"\x00\x00\x00\x00"
            socket.send_bytes(b"\x01")
            init = socket.receive_bytes()
            width, height = struct.unpack(">HH", init[:4])
            assert (width, height) == (1024, 768)
            socket.send_bytes(b"\x00")
            socket.send_bytes(b"\x02\x00\x00\x00\x01\x00\x00\x00\x01")
            socket.send_bytes(b"\x03\x00\x00\x00\x00\x00\x00\x00\x00")
            update = socket.receive_bytes()
            assert update[0] == 0 and len(update) > 16
            socket.send_bytes(b"\x05\x01" + struct.pack(">HH", 400, 300))
        evidence = tmp_path / "vnc-relay.txt"
        evidence.write_text(
            "WEBSOCKET-RELAY-OK 1024x768 FRAMEBUFFER-UPDATE POINTER-EVENT SENT CLEAN-CLOSE\n",
            encoding="utf-8",
        )
    finally:
        plane.shutdown()
