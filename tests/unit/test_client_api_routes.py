"""Every ApiClient method against a real backend over HTTP, plus malformed-response handling."""

import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import uvicorn

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.client.api import ApiClient, ApiClientError

TOKEN = "r" * 32
TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/l0-office.yml"
SCENARIO = Path(__file__).parents[2] / "examples/scenarios/office-sweep.yml"
LIMITS = {
    "max_endpoints": 50,
    "max_namespaces": 0,
    "max_run_seconds": 60,
    "max_incremental_mb": 256,
    "memory_reserve_mb": 256,
}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def idle_job(command, stdout):
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=stdout,
        stderr=subprocess.PIPE,
        start_new_session=sys.platform != "win32",
    )


@pytest.fixture
def backend(tmp_path):
    plane = ControlPlane(tmp_path)
    plane.benchmarks._launcher = idle_job
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(plane, api_token=TOKEN), host="127.0.0.1", port=port, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    yield ApiClient(f"http://127.0.0.1:{port}", token=TOKEN, timeout=10)
    server.should_exit = True
    thread.join(timeout=15)


def wait(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached")


def test_every_client_method_round_trips(backend: ApiClient) -> None:
    source = TOPOLOGY.read_text(encoding="utf-8")
    assert backend.health()["status"] == "ok"
    assert backend.validate_topology(source)["topology"]["id"] == "l0-office"
    assert backend.load_topology(source)["topology_id"] == "l0-office"
    assert [item["topology_id"] for item in backend.topologies()] == ["l0-office"]
    assert backend.topology("l0-office")["deployed"] is False
    scenario = SCENARIO.read_text(encoding="utf-8")
    assert backend.validate_scenario(scenario)["topology_check"]["loaded"] is True
    assert backend.deploy("l0-office")["state"] == "running"
    assert backend.deployment("l0-office")["backend"] == "synthetic"
    assert backend.resources()["active_deployments"] == 1
    started = backend.run_experiment("routes-1", "l0-office", scenario, wait=False)
    assert started["experiment_id"] == "routes-1"
    final = wait(lambda: (e := backend.experiment("routes-1"))["status"] == "succeeded" and e)
    assert final["progress"]["completed_actions"] == 7
    assert backend.experiments()[0]["experiment_id"] == "routes-1"
    events = backend.telemetry("routes-1")
    assert backend.telemetry("routes-1", after=events[0]["sequence"], limit=1) == events[1:2]
    assert backend.report("routes-1")["status"] == "succeeded"
    assert "routes-1" in backend.report_markdown("routes-1")
    assert backend.capture("routes-1")[:4] in {b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"}
    with pytest.raises(ApiClientError) as inactive:
        backend.cancel_experiment("routes-1")
    assert inactive.value.status == 422
    with pytest.raises(ApiClientError) as big:
        backend.capture("routes-1", limit=10)
    assert "client limit" in str(big.value)
    job = backend.start_benchmark({"kind": "l0", "counts": [5], "limits": LIMITS})
    assert backend.benchmark_job(job["job_id"])["state"] == "running"
    assert backend.benchmark_jobs()[0]["job_id"] == job["job_id"]
    assert backend.cancel_benchmark(job["job_id"])["job_id"] == job["job_id"]
    wait(lambda: backend.benchmark_job(job["job_id"])["state"] == "cancelled")
    assert backend.benchmark_results() == []
    with pytest.raises(ApiClientError) as missing:
        backend.benchmark_result("absent.json")
    assert missing.value.status == 422
    assert backend.destroy("l0-office")["state"] == "destroyed"
    assert backend.unload_topology("l0-office")["state"] == "deleted"
    assert backend.reset_all()["deployments_destroyed"] == 0


class WrongShapes(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps([1, 2] if self.path.startswith("/v1/health") else {"x": 1}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


def test_wrong_response_shapes_are_reported_not_crashed() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), WrongShapes)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ApiClient(f"http://127.0.0.1:{server.server_port}", timeout=2)
        with pytest.raises(ApiClientError) as not_object:
            client.health()
        assert not_object.value.code == "malformed_response" and "expected an object" in str(
            not_object.value
        )
        with pytest.raises(ApiClientError) as not_list:
            client.topologies()
        assert "expected a list" in str(not_list.value)
        with pytest.raises(ApiClientError) as no_markdown:
            client.report_markdown("x")
        assert no_markdown.value.code == "malformed_response"
    finally:
        server.shutdown()
        server.server_close()


def test_client_settings_are_validated() -> None:
    for timeout in (0, -1, 601):
        with pytest.raises(ValueError):
            ApiClient("http://127.0.0.1:1", timeout=timeout)
    assert "set" in repr(ApiClient("http://127.0.0.1:1", token="secret-token-value"))
    assert "secret" not in repr(ApiClient("http://127.0.0.1:1", token="secret-token-value"))
