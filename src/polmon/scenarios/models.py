"""Strict scenario schema with no arbitrary command surface."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from polmon.topology.models import StrictModel, _identifier


class ActionKind(StrEnum):
    ICMP_PROBE = "icmp_probe"
    TCP_PROBE = "tcp_probe"


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
    source: str
    target: str
    service: str | None = None

    _validate_ids = field_validator("id", "source", "target")(_identifier)

    @model_validator(mode="after")
    def validate_kind_fields(self) -> ScenarioAction:
        if self.kind is ActionKind.TCP_PROBE and self.service is None:
            raise ValueError("tcp_probe requires a declared service identifier")
        if self.kind is ActionKind.ICMP_PROBE and self.service is not None:
            raise ValueError("icmp_probe does not accept a service identifier")
        if self.service is not None:
            _identifier(self.service)
        return self


class Condition(StrictModel):
    action: str
    field: Literal["success", "detail"]
    equals: bool | str

    _validate_action = field_validator("action")(_identifier)

    @model_validator(mode="after")
    def validate_value_type(self) -> Condition:
        if self.field == "success" and not isinstance(self.equals, bool):
            raise ValueError("success conditions require a boolean value")
        if self.field == "detail" and not isinstance(self.equals, str):
            raise ValueError("detail conditions require a string value")
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

    _validate_ids = field_validator("id", "required_topology")(_identifier)

    @model_validator(mode="after")
    def validate_scenario(self) -> Scenario:
        action_ids = [action.id for action in self.sequence]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("scenario action identifiers must be unique")
        unpermitted = sorted({action.kind for action in self.sequence} - self.permitted_actions)
        if unpermitted:
            raise ValueError(f"scenario sequence contains unpermitted actions: {unpermitted}")
        known = set(action_ids)
        for condition in [*self.success_conditions, *self.failure_conditions]:
            if condition.action not in known:
                raise ValueError(f"condition references unknown action '{condition.action}'")
        return self

