"""Byte-exact proof on a transient, disconnected pair of managed namespaces."""

import select
import shutil
import subprocess
from pathlib import Path

import pytest

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.orchestration import Orchestrator
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"
CAPTURE = Path(__file__).with_name("packet_capture.py")
FRAME = bytes.fromhex("02000088000202000088000188b5414200ff")


def available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv")):
        return False
    return (
        subprocess.run(
            ["sudo", "-n", "ip", "netns", "list"], capture_output=True, timeout=3, check=False
        ).returncode
        == 0
    )


def captured_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 4)
    assert ready, "namespace capture did not respond within four seconds"
    return process.stdout.readline().strip()


@pytest.mark.integration
@pytest.mark.privileged
def test_byte_exact_frame_remains_inside_hostless_namespace_pair() -> None:
    if not available():
        pytest.skip("NOT RUN — environment unavailable: sudo/ip namespace support required")
    backend = NamespaceBackend(hostless_pair=True)
    control = Orchestrator(load_topology(EXAMPLE), backend)
    receiver: subprocess.Popen[str] | None = None
    try:
        control.validate()
        control.create()
        control.start()
        assert backend.names is not None
        assert not backend.created_bridges and not backend.created_veths
        namespaces = backend.names.namespaces
        assert set(backend.created_namespaces) == set(namespaces.values())
        for namespace in namespaces.values():
            links = backend.runner.run(
                ["ip", "-o", "-n", namespace, "link", "show"], privileged=True
            ).stdout
            names = {
                line.split(": ", 1)[1].split(":", 1)[0].split("@", 1)[0]
                for line in links.splitlines()
                if ": " in line
            }
            assert names == {"lo", "eth0"}
            for family in ("-4", "-6"):
                assert not backend.runner.run(
                    ["ip", family, "-n", namespace, "route", "show", "default"],
                    privileged=True,
                ).stdout.strip()
        receiver = subprocess.Popen(
            [
                "sudo",
                "-n",
                "ip",
                "netns",
                "exec",
                namespaces["server"],
                backend.python_executable,
                "-I",
                str(CAPTURE),
                "eth0",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert captured_line(receiver) == "READY"
        result = backend.send_packet("client", "eth0", FRAME.hex())
        assert result == {"interface": "eth0", "byte_count": len(FRAME), "state": "sent"}
        assert bytes.fromhex(captured_line(receiver)) == FRAME
        assert receiver.wait(timeout=3) == 0
    finally:
        if receiver is not None and receiver.poll() is None:
            receiver.kill()
            receiver.wait(timeout=3)
        control.destroy()
    assert backend.names is not None
    remaining = backend.runner.run(["ip", "netns", "list"], privileged=True).stdout
    assert all(namespace not in remaining for namespace in backend.names.namespaces.values())
