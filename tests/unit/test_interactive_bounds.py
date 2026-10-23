"""Interactive console and VNC resources are bounded and never orphan what they start."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from polmon import console
from polmon.api import control as control_module
from polmon.api.control import ControlPlane
from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.namespace.runner import CommandRunner, stop_process_group
from polmon.core.diagnostics import ResourceSnapshot
from polmon.resources.policy import ResourceLimitError
from polmon.topology import parse_topology

EXAMPLES = Path(__file__).parents[2] / "examples/topologies"


class LiveSession:
    def __init__(self, session_id, topology_id, node_id, backend, transcript) -> None:  # noqa: ANN001
        self.id = session_id
        self.topology_id = topology_id
        self.node_id = node_id
        self.returncode = None
        self.process = SimpleNamespace(poll=lambda: self.returncode)

    def snapshot(self, after: int = 0) -> dict[str, object]:
        return {"session_id": self.id}

    def close(self) -> None:
        self.returncode = 0


def test_console_sessions_are_capped_per_node_and_globally(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(console, "ConsoleSession", LiveSession)
    sessions = console.ConsoleSessions(tmp_path)
    try:
        for _ in range(console.MAX_LIVE_SESSIONS_PER_NODE):
            sessions.create("lab", "alpha", None)  # type: ignore[arg-type]
        with pytest.raises(ResourceLimitError) as refused:
            sessions.create("lab", "alpha", None)  # type: ignore[arg-type]
        assert refused.value.message_code == "console.node_session_limit"
        assert refused.value.status_code == 429
        assert refused.value.params == {"limit": console.MAX_LIVE_SESSIONS_PER_NODE}

        # A closed session frees its slot.
        first = next(iter(sessions.sessions.values()))
        first.close()
        sessions.create("lab", "alpha", None)  # type: ignore[arg-type]

        node = 0
        while len(sessions.sessions) < console.MAX_LIVE_SESSIONS + 1:
            sessions.create("lab", f"node{node // 4}", None)  # type: ignore[arg-type]
            node += 1
        with pytest.raises(ResourceLimitError) as refused:
            sessions.create("lab", "fresh", None)  # type: ignore[arg-type]
        assert refused.value.message_code == "console.session_limit"
    finally:
        sessions.close()


def test_vnc_listens_on_namespace_loopback_and_relay_runs_unprivileged() -> None:
    topology = parse_topology((EXAMPLES / "l1-two-node.yml").read_text(encoding="utf-8"))
    backend = NamespaceBackend(require_linux=False)
    backend.validate(topology)
    backend.topology = topology  # as create() records it
    node = topology.nodes[0]
    address, port = backend.vnc_service(node.id)
    assert address == "127.0.0.1"
    assert port == 5900 + node.interfaces[0].ipv4.packed[-1]
    argv = backend.vnc_proxy_argv(node.id)
    assert argv[:4] == ["ip", "netns", "exec", backend.names.namespaces[node.id]]
    owner = [str(backend.owner_uid), "--regid", str(backend.owner_gid)]
    assert argv[4:9] == ["setpriv", "--reuid", *owner]
    assert argv[-2:] == ["127.0.0.1", str(port)]


def test_vnc_start_reuses_a_live_display_stack() -> None:
    topology = parse_topology((EXAMPLES / "l1-two-node.yml").read_text(encoding="utf-8"))
    backend = NamespaceBackend(require_linux=False)
    backend.validate(topology)
    backend.topology = topology  # as create() records it
    node = topology.nodes[0].id
    live = SimpleNamespace(poll=lambda: None)
    backend.vnc_processes[node] = (live, live, live)  # type: ignore[assignment]
    backend.vnc_displays[node] = {"node_id": node, "port": 5911}
    backend.run_directory = Path("/nonexistent")
    assert backend.start_vnc(node) == {"node_id": node, "port": 5911}


def vnc_plane(tmp_path, monkeypatch, **options) -> ControlPlane:  # noqa: ANN001, ANN003
    plane = ControlPlane(tmp_path, **options)
    backend = NamespaceBackend.__new__(NamespaceBackend)
    backend.vnc_processes = {}
    backend.start_vnc = lambda node_id: {"node_id": node_id}  # type: ignore[method-assign]
    plane.deployments["lab"] = SimpleNamespace(backend=backend)  # type: ignore[assignment]
    monkeypatch.setattr(
        plane,
        "console_readiness",
        lambda topology_id, node_id: {"vnc": {"reason_codes": []}, "node": {"id": node_id}},
    )
    return plane


def test_vnc_grants_are_bounded_and_dropped_on_destroy(tmp_path, monkeypatch) -> None:
    plane = vnc_plane(tmp_path, monkeypatch)
    try:
        grants = [
            plane.console_vnc_start("lab", "alpha")["session_id"]
            for _ in range(control_module.MAX_VNC_SESSIONS + 3)
        ]
        assert len(plane.vnc_sessions) == control_module.MAX_VNC_SESSIONS
        assert grants[0] not in plane.vnc_sessions and grants[-1] in plane.vnc_sessions
        plane.vnc_sessions["other"] = ("kept", "alpha")
        plane.deployments.pop("lab")
        plane.destroy("lab")
        assert plane.vnc_sessions == {"other": ("kept", "alpha")}
    finally:
        plane.deployments.pop("lab", None)
        plane.shutdown()


def test_a_new_vnc_display_is_admitted_against_available_memory(tmp_path, monkeypatch) -> None:
    available_mb = control_module.VNC_DISPLAY_MEMORY_MB + 255  # one MiB short of the reserve

    def snapshot() -> ResourceSnapshot:
        return ResourceSnapshot(1, 0.1, 1.0, available_mb * 1_048_576, 0)

    plane = vnc_plane(tmp_path, monkeypatch, snapshot=snapshot)
    try:
        with pytest.raises(ResourceLimitError) as refused:
            plane.console_vnc_start("lab", "alpha")
        assert refused.value.message_code == "console.vnc_memory"
        assert refused.value.status_code == 429
        assert refused.value.params == {
            "required_mb": control_module.VNC_DISPLAY_MEMORY_MB + 256,
            "available_mb": available_mb,
        }
        assert plane.vnc_sessions == {}

        # Joining a display that already runs costs nothing new and is always allowed.
        live = SimpleNamespace(poll=lambda: None)
        plane.deployments["lab"].backend.vnc_processes["alpha"] = (live, live, live)
        assert plane.console_vnc_start("lab", "alpha")["display"] == {"node_id": "alpha"}

        available_mb += 1
        assert plane.console_vnc_start("lab", "beta")["display"] == {"node_id": "beta"}
    finally:
        plane.deployments.pop("lab", None)
        plane.shutdown()


class ClosingSocket:
    def __init__(self) -> None:
        self.codes: list[int] = []

    async def close(self, code: int = 1000) -> None:
        self.codes.append(code)


def test_vnc_relays_are_capped_with_a_coded_close(tmp_path, monkeypatch) -> None:
    plane = vnc_plane(tmp_path, monkeypatch)
    try:
        token = plane.console_vnc_start("lab", "alpha")["session_id"]
        plane.vnc_relays[("lab", "alpha")] = control_module.MAX_VNC_RELAYS_PER_NODE
        socket = ClosingSocket()
        asyncio.run(plane.console_vnc_relay(token, socket))
        assert socket.codes == [4429]

        plane.vnc_relays.clear()
        plane.vnc_relays[("lab", "other")] = control_module.MAX_VNC_RELAYS
        asyncio.run(plane.console_vnc_relay(token, socket))
        assert socket.codes == [4429, 4429]
        assert plane.vnc_relays == {("lab", "other"): control_module.MAX_VNC_RELAYS}
        logged = plane.logs_query(limit=20)["records"]
        assert any(item["event"] == "console.vnc.relay_limit" for item in logged)
    finally:
        plane.deployments.pop("lab", None)
        plane.shutdown()


def gone(pid: int) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):  # reaped between open and read
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(sys.platform != "linux", reason="process groups and /proc are Linux-only")
def test_bounded_command_timeout_stops_the_whole_process_group() -> None:
    # The leader ignores nothing, its child ignores SIGTERM: both must be gone after the timeout,
    # as ``sudo`` (the real leader) dies on SIGTERM while what it runs may not.
    script = "trap '' TERM; sleep 60 & echo $!; wait"
    result = CommandRunner().run_bounded(["sh", "-c", script], timeout=0.5)
    assert result.timed_out
    assert gone(int(result.stdout.split()[0]))


@pytest.mark.skipif(sys.platform != "linux", reason="process groups and /proc are Linux-only")
def test_stop_process_group_reaches_members_after_the_leader_exits() -> None:
    process = subprocess.Popen(
        ["sh", "-c", "sleep 60 & echo $!; exit 0"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    member = int(process.stdout.readline())  # type: ignore[union-attr]
    process.wait(timeout=5)
    assert os.getpgid(member) == process.pid
    stop_process_group(process, grace=0.5)
    process.stdout.close()  # type: ignore[union-attr]
    assert gone(member)


PROXY = (
    "import os, sys\n"
    "open(sys.argv[1], 'a').write(f'{os.getpid()}\\n')\n"
    "sys.stdout.buffer.write(b'RFB 003.008\\n'); sys.stdout.flush()\n"
    "while sys.argv[2] == 'serve' and os.read(0, 65536): pass\n"
)


def relay_client(tmp_path, monkeypatch, mode: str):  # noqa: ANN001, ANN201
    """A relay whose proxy is a local stand-in (no sudo, no namespace)."""
    from fastapi.testclient import TestClient

    from polmon.backend import create_app

    plane = vnc_plane(tmp_path, monkeypatch)
    pids = tmp_path / "proxy-pids"
    backend = plane.deployments["lab"].backend
    backend.vnc_proxy_argv = lambda node_id: [sys.executable, "-c", PROXY, str(pids), mode]
    spawn = asyncio.create_subprocess_exec

    async def without_sudo(*argv, **options):  # noqa: ANN002, ANN003, ANN202
        assert argv[:2] == ("sudo", "-n")
        return await spawn(*argv[2:], **options)

    monkeypatch.setattr(control_module.asyncio, "create_subprocess_exec", without_sudo)
    relay = plane.console_vnc_start("lab", "alpha")["relay_path"]
    return plane, TestClient(create_app(plane)), relay, pids


def test_vnc_relay_stops_its_proxy_when_clients_leave(tmp_path, monkeypatch) -> None:
    plane, client, relay, pids = relay_client(tmp_path, monkeypatch, "serve")
    try:
        with client.websocket_connect(relay) as first, client.websocket_connect(relay) as second:
            assert first.receive_bytes() == second.receive_bytes() == b"RFB 003.008\n"
        started = [int(item) for item in pids.read_text().split()]
        assert len(started) == 2 and all(gone(pid) for pid in started)
        assert plane.vnc_relays == {}
    finally:
        plane.deployments.pop("lab", None)
        plane.shutdown()


def test_vnc_relay_closes_the_client_when_the_display_ends(tmp_path, monkeypatch) -> None:
    from starlette.websockets import WebSocketDisconnect

    plane, client, relay, _ = relay_client(tmp_path, monkeypatch, "exit")
    try:
        with client.websocket_connect(relay) as socket:
            assert socket.receive_bytes() == b"RFB 003.008\n"
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_bytes()
            assert closed.value.code == 1000
    finally:
        plane.deployments.pop("lab", None)
        plane.shutdown()
