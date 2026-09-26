import shutil
import subprocess
from pathlib import Path

import pytest

from polmon.api.control import ControlPlane

SCENARIO = Path(__file__).parents[2] / "examples/scenarios/recon.yml"
TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"


def namespace_available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv")):
        return False
    result = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    )
    return result.returncode == 0


@pytest.mark.integration
@pytest.mark.privileged
def test_real_experiment_reports_resets_and_repeats(tmp_path) -> None:
    if not namespace_available():
        pytest.skip("NOT RUN — environment unavailable: namespace privileges required")
    plane = ControlPlane(tmp_path)
    topology_source = TOPOLOGY.read_text(encoding="utf-8")
    scenario_source = SCENARIO.read_text(encoding="utf-8").replace(
        "cleanup_policy: always", "cleanup_policy: never"
    )
    topology_id = str(plane.load_topology(topology_source)["topology_id"])
    try:
        plane.deploy(topology_id)
        first = plane.run_experiment("recovery-one", topology_id, scenario_source)
        assert first["status"] == "succeeded"
        assert plane.experiment_report("recovery-one")["status"] == "succeeded"
        assert plane.reset_all()["deployments_destroyed"] == 1

        plane.deploy(topology_id)
        second = plane.run_experiment("recovery-two", topology_id, scenario_source)
        assert second["status"] == "succeeded"
        assert plane.reset_all()["deployments_destroyed"] == 1
        assert not plane.deployments
    finally:
        plane.reset_all()
