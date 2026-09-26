"""Explicit performance benchmarks (``pytest -m performance``); small sizes only.

Large L0 sizes (100, 250) are never run from pytest; use ``polmon-benchmark l0 --large``.
"""

import json

import pytest

from polmon.benchmarks import cli
from polmon.benchmarks.l1 import namespace_environment_available

pytestmark = pytest.mark.performance


def _run(tmp_path, *arguments: str) -> dict:
    code = cli.main([*arguments, "--output-dir", str(tmp_path)])
    [written] = tmp_path.glob("*.json")
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert code == cli.EXIT_OK, payload.get("error")
    assert list(tmp_path.glob("*.csv")), "raw CSV measurements must be retained"
    return payload


def test_l0_benchmark_small_sizes_are_reproducible(tmp_path) -> None:
    payload = _run(
        tmp_path, "l0", "--counts", "10", "25", "--repeats", "2", "--idle-seconds", "0.05"
    )
    rows = payload["measurements"]
    assert payload["status"] == "complete"
    assert [(row["endpoint_count"], row["repeat"]) for row in rows] == [
        (10, 1),
        (10, 2),
        (25, 1),
        (25, 2),
    ]
    for row in rows:
        assert row["cleanup_complete"] is True
        assert row["packet_loss_percent"] == 0.0
        assert row["traffic_successes"] == 2 * (row["endpoint_count"] - 1)
        assert row["python_heap_deployed_bytes"] > 0
        assert row["python_heap_residual_bytes"] < row["python_heap_deployed_bytes"]
    assert payload["hardware"]["logical_cpu_count"]
    assert any("not equivalent" in item for item in payload["limitations"])


@pytest.mark.privileged
def test_l1_benchmark_measures_namespaces_and_cleans_up(tmp_path) -> None:
    available, reason = namespace_environment_available()
    if not available:
        pytest.skip(f"NOT RUN — environment unavailable: {reason}")
    payload = _run(tmp_path, "l1", "--repeats", "1", "--ping-count", "3", "--idle-seconds", "0.2")
    [row] = payload["measurements"]
    assert row["cleanup_complete"] is True and row["remaining_lab_resources"] == []
    assert row["ping_received"] == 3 and row["services_reachable"] == 1


@pytest.mark.privileged
def test_target_benchmark_fifty_l0_two_l1(tmp_path) -> None:
    available, reason = namespace_environment_available()
    if not available:
        pytest.skip(f"NOT RUN — environment unavailable: {reason}")
    payload = _run(tmp_path, "target", "--repeats", "1", "--idle-seconds", "0.2")
    [row] = payload["measurements"]
    assert row["l0_count"] == 50 and row["l1_count"] == 2
    assert row["l1_services_reachable"] == 2
    assert row["l0_to_l1_loss_percent"] == 0.0 and row["l0_to_l0_loss_percent"] == 0.0
    assert row["cleanup_complete"] is True
