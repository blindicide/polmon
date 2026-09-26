from pathlib import Path

import pytest

from polmon.core.errors import ConfigurationError
from polmon.scenarios import ScenarioEngine, load_scenario, parse_scenario
from polmon.scenarios.engine import ExecutionStatus, Observation
from polmon.topology import load_topology

SCENARIO = Path(__file__).parents[2] / "examples/scenarios/recon.yml"
TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"


class Executor:
    def __init__(self, *, fail: bool = False, timeout: bool = False) -> None:
        self.fail = fail
        self.timeout = timeout
        self.actions = []

    def execute(self, action, topology, timeout_seconds):
        self.actions.append(action.id)
        if self.timeout:
            raise TimeoutError
        return Observation(action.id, not self.fail, "reachable" if not self.fail else "blocked")


def test_controlled_recon_executes_in_order_and_cleans_up() -> None:
    cleaned = []
    executor = Executor()
    result = ScenarioEngine().run(
        load_scenario(SCENARIO), load_topology(TOPOLOGY), executor, lambda: cleaned.append(True)
    )
    assert result.status is ExecutionStatus.SUCCEEDED
    assert executor.actions == ["reach-server", "inspect-web"]
    assert result.cleanup_performed and cleaned == [True]


def test_failed_observations_produce_failed_result_and_cleanup() -> None:
    result = ScenarioEngine().run(
        load_scenario(SCENARIO), load_topology(TOPOLOGY), Executor(fail=True), lambda: None
    )
    assert result.status is ExecutionStatus.FAILED
    assert result.cleanup_performed


def test_executor_timeout_terminates_sequence_and_cleans_up() -> None:
    result = ScenarioEngine().run(
        load_scenario(SCENARIO), load_topology(TOPOLOGY), Executor(timeout=True), lambda: None
    )
    assert result.status is ExecutionStatus.TIMED_OUT
    assert len(result.observations) == 0
    assert "timed out" in result.errors[0]


def test_pre_cancel_is_cleared_for_new_run() -> None:
    engine = ScenarioEngine()
    engine.cancel()
    result = engine.run(load_scenario(SCENARIO), load_topology(TOPOLOGY), Executor(), lambda: None)
    assert result.status is ExecutionStatus.SUCCEEDED


def test_cooperative_cancel_stops_before_second_action() -> None:
    engine = ScenarioEngine()

    class CancellingExecutor(Executor):
        def execute(self, action, topology, timeout_seconds):
            result = super().execute(action, topology, timeout_seconds)
            engine.cancel()
            return result

    result = engine.run(
        load_scenario(SCENARIO), load_topology(TOPOLOGY), CancellingExecutor(), lambda: None
    )
    assert result.status is ExecutionStatus.CANCELLED
    assert len(result.observations) == 1
    assert result.cleanup_performed


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("icmp_probe", "shell", "Input should be"),
        ("  - tcp_probe\n", "", "unpermitted"),
        ("action: reach-server", "action: missing", "unknown action"),
    ],
)
def test_invalid_scenarios_are_rejected_before_execution(old: str, new: str, message: str) -> None:
    source = SCENARIO.read_text(encoding="utf-8").replace(old, new, 1)
    with pytest.raises(ConfigurationError) as caught:
        parse_scenario(source)
    assert message in str(caught.value.details)


def test_scenario_rejects_non_designated_target_and_undeclared_service() -> None:
    scenario = load_scenario(SCENARIO)
    topology = load_topology(TOPOLOGY)
    bad_target = scenario.model_copy(
        update={"sequence": [scenario.sequence[0].model_copy(update={"target": "outside"})]}
    )
    with pytest.raises(Exception, match="outside the designated"):
        ScenarioEngine().validate_against(bad_target, topology)
    bad_service = scenario.model_copy(
        update={"sequence": [scenario.sequence[1].model_copy(update={"service": "ssh"})]}
    )
    with pytest.raises(Exception, match="undeclared target service"):
        ScenarioEngine().validate_against(bad_service, topology)


def test_cleanup_failure_is_reported_without_masking_result() -> None:
    def broken_cleanup():
        raise RuntimeError("injected")

    result = ScenarioEngine().run(
        load_scenario(SCENARIO), load_topology(TOPOLOGY), Executor(), broken_cleanup
    )
    assert result.status is ExecutionStatus.FAILED
    assert result.errors == ("cleanup failed: RuntimeError",)
