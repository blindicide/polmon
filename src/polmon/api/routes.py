"""FastAPI route declarations and request contracts."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
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
SessionId = Annotated[str, Path(pattern=r"^[0-9a-f]{12}$")]
ResultName = Annotated[str, Path(pattern=RESULT_NAME.pattern)]


class YamlDocument(BaseModel):
    yaml: str = Field(min_length=1, max_length=2_000_000)


class ExperimentRequest(BaseModel):
    experiment_id: str = Field(min_length=1, max_length=64, pattern=EXPERIMENT_ID.pattern)
    topology_id: str = Field(min_length=1, max_length=32, pattern=IDENTIFIER.pattern)
    scenario_yaml: str = Field(min_length=1, max_length=2_000_000)
    # False: return HTTP 202 once admitted; poll GET /v1/experiments/{id} for progress.
    wait: bool = True


class ConsoleExecRequest(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=32)
    timeout_seconds: float = Field(default=10, ge=0.1, le=60)


class ConsoleInputRequest(BaseModel):
    data: str = Field(min_length=1, max_length=4096)


class PacketSendRequest(BaseModel):
    interface_id: str = Field(min_length=1, max_length=32, pattern=IDENTIFIER.pattern)
    frame_hex: str = Field(max_length=8192)


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


@router.post("/topologies/import")
def import_topology(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).load_topology(document.yaml)


@router.get("/topologies")
def list_topologies(request: Request) -> list[dict[str, object]]:
    return control(request).list_topologies()


@router.get("/topologies/{topology_id}")
def topology_detail(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).topology_detail(topology_id)


@router.put("/topologies/{topology_id}")
def put_topology(
    topology_id: TopologyId, document: YamlDocument, request: Request
) -> dict[str, object]:
    return control(request).load_topology(document.yaml, topology_id)


@router.delete("/topologies/{topology_id}")
def unload_topology(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).unload_topology(topology_id)


@router.post("/scenarios/validate")
def validate_scenario(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).validate_scenario(document.yaml)


@router.post("/scenarios")
def load_scenario(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).load_scenario(document.yaml)


@router.post("/scenarios/import")
def import_scenario(document: YamlDocument, request: Request) -> dict[str, object]:
    return control(request).load_scenario(document.yaml)


@router.get("/scenarios")
def list_scenarios(request: Request) -> list[dict[str, object]]:
    return control(request).list_scenarios()


@router.get("/scenarios/{scenario_id}")
def scenario_detail(scenario_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).scenario_detail(scenario_id)


@router.put("/scenarios/{scenario_id}")
def put_scenario(
    scenario_id: TopologyId, document: YamlDocument, request: Request
) -> dict[str, object]:
    return control(request).load_scenario(document.yaml, scenario_id)


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).unload_scenario(scenario_id)


@router.post("/deployments/{topology_id}")
def deploy(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).deploy(topology_id)


@router.get("/deployments/{topology_id}")
def deployment(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).deployment(topology_id)


@router.delete("/deployments/{topology_id}")
def destroy(topology_id: TopologyId, request: Request) -> dict[str, object]:
    return control(request).destroy(topology_id)


@router.post("/deployments/{topology_id}/nodes/{node_id}/packets")
def send_packet(
    topology_id: TopologyId,
    node_id: TopologyId,
    payload: PacketSendRequest,
    request: Request,
) -> dict[str, object]:
    return control(request).send_packet(
        topology_id, node_id, payload.interface_id, payload.frame_hex
    )


@router.get("/deployments/{topology_id}/nodes/{node_id}/console/readiness")
def console_readiness(
    topology_id: TopologyId, node_id: TopologyId, request: Request
) -> dict[str, object]:
    return control(request).console_readiness(topology_id, node_id)


@router.post("/deployments/{topology_id}/nodes/{node_id}/console/vnc")
def console_vnc(
    topology_id: TopologyId, node_id: TopologyId, request: Request
) -> dict[str, object]:
    return control(request).console_vnc_start(topology_id, node_id)


@router.websocket("/deployments/{topology_id}/nodes/{node_id}/console/vnc/{session_id}")
async def console_vnc_relay(
    topology_id: str, node_id: str, session_id: str, websocket: WebSocket
) -> None:
    del topology_id, node_id
    await websocket.accept()
    await websocket.app.state.control.console_vnc_relay(session_id, websocket)


@router.post("/deployments/{topology_id}/nodes/{node_id}/console/exec")
def console_exec(
    topology_id: TopologyId,
    node_id: TopologyId,
    payload: ConsoleExecRequest,
    request: Request,
) -> dict[str, object]:
    return control(request).console_exec(
        topology_id, node_id, payload.argv, payload.timeout_seconds
    )


@router.post("/deployments/{topology_id}/nodes/{node_id}/console/sessions")
def console_session_create(
    topology_id: TopologyId, node_id: TopologyId, request: Request
) -> dict[str, object]:
    return control(request).console_session_create(topology_id, node_id)


@router.get("/deployments/{topology_id}/nodes/{node_id}/console/sessions/{session_id}")
def console_session(
    topology_id: TopologyId,
    node_id: TopologyId,
    session_id: SessionId,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    del topology_id, node_id
    return control(request).console_session(session_id, after)


@router.get("/deployments/{topology_id}/nodes/{node_id}/console/sessions/{session_id}/stream")
def console_session_stream(
    topology_id: TopologyId,
    node_id: TopologyId,
    session_id: SessionId,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    """Cursor polling stream; clients repeat this request with the returned cursor."""
    del topology_id, node_id
    return control(request).console_session(session_id, after)


@router.post("/deployments/{topology_id}/nodes/{node_id}/console/sessions/{session_id}/input")
def console_session_input(
    topology_id: TopologyId,
    node_id: TopologyId,
    session_id: SessionId,
    payload: ConsoleInputRequest,
    request: Request,
) -> dict[str, object]:
    del topology_id, node_id
    return control(request).console_session_input(session_id, payload.data)


@router.get("/deployments/{topology_id}/nodes/{node_id}/console/sessions/{session_id}/transcript")
def console_session_transcript(
    topology_id: TopologyId,
    node_id: TopologyId,
    session_id: SessionId,
    request: Request,
) -> dict[str, object]:
    del topology_id, node_id
    return control(request).console_transcript(session_id)


@router.delete("/deployments/{topology_id}/nodes/{node_id}/console/sessions/{session_id}")
def console_session_delete(
    topology_id: TopologyId,
    node_id: TopologyId,
    session_id: SessionId,
    request: Request,
) -> dict[str, object]:
    del topology_id, node_id
    return control(request).console_session_delete(session_id)


@router.post("/reset")
def reset(request: Request) -> dict[str, object]:
    return control(request).reset_all()


@router.get("/resources")
def resource_status(request: Request) -> dict[str, object]:
    return control(request).resource_status()


@router.get("/logs")
def logs(
    request: Request,
    level: str | None = None,
    source: str | None = None,
    deployment: str | None = None,
    topology: str | None = None,
    node: str | None = None,
    session: str | None = None,
    experiment: str | None = None,
    search: str | None = None,
    since: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict[str, object]:
    return control(request).logs_query(
        level=level,
        source=source,
        deployment=deployment,
        topology=topology,
        node=node,
        session=session,
        experiment=experiment,
        search=search,
        since=since,
        limit=limit,
    )


@router.get("/logs/files")
def log_files(request: Request) -> dict[str, object]:
    return control(request).logs_files()


@router.get("/logs/stream")
def log_stream(
    request: Request,
    since: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> StreamingResponse:
    store = control(request).logs

    def events():
        cursor = since
        for _ in range(20):
            result = store.wait_for(cursor, timeout=0.5)
            records = result["records"]
            if not isinstance(records, list) or not records:
                yield ": heartbeat\n\n"
                continue
            for record in records[:limit]:
                if not isinstance(record, dict):
                    continue
                cursor = int(record.get("cursor", cursor))
                payload = json.dumps(record, ensure_ascii=False)
                yield f"id: {cursor}\nevent: log\ndata: {payload}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


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
