"""Telemetry record types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class EventCategory(StrEnum):
    SCENARIO = "scenario"
    NODE_LIFECYCLE = "node_lifecycle"
    NETWORK_OBSERVATION = "network_observation"
    EXECUTION_ERROR = "execution_error"
    RESOURCE = "resource"


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    sequence: int
    experiment_id: str
    timestamp: datetime
    category: EventCategory
    event: str
    node_id: str | None
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class CaptureSummary:
    experiment_id: str
    path: Path
    frame_count: int
    captured_bytes: int
    dropped_frames: int
    truncated_frames: int

