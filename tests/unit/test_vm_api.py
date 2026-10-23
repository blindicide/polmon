"""Задания виртуальных машин за HTTP API: поддельная команда дополнения вместо настоящих гостей."""

import json
import os
import sys
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from polmon.api import vm as vm_module
from polmon.api.control import ControlPlane
from polmon.api.vm import MANIFEST, TOPOLOGY, VMJobs, VMRequest
from polmon.backend import create_app
from polmon.core.errors import ConfigurationError
from polmon.topology import load_topology

ROOT = Path(__file__).parents[2]
FAKE = """
import json, os, signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
action = sys.argv[1]
args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
behavior = os.environ.get("FAKE", "ok")
if action == "readiness":
    print(json.dumps({"ready": True, "modes": {"userns": True, "netns": False}, "missing": [],
                      "version": "0.8.0", "integration_verified": False, "extra": 1}))
elif action == "acquire-image":
    open(args["--image"], "w").write("image")
    print(json.dumps({"bytes": 5}))
elif action == "verify-image":
    print(json.dumps({"sha256": "abc"}))
elif action == "run":
    open(os.path.join(args["--directory"], "alpha.qcow2"), "w").write("overlay")
    if behavior == "fail":
        print(json.dumps({"error_code": "vm.host_memory"}), file=sys.stderr)
        sys.exit(2)
    if behavior == "hang":
        time.sleep(60)
    print(json.dumps({"ready_seconds": 1.5, "probes": {"alpha": [True]}, "sample": {}}))
elif action == "recover":
    print(json.dumps({"recovered": True}))
"""


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / "fake_addon.py"
    script.write_text(FAKE, encoding="utf-8")
    state = {"FAKE": "ok"}

    def make(**options) -> VMJobs:
        return VMJobs(
            tmp_path / "vm",
            command=lambda *arguments: [sys.executable, str(script), *arguments],
            environment=lambda: {**os.environ, **state},
            available=lambda: True,
            **options,
        )

    make.state = state
    return make


