"""Packet validation and the owned, hostless namespace send boundary."""

import sys
from ipaddress import IPv4Network
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.namespace.packet import parse_frame, require_lab_destination
from polmon.backends.namespace.packet_io import PACKET_MODE_FLAG
from polmon.backends.namespace.packet_io import main as packet_writer_main
from polmon.backends.namespace.runner import CommandResult
from polmon.backends.namespace.static_http import HTTP_MODE_FLAG
from polmon.client.app import main as client_main
from polmon.core.errors import ConfigurationError
from polmon.orchestration import Orchestrator
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"
TOKEN = "p" * 32
FRAME = bytes.fromhex("02000088000202000088000188b5414200ff")


class PacketRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool, str | None]] = []
        self.extra_link = False
        self.default_route = False
        self.default_route_namespace: str | None = None
        self.started: list[list[str]] = []

    def run(self, command, *, privileged=False, check=True, timeout=10, input=None):
        self.calls.append((command, privileged, input))
        if command[:3] == ["ip", "-o", "-n"] and command[-2:] == ["link", "show"]:
            links = "1: lo: <LOOPBACK>\n2: eth0@if3: <BROADCAST>\n"
            if self.extra_link:
                links += "3: uplink0: <BROADCAST>\n"
            return CommandResult(links, "", 0)
        if command[-3:] == ["route", "show", "default"]:
            routed = self.default_route or command[3] == self.default_route_namespace
            return CommandResult("default via 1.2.3.4\n" if routed else "", "", 0)
        if "packet_io.py" in " ".join(command) or PACKET_MODE_FLAG in command:
            return CommandResult(str(len(bytes.fromhex(input))), "", 0)
        return CommandResult("", "", 0)

    def start(self, command, *, privileged=False):
        self.started.append(command)
        class Process:
            pid = 123

            def poll(self):
                return 0

        return Process()


def deployed_pair():
    runner = PacketRunner()
    topology = load_topology(EXAMPLE)
    backend = NamespaceBackend(
        runner=runner, python_executable=sys.executable, require_linux=False, hostless_pair=True
    )
    control = Orchestrator(topology, backend)
    control.validate()
    control.create()
    control.start()
    return topology, control, backend, runner


def test_frame_bytes_and_lab_destinations() -> None:
    assert parse_frame(FRAME.hex()) == FRAME
    spaced_hex = " ".join(FRAME.hex()[index : index + 2] for index in range(0, 36, 2))
    assert parse_frame(spaced_hex) == FRAME
    subnet = IPv4Network("192.168.236.0/24")
    require_lab_destination(FRAME, subnet)  # opaque EtherType and malformed payload are retained
    for target in ("192.168.236.200", "255.255.255.255", "224.0.0.1"):
        frame = (
            bytes.fromhex("ffffffffffff0200008800010800")
            + bytes.fromhex("450000140000000040110000c0a8ec0a")
            + bytes(map(int, target.split(".")))
        )
        require_lab_destination(frame, subnet)
    outside = bytes.fromhex("ffffffffffff0200008800010800") + bytes.fromhex(
        "450000140000000040110000c0a8ec0a08080808"
    )
    with pytest.raises(ConfigurationError) as error:
        require_lab_destination(outside, subnet)
    assert error.value.message_code == "packet.off_lab_target"
    with pytest.raises(ConfigurationError) as error:
        parse_frame("aa" * 1515)
    assert error.value.message_code == "packet.size"


