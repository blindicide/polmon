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
            )
        nodes = {node.id: node for node in topology.nodes}
        for action in scenario.sequence:
            if action.source not in nodes or action.target not in nodes:
                raise ScenarioError(
                    f"action '{action.id}' references a node outside the designated topology"
                )
            if action.source == action.target:
                raise ScenarioError(
                    f"action '{action.id}' must use distinct source and target nodes"
                )
            if action.kind is ActionKind.TCP_PROBE:
                services = {service.id for service in nodes[action.target].services}
                if action.service not in services:
                    raise ScenarioError(
                        f"action '{action.id}' references undeclared target service "
                        f"'{action.service}'"
                    )

    def run(
        self,
        scenario: Scenario,
        topology: Topology,
        executor: ActionExecutor,
        cleanup: Callable[[], None],
        *,
        reset_cancellation: bool = True,
    ) -> ScenarioResult:
        self.validate_against(scenario, topology)
        if reset_cancellation:
            self.reset_cancellation()
        started_at = datetime.now(UTC)
        start = self.clock()
        observations: list[Observation] = []
        errors: list[str] = []
        status = ExecutionStatus.FAILED
        cleaned = False
        try:
            for action in scenario.sequence:
                if self._cancelled.is_set():
                    status = ExecutionStatus.CANCELLED
                    break
                remaining = scenario.timeout_seconds - (self.clock() - start)
                if remaining <= 0:
                    status = ExecutionStatus.TIMED_OUT
                    break
                try:
                    observations.append(executor.execute(action, topology, remaining))
                except TimeoutError:
                    status = ExecutionStatus.TIMED_OUT
                    errors.append(f"action '{action.id}' timed out")
                    break
                except Exception as error:
                    errors.append(f"action '{action.id}' failed: {type(error).__name__}")
                    status = ExecutionStatus.FAILED
                    break
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
                    errors.append(f"cleanup failed: {type(error).__name__}")
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
        )

    @staticmethod
    def _matches(condition: Condition, observations: dict[str, Observation]) -> bool:
        observation = observations.get(condition.action)
        return observation is not None and getattr(observation, condition.field) == condition.equals
