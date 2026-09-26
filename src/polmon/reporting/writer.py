"""Atomic machine- and human-readable experiment report writer."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from polmon.scenarios.engine import ScenarioResult
from polmon.scenarios.models import Condition, Scenario
from polmon.telemetry.models import CaptureSummary, EventCategory, TelemetryEvent
from polmon.topology.models import Topology
from polmon.version import __version__


@dataclass(frozen=True, slots=True)
class ReportArtifacts:
    json_path: Path
    markdown_path: Path
    document: dict[str, object]


def _condition(
    condition: Condition, role: str, observations: dict[str, dict[str, object]]
) -> dict[str, object]:
    observed = observations.get(condition.action)
    actual = observed.get(condition.field) if observed is not None else None
    return {
        "role": role,
        "action": condition.action,
        "field": condition.field,
        "expected": condition.equals,
        "actual": actual,
        "matched": actual == condition.equals,
    }


def _event(event: TelemetryEvent) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "timestamp": event.timestamp.isoformat(),
        "category": event.category.value,
        "event": event.event,
        "node_id": event.node_id,
        "payload": event.payload,
    }


def build_experiment_report(
    experiment_id: str,
    topology: Topology,
    scenario: Scenario,
    result: ScenarioResult,
    events: list[TelemetryEvent],
    capture: CaptureSummary,
) -> dict[str, object]:
    observations = {
        item.action_id: {
            "action_id": item.action_id,
            "success": item.success,
            "detail": item.detail,
            "data": item.data,
        }
        for item in result.observations
    }
    comparisons = [
        *(
            _condition(condition, "success_requirement", observations)
            for condition in scenario.success_conditions
        ),
        *(
            _condition(condition, "failure_trigger", observations)
            for condition in scenario.failure_conditions
        ),
    ]
    rendered_events = [_event(event) for event in events]
    return {
        "schema_version": 1,
        "polmon_version": __version__,
        "experiment_id": experiment_id,
        "topology": topology.model_dump(mode="json", by_alias=True),
        "scenario": scenario.model_dump(mode="json"),
        "execution": {
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "status": result.status.value,
            "cleanup_performed": result.cleanup_performed,
        },
        "observed_events": rendered_events,
        "expected_vs_actual": comparisons,
        "errors": list(result.errors),
        "resource_statistics": [
            event["payload"]
            for event in rendered_events
            if event["category"] == EventCategory.RESOURCE.value
        ],
        "capture": {
            "path": str(capture.path),
            "frame_count": capture.frame_count,
            "captured_bytes": capture.captured_bytes,
            "dropped_frames": capture.dropped_frames,
            "truncated_frames": capture.truncated_frames,
        },
        "status": result.status.value,
    }


def _markdown(document: dict[str, object]) -> str:
    execution = document["execution"]
    capture = document["capture"]
    assert isinstance(execution, dict) and isinstance(capture, dict)
    comparisons = document["expected_vs_actual"]
    assert isinstance(comparisons, list)
    comparison_lines = [
        f"- `{item['action']}.{item['field']}` expected `{item['expected']}`, "
        f"observed `{item['actual']}` — {'MATCH' if item['matched'] else 'MISMATCH'}"
        for item in comparisons
        if isinstance(item, dict)
    ]
    errors = document["errors"]
    assert isinstance(errors, list)
    error_lines = [f"- {item}" for item in errors] or ["- None"]
    resources = document["resource_statistics"]
    assert isinstance(resources, list)
    return "\n".join(
        [
            f"# Experiment {document['experiment_id']}",
            "",
            f"- Polmon version: `{document['polmon_version']}`",
            f"- Status: **{document['status']}**",
            f"- Started: `{execution['started_at']}`",
            f"- Finished: `{execution['finished_at']}`",
            f"- Cleanup performed: `{execution['cleanup_performed']}`",
            "",
            "## Expected versus actual",
            "",
            *comparison_lines,
            "",
            "## Errors",
            "",
            *error_lines,
            "",
            "## Resource statistics",
            "",
            "```json",
            json.dumps(resources, indent=2, sort_keys=True),
            "```",
            "",
            "## Capture",
            "",
            f"- Frames: `{capture['frame_count']}`",
            f"- Captured bytes: `{capture['captured_bytes']}`",
            f"- Dropped frames: `{capture['dropped_frames']}`",
            f"- Truncated frames: `{capture['truncated_frames']}`",
            "",
            "## Topology",
            "",
            "```json",
            json.dumps(document["topology"], indent=2, sort_keys=True),
            "```",
            "",
            "## Scenario",
            "",
            "```json",
            json.dumps(document["scenario"], indent=2, sort_keys=True),
            "```",
            "",
            "## Observed events",
            "",
            "```json",
            json.dumps(document["observed_events"], indent=2, sort_keys=True),
            "```",
            "",
        ]
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_experiment_report(
    directory: str | Path,
    experiment_id: str,
    topology: Topology,
    scenario: Scenario,
    result: ScenarioResult,
    events: list[TelemetryEvent],
    capture: CaptureSummary,
) -> ReportArtifacts:
    document = build_experiment_report(
        experiment_id, topology, scenario, result, events, capture
    )
    root = Path(directory)
    json_path = root / f"{experiment_id}.json"
    markdown_path = root / f"{experiment_id}.md"
    _atomic_write(json_path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    _atomic_write(markdown_path, _markdown(document))
    return ReportArtifacts(json_path, markdown_path, document)
