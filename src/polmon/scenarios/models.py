"""Strict scenario schema with a bounded automated command surface."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from polmon.core.errors import CodedValueError
from polmon.scenarios.catalog import validate_command
from polmon.topology.models import StrictModel, _identifier


class ActionKind(StrEnum):
    ICMP_PROBE = "icmp_probe"
    TCP_PROBE = "tcp_probe"
    SSH_EXEC = "ssh_exec"
    WAIT = "wait"


class InitialCondition(StrEnum):
    TOPOLOGY_DEPLOYED = "topology_deployed"
    SERVICES_STARTED = "services_started"


class CleanupPolicy(StrEnum):
    ALWAYS = "always"
    ON_FAILURE = "on_failure"
    NEVER = "never"


class ScenarioAction(StrictModel):
    id: str
    kind: ActionKind
    source: str | None = None
    target: str | None = None
    service: str | None = None
    command: str | None = None
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    expected_exit_status: int = Field(default=0, ge=0, le=255)
    seconds: float | None = Field(default=None, gt=0, le=60)

    _validate_id = field_validator("id")(_identifier)

    @model_validator(mode="after")
    def validate_kind_fields(self) -> ScenarioAction:
        if self.kind in {ActionKind.ICMP_PROBE, ActionKind.TCP_PROBE}:
            if self.source is None or self.target is None:
                raise CodedValueError(
                    f"{self.kind.value} requires source and target nodes",
                    "scenario.action_nodes_required",
                    action=self.id,
                )
            _identifier(self.source)
            _identifier(self.target)
        if self.kind is ActionKind.TCP_PROBE and self.service is None:
            raise CodedValueError(
                "tcp_probe requires a declared service identifier",
                "scenario.tcp_probe_needs_service",
            )
        if self.kind is ActionKind.ICMP_PROBE and self.service is not None:
            raise CodedValueError(
                "icmp_probe does not accept a service identifier",
                "scenario.icmp_probe_no_service",
            )
        if self.kind is ActionKind.SSH_EXEC:
            if self.target is None:
                raise CodedValueError(
                    "ssh_exec requires a target node",
                    "scenario.action_target_required",
                    action=self.id,
                )
            _identifier(self.target)
            if self.source is not None:
                _identifier(self.source)
            if self.service is not None:
                raise CodedValueError(
                    "ssh_exec does not accept a service identifier",
                    "scenario.ssh_exec_no_service",
                )
            validate_command(self.command, self.parameters)
        if self.kind is ActionKind.WAIT:
            if self.seconds is None:
                raise CodedValueError(
                    "wait requires seconds",
                    "scenario.wait_seconds_required",
                )
            if any(
                value is not None
                for value in (self.source, self.target, self.service, self.command)
            ):
                raise CodedValueError(
                    "wait accepts only seconds",
                    "scenario.wait_fields_invalid",
                )
            if self.parameters:
                raise CodedValueError(
                    "wait does not accept parameters",
                    "scenario.wait_fields_invalid",
                )
        if self.service is not None:
            _identifier(self.service)
        return self


class Condition(StrictModel):
    action: str
    field: Literal["success", "detail", "duration_seconds", "stdout"]
    equals: bool | str | float | int | None = None
    minimum: float | None = Field(default=None, ge=0, le=3600)
    maximum: float | None = Field(default=None, ge=0, le=3600)
    pattern: str | None = Field(default=None, max_length=128)

    _validate_action = field_validator("action")(_identifier)

    @model_validator(mode="after")
    def validate_value_type(self) -> Condition:
        if self.field == "success" and not isinstance(self.equals, bool):
            raise CodedValueError(
                "success conditions require a boolean value",
                "scenario.success_needs_boolean",
            )
        if self.field == "detail" and not isinstance(self.equals, str):
            raise CodedValueError(
                "detail conditions require a string value",
                "scenario.detail_needs_string",
            )
        if self.field == "duration_seconds":
            if self.equals is not None and not isinstance(self.equals, int | float):
                raise CodedValueError(
                    "duration conditions require a number",
                    "scenario.duration_needs_number",
                )
            if self.minimum is None and self.maximum is None and self.equals is None:
                raise CodedValueError(
                    "duration conditions require a bound",
                    "scenario.duration_bound_required",
                )
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise CodedValueError(
                    "duration minimum cannot exceed maximum",
                    "scenario.duration_bounds_invalid",
                )
        if self.field == "stdout" and self.equals is None and self.pattern is None:
            raise CodedValueError(
                "stdout conditions require equals or pattern",
                "scenario.stdout_match_required",
            )
        if self.pattern is not None:
            import re

            try:
                re.compile(self.pattern)
            except re.error as error:
                raise CodedValueError(
                    "stdout pattern is not a valid regular expression",
                    "scenario.stdout_pattern_invalid",
                ) from error
        return self


class Scenario(StrictModel):
    id: str
    required_topology: str
    initial_conditions: list[InitialCondition] = Field(min_length=1)
    permitted_actions: set[ActionKind] = Field(min_length=1)
    sequence: list[ScenarioAction] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0, le=3600)
    success_conditions: list[Condition] = Field(min_length=1)
    failure_conditions: list[Condition] = Field(default_factory=list)
    cleanup_policy: CleanupPolicy = CleanupPolicy.ALWAYS
    cleanup_steps: list[ScenarioAction] = Field(default_factory=list, alias="cleanup")

    _validate_ids = field_validator("id", "required_topology")(_identifier)

    @model_validator(mode="after")
    def validate_scenario(self) -> Scenario:
        action_ids = [action.id for action in self.sequence]
        if len(action_ids) != len(set(action_ids)):
            raise CodedValueError(
                "scenario action identifiers must be unique",
                "scenario.duplicate_action_ids",
            )
        unpermitted = sorted({action.kind for action in self.sequence} - self.permitted_actions)
        if unpermitted:
            raise CodedValueError(
                f"scenario sequence contains unpermitted actions: {unpermitted}",
                "scenario.unpermitted_actions",
                actions=unpermitted,
            )
        known = set(action_ids)
        for condition in [*self.success_conditions, *self.failure_conditions]:
            if condition.action not in known:
                raise CodedValueError(
                    f"condition references unknown action '{condition.action}'",
                    "scenario.unknown_condition_action",
                    action=condition.action,
                )
        cleanup_ids = [action.id for action in self.cleanup_steps]
        if len(cleanup_ids) != len(set(cleanup_ids)) or known.intersection(cleanup_ids):
            raise CodedValueError(
                "cleanup action identifiers must be unique and separate from the sequence",
                "scenario.duplicate_cleanup_action_ids",
            )
        return self
