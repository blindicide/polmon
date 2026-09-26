import shutil
import subprocess
from pathlib import Path

import pytest

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.orchestration import Orchestrator
from polmon.scenarios import ScenarioEngine, load_scenario
from polmon.scenarios.engine import ExecutionStatus
from polmon.scenarios.executors import NamespaceScenarioExecutor
from polmon.topology import load_topology

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
def test_controlled_recon_runs_against_l1_and_cleans_up() -> None:
    if not namespace_available():
        pytest.skip("NOT RUN — environment unavailable: namespace privileges required")
    topology = load_topology(TOPOLOGY)
    backend = NamespaceBackend()
    control = Orchestrator(topology, backend)
    control.validate()
    control.create()
    control.start()
    result = ScenarioEngine().run(
        load_scenario(SCENARIO), topology, NamespaceScenarioExecutor(backend), control.destroy
    )
    assert result.status is ExecutionStatus.SUCCEEDED
    assert [item.success for item in result.observations] == [True, True]
    assert result.cleanup_performed
    assert not backend.created_namespaces

