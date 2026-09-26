"""Fixtures for the Qt client tests: real widgets, real in-process backends, isolated settings.

CI runs this suite under ``xvfb-run`` on Linux (platform ``xcb``) and with
``QT_QPA_PLATFORM=offscreen`` on Windows. Locally, without a display, the offscreen platform is
selected so the suite still runs headless.
"""

import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="NOT RUN — environment unavailable: PySide6 not installed")

ROOT = Path(__file__).parents[2]
TOKEN = "q" * 32
HYBRID = ROOT / "examples/topologies/hybrid-small.yml"


def pytest_collection_modifyitems(items) -> None:
    for item in items:
        if "tests/gui" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.gui)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def l0_topology() -> str:
    """The small hybrid example with every node as L0: runs rootless on any OS."""
    source = HYBRID.read_text(encoding="utf-8").replace("class: l1", "class: l0")
    return source.replace(
        "    services:\n      - id: web\n        protocol: tcp\n        port: 8080\n"
        "        implementation: static_http\n",
        "",
    )


def ping_scenario(actions: int = 1, timeout: float = 10, cleanup: str = "never") -> str:
    sequence = "".join(
        f"  - {{id: ping-{index}, kind: icmp_probe, source: sensor-1, target: service-1}}\n"
        for index in range(actions)
    )
    return (
        "id: gui-ping\nrequired_topology: hybrid-small\ninitial_conditions: [topology_deployed]\n"
        f"permitted_actions: [icmp_probe]\nsequence:\n{sequence}timeout_seconds: {timeout}\n"
        "success_conditions:\n  - {action: ping-0, field: success, equals: true}\n"
        f"cleanup_policy: {cleanup}\n"
    )


# Routes added in v0.2.0; answering them with FastAPI's 404 emulates a v0.1.x backend.
V020_ROUTES = (
    ("GET", re.compile(r"^/v1/topologies(/[^/]+)?$")),
    ("POST", re.compile(r"^/v1/scenarios/validate$")),
    ("GET", re.compile(r"^/v1/experiments$")),
    ("GET", re.compile(r"^/v1/experiments/[^/]+/report/markdown$")),
    ("*", re.compile(r"^/v1/benchmarks(/.*)?$")),
)


def legacy(app):
    """Wrap an ASGI app so that the v0.2.0 routes do not exist."""

    async def wrapper(scope, receive, send):
        if scope["type"] == "http" and any(
            method in {"*", scope["method"]} and pattern.match(scope["path"])
            for method, pattern in V020_ROUTES
        ):
            body = b'{"detail":"Not Found"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await app(scope, receive, send)

    return wrapper


class LiveBackend:
    """A real FastAPI backend on a free loopback port, in a thread of this process."""

    def __init__(
        self,
        data_directory: Path,
        *,
        token: str | None = TOKEN,
        legacy_api: bool = False,
        **plane_options,
    ):
        import uvicorn

        from polmon.api.control import ControlPlane
        from polmon.backend import create_app

        self.plane = ControlPlane(data_directory, **plane_options)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.token = token
        application = create_app(self.plane, api_token=token)
        if legacy_api:
            application = legacy(application)
        self.server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=self.port,
                log_level="error",
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> "LiveBackend":
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert self.server.started, "backend did not start"
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


@pytest.fixture
def backend_factory(tmp_path):
    started: list[LiveBackend] = []

    def make(**options) -> LiveBackend:
        backend = LiveBackend(tmp_path / f"backend-{len(started)}", **options).start()
        started.append(backend)
        return backend

    yield make
    for backend in started:
        backend.stop()


@pytest.fixture
def live_backend(backend_factory) -> LiveBackend:
    return backend_factory()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox

    from polmon.client import theme
    from polmon.client.mainwindow import MainWindow

    # Confirmation dialogs would block a headless run: answer "Yes" and record the question.
    asked: list[str] = []

    def yes(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    app = QApplication.instance()
    theme.apply(app, "light")
    settings = QSettings(str(tmp_path / "client.ini"), QSettings.Format.IniFormat)
    main = MainWindow(settings)
    main.asked = asked
    qtbot.addWidget(main)
    main.resize(1280, 800)
    main.show()
    yield main
    main.shutdown(wait_ms=5000)


def connect(qtbot, window, backend: LiveBackend | None = None, *, url=None, token=None) -> None:
    window.bar.url.setText(url or backend.url)
    window.bar.token.setText(token if token is not None else (backend.token or ""))
    window.connect_backend()


def wait_connected(qtbot, window, timeout: int = 10_000) -> None:
    from polmon.client.state import ConnectionState

    qtbot.waitUntil(lambda: window.session.state is ConnectionState.CONNECTED, timeout=timeout)
    qtbot.waitUntil(lambda: window.session.resources is not None, timeout=timeout)


def log_text(window) -> str:
    return window.log_view.toPlainText()
