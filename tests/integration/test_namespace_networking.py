import shutil
import subprocess
import time
from pathlib import Path

import pytest

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.orchestration import Orchestrator
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"


def namespace_available() -> bool:
    tools = (shutil.which("ip"), shutil.which("sudo"), shutil.which("setpriv"))
    if any(tool is None for tool in tools):
        return False
    result = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    )
    return result.returncode == 0


@pytest.mark.integration
@pytest.mark.privileged
def test_two_l1_nodes_ping_service_and_teardown() -> None:
    if not namespace_available():
        pytest.skip("NOT RUN — environment unavailable: sudo/ip/setpriv namespace support required")
    backend = NamespaceBackend()
    control = Orchestrator(load_topology(EXAMPLE), backend)
    try:
        control.validate()
        control.create()
        control.start()
        assert backend.ping("client", "10.88.0.20")
        for _ in range(20):
            if backend.probe_tcp("client", "10.88.0.20", 8080):
                break
            time.sleep(0.1)
        else:
            pytest.fail("L1 HTTP service did not become reachable")
    finally:
        control.destroy()
    listed = backend.runner.run(["ip", "netns", "list"], privileged=True).stdout
    assert all(name not in listed for name in backend.names.namespaces.values())
    assert not backend.created_bridges
    assert not backend.created_veths
