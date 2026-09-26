"""Drive the real Tk client against a live backend (needs a display; CI uses Xvfb)."""

import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

TOKEN = "g" * 32
TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/hybrid-small.yml"


def display_available() -> bool:
    return sys.platform == "win32" or bool(os.environ.get("DISPLAY"))


@pytest.fixture
def live_backend(tmp_path):
    import uvicorn

    from polmon.api.control import ControlPlane
    from polmon.backend import create_app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(ControlPlane(tmp_path), api_token=TOKEN),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def app(monkeypatch):
    if not display_available():
        pytest.skip("NOT RUN — environment unavailable: no display (run under xvfb-run)")
    import tkinter as tk

    from polmon.client import app as client_app

    errors: list[str] = []
    monkeypatch.setattr(client_app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setattr(client_app.messagebox, "showinfo", lambda title, text: errors.append(text))
    root = tk.Tk()
    instance = client_app.PolmonApp(root)
    instance.errors = errors
    yield instance
    instance.executor.shutdown(wait=True)
    root.destroy()


def settle(app, timeout: float = 15.0) -> None:
    """Pump the Tk event loop until the background operation has been reported."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.root.update()
        if app.future is not None and app.future.done() and app.status.get() in {"Ready", "Error"}:
            app.root.update()
            return
        time.sleep(0.01)
    raise AssertionError(f"GUI operation did not finish: status={app.status.get()!r}")


def test_window_shows_the_version_and_stays_responsive_while_offline(app) -> None:
    from polmon.version import __version__

    assert app.root.title() == f"polmon {__version__}"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app.server_url.set(f"http://127.0.0.1:{port}")
    app.connect()
    app.root.update()  # the UI thread returns immediately; the request runs on the worker
    settle(app)
    assert app.status.get() == "Error"
    assert "unable to reach backend" in app.errors[-1]


def test_token_gates_the_workflow_and_is_never_shown(app, live_backend) -> None:
    app.server_url.set(live_backend)
    app.topology_source = TOPOLOGY.read_text(encoding="utf-8").replace("class: l1", "class: l0")
    app.topology_source = app.topology_source.replace(
        "    services:\n      - id: web\n        protocol: tcp\n        port: 8080\n"
        "        implementation: static_http\n",
        "",
    )
    app.validate_topology()
    settle(app)
    assert app.status.get() == "Error" and "HTTP 401 unauthorized" in app.errors[-1]

    app.api_token.set(TOKEN)
    app.scenario_source = """id: gui-ping
required_topology: hybrid-small
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
  - {id: ping, kind: icmp_probe, source: sensor-1, target: service-1}
timeout_seconds: 5
success_conditions:
  - {action: ping, field: success, equals: true}
cleanup_policy: never
"""
    for action in (app.connect, app.validate_topology, app.deploy, app.run_experiment, app.reset):
        action()
        settle(app)
        assert app.status.get() == "Ready", app.errors
    shown = app.output.get("1.0", "end")
    assert '"state": "running"' in shown and '"deployments_destroyed": 1' in shown
    assert '"status": "succeeded"' in shown and '"network_observation"' in shown
    assert TOKEN not in shown
