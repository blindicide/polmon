import io
import json

import pytest

from polmon.backends.namespace.backend import parse_ping_summary
from polmon.benchmarks import cli, l1, synthetic, target
from polmon.benchmarks.common import (
    BenchmarkLimitError,
    BenchmarkLimits,
    Progress,
    document,
    percentile,
    write_results,
)
from polmon.resources import ResourceLimitError


class TtyStream(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_progress_is_line_per_step_off_tty_and_carriage_return_on_tty() -> None:
    plain = io.StringIO()
    progress = Progress(4, label="bench", stream=plain)
    progress.update(0, "starting")
    progress.update(2, "half")
    lines = plain.getvalue().splitlines()
    assert lines[0].startswith("[bench]   0.0% step 0/4 elapsed")
    assert "eta ?" in lines[0]
    assert "50.0% step 2/4" in lines[1] and lines[1].endswith("half")
    assert "\r" not in plain.getvalue() and "\x1b" not in plain.getvalue()

    tty = TtyStream()
    progress = Progress(2, stream=tty)
    progress.update(1, "one")
    progress.update(2, "two")
    assert tty.getvalue().startswith("\r\x1b[2K")
    assert tty.getvalue().endswith("two\n")


def test_progress_rejects_empty_plans() -> None:
    with pytest.raises(ValueError):
        Progress(0)


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == 3.0
    assert percentile([1.0, 2.0], 0.95) == 2.0
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_limits_reject_oversized_topologies_before_creation() -> None:
    limits = BenchmarkLimits(max_endpoints=10)
    limits.admit(synthetic.build_topology(10))
    with pytest.raises(ResourceLimitError):
        limits.admit(synthetic.build_topology(11))
    with pytest.raises(ResourceLimitError):
        BenchmarkLimits(max_namespaces=1).admit(l1.build_topology(2))


def test_limits_stop_suite_on_memory_growth() -> None:
    limits = BenchmarkLimits(max_incremental_memory_mb=1)
    limits.check_memory({"incremental_memory_bytes": 1_048_576})
    with pytest.raises(BenchmarkLimitError) as raised:
        limits.check_memory({"peak_incremental_memory_bytes": 2 * 1_048_576})
    assert raised.value.details["limit_mb"] == 1


def test_topology_builders_bound_their_sizes() -> None:
    assert len(synthetic.build_topology(250).nodes) == 250
    with pytest.raises(ValueError):
        synthetic.build_topology(251)
    with pytest.raises(ValueError):
        l1.build_topology(1)
    demo = target.build_topology(50, 2)
    assert demo.estimate_resources().l0_endpoints == 50
    assert demo.estimate_resources().l1_namespaces == 2
    assert all(node.services for node in demo.nodes if node.id.startswith("l1-"))


def test_ping_summary_parser_handles_loss_and_rtt() -> None:
    parsed = parse_ping_summary(
        "5 packets transmitted, 4 received, 20% packet loss, time 804ms\n"
        "rtt min/avg/max/mdev = 0.035/0.049/0.071/0.013 ms\n"
    )
    assert parsed["loss_percent"] == 20.0 and parsed["rtt_avg_ms"] == 0.049
    empty = parse_ping_summary("3 packets transmitted, 0 received, 100% packet loss")
    assert empty["rtt_avg_ms"] is None and empty["loss_percent"] == 100.0
    with pytest.raises(ValueError):
        parse_ping_summary("ping: connect: Network is unreachable")


def test_results_keep_raw_json_and_flat_csv(tmp_path) -> None:
    from datetime import UTC, datetime

    payload = document(
        "l0",
        workload={"repeats": 1},
        limits=BenchmarkLimits(),
        limitations=["example"],
        measurements=[{"endpoint_count": 10, "nested": {"a": 1}}, {"endpoint_count": 25}],
        started_at=datetime.now(UTC),
    )
    json_path, csv_path = write_results(tmp_path / "run", payload)
    assert json.loads(json_path.read_text(encoding="utf-8"))["polmon_version"]
    rows = csv_path.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "endpoint_count,nested"
    assert rows[1] == '10,"{""a"": 1}"'
    empty = dict(payload, measurements=[])
    assert write_results(tmp_path / "empty", empty)[1] is None


def test_cli_requires_large_for_counts_above_fifty(tmp_path) -> None:
    with pytest.raises(SystemExit, match="--large"):
        cli.main(["l0", "--counts", "100", "--output-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="repeats"):
        cli.main(["l0", "--repeats", "0", "--output-dir", str(tmp_path)])


def test_cli_aborts_and_retains_partial_results_when_admission_fails(tmp_path, capsys) -> None:
    code = cli.main(
        ["l0", "--counts", "10", "25", "--max-endpoints", "20", "--output-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_ABORTED
    written = list(tmp_path.glob("l0-*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["status"] == "aborted"
    assert payload["error"]["code"] == "resource_limit"
    assert payload["measurements"] == []
    assert "aborted" in capsys.readouterr().err


def test_privileged_benchmarks_report_not_run_without_lab(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(l1, "namespace_environment_available", lambda: (False, "no sudo"))
    code = cli.main(["l1", "--json", "--output-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == cli.EXIT_NOT_RUN
    payload = json.loads(captured.out)  # stdout is pure JSON even when progress is printed
    assert payload["status"] == "not_run"
    assert payload["error"]["message"].startswith("NOT RUN — environment unavailable")
    assert "NOT RUN" in captured.err


def test_summarize_renders_only_recorded_values(tmp_path) -> None:
    from datetime import UTC, datetime

    rows = [
        {
            "endpoint_count": 10,
            "repeat": index,
            "creation_seconds": value,
            "cleanup_complete": True,
        }
        for index, value in enumerate((0.001, 0.003, 0.002), start=1)
    ]
    payload = document(
        "l0",
        workload={},
        limits=BenchmarkLimits(),
        limitations=[],
        measurements=rows,
        started_at=datetime.now(UTC),
    )
    source = tmp_path / "l0.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "summary.md"
    assert cli.main(["summarize", str(source), "--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    assert "| 10 | 3 | 2.00 (1.00–3.00) |" in text
    assert "n/a" in text  # columns without recorded values are never invented
    assert text.rstrip().endswith("yes |")


def test_l0_run_once_measures_and_cleans_up_in_process() -> None:
    row = synthetic.run_once(10, 1, 0.0)
    assert row["fidelity"] == "L0" and row["cleanup_complete"] is True
    assert row["traffic_attempts"] == 18 and row["packet_loss_percent"] == 0.0
    assert row["python_heap_deployed_bytes"] > 0
    assert row["latency_p95_ms"] >= row["latency_p50_ms"] > 0


def test_worker_prints_one_json_row_and_rejects_bad_input(capsys) -> None:
    from polmon.benchmarks import worker

    params = json.dumps({"endpoint_count": 3, "repeat": 1, "idle_seconds": 0})
    assert worker.main(["l0", params]) == 0
    row = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert row["endpoint_count"] == 3 and row["cleanup_complete"] is True
    assert worker.main(["l0"]) == 2
    assert worker.main(["l0", "[]"]) == 2
    with pytest.raises(ValueError, match="unknown benchmark kind"):
        worker.measure("l9", {})
