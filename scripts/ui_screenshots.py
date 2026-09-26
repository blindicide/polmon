#!/usr/bin/env python3
"""Regenerate docs/ui/*.png by rendering the real Qt client against a real backend.

Nothing is mocked: a ``polmon-backend`` process is started with a fresh token, the unmodified
``MainWindow`` connects to it, loads ``examples/topologies/l0-office.yml`` (rootless L0),
deploys it, runs ``examples/scenarios/office-sweep.yml``, and each page is grabbed from the live
widgets (``QWidget.grab``). The only change from interactive use is a faster health-poll
interval so the sparklines fill within the run. Writes ``SCREENSHOTS.md`` with the inventory.

Usage: python scripts/ui_screenshots.py [--output docs/ui] [--no-benchmark]
Runs on the offscreen platform unless QT_QPA_PLATFORM is set or a display is used.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_support import ROOT, BackendProcess, auto_confirm, settle, wait_until  # noqa: E402

TOPOLOGY = ROOT / "examples/topologies/l0-office.yml"
SCENARIO = ROOT / "examples/scenarios/office-sweep.yml"
CAPTIONS: dict[str, str] = {}


def oversized_topology(count: int = 300) -> str:
    """A syntactically valid topology larger than the default 250-endpoint admission limit."""
    lines = ["id: too-big", "networks:", "  - id: lab", "    ipv4_subnet: 10.30.0.0/22", "nodes:"]
    for index in range(1, count + 1):
        lines += [
            f"  - id: node-{index}",
            "    class: l0",
            "    interfaces:",
            "      - id: eth0",
            "        network: lab",
            f'        mac: "02:30:00:00:{index // 256:02x}:{index % 256:02x}"',
            f"        ipv4: 10.30.{index // 250}.{index % 250 + 2}",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=ROOT / "docs/ui")
    parser.add_argument("--no-benchmark", action="store_true", help="skip the benchmark page run")
    args = parser.parse_args()
    if not os.environ.get("QT_QPA_PLATFORM") and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    args.output.mkdir(parents=True, exist_ok=True)

    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QSettings, qVersion
    from PySide6.QtWidgets import QApplication

    from polmon.client.app import create_application
    from polmon.client.mainwindow import MainWindow
    from polmon.client.state import ConnectionState
    from polmon.version import __version__

    notes: list[str] = []
    workdir = Path(tempfile.mkdtemp(prefix="polmon-ui-"))
    backend = BackendProcess(workdir / "backend").start()
    app = create_application(["polmon-screenshots"], theme_preference="light")
    auto_confirm(notes.append)
    settings = QSettings(str(workdir / "client.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    window.resize(1440, 900)
    window.show()
    window.set_theme("light")
    shots: list[tuple[str, str]] = []

    def grab(name: str, caption: str) -> None:
        settle(app, 0.3)
        path = args.output / f"{name}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"could not write {path}")
        shots.append((name, caption))
        print(f"wrote {path}")

    try:
        window.bar.url.setText(backend.url)
        window.bar.token.setText(backend.token)
        window.bar.connect_button.click()
        wait_until(app, lambda: window.session.state is ConnectionState.CONNECTED, "connect")
        window.poll_timer.setInterval(400)  # fill the sparklines faster than the 3 s default

        topologies = window.pages["topologies"]
        window.navigate("topologies", TOPOLOGY)
        wait_until(app, lambda: topologies.result is not None, "topology validation")
        topologies.tabs.setCurrentWidget(topologies.nodes)
        grab(
            "topologies",
            "Topology editor with backend validation and the node/interface "
            "inspector (MAC, IPv4, class)",
        )

        topologies.deploy_button.click()
        wait_until(app, lambda: window.session.deployed("l0-office"), "deployment", 60)
        wait_until(app, lambda: not window.context.busy, "deployment finished", 60)
        window.navigate("deployment")
        settle(app, 2.5)
        grab("deployment", "Deployment control with owned resources and live resource counters")

        scenarios = window.pages["scenarios"]
        window.navigate("scenarios", SCENARIO)
        wait_until(app, scenarios.ready, "scenario validation")
        scenarios.run_button.click()
        wait_until(app, lambda: scenarios.outcome.status == "succeeded", "experiment", 60)
        grab("scenarios", "Scenario inspection and a completed experiment with per-action status")
        experiment_id = str(scenarios.last_record["experiment_id"])

        telemetry = window.pages["telemetry"]
        scenarios.telemetry_button.click()
        wait_until(app, lambda: telemetry.model.rowCount() > 5, "telemetry")
        for row in range(telemetry.proxy.rowCount()):
            if telemetry.proxy.index(row, 2).data() == "network_observation":
                telemetry.table.selectRow(row)
                break
        grab(
            "telemetry",
            "Experiment-scoped telemetry stream with category/text filters, event "
            "payload and capture summary",
        )

        reports = window.pages["reports"]
        scenarios.report_button.click()
        wait_until(app, lambda: reports.report is not None, "report")
        grab("reports", "Report: overall status and expected-versus-actual conditions")
        reports.tabs.setCurrentWidget(reports.rendered)
        grab("report-markdown", "The human-readable Markdown report as generated by the backend")

        if not args.no_benchmark and sys.platform.startswith("linux"):
            benchmarks = window.pages["benchmarks"]
            window.navigate("benchmarks")
            benchmarks.counts.setText("5 10")
            benchmarks.idle.setValue(0.2)
            benchmarks.run_button.click()
            wait_until(
                app,
                lambda: benchmarks.job_badge.status in {"succeeded", "failed", "aborted", "error"},
                "benchmark",
                180,
            )
            wait_until(app, lambda: benchmarks.results.rowCount() > 0, "benchmark results")
            wait_until(app, lambda: benchmarks.measurements.rowCount() > 0, "benchmark detail")
            grab("benchmarks", "Bounded benchmark job with explicit limits and a retained result")
        else:
            notes.append("benchmark page not rendered (Linux-only measurement or --no-benchmark)")

        window.navigate("dashboard")
        settle(app, 4)
        grab(
            "dashboard",
            "Dashboard: backend identity, live counters with sparklines, " "admission limits",
        )

        window.navigate("topologies")
        topologies.editor.setPlainText(
            TOPOLOGY.read_text(encoding="utf-8").replace("10.20.0.0/24", "8.8.8.0/24", 1)
        )
        wait_until(app, lambda: topologies.problems.rowCount() > 0, "validation error")
        grab("validation-error", "Validation errors mapped to the offending YAML line")

        topologies.editor.setPlainText(oversized_topology())
        wait_until(app, lambda: topologies.result is not None, "oversized validation")
        topologies.deploy_button.click()
        deployment = window.pages["deployment"]
        wait_until(app, lambda: deployment.banner.isVisible(), "admission rejection")
        grab(
            "admission-rejected",
            "Admission control refusing a 300-endpoint deployment, "
            "naming the limit that was hit",
        )

        window.set_theme("dark")
        window.navigate("dashboard")
        settle(app, 1.5)
        grab("dashboard-dark", "Dark theme: dashboard")
        window.navigate("scenarios")
        grab("scenarios-dark", "Dark theme: scenarios")
        window.set_theme("light")

        deployment.reset_now()
        wait_until(app, lambda: not window.session.deployments, "reset", 60)
    finally:
        window.shutdown(wait_ms=3000)
        backend.stop()

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Desktop client screenshots",
        "",
        "Rendered from the running Qt widgets by `python scripts/ui_screenshots.py` (no mock-ups):",
        "a real `polmon-backend` process with an API token, the unmodified main window, the",
        "`l0-office` example topology and the `office-sweep` scenario. CI regenerates the same",
        "set as the `ui-screenshots` artifact.",
        "",
        f"- Generated: {stamp}",
        f"- polmon {__version__}, Qt {qVersion()}, PySide6 {pyside_version}",
        f"- Platform: `{QApplication.platformName()}` on {platform.system()} "
        f"{platform.release()}, window 1440×900",
        f"- Experiment: `{experiment_id}`",
        "",
    ]
    for name, caption in shots:
        lines += [f"## {name}", "", caption + ".", "", f"![{name}]({name}.png)", ""]
    if notes:
        lines += ["## Notes", ""] + [f"- {note}" for note in notes] + [""]
    (args.output / "SCREENSHOTS.md").write_text("\n".join(lines).rstrip() + "\n", "utf-8")
    print(f"wrote {args.output / 'SCREENSHOTS.md'} ({len(shots)} screenshots)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
