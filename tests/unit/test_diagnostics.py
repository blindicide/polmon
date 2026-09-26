import json
import logging

from polmon.core.diagnostics import collect_diagnostics, main, resource_snapshot
from polmon.core.logging import JsonFormatter
from polmon.version import __version__


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
    assert json.loads(capsys.readouterr().out)["polmon_version"] == __version__


def test_json_log_formatter_is_structured() -> None:
    record = logging.LogRecord(
        "polmon.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    record.event = "test"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["event"] == "test"
    assert payload["version"] == __version__


def test_json_log_lines_carry_version_event_and_utf8(capsys) -> None:
    import json
    import logging

    from polmon.core.logging import configure_logging
    from polmon.version import __version__

    configure_logging("info")
    logging.getLogger("polmon.test").info("NOT RUN — ünïcode", extra={"event": "probe"})
    line = capsys.readouterr().err.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["version"] == __version__ and record["event"] == "probe"
    assert record["message"] == "NOT RUN — ünïcode"  # UTF-8, not \\u escapes or mojibake
    assert "—" in line
    logging.getLogger().handlers.clear()


def test_lab_readiness_is_read_only_and_reports_each_check() -> None:
    import subprocess

    from polmon.core.diagnostics import lab_readiness

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "sudo: a password is required")

    result = lab_readiness(run=fake_run)
    assert calls in ([], [["sudo", "-n", "ip", "netns", "list"]])  # the only privileged probe
    assert result["ready"] is False
    assert set(result["checks"]) >= {"tool_ip", "tun_device", "passwordless_sudo_ip"}
    assert result["checks"]["passwordless_sudo_ip"]["ok"] is False


def test_lab_flag_sets_exit_status_and_keeps_json_clean(capsys, monkeypatch) -> None:
    from polmon.core import diagnostics

    monkeypatch.setattr(diagnostics, "lab_readiness", lambda: {"ready": False, "checks": {}})
    assert main(["--json", "--lab"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["lab"] == {"ready": False, "checks": {}}
    monkeypatch.setattr(diagnostics, "lab_readiness", lambda: {"ready": True, "checks": {}})
    assert main(["--json", "--lab"]) == 0
