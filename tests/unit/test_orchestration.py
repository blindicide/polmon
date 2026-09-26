from pathlib import Path

import pytest

from polmon.backends.mock import MockBackend
from polmon.orchestration.lifecycle import (
    LifecycleState,
    OrchestrationError,
    Orchestrator,
    OwnershipRegistry,
)
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/hybrid-small.yml"


def orchestrator(
    backend: MockBackend | None = None, ownership: OwnershipRegistry | None = None
) -> Orchestrator:
    return Orchestrator(load_topology(EXAMPLE), backend or MockBackend(), ownership=ownership)


def test_complete_lifecycle_and_idempotent_cleanup() -> None:
    control = orchestrator()
    control.validate()
    control.validate()
    control.create()
    control.create()
    assert control.inspect().state is LifecycleState.CREATED
    assert len(control.inspect().owned_resources) == 2
    control.start()
    control.start()
    control.stop()
    control.stop()
    control.destroy()
    control.destroy()
    assert control.inspect().state is LifecycleState.DESTROYED
    assert not control.inspect().owned_resources


def test_destroy_running_topology_stops_first() -> None:
    backend = MockBackend()
    control = orchestrator(backend)
    control.validate()
    control.create()
    control.start()
    control.destroy()
    assert backend.calls[-2:] == ["stop", "destroy"]


def test_illegal_transition_preserves_state() -> None:
    control = orchestrator()
    with pytest.raises(OrchestrationError, match="cannot start"):
        control.start()
    assert control.state is LifecycleState.NEW


@pytest.mark.parametrize("operation", ["validate", "start", "stop"])
def test_operation_failure_preserves_previous_state(operation: str) -> None:
    backend = MockBackend(fail_on=operation)
    control = orchestrator(backend, OwnershipRegistry())
    if operation != "validate":
        control.validate()
        control.create()
    if operation == "stop":
        control.start()
    previous = control.state
    with pytest.raises(OrchestrationError, match=operation):
        getattr(control, operation)()
    assert control.state is previous
    backend.fail_on = None
    control.destroy()


def test_partial_create_failure_is_cleaned_up() -> None:
    backend = MockBackend(fail_on="create")
    ownership = OwnershipRegistry()
    control = orchestrator(backend, ownership)
    control.validate()
    with pytest.raises(OrchestrationError, match="create"):
        control.create()
    assert control.state is LifecycleState.VALIDATED
    assert not backend.resources
    assert not ownership.resources_for(control._owner_id)


def test_resource_ownership_conflicts_roll_back_second_backend() -> None:
    ownership = OwnershipRegistry()
    first = orchestrator(MockBackend(resource_prefix="shared"), ownership)
    second = orchestrator(MockBackend(resource_prefix="shared"), ownership)
    first.validate()
    first.create()
    second.validate()
    with pytest.raises(OrchestrationError, match="ownership conflict"):
        second.create()
    assert second.state is LifecycleState.VALIDATED
    assert not second.backend.resources
    first.destroy()


def test_destroy_failure_releases_ownership_but_is_retryable() -> None:
    backend = MockBackend(fail_on="destroy")
    ownership = OwnershipRegistry()
    control = orchestrator(backend, ownership)
    control.validate()
    control.create()
    with pytest.raises(OrchestrationError, match="destroy"):
        control.destroy()
    assert not ownership.resources_for(control._owner_id)
    assert control.state is LifecycleState.CREATED
    backend.fail_on = None
    control.destroy()
    assert control.state is LifecycleState.DESTROYED
