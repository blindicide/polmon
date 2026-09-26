"""Operator workflows driven through the real widgets against real in-process backends."""

import subprocess
import sys
import time

import pytest
from conftest import connect, l0_topology, log_text, ping_scenario, wait_connected

from polmon.api import control as control_module
from polmon.client.state import ConnectionState
from polmon.resources import ResourceLimits


def write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def open_and_validate_topology(qtbot, window, path) -> None:
    window.navigate("topologies", path)
    page = window.pages["topologies"]
    qtbot.waitUntil(lambda: page.result is not None, timeout=10_000)


def deploy_from_editor(qtbot, window) -> None:
    window.pages["topologies"].deploy()
    qtbot.waitUntil(lambda: window.session.deployed("hybrid-small"), timeout=20_000)
    qtbot.waitUntil(lambda: not window.context.busy, timeout=20_000)


def open_scenario(qtbot, window, path) -> None:
    window.navigate("scenarios", path)
    page = window.pages["scenarios"]
    qtbot.waitUntil(page.ready, timeout=10_000)


def test_full_operator_workflow(window, qtbot, live_backend, tmp_path) -> None:
    topology = write(tmp_path, "l0-small.yml", l0_topology())
    scenario = write(tmp_path, "ping.yml", ping_scenario(actions=3))
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)

    open_and_validate_topology(qtbot, window, topology)
    page = window.pages["topologies"]
    assert page.badge.status == "valid"
    nodes = {page.nodes.topLevelItem(i).text(0) for i in range(page.nodes.topLevelItemCount())}
    assert {"sensor-1", "service-1"} <= nodes
    first = page.nodes.topLevelItem(0)
    assert first.text(1) == "L0" and first.child(0).text(3).count(":") == 5  # MAC shown
    assert page.networks.rowCount() >= 1
    summary = {page.summary.item(r, 0).text(): page.summary.item(r, 2).text()
               for r in range(page.summary.rowCount())}
    assert summary["Endpoints"].startswith("fits")

    deploy_from_editor(qtbot, window)
    deployment = window.pages["deployment"]
    qtbot.waitUntil(lambda: deployment.table.rowCount() == 1, timeout=10_000)
    assert deployment.table.item(0, 1).text() == "running"
    assert deployment.owned.count() >= 2
    tiles = deployment.tiles
    qtbot.waitUntil(lambda: tiles.endpoints.value.text() == "2", timeout=10_000)

    open_scenario(qtbot, window, scenario)
    scenarios = window.pages["scenarios"]
    assert scenarios.summary.item(2, 1).text() == "compatible and deployed"
    assert scenarios.sequence.rowCount() == 3
    scenarios.run()
    assert window.context.busy and window.progress.isVisible()
    qtbot.waitUntil(lambda: scenarios.outcome.status == "succeeded", timeout=30_000)
    assert [scenarios.sequence.item(r, 5).text() for r in range(3)] == ["ok", "ok", "ok"]
    assert scenarios.conditions.item(0, 4).text() == "met"
    assert "succeeded" in window.statusBar().currentMessage()  # finish is announced
    scenarios.validate(quiet=True)  # background re-validation must not wipe the run results
    qtbot.wait(500)
    assert [scenarios.sequence.item(r, 5).text() for r in range(3)] == ["ok", "ok", "ok"]
    assert scenarios.conditions.item(0, 4).text() == "met"
    experiment_id = scenarios.last_record["experiment_id"]

    telemetry = window.pages["telemetry"]
    assert telemetry.empty.isVisibleTo(window) or telemetry.experiment_id is None
    scenarios.telemetry_button.click()
    qtbot.waitUntil(lambda: telemetry.model.rowCount() >= 5, timeout=10_000)
    assert not telemetry.empty.isVisibleTo(window)
    categories = {event["category"] for event in telemetry.model.events}
    assert {"scenario", "network_observation", "resource"} <= categories
    telemetry.category_boxes["resource"].setChecked(False)
    assert all(
        telemetry.proxy.index(r, 2).data() != "resource" for r in range(telemetry.proxy.rowCount())
    )
    telemetry.search.setText("ping-1")
    assert telemetry.proxy.rowCount() == 1
    capture = {telemetry.capture.item(r, 0).text(): telemetry.capture.item(r, 1).text()
               for r in range(telemetry.capture.rowCount())}
    assert int(capture["Frames captured"]) >= 1

    scenarios.report_button.click()
    reports = window.pages["reports"]
    qtbot.waitUntil(lambda: reports.report is not None, timeout=10_000)
    assert reports.status.status == "succeeded"
    assert reports.comparison.item(0, 5).text() == "met"
    assert reports.observations.rowCount() == 3
    assert experiment_id in reports.markdown
    assert reports.rendered.toPlainText().strip()

    window.pages["deployment"].reset()
    qtbot.waitUntil(lambda: not window.session.deployments, timeout=20_000)
    assert window.asked and "Tear down all 1 deployment" in window.asked[-1]
    assert "Traceback" not in log_text(window)


