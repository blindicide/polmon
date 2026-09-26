"""``polmon-demo``: the Phase I MVP demonstration, driven end to end over the HTTP API.

Steps: health → validate/load topology → admitted deployment → controlled experiment → telemetry
and capture → report → complete reset → independent cleanup verification. Every outcome is
checked; the run fails loudly instead of reporting a partial demonstration as a success.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from polmon.api.auth import TOKEN_ENVIRONMENT_VARIABLE, read_token_file
from polmon.client.api import ApiClient, ApiClientError
from polmon.core.errors import PolmonError
from polmon.core.progress import Progress
from polmon.topology import parse_topology
from polmon.version import __version__

REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_TOPOLOGY = REPOSITORY / "examples/topologies/mvp-demo.yml"
DEFAULT_SCENARIO = REPOSITORY / "examples/scenarios/mvp-recon.yml"
STEPS = 9


class DemoFailure(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _lab_names_present(names: list[str]) -> list[str]:
    """Names from the deployment that the local kernel still reports (local backends only)."""
    if not names or shutil.which("ip") is None:
        return []
    namespaces = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, text=True, check=False
    ).stdout
    links = subprocess.run(
        ["ip", "-o", "link", "show"], capture_output=True, text=True, check=False
    ).stdout
    link_names = {line.split(": ")[1].split("@")[0] for line in links.splitlines() if ": " in line}
    namespace_names = {line.split()[0] for line in namespaces.splitlines() if line.strip()}
    return sorted(name for name in names if name in link_names or name in namespace_names)


class LocalBackend:
    """A disposable backend process with its own data directory (``--start-backend``)."""

    def __init__(self, data_directory: Path) -> None:
        self.data_directory = data_directory
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log_path = data_directory / "backend.log"
        self.process: subprocess.Popen[bytes] | None = None
        # A fresh random token per run: the demonstration always exercises API authentication.
        self.token = secrets.token_urlsafe(32)

    def start(self) -> None:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("wb")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "polmon.backend", "--port", str(self.port)],
            cwd=self.data_directory,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, TOKEN_ENVIRONMENT_VARIABLE: self.token},
        )
        client = ApiClient(self.url, timeout=1.0, token=self.token)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise DemoFailure(f"backend exited early; see {self.log_path}")
            try:
                client.health()
                return
            except ApiClientError:
                time.sleep(0.1)
        raise DemoFailure("backend did not become healthy within 20 s")

    def stop(self) -> dict[str, object]:
        if self.process is None:
            return {"stopped": False}
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        log = self.log_path.read_text(encoding="utf-8", errors="replace")
        return {
            "stopped": True,
            "returncode": self.process.returncode,
            "shutdown_cleanup_logged": "shutdown_cleanup" in log,
            "shutdown_cleanup_failed": "shutdown_cleanup_failed" in log,
        }


def run_demo(
    client: ApiClient,
    topology_source: str,
    scenario_source: str,
    *,
    experiment_id: str,
    progress: Progress,
    local: bool,
) -> dict[str, object]:
    record: dict[str, object] = {"steps": []}
    steps: list[dict[str, object]] = record["steps"]  # type: ignore[assignment]
    started = time.perf_counter()

    def step(number: int, name: str, detail: str) -> None:
        steps.append({"step": name, "elapsed_seconds": round(time.perf_counter() - started, 3)})
        progress.update(number, detail)

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise DemoFailure(message)

    health = client.health()
    require(health.get("status") == "ok", f"backend unhealthy: {health}")
    record["backend_version"] = health.get("version")
    step(1, "health", f"backend polmon {health.get('version')}")

    validated = client.validate_topology(topology_source)
    loaded = client.load_topology(topology_source)
    topology_id = str(loaded["topology_id"])
    record["topology"] = {"id": topology_id, "estimate": validated.get("resources")}
    step(2, "topology", f"loaded {topology_id}")

    before = client.resources()
    deployment = client.deploy(topology_id)
    after = client.resources()
    resources = [str(item) for item in deployment.get("resources", [])]
    kinds = Counter(item.split(":", 1)[0] for item in resources)
    require(deployment.get("state") == "running", f"deployment not running: {deployment}")
    require(kinds.get("netns", 0) >= 2 and kinds.get("tap", 0) == 1, f"unexpected lab: {kinds}")
    require(kinds.get("synthetic", 0) == 50, f"expected 50 L0 endpoints: {kinds}")
    snapshot_before = before.get("snapshot", {})
    snapshot_after = after.get("snapshot", {})
    record["deployment"] = {
        "state": deployment.get("state"),
        "backend": deployment.get("backend"),
        "resource_counts": dict(sorted(kinds.items())),
        "backend_rss_before_bytes": snapshot_before.get("process_rss_bytes"),
        "backend_rss_after_bytes": snapshot_after.get("process_rss_bytes"),
        "available_memory_before_bytes": snapshot_before.get("available_memory_bytes"),
        "available_memory_after_bytes": snapshot_after.get("available_memory_bytes"),
        "limits": after.get("limits"),
    }
    step(3, "deploy", f"{kinds.get('synthetic', 0)} L0 + {kinds.get('netns', 0)} L1 running")

    experiment = client.run_experiment(experiment_id, topology_id, scenario_source)
    observations = experiment.get("observations", [])
    record["experiment"] = {
        "id": experiment_id,
        "status": experiment.get("status"),
        "observations": [
            {
                "action": item.get("action_id"),
                "success": item.get("success"),
                "detail": item.get("detail"),
                "path": (item.get("data") or {}).get("path"),
                "protocol": (item.get("data") or {}).get("protocol"),
            }
            for item in observations
            if isinstance(item, dict)
        ],
        "errors": experiment.get("errors"),
    }
    require(experiment.get("status") == "succeeded", f"experiment did not succeed: {experiment}")
    step(4, "experiment", f"{experiment_id} {experiment.get('status')}")

    telemetry = client.telemetry(experiment_id)
    categories = Counter(str(item.get("category")) for item in telemetry)
    capture = experiment.get("capture") or {}
    record["telemetry"] = {
        "event_count": len(telemetry),
        "categories": dict(sorted(categories.items())),
        "capture": {
            key: capture.get(key)
            for key in ("frame_count", "captured_bytes", "dropped_frames", "truncated_frames")
        },
    }
    require(len(telemetry) > 0, "no telemetry events recorded")
    require(int(capture.get("frame_count") or 0) > 0, "no frames captured")
    step(5, "telemetry", f"{len(telemetry)} events, {capture.get('frame_count')} frames")

    report = client.report(experiment_id)
    require(report.get("status") == "succeeded", f"report status: {report.get('status')}")
    require(report.get("experiment_id") == experiment_id, "report belongs to another experiment")
    record["report"] = {
        "status": report.get("status"),
        "polmon_version": report.get("polmon_version"),
        "document": report,
        "paths": experiment.get("reports"),
    }
    step(6, "report", "report generated")

    reset = client.reset_all()
    record["reset"] = reset
    require(int(reset.get("deployments_destroyed") or 0) == 1, f"reset: {reset}")
    step(7, "reset", f"{reset.get('deployments_destroyed')} deployment(s) destroyed")

    status = client.resources()
    names = [item.split(":", 1)[1] for item in resources if not item.startswith("synthetic:")]
    remaining = _lab_names_present(names) if local else None
    record["cleanup"] = {
        "active_deployments": status.get("active_deployments"),
        "checked_locally": local,
        "remaining_lab_resources": remaining,
    }
    require(status.get("active_deployments") == 0, "deployments remain after reset")
    require(not remaining, f"lab resources remain after reset: {remaining}")
    step(8, "verify", "no deployments or lab resources remain")
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polmon-demo", description="Run the Phase I MVP demonstration over the HTTP API."
    )
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--url", help="use an already running backend at this URL")
    target.add_argument(
        "--start-backend",
        action="store_true",
        help="start a disposable local backend (default when --url is not given)",
    )
    parser.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument(
        "--output-dir", type=Path, default=None, help="write the demonstration record here"
    )
    parser.add_argument("--json", action="store_true", help="print the record as JSON on stdout")
    parser.add_argument(
        "--token-file",
        type=Path,
        help=f"API token for --url (mode 600); {TOKEN_ENVIRONMENT_VARIABLE} is used otherwise",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started_at = datetime.now(UTC)
    experiment_id = args.experiment_id or f"mvp-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    topology_source = args.topology.read_text(encoding="utf-8")
    scenario_source = args.scenario.read_text(encoding="utf-8")
    progress = Progress(STEPS, label="demo")
    progress.update(0, "starting")
    workdir = Path(tempfile.mkdtemp(prefix="polmon-demo-"))
    backend = None if args.url else LocalBackend(workdir / "backend")
    record: dict[str, object] = {
        "demo": "phase-1-mvp",
        "polmon_version": __version__,
        "started_at": started_at.isoformat(),
        "topology_file": args.topology.name,
        "scenario_file": args.scenario.name,
        "backend_mode": "url" if args.url else "local-process",
    }
    status = 1
    token: str | None = None
    try:
        if backend is not None:
            backend.start()
            token = backend.token
        elif args.token_file is not None:
            token = read_token_file(args.token_file)
        else:
            token = os.environ.get(TOKEN_ENVIRONMENT_VARIABLE)
        client = ApiClient(args.url or backend.url, token=token)  # type: ignore[union-attr]
        record["api_authentication"] = "bearer-token" if token else "none"
        record.update(
            run_demo(
                client,
                topology_source,
                scenario_source,
                experiment_id=experiment_id,
                progress=progress,
                local=backend is not None,
            )
        )
        record["status"] = "passed"
        status = 0
    except (DemoFailure, ApiClientError, OSError, PolmonError) as error:
        record["status"] = "failed"
        record["error"] = f"{type(error).__name__}: {error}"
        if args.url is not None:
            # Remove only this demonstration's deployment from a shared backend. A local
            # backend is reset by its own SIGTERM shutdown below.
            with contextlib.suppress(ApiClientError):
                ApiClient(args.url, token=token).destroy(parse_topology(topology_source).id)
    finally:
        if backend is not None:
            record["backend_shutdown"] = backend.stop()
            report = record.get("report")
            paths = report.get("paths") if isinstance(report, dict) else None
            record["report_markdown"] = _read_markdown(backend.data_directory, paths)
        record["finished_at"] = datetime.now(UTC).isoformat()
        progress.update(STEPS, f"demo {record.get('status')}")
        shutil.rmtree(workdir, ignore_errors=True)
    if args.output_dir is not None:
        _write_record(args.output_dir, experiment_id, record)
    if args.json:
        print(json.dumps(record, sort_keys=True))
    else:
        print(f"demo: {record['status']}" + (f" ({record['error']})" if "error" in record else ""))
    return status


def _read_markdown(data_directory: Path, paths: object) -> str | None:
    if not isinstance(paths, dict) or not paths.get("markdown"):
        return None
    path = Path(str(paths["markdown"]))
    if not path.is_absolute():
        path = data_directory / path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _write_record(directory: Path, experiment_id: str, record: dict[str, object]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    markdown = record.pop("report_markdown", None)
    (directory / f"{experiment_id}.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if isinstance(markdown, str):
        (directory / f"{experiment_id}-report.md").write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