def finished(jobs: VMJobs, job_id: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.job(job_id)
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def with_image(jobs: VMJobs) -> None:
    jobs.image_path.parent.mkdir(parents=True)
    jobs.image_path.write_text("image")


def test_pinned_data_matches_the_shipped_examples(tmp_path):
    manifest = json.loads((ROOT / "examples/vm/alpine-3.24.1-manifest.json").read_text())
    assert manifest == MANIFEST
    shipped = yaml.safe_load((ROOT / "examples/topologies/l1-vm-addon.yml").read_text())
    assert yaml.safe_load(TOPOLOGY) == shipped
    (tmp_path / "topology.yml").write_text(TOPOLOGY)
    assert load_topology(tmp_path / "topology.yml").id == "vm-clones"
    assert vm_module.IMAGE_NAME.endswith(".qcow2") and "/" not in vm_module.IMAGE_NAME


def test_status_reports_the_missing_image_and_what_will_be_downloaded(fake):
    status = fake().status()
    assert status["available"] and status["running"] is None
    image = status["image"]
    assert image["present"] is False and image["sha256"] == MANIFEST["sha256"]
    assert image["source_url"].startswith("https://")


def test_readiness_passes_only_known_fields_and_is_refused_for_root(fake, monkeypatch):
    jobs = fake()
    report = jobs.readiness()
    assert report["ready"] and report["modes"] == {"userns": True, "netns": False}
    assert "extra" not in report
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    root = jobs.readiness()
    assert not root["ready"] and "vm.running_as_root" in root["missing"]
    assert root["modes"] == {"userns": False, "netns": False}
    with pytest.raises(ConfigurationError) as error:
        jobs.start(VMRequest(action="acquire"))
    assert error.value.message_code == "vm.running_as_root"


def test_missing_addon_is_reported_and_refuses_every_job(fake):
    jobs = VMJobs(Path("/nonexistent/vm"), available=lambda: False)
    assert jobs.readiness()["missing"] == ["vm.addon_missing"]
    assert jobs.status()["available"] is False
    with pytest.raises(ConfigurationError) as error:
        jobs.start(VMRequest(action="acquire"))
    assert error.value.message_code == "vm.addon_missing"


def test_acquire_then_verify_then_run_succeeds_and_leaves_no_run_directory(fake):
    jobs = fake()
    with pytest.raises(ConfigurationError) as error:
        jobs.start(VMRequest(action="run"))
    assert error.value.message_code == "vm.image_missing"
    acquired = finished(jobs, str(jobs.start(VMRequest(action="acquire"))["job_id"]))
    assert acquired["state"] == "succeeded" and jobs.status()["image"]["present"]
    with pytest.raises(ConfigurationError) as error:
        jobs.start(VMRequest(action="acquire"))
    assert error.value.message_code == "vm.image_exists"
    verified = finished(jobs, str(jobs.start(VMRequest(action="verify"))["job_id"]))
    assert verified["result"] == {"sha256": "abc"}
    ran = finished(jobs, str(jobs.start(VMRequest(action="run"))["job_id"]))
    assert ran["state"] == "succeeded" and ran["result"]["probes"] == {"alpha": [True]}
    assert list((jobs.directory / "runs").iterdir()) == []
    assert [item["action"] for item in jobs.jobs()] == ["run", "verify", "acquire"]


def test_failed_job_carries_the_addon_error_code(fake):
    jobs = fake()
    with_image(jobs)
    fake.state["FAKE"] = "fail"
    job = finished(jobs, str(jobs.start(VMRequest(action="run"))["job_id"]))
    assert job["state"] == "failed" and job["message_code"] == "vm.host_memory"
    assert job["exit_code"] == 2
    assert list((jobs.directory / "runs").iterdir()) == []


def test_unavailable_mode_is_refused_before_anything_starts(fake):
    jobs = fake()
    with_image(jobs)
    with pytest.raises(ConfigurationError) as error:
        jobs.start(VMRequest(action="run", mode="netns"))
    assert error.value.message_code == "vm.mode_unavailable"
    assert error.value.params == {"mode": "netns"}
    assert jobs.jobs() == []


def test_one_job_at_a_time_and_cancel_cleans_up(fake):
    jobs = fake()
    with_image(jobs)
    fake.state["FAKE"] = "hang"
    first = jobs.start(VMRequest(action="run"))
    with pytest.raises(ConfigurationError) as error:
        jobs.start(VMRequest(action="verify"))
    assert error.value.message_code == "vm.job_running"
    with pytest.raises(ConfigurationError):
        jobs.recover()
    deadline = time.monotonic() + 10
    while not any((jobs.directory / "runs").glob("*/alpha.qcow2")) and time.monotonic() < deadline:
        time.sleep(0.05)
    jobs.cancel(str(first["job_id"]))
    done = finished(jobs, str(first["job_id"]))
    assert done["state"] == "cancelled" and done["message_code"] == "vm.cancelled"
    assert list((jobs.directory / "runs").iterdir()) == []
    with pytest.raises(ConfigurationError) as error:
        jobs.cancel(str(first["job_id"]))
    assert error.value.message_code == "vm.job_not_running"
    with pytest.raises(ConfigurationError) as error:
        jobs.job("0" * 12)
    assert error.value.message_code == "vm.unknown_job"


def test_a_job_over_its_time_limit_is_stopped(fake, monkeypatch):
    jobs = fake()
    with_image(jobs)
    fake.state["FAKE"] = "hang"
    monkeypatch.setitem(vm_module.JOB_SECONDS, "run", 0.5)
    job = finished(jobs, str(jobs.start(VMRequest(action="run"))["job_id"]))
    assert job["state"] == "failed" and job["message_code"] == "vm.timeout"


def test_recover_removes_leftover_run_directories(fake):
    jobs = fake()
    leftover = jobs.directory / "runs" / "abc"
    leftover.mkdir(parents=True)
    (leftover / "state.json").write_text("{}")
    assert jobs.recover() == {"directories": 1, "recovered": 1, "failed": 0}
    assert not leftover.exists()
    leftover.mkdir()
    jobs.recover_at_startup()
    assert not leftover.exists()


def test_http_contract_and_capability(tmp_path, monkeypatch):
    monkeypatch.setattr(vm_module, "addon_available", lambda: False)
    plane = ControlPlane(tmp_path, l0_only=True)
    try:
        client = TestClient(create_app(plane))
        capabilities = client.get("/v1/resources").json()["capabilities"]
        assert capabilities["fidelity"] == "l0_only" and capabilities["vm"] is False
        assert client.get("/v1/vm/status").json()["available"] is False
        assert client.get("/v1/vm/readiness").json()["missing"] == ["vm.addon_missing"]
        refused = client.post("/v1/vm/jobs", json={"action": "acquire"})
        assert refused.status_code == 422
        assert refused.json()["error"]["message_code"] == "vm.addon_missing"
        assert client.post("/v1/vm/jobs", json={"action": "format"}).status_code == 422
        assert client.post("/v1/vm/jobs", json={"action": "run", "url": "x"}).status_code == 422
        assert client.get("/v1/vm/jobs").json() == []
        missing = client.get("/v1/vm/jobs/000000000000")
        assert missing.json()["error"]["message_code"] == "vm.unknown_job"
        assert client.get("/v1/vm/jobs/not-an-id").status_code == 422
    finally:
        plane.close()
