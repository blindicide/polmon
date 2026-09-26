import shutil
import subprocess
from pathlib import Path

import pytest

from polmon.backends.hybrid.backend import HybridBackend
from polmon.orchestration import Orchestrator
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/hybrid-tap.yml"


def hybrid_available() -> bool:
    tools_missing = any(shutil.which(tool) is None for tool in ("ip", "sudo"))
    if tools_missing or not Path("/dev/net/tun").exists():
        return False
    result = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    )
    return result.returncode == 0


@pytest.mark.integration
@pytest.mark.privileged
def test_l0_pings_l1_through_shared_tap_and_cleans_up() -> None:
    if not hybrid_available():
        pytest.skip("NOT RUN — environment unavailable: TAP and namespace privileges required")
    backend = HybridBackend()
    control = Orchestrator(load_topology(EXAMPLE), backend)
    names = []
    try:
        control.validate()
        control.create()
        names = list(backend.tap_names.values())
        control.start()
        assert backend.ping_l1("synthetic", "10.89.0.20")
        assert len(backend.capture) >= 4
    finally:
        control.destroy()
    links = backend.runner.run(["ip", "-o", "link", "show"], privileged=True).stdout
    assert all(name not in links for name in names)


@pytest.mark.integration
@pytest.mark.privileged
def test_kernel_ping_from_l1_reaches_l0_and_both_directions_coexist() -> None:
    if not hybrid_available():
        pytest.skip("NOT RUN — environment unavailable: TAP and namespace privileges required")
    backend = HybridBackend()
    control = Orchestrator(load_topology(EXAMPLE), backend)
    try:
        control.validate()
        control.create()
        control.start()
        stats = backend.namespace.ping_statistics("linux", "10.89.0.10", count=5, interval=0.2)
        assert stats["received"] == 5 and stats["loss_percent"] == 0.0
        assert backend.ping_l1("synthetic", "10.89.0.20")  # still works with the responder running
        answered = backend.inspect().details["answered_for_l0"]
        assert sum(item["icmp_echo"] for item in answered.values()) >= 5
        assert sum(item["arp"] for item in answered.values()) >= 1
    finally:
        control.destroy()
    assert not backend.responders
