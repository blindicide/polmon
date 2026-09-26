"""FastAPI route declarations and request contracts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from polmon.api.control import ControlPlane
from polmon.telemetry.store import EXPERIMENT_ID
from polmon.topology.models import IDENTIFIER
from polmon.version import __version__

router = APIRouter(prefix="/v1")

TopologyId = Annotated[str, Path(pattern=IDENTIFIER.pattern)]
ExperimentId = Annotated[str, Path(pattern=EXPERIMENT_ID.pattern)]


class YamlDocument(BaseModel):
    yaml: str = Field(min_length=1, max_length=2_000_000)


class ExperimentRequest(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=64, pattern=EXPERIMENT_ID.pattern)
    topology_id: str = Field(min_length=1, max_length=32, pattern=IDENTIFIER.pattern)
    scenario_yaml: str = Field(min_length=1, max_length=2_000_000)


def control(request: Request) -> ControlPlane:
    return request.app.state.control


@router.get("/health")
def health() -> dict[str, str]:
    return {"name": "polmon", "version": __version__, "status": "ok"}


@router.post("/topologies/validate")
def validate_topology(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).validate_topology(document.yaml)


@router.post("/topologies")
def load_topology(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).load_topology(document.yaml)


@router.post("/deployments/{topology_id}")
def deploy(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).deploy(topology_id)


@router.get("/deployments/{topology_id}")
def deployment(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).deployment(topology_id)


@router.delete("/deployments/{topology_id}")
def destroy(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).destroy(topology_id)


@router.post("/reset")
def reset(request: Request) -> dict[str, object]:
    return control(request).reset_all()


@router.get("/resources")
def resource_status(request: Request) -> dict[str, object]:
    return control(request).resource_status()


@router.post("/experiments")
def experiment(payload: ExperimentRequest, request: Request) -> dict[str, object]:
    return control(request).run_experiment(
        payload.experiment_id, payload.topology_id, payload.scenario_yaml
    )


@router.get("/experiments/{experiment_id}")
def experiment_status(experiment_id: ExperimentId, request: Request) -> dict[str, object]:
    return control(request).experiment(experiment_id)


@router.post("/experiments/{experiment_id}/cancel")
def cancel_experiment(experiment_id: ExperimentId, request: Request) -> dict[str, object]:
    return control(request).cancel_experiment(experiment_id)


@router.get("/experiments/{experiment_id}/telemetry")
def experiment_telemetry(experiment_id: ExperimentId, request: Request) -> list[dict[str, object]]:
    return control(request).experiment_telemetry(experiment_id)


@router.get("/experiments/{experiment_id}/report")
def experiment_report(experiment_id: ExperimentId, request: Request) -> dict[str, object]:
    return control(request).experiment_report(experiment_id)
