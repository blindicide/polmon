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
