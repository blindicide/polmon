"""FastAPI route declarations and request contracts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from polmon.api.benchmarks import RESULT_NAME, BenchmarkRequest
from polmon.api.control import ControlPlane
from polmon.telemetry.store import EXPERIMENT_ID
from polmon.topology.models import IDENTIFIER
from polmon.version import __version__

router = APIRouter(prefix="/v1")

TopologyId = Annotated[str, Path(pattern=IDENTIFIER.pattern)]
ExperimentId = Annotated[str, Path(pattern=EXPERIMENT_ID.pattern)]
JobId = Annotated[str, Path(pattern=r"^[0-9a-f]{12}$")]
ResultName = Annotated[str, Path(pattern=RESULT_NAME.pattern)]


class YamlDocument(BaseModel):
    yaml: str = Field(min_length=1, max_length=2_000_000)


class ExperimentRequest(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=64, pattern=EXPERIMENT_ID.pattern)
    topology_id: str = Field(min_length=1, max_length=32, pattern=IDENTIFIER.pattern)
    scenario_yaml: str = Field(min_length=1, max_length=2_000_000)
    # False: return HTTP 202 once admitted; poll GET /v1/experiments/{id} for progress.
    wait: bool = True


def control(request: Request) -> ControlPlane:
    return request.app.state.control


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    return {
        "name": "polmon",
        "version": __version__,
        "status": "ok",
        "capabilities": control(request).capabilities(),
    }


@router.post("/topologies/validate")
def validate_topology(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).validate_topology(document.yaml)


@router.post("/topologies")
def load_topology(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).load_topology(document.yaml)


@router.get("/topologies")
def list_topologies(request: Request) -> list[dict[str, object]]:
    return control(request).list_topologies()


@router.get("/topologies/{topology_id}")
def topology_detail(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).topology_detail(topology_id)


@router.delete("/topologies/{topology_id}")
def unload_topology(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).unload_topology(topology_id)


@router.post("/scenarios/validate")
def validate_scenario(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).validate_scenario(document.yaml)


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


@router.get("/experiments")
def list_experiments(
    request: Request, limit: Annotated[int, Query(ge=1, le=1000)] = 200
) -> list[dict[str, object]]:
    return control(request).list_experiments(limit)


@router.post("/experiments")
def experiment(
    payload: ExperimentRequest, request: Request, response: Response
) -> dict[str, object]:
    result = control(request).run_experiment(
        payload.experiment_id, payload.topology_id, payload.scenario_yaml, wait=payload.wait
    )
    if not payload.wait:
        response.status_code = 202
    return result


@router.get("/experiments/{experiment_id}")
def experiment_status(experiment_id: ExperimentId, request: Request) -> dict[str, object]:
    return control(request).experiment(experiment_id)


@router.post("/experiments/{experiment_id}/cancel")
def cancel_experiment(experiment_id: ExperimentId, request: Request) -> dict[str, object]:
    return control(request).cancel_experiment(experiment_id)


@router.get("/experiments/{experiment_id}/telemetry")
def experiment_telemetry(
    experiment_id: ExperimentId,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int | None, Query(ge=1, le=5000)] = None,
) -> list[dict[str, object]]:
    return control(request).experiment_telemetry(experiment_id, after=after, limit=limit)


@router.get("/experiments/{experiment_id}/report")
def experiment_report(experiment_id: ExperimentId, request: Request) -> dict[str, object]:
    return control(request).experiment_report(experiment_id)


@router.get("/experiments/{experiment_id}/report/markdown")
def experiment_report_markdown(experiment_id: ExperimentId, request: Request) -> dict[str, object]:
    return control(request).experiment_report_markdown(experiment_id)


@router.get("/experiments/{experiment_id}/capture", response_class=FileResponse)
def experiment_capture(experiment_id: ExperimentId, request: Request) -> FileResponse:
    path = control(request).experiment_capture_path(experiment_id)
    return FileResponse(
        path, media_type="application/vnd.tcpdump.pcap", filename=f"{experiment_id}.pcap"
    )


@router.post("/benchmarks")
def start_benchmark(
    payload: BenchmarkRequest, request: Request, response: Response
) -> dict[str, object]:
    response.status_code = 202
    return control(request).start_benchmark(payload)


@router.get("/benchmarks/jobs")
def benchmark_jobs(request: Request) -> list[dict[str, object]]:
    return control(request).benchmarks.jobs()


@router.get("/benchmarks/jobs/{job_id}")
def benchmark_job(job_id: JobId, request: Request) -> dict[str, object]:
    return control(request).benchmarks.job(job_id)


@router.post("/benchmarks/jobs/{job_id}/cancel")
def cancel_benchmark(job_id: JobId, request: Request) -> dict[str, object]:
    return control(request).benchmarks.cancel(job_id)


@router.get("/benchmarks/results")
def benchmark_results(request: Request) -> list[dict[str, object]]:
    return control(request).benchmarks.results()


@router.get("/benchmarks/results/{name}")
def benchmark_result(name: ResultName, request: Request) -> dict[str, object]:
    return control(request).benchmarks.result(name)
