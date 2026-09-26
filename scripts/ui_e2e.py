#!/usr/bin/env python3
"""Live end-to-end demonstration: the Qt client drives a real local backend.

connect → validate topology → deploy → validate scenario → run experiment → telemetry →
report → reset, by clicking the same buttons an operator clicks (file dialogs are replaced by
opening the example paths directly; confirmation dialogs are answered Yes and recorded). Every
step is checked against the backend's own API afterwards, and the run fails loudly on any
mismatch. Writes ``ui-e2e-<stamp>.log`` (step log + the client's activity log),
``ui-e2e-<stamp>.json`` (machine-readable record), ``ui-e2e-<stamp>-report.md`` (the report as
shown in the client) and a screenshot of the report page.

Default workload: ``examples/topologies/l0-office.yml`` + ``examples/scenarios/office-sweep.yml``
(rootless). ``--hybrid`` uses the L0 + L1 MVP demonstration (``mvp-demo.yml`` +
``mvp-recon.yml``) and needs the authorised privileged laboratory (``polmon-diagnostics --lab``).

Usage: xvfb-run -a python scripts/ui_e2e.py [--output-dir docs/ui/e2e] [--hybrid]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_support import ROOT, BackendProcess, auto_confirm, settle, wait_until  # noqa: E402

WORKLOADS = {
    "l0": (
        ROOT / "examples/topologies/l0-office.yml",
        ROOT / "examples/scenarios/office-sweep.yml",
    ),
    "hybrid": (
        ROOT / "examples/topologies/mvp-demo.yml",
        ROOT / "examples/scenarios/mvp-recon.yml",
    ),
}


class Failure(RuntimeError):
    pass


def lab_leftovers(names: list[str]) -> list[str]:
    """Deployment-owned kernel objects still present (hybrid runs on this host only)."""
    if not names or shutil.which("ip") is None:
        return []
    namespaces = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, text=True, check=False
    ).stdout
    links = subprocess.run(
        ["ip", "-o", "link", "show"], capture_output=True, text=True, check=False
    ).stdout
    present = {line.split()[0] for line in namespaces.splitlines() if line.strip()}
    present |= {line.split(": ")[1].split("@")[0] for line in links.splitlines() if ": " in line}
    return sorted(name for name in names if name in present)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/ui/e2e")
    parser.add_argument("--hybrid", action="store_true", help="L0+L1 workload (privileged lab)")
    args = parser.parse_args()
    if not os.environ.get("QT_QPA_PLATFORM") and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QSettings, qVersion
    from PySide6.QtWidgets import QApplication

    from polmon.client.api import ApiClient
    from polmon.client.app import create_application
    from polmon.client.mainwindow import MainWindow
    from polmon.client.state import ConnectionState
    from polmon.version import __version__

    kind = "hybrid" if args.hybrid else "l0"
    topology_path, scenario_path = WORKLOADS[kind]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.output_dir / f"ui-e2e-{kind}-{stamp}"
    lines: list[str] = []
    steps: list[dict[str, object]] = []
    began = time.monotonic()

    def log(message: str) -> None:
        line = f"[{time.monotonic() - began:7.2f}s] {message}"
        lines.append(line)
        print(line, flush=True)

    def step(name: str, detail: dict[str, object]) -> None:
        steps.append({"step": name, "at_seconds": round(time.monotonic() - began, 3), **detail})
        log(f"STEP {name}: {json.dumps(detail, sort_keys=True, default=str)}")

    workdir = Path(tempfile.mkdtemp(prefix="polmon-ui-e2e-"))
    backend = BackendProcess(workdir / "backend").start()
    log(f"backend process pid {backend.process.pid} at {backend.url} (fresh API token)")
    app = create_application(["polmon-ui-e2e"], theme_preference="light")
    auto_confirm(log)
    window = MainWindow(QSettings(str(workdir / "client.ini"), QSettings.Format.IniFormat))
    window.resize(1440, 900)
    window.show()
    api = ApiClient(backend.url, token=backend.token)  # independent verification only
    record: dict[str, object] = {
        "polmon_version": __version__,
        "qt": qVersion(),
        "pyside6": pyside_version,
        "platform": QApplication.platformName(),
        "os": f"{platform.system()} {platform.release()}",
        "workload": kind,
        "topology": str(topology_path.relative_to(ROOT)),
        "scenario": str(scenario_path.relative_to(ROOT)),
        "command": "python scripts/ui_e2e.py" + (" --hybrid" if args.hybrid else ""),
        "started_at": datetime.now(UTC).isoformat(),
        "steps": steps,
    }
    status = "failed"
    try:
        window.bar.url.setText(backend.url)
        window.bar.token.setText(backend.token)
        window.bar.connect_button.click()
        wait_until(app, lambda: window.session.state is ConnectionState.CONNECTED, "connect")
        step(
            "connect",
            {
                "state": window.session.state.value,
                "backend_version": window.session.backend_version,
                "platform": QApplication.platformName(),
            },
        )

        topologies = window.pages["topologies"]
        window.navigation.setCurrentRow(1)
        topologies.open_path(topology_path)
        topologies.validate_button.click()
        wait_until(
            app,
            lambda: topologies.result is not None and topologies.badge.status == "valid",
            "topology validation",
        )
        estimate = topologies.result["resources"]
        step(
            "validate_topology",
            {
                "topology_id": topologies.result["topology_id"],
                "nodes_in_inspector": topologies.nodes.topLevelItemCount(),
                "resources": estimate,
            },
        )

        topologies.deploy_button.click()
        topology_id = str(topologies.result["topology_id"])
        wait_until(app, lambda: window.session.deployed(topology_id), "deployment", 120)
        wait_until(app, lambda: not window.context.busy, "deploy operation", 120)
        deployed = api.deployment(topology_id)
        if deployed.get("state") != "running":
            raise Failure(f"backend reports deployment state {deployed.get('state')}")
        owned = [str(item) for item in deployed.get("resources") or []]
        step(
            "deploy",
            {
                "state": deployed["state"],
                "backend": deployed["backend"],
                "owned_resources": len(owned),
                "deployment_seconds": deployed.get("deployment_seconds"),
            },
        )

        scenarios = window.pages["scenarios"]
        window.navigation.setCurrentRow(3)
        scenarios.open_path(scenario_path)
        scenarios.validate_button.click()
        wait_until(app, scenarios.ready, "scenario validation and compatibility")
        step(
            "validate_scenario",
            {
                "scenario_id": scenarios.result["scenario_id"],
                "topology_check": scenarios.result["topology_check"],
            },
        )

        scenarios.run_button.click()
        wait_until(
            app,
            lambda: scenarios.outcome.status not in {"running", "cancelling"},
            "experiment",
            180,
        )
        experiment_id = str(scenarios.last_record["experiment_id"])
        backend_view = api.experiment(experiment_id)
        shown = scenarios.outcome.status
        if backend_view.get("status") != shown:
            raise Failure(f"client shows {shown}, backend reports {backend_view.get('status')}")
        observations = [
            {key: item[key] for key in ("action_id", "success", "detail")}
            for item in backend_view.get("observations") or []
        ]
        step(
            "experiment",
            {"experiment_id": experiment_id, "status": shown, "observations": observations},
        )
        if shown != "succeeded":
            raise Failure(f"experiment {experiment_id} finished {shown}")

        telemetry = window.pages["telemetry"]
        scenarios.telemetry_button.click()
        wait_until(
            app, lambda: telemetry.model.rowCount() > 0 and telemetry.status == shown, "telemetry"
        )
        backend_events = api.telemetry(experiment_id)
        if telemetry.model.rowCount() != len(backend_events):
            raise Failure(
                f"client shows {telemetry.model.rowCount()} events, backend has "
                f"{len(backend_events)}"
            )
        categories: dict[str, int] = {}
        for event in telemetry.model.events:
            categories[str(event["category"])] = categories.get(str(event["category"]), 0) + 1
        capture = {
            telemetry.capture.item(r, 0).text(): telemetry.capture.item(r, 1).text()
            for r in range(telemetry.capture.rowCount())
        }
        step(
            "telemetry",
            {"events": telemetry.model.rowCount(), "by_category": categories, "capture": capture},
        )

        reports = window.pages["reports"]
        scenarios.report_button.click()
        wait_until(
            app,
            lambda: reports.report is not None and reports.experiment_id == experiment_id,
            "report",
        )
        comparisons = [
            {"action": item["action"], "field": item["field"], "outcome": item["outcome"]}
            for item in reports.report["expected_vs_actual"]
        ]
        prefix.with_name(prefix.name + "-report.md").write_text(reports.markdown, "utf-8")
        settle(app, 0.3)
        window.grab().save(str(prefix.with_name(prefix.name + "-report.png")))
        step(
            "report",
            {
                "status": reports.status.status,
                "expected_vs_actual": comparisons,
                "markdown_bytes": len(reports.markdown.encode("utf-8")),
            },
        )

        deployment = window.pages["deployment"]
        window.navigation.setCurrentRow(2)
        deployment.reset_button.click()
        wait_until(app, lambda: not window.session.deployments, "reset", 120)
        wait_until(app, lambda: not window.context.busy, "reset operation", 120)
        remaining = [item for item in api.topologies() if item.get("deployed")]
        leftovers = lab_leftovers([name for name in owned if not name.startswith("synthetic:")])
        if remaining or leftovers:
            raise Failure(f"after reset: deployed={remaining} leftovers={leftovers}")
        step(
            "reset",
            {
                "deployments_remaining": 0,
                "kernel_leftovers": leftovers,
                "definitions_kept": [item["topology_id"] for item in api.topologies()],
            },
        )
        status = "passed"
    except Exception as error:  # the record says exactly where the run stopped
        log(f"FAILED: {type(error).__name__}: {error}")
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        window.shutdown(wait_ms=3000)
        exit_code = backend.stop()
        record["backend_exit_code"] = exit_code
        record["finished_at"] = datetime.now(UTC).isoformat()
        record["status"] = status
        record["duration_seconds"] = round(time.monotonic() - began, 3)
        activity = window.log_view.toPlainText()
        if backend.token in activity or backend.token in "\n".join(lines):
            status = record["status"] = "failed"
            record["error"] = "API token appeared in the client log"
        log(f"{status.upper()}: writing {prefix}.json/.log (report: -report.md/-report.png)")
        prefix.with_name(prefix.name + ".json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8"
        )
        prefix.with_name(prefix.name + ".log").write_text(
            "\n".join([*lines, "", "--- client activity log ---", activity, ""]), "utf-8"
        )
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