def test_admission_rejection_names_the_limit(window, qtbot, backend_factory, tmp_path) -> None:
    backend = backend_factory(limits=ResourceLimits(max_endpoint_count=1))
    connect(qtbot, window, backend)
    wait_connected(qtbot, window)
    open_and_validate_topology(qtbot, window, write(tmp_path, "t.yml", l0_topology()))
    summary = window.pages["topologies"].summary
    assert summary.item(2, 2).text().startswith("exceeds")
    window.pages["topologies"].deploy()
    banner = window.pages["deployment"].banner
    qtbot.waitUntil(lambda: banner.isVisible(), timeout=10_000)
    assert banner.problem.title == "Refused by admission control"
    assert "Endpoints: projected 2, limit 1" in banner.problem.items
    assert not window.session.deployments


def test_validation_errors_point_at_the_line(window, qtbot, live_backend, tmp_path) -> None:
    broken = l0_topology().replace("ipv4_subnet: 10.77.0.0/24", "ipv4_subnet: 8.8.8.0/24")
    assert broken != l0_topology()
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    window.navigate("topologies", write(tmp_path, "broken.yml", broken))
    page = window.pages["topologies"]
    qtbot.waitUntil(lambda: page.problems.rowCount() > 0, timeout=10_000)
    assert page.badge.status == "invalid"
    location = page.problems.item(0, 1).text()
    line = int(page.problems.item(0, 0).text())
    assert location.startswith("networks.0.ipv4_subnet")
    assert "8.8.8.0/24" in broken.splitlines()[line - 1]
    assert "laboratory ranges" in page.problems.item(0, 2).text()
    assert page.editor._error_line == line
    assert page.tabs.currentWidget() is page.problems
    assert not window.session.backend_topologies  # nothing was loaded


def slow_executor(monkeypatch, seconds: float) -> None:
    original = control_module.SyntheticScenarioExecutor.execute

    def slow(self, action, topology, timeout_seconds):
        time.sleep(seconds)
        return original(self, action, topology, timeout_seconds)

    monkeypatch.setattr(control_module.SyntheticScenarioExecutor, "execute", slow)


def test_running_experiment_can_be_cancelled(
    window, qtbot, live_backend, tmp_path, monkeypatch
) -> None:
    slow_executor(monkeypatch, 0.3)
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    open_and_validate_topology(qtbot, window, write(tmp_path, "t.yml", l0_topology()))
    deploy_from_editor(qtbot, window)
    open_scenario(qtbot, window, write(tmp_path, "s.yml", ping_scenario(actions=30, timeout=60)))
    scenarios = window.pages["scenarios"]
    scenarios.run()
    qtbot.waitUntil(lambda: window.progress.update_ is not None, timeout=10_000)
    update = window.progress.update_
    assert update.total == 30 and "elapsed" in window.progress.detail.text()
    assert window.context.cancel_operation()  # Esc / Cancel: graceful backend cancellation
    qtbot.waitUntil(lambda: scenarios.outcome.status == "cancelled", timeout=20_000)
    done = sum(scenarios.sequence.item(r, 5).text() == "ok" for r in range(30))
    assert 0 < done < 30
    assert not window.context.busy


def test_backend_dying_mid_experiment_is_reported(
    window, qtbot, backend_factory, tmp_path, monkeypatch
) -> None:
    slow_executor(monkeypatch, 0.3)
    monkeypatch.setattr("polmon.client.pages.scenarios.MAX_POLL_FAILURES", 4)
    backend = backend_factory()
    connect(qtbot, window, backend)
    wait_connected(qtbot, window)
    open_and_validate_topology(qtbot, window, write(tmp_path, "t.yml", l0_topology()))
    deploy_from_editor(qtbot, window)
    open_scenario(qtbot, window, write(tmp_path, "s.yml", ping_scenario(actions=40, timeout=60)))
    scenarios = window.pages["scenarios"]
    scenarios.run()
    qtbot.waitUntil(lambda: window.progress.update_ is not None, timeout=10_000)
    backend.stop()
    qtbot.waitUntil(lambda: scenarios.outcome.status == "unknown", timeout=30_000)
    assert scenarios.banner.problem.title == "Backend lost"
    assert "outcome is unknown" in scenarios.banner.problem.detail
    qtbot.waitUntil(lambda: window.session.state is ConnectionState.LOST, timeout=15_000)
    assert not window.context.busy
    assert "Traceback" not in log_text(window)


def fake_benchmark(command, stdout):
    script = (
        "import sys, time\n"
        "for step in (1, 2):\n"
        "    print(f'[benchmark l0]  50.0% step {step}/4 elapsed 0.1s eta 0.2s endpoints=10',"
        " file=sys.stderr, flush=True)\n"
        "    time.sleep(0.3)\n"
        "time.sleep(30)\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=stdout,
        stderr=subprocess.PIPE,
        start_new_session=sys.platform != "win32",
    )


