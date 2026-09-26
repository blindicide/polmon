import json
import logging

from polmon.core.diagnostics import collect_diagnostics, main, resource_snapshot
from polmon.core.logging import JsonFormatter


def test_diagnostics_are_allow_listed_and_secret_free() -> None:
    result = collect_diagnostics()
    assert set(result) == {
        "polmon_version",
        "python_version",
        "python_supported",
        "platform",
        "architecture",
        "cpu_count",
        "capabilities",
        "resources",
    }
    serialized = json.dumps(result).lower()
    assert "password" not in serialized
    assert "token" not in serialized
    assert result["python_supported"] is True


def test_resource_snapshot_has_nonzero_process_metrics() -> None:
    snapshot = resource_snapshot(active_endpoints=3, active_namespaces=1)
    assert snapshot.process_rss_bytes > 0
    assert snapshot.process_cpu_seconds >= 0
    assert snapshot.process_cpu_percent is None or snapshot.process_cpu_percent >= 0
    assert snapshot.active_endpoints == 3
    assert snapshot.active_namespaces == 1


def test_diagnostics_json_cli(capsys) -> None:
    assert main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["polmon_version"] == "0.0.2"


def test_json_log_formatter_is_structured() -> None:
    record = logging.LogRecord(
        "polmon.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    record.event = "test"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["event"] == "test"
    assert payload["version"] == "0.0.2"
