"""Deterministic, cooperative scenario execution and cleanup."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Event
from typing import Protocol

from polmon.core.errors import PolmonError
from polmon.scenarios.models import (
    ActionKind,
    CleanupPolicy,
    Condition,
    InitialCondition,
    Scenario,
    ScenarioAction,
)
from polmon.topology.models import Topology


class ScenarioError(PolmonError):
    code = "scenario_error"
    status_code = 422


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Observation:
    action_id: str
    success: bool
    detail: str
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    topology_id: str
    status: ExecutionStatus
    started_at: datetime
    finished_at: datetime
    observations: tuple[Observation, ...]
    errors: tuple[str, ...]
    cleanup_performed: bool
    # One {"message_code", "params", "message"} entry per ``errors`` item, for localized clients.
    error_details: tuple[dict[str, object], ...] = ()


class ActionExecutor(Protocol):
    def execute(
        self, action: ScenarioAction, topology: Topology, timeout_seconds: float
    ) -> Observation: ...


class ScenarioEngine:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def reset_cancellation(self) -> None:
        self._cancelled.clear()

    def validate_against(self, scenario: Scenario, topology: Topology) -> None:
        if scenario.required_topology != topology.id:
            raise ScenarioError(
                "scenario requires a different topology",
                details={"required": scenario.required_topology, "actual": topology.id},
                message_code="scenario.topology_mismatch",
                params={"required": scenario.required_topology, "actual": topology.id},
            )
        nodes = {node.id: node for node in topology.nodes}
        for action in scenario.sequence:
            if action.source not in nodes or action.target not in nodes:
                raise ScenarioError(
                    f"action '{action.id}' references a node outside the designated topology",
                    message_code="scenario.node_outside_topology",
                    params={"action": action.id},
                )
            if action.source == action.target:
                raise ScenarioError(
                    f"action '{action.id}' must use distinct source and target nodes",
                    message_code="scenario.same_source_target",
                    params={"action": action.id},
                )
            if action.kind is ActionKind.TCP_PROBE:
                services = {service.id for service in nodes[action.target].services}
                if action.service not in services:
                    raise ScenarioError(
                        f"action '{action.id}' references undeclared target service "
                        f"'{action.service}'",
                        message_code="scenario.undeclared_service",
                        params={"action": action.id, "service": action.service},
                    )

    def run(
        self,
        scenario: Scenario,
        topology: Topology,
        executor: ActionExecutor,
        cleanup: Callable[[], None],
        *,
        reset_cancellation: bool = True,
        precondition: Callable[[InitialCondition], bool] | None = None,
        on_action: Callable[[int, ScenarioAction], None] | None = None,
        on_observation: Callable[[int, ScenarioAction, Observation], None] | None = None,
    ) -> ScenarioResult:
        """Execute the sequence; ``precondition`` verifies each declared initial condition.

        Without a checker every declared initial condition is treated as unverifiable and the run
        fails before any action: a declared precondition is never assumed to hold.
        ``on_action`` is called before and ``on_observation`` after each action (zero-based
        index), so callers can publish live progress and record observations as they happen.
        """
        self.validate_against(scenario, topology)
        if reset_cancellation:
            self.reset_cancellation()
        started_at = datetime.now(UTC)
        start = self.clock()
        observations: list[Observation] = []
        errors: list[str] = []
        details: list[dict[str, object]] = []

        def failed(message: str, code: str, **params: object) -> None:
            errors.append(message)
            details.append({"message_code": code, "params": params, "message": message})

        status = ExecutionStatus.FAILED
        cleaned = False
        try:
            unmet = [
                condition.value
                for condition in scenario.initial_conditions
                if precondition is None or not precondition(condition)
            ]
            if unmet:
                failed(
                    f"initial conditions not satisfied: {', '.join(unmet)}",
                    "experiment.initial_conditions_unmet",
                    conditions=", ".join(unmet),
                )
            else:
                for index, action in enumerate(scenario.sequence):
                    if self._cancelled.is_set():
                        status = ExecutionStatus.CANCELLED
                        break
                    remaining = scenario.timeout_seconds - (self.clock() - start)
                    if remaining <= 0:
                        status = ExecutionStatus.TIMED_OUT
                        break
                    if on_action is not None:
                        on_action(index, action)
                    try:
                        observation = executor.execute(action, topology, remaining)
                    except TimeoutError:
                        status = ExecutionStatus.TIMED_OUT
                        failed(
                            f"action '{action.id}' timed out",
                            "experiment.action_timed_out",
                            action=action.id,
                        )
                        break
                    except Exception as error:
                        failed(
                            f"action '{action.id}' failed: {type(error).__name__}",
                            "experiment.action_failed",
                            action=action.id,
                            cause=type(error).__name__,
                        )
                        status = ExecutionStatus.FAILED
                        break
                    observations.append(observation)
                    if on_observation is not None:
                        on_observation(index, action, observation)
                else:
                    by_action = {item.action_id: item for item in observations}
                    success = all(
                        self._matches(condition, by_action)
                        for condition in scenario.success_conditions
                    )
                    failure = any(
                        self._matches(condition, by_action)
                        for condition in scenario.failure_conditions
                    )
                    status = (
                        ExecutionStatus.SUCCEEDED
                        if success and not failure
                        else ExecutionStatus.FAILED
                    )
        finally:
            should_clean = scenario.cleanup_policy is CleanupPolicy.ALWAYS or (
                scenario.cleanup_policy is CleanupPolicy.ON_FAILURE
                and status is not ExecutionStatus.SUCCEEDED
            )
            if should_clean:
                try:
                    cleanup()
                    cleaned = True
                except Exception as error:
                    failed(
                        f"cleanup failed: {type(error).__name__}",
                        "experiment.cleanup_failed",
                        cause=type(error).__name__,
                    )
                    status = ExecutionStatus.FAILED
        return ScenarioResult(
            scenario.id,
            topology.id,
            status,
            started_at,
            datetime.now(UTC),
            tuple(observations),
            tuple(errors),
            cleaned,
            tuple(details),
        )

    @staticmethod
    def _matches(condition: Condition, observations: dict[str, Observation]) -> bool:
        observation = observations.get(condition.action)
        return observation is not None and getattr(observation, condition.field) == condition.equals