def test_hostless_pair_sends_exact_bytes_and_refuses_unsafe_paths() -> None:
    topology, control, backend, runner = deployed_pair()
    try:
        assert control.inspect().state == "running"
        assert not backend.created_bridges and not backend.created_veths
        assert backend.send_packet("client", "eth0", FRAME.hex())["byte_count"] == len(FRAME)
        send = next(call for call in runner.calls if "packet_io.py" in " ".join(call[0]))
        assert send[0][:3] == ["ip", "netns", "exec"]
        assert send[0][-1] == "eth0" and send[1] is True and send[2] == FRAME.hex()
        assert all(
            not (call[0][:2] == ["ip", "link"] or "bridge" in " ".join(call[0]))
            for call in runner.calls
        )
        for node, interface, code in (
            ("missing", "eth0", "packet.node_unknown"),
            ("client", "missing", "packet.interface_unknown"),
        ):
            with pytest.raises(ConfigurationError) as error:
                backend.send_packet(node, interface, FRAME.hex())
            assert error.value.message_code == code
        runner.extra_link = True
        with pytest.raises(ConfigurationError) as error:
            backend.send_packet("client", "eth0", FRAME.hex())
        assert error.value.message_code == "packet.egress_link"
        runner.extra_link = False
        runner.default_route = True
        with pytest.raises(ConfigurationError) as error:
            backend.send_packet("client", "eth0", FRAME.hex())
        assert error.value.message_code == "packet.egress_route"
        runner.default_route = False
        assert backend.names is not None
        runner.default_route_namespace = backend.names.namespaces["server"]
        with pytest.raises(ConfigurationError) as error:
            backend.send_packet("client", "eth0", FRAME.hex())
        assert error.value.message_code == "packet.egress_route"
        runner.default_route_namespace = None
        for _ in range(19):
            backend.send_packet("client", "eth0", FRAME.hex())
        with pytest.raises(ConfigurationError) as error:
            backend.send_packet("client", "eth0", FRAME.hex())
        assert error.value.message_code == "packet.rate_limit"
    finally:
        control.destroy()


def test_authenticated_packet_route_returns_operation_and_refusal(tmp_path, monkeypatch) -> None:
    topology, control, backend, runner = deployed_pair()
    plane = ControlPlane(tmp_path)
    plane.topologies[topology.id] = topology
    plane.deployments[topology.id] = control
    client = TestClient(create_app(plane, api_token=TOKEN))
    path = f"/v1/deployments/{topology.id}/nodes/client/packets"
    payload = {"interface_id": "eth0", "frame_hex": FRAME.hex()}
    try:
        assert client.post(path, json=payload).status_code == 401
        headers = {"Authorization": f"Bearer {TOKEN}"}
        sent = client.post(path, json=payload, headers=headers)
        assert sent.status_code == 200
        result = sent.json()
        assert result["state"] == "sent" and result["byte_count"] == len(FRAME)
        assert len(result["operation_id"]) == 16
        refused = client.post(
            path, json={**payload, "interface_id": "host0"}, headers=headers
        ).json()
        assert refused["state"] == "refused"
        assert refused["message_code"] == "packet.interface_unknown"
        assert refused["operation_id"] != result["operation_id"]
        absent = client.post(
            "/v1/deployments/absent/nodes/client/packets", json=payload, headers=headers
        ).json()
        assert absent["state"] == "refused" and absent["message_code"] == "packet.not_deployed"
        monkeypatch.setattr(backend, "send_packet", lambda *args: (_ for _ in ()).throw(OSError()))
        failed = client.post(path, json=payload, headers=headers).json()
        assert failed["state"] == "error" and failed["message_code"] == "packet.backend_error"
        assert failed["operation_id"] not in {result["operation_id"], refused["operation_id"]}
        assert not any(FRAME.hex() in " ".join(call[0]) for call in runner.calls)
    finally:
        plane.shutdown()


def test_frozen_backend_uses_embedded_helpers_and_writer_refuses_host(monkeypatch) -> None:
    topology, control, backend, runner = deployed_pair()
    try:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        sent = backend.send_packet("client", "eth0", FRAME.hex())
        assert sent["state"] == "sent"
        command = next(call[0] for call in runner.calls if PACKET_MODE_FLAG in call[0])
        assert command == [
            "ip", "netns", "exec", backend.names.namespaces["client"],
            backend.python_executable, PACKET_MODE_FLAG,
            backend.names.namespaces["client"], "eth0",
        ]
        backend._start_service("server", "web", 8080, "192.168.236.20")
        assert HTTP_MODE_FLAG in runner.started[-1]
        assert str(Path(__file__).parents[2] / "src/polmon/backends/namespace/static_http.py") \
            not in runner.started[-1]
    finally:
        control.destroy()
    assert packet_writer_main(["polmon12345678n", "eth0"]) == 2


def test_client_private_namespace_dispatch_is_qt_free(monkeypatch) -> None:
    from polmon.backends.namespace import packet_io, static_http

    monkeypatch.setattr(packet_io, "main", lambda args: 37 if args == ["ns", "eth0"] else 1)
    monkeypatch.setattr(static_http, "main", lambda args: 41 if args == ["--port", "8"] else 1)
    assert client_main([PACKET_MODE_FLAG, "ns", "eth0"]) == 37
    assert client_main([HTTP_MODE_FLAG, "--port", "8"]) == 41
