"""Counter provenance, identity, retention and real rootless procfs observations."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.resources.analytics import ResourceAnalytics, Subject, network_sample, process_sample


def proc_process(proc, pid=123, *, start=50, cpu=100, rss=4, io=True):
    path = proc / str(pid)
    path.mkdir(exist_ok=True)
    fields = ["0"] * 22
    fields[0], fields[11], fields[12] = "S", str(cpu), "0"
    fields[19], fields[21] = str(start), str(rss)
    (path / "stat").write_text(f"{pid} (a tricky ) name) " + " ".join(fields))
    task = path / "task" / str(pid)
    task.mkdir(parents=True, exist_ok=True)
    (task / "children").write_text("")
    if io:
        (path / "io").write_text("read_bytes: 12\nwrite_bytes: 34\n")
    return path


def subject(pid=123, uuid="u"):
    return Subject("lab", "node", uuid, "l1", (pid,))


def test_procfs_names_cpu_deltas_and_pid_reuse(tmp_path):
    proc_process(tmp_path)
    meter = ResourceAnalytics(proc=tmp_path, interval_seconds=1)
    assert meter.sample([subject()], now=10)
    assert not meter.sample([subject()], now=10.2)
    assert meter.export()["samples"][0]["nodes"][0]["cpu_percent"] is None
    proc_process(tmp_path, cpu=150)
    meter.sample([subject()], now=11)
    row = meter.export()["samples"][-1]["nodes"][0]
    assert row["cpu_percent"] == 50 / os.sysconf("SC_CLK_TCK") * 100
    assert row["read_bytes"] == 12
    proc_process(tmp_path, start=51, cpu=1)
    meter.sample([subject()], now=12)
    assert meter.export()["samples"][-1]["nodes"][0]["cpu_percent"] is None


def test_missing_counters_and_gap_are_not_zero(tmp_path):
    proc_process(tmp_path, io=False)
    meter = ResourceAnalytics(proc=tmp_path, interval_seconds=1)
    meter.sample([subject()], now=1)
    meter.sample([subject()], now=10)
    last = meter.export()["samples"][-1]
    assert last["sampling_gap"]
    assert last["nodes"][0]["read_bytes"] is None
    assert last["nodes"][0]["cpu_percent"] is None
    assert last["nodes"][0]["network"] is None
    assert process_sample(999, tmp_path) is None
    assert network_sample([123], None, tmp_path) is None


def test_no_duplicate_process_charges(tmp_path):
    proc_process(tmp_path)
    meter = ResourceAnalytics(proc=tmp_path)
    meter.sample([subject(), subject(uuid="sibling")], now=1)
    last = meter.export()["samples"][-1]
    assert last["nodes"][1]["rss_bytes"] is None
    assert last["nodes"][1]["shared_process_excluded"]
    assert last["deployments"][0]["rss_bytes"] == 4 * os.sysconf("SC_PAGE_SIZE")
    assert not last["deployments"][0]["complete"]
    with pytest.raises(ValueError, match="duplicate"):
        meter.sample([subject(), subject()], now=4)


def test_count_bytes_and_previous_identity_are_bounded(tmp_path):
    proc_process(tmp_path)
    meter = ResourceAnalytics(proc=tmp_path, interval_seconds=1, retention=3, max_bytes=4096)
    for i in range(20):
        meter.sample([subject(uuid=str(i))], now=float(i))
    result = meter.export()
    assert 1 <= len(result["samples"]) <= 3
    assert result["stored_bytes"] <= 4096
    assert result["dropped_samples"] >= 17
    assert len(meter._previous) == 1
    assert result["samples"][-1]["nodes"][0]["cpu_percent"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval_seconds": 0},
        {"interval_seconds": float("nan")},
        {"retention": 1001},
        {"max_bytes": 1024},
        {"max_subjects": 0},
    ],
)
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        ResourceAnalytics(**kwargs)


def test_subject_budget_and_process_tree_bound(tmp_path):
    path = proc_process(tmp_path)
    (path / "task/123/children").write_text(" ".join(str(i) for i in range(200, 400)))
    meter = ResourceAnalytics(proc=tmp_path, max_subjects=1)
    meter.sample([subject()], now=1)
    assert not meter.export()["samples"][0]["nodes"][0]["process_tree_complete"]
    with pytest.raises(ValueError, match="subject limit"):
        meter.sample([subject(), subject(uuid="two")], now=4)


def test_live_process_and_api_history(tmp_path):
    if not Path("/proc/self/stat").exists():
        pytest.skip("Linux procfs observation")
    actual = process_sample(os.getpid())
    assert actual and actual["rss_bytes"] > 0 and actual["cpu_seconds"] >= 0
    plane = ControlPlane(tmp_path, l0_only=True)
    try:
        with TestClient(create_app(plane)) as client:
            response = client.get("/v1/resources/history?limit=2")
            assert response.status_code == 200
            body = response.json()
            assert body["samples"][0]["nodes"][0]["rss_bytes"] > 0
            assert body["samples"][0]["nodes"][0]["network"] is None
            assert client.get("/v1/resources/history?limit=1001").status_code == 422
    finally:
        plane.close()