def test_benchmark_job_progress_and_cancel(window, qtbot, live_backend) -> None:
    live_backend.plane.benchmarks._launcher = fake_benchmark
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    window.navigate("benchmarks")
    page = window.pages["benchmarks"]
    request = page.request()
    assert request["limits"]["memory_reserve_mb"] >= 256 and request["repeats"] == 1
    page.run()
    qtbot.waitUntil(
        lambda: window.progress.update_ is not None and window.progress.update_.completed == 2,
        timeout=10_000,
    )
    assert window.progress.update_.total == 4
    assert page.cancel_button.isEnabled()
    page.cancel_button.click()
    qtbot.waitUntil(lambda: page.job_badge.status == "cancelled", timeout=30_000)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="benchmarks measure via procfs")
def test_real_benchmark_result_is_listed_and_inspectable(window, qtbot, live_backend) -> None:
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    window.navigate("benchmarks")
    page = window.pages["benchmarks"]
    page.counts.setText("3")
    page.idle.setValue(0)
    page.run()
    qtbot.waitUntil(lambda: page.job_badge.status == "succeeded", timeout=90_000)
    qtbot.waitUntil(lambda: page.results.rowCount() == 1, timeout=10_000)
    page.results.selectRow(0)
    qtbot.waitUntil(lambda: page.measurements.rowCount() == 1, timeout=10_000)
    assert "l0" in page.summary.toPlainText().lower()


def test_documents_save_with_ctrl_s_and_telemetry_exports_csv(
    window, qtbot, live_backend, tmp_path
) -> None:
    import csv

    topology = write(tmp_path, "office.yml", l0_topology())
    scenario = write(tmp_path, "ping.yml", ping_scenario(actions=2))
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    open_and_validate_topology(qtbot, window, topology)
    page = window.pages["topologies"]
    page.editor.appendPlainText("# edited in the client")
    assert page.document_label.text().endswith("•")  # unsaved marker
    window.save_document()  # Ctrl+S
    assert topology.read_text(encoding="utf-8").rstrip().endswith("# edited in the client")
    assert not page.document_label.text().endswith("•")

    deploy_from_editor(qtbot, window)
    open_scenario(qtbot, window, scenario)
    scenarios = window.pages["scenarios"]
    scenarios.editor.appendPlainText("# note")
    window.save_document()
    assert scenario.read_text(encoding="utf-8").rstrip().endswith("# note")
    open_scenario(qtbot, window, scenario)
    scenarios.run()
    qtbot.waitUntil(lambda: scenarios.outcome.status == "succeeded", timeout=30_000)

    scenarios.telemetry_button.click()
    telemetry = window.pages["telemetry"]
    qtbot.waitUntil(lambda: telemetry.model.rowCount() >= 4, timeout=10_000)
    for name, box in telemetry.category_boxes.items():
        box.setChecked(name == "network_observation")
    capture = tmp_path / "run.pcap"
    qtbot.waitUntil(telemetry.capture_button.isEnabled, timeout=10_000)
    telemetry.save_capture(capture)
    qtbot.waitUntil(lambda: capture.exists() and capture.stat().st_size > 24, timeout=10_000)
    assert capture.read_bytes()[:4] in {b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"}
    exported = tmp_path / "events.csv"
    assert telemetry.write_csv(exported) == 2
    rows = list(csv.DictReader(exported.open(encoding="utf-8")))
    assert [row["event"] for row in rows] == ["ping-0", "ping-1"]
    assert '"success": true' in rows[0]["payload"]


def test_last_page_is_restored(window, qtbot, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from polmon.client.mainwindow import MainWindow

    window.navigate("reports")
    window.settings.sync()
    settings = QSettings(window.settings.fileName(), QSettings.Format.IniFormat)
    second = MainWindow(settings)
    qtbot.addWidget(second)
    try:
        assert second.current_page.key == "reports"
    finally:
        second.shutdown(wait_ms=2000)


def test_older_backend_is_usable_with_a_clear_warning(
    window, qtbot, backend_factory, tmp_path
) -> None:
    """A v0.1.x backend lacks the v0.2.0 routes: connect, deploy, destroy and warn, not fail."""
    backend = backend_factory(legacy_api=True)
    probe = backend.url
    connect(qtbot, window, backend)
    wait_connected(qtbot, window)
    banner = window.pages["dashboard"].banner
    qtbot.waitUntil(lambda: banner.isVisible(), timeout=10_000)
    assert banner.problem.title == "Older backend"
    assert "topology listing" in banner.problem.detail
    open_and_validate_topology(qtbot, window, write(tmp_path, "t.yml", l0_topology()))
    deploy_from_editor(qtbot, window)  # tracked through the topology the client loaded
    deployment = window.pages["deployment"]
    qtbot.waitUntil(lambda: deployment.table.rowCount() == 1, timeout=10_000)
    deployment.destroy()
    qtbot.waitUntil(lambda: not window.session.deployments, timeout=20_000)
    assert window.session.state.value == "connected" and probe
    assert "Traceback" not in log_text(window)
