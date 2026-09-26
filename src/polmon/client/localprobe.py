"""Packaged-client proof of the Local backend flow through the real main window.

``polmon-client --local-backend-gui-probe OUT.json`` drives the same widgets an operator uses:
connect with the Local preset, try to deploy an L1 topology (refused in the UI and by the
backend), then leave through each exit path — disconnect, backend killed, window closed — and
record that the owned backend process ended every time. It runs on the offscreen platform so a
CI runner (or a user) sees no window; the optional screenshot is a real grab of that window.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from polmon.client.api import ApiClient, ApiClientError
from polmon.client.local_backend import _L1_TOPOLOGY, LOCAL_FIDELITY_MESSAGE, LOCAL_LABEL


class ProbeFailure(RuntimeError):
    """A lifecycle expectation did not hold."""


def _wait(app, predicate: Callable[[], bool], timeout: float, what: str) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise ProbeFailure(f"timed out after {timeout:g} s waiting for {what}")


def gui_lifecycle_probe(
    output: Path,
    executable: str | Path | None = None,
    *,
    screenshot: Path | None = None,
    stream=None,  # noqa: ANN001
) -> int:
    out = stream or sys.stdout
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QSettings

    from polmon.client.app import create_application
    from polmon.client.mainwindow import MainWindow
    from polmon.client.state import ConnectionState

    app = create_application(["polmon-local-probe"], theme_preference="light")
    record: dict[str, object] = {"label": LOCAL_LABEL}
    with tempfile.TemporaryDirectory(prefix="polmon-gui-probe-") as directory:
        settings = QSettings(str(Path(directory) / "probe.ini"), QSettings.Format.IniFormat)
        window = MainWindow(settings, backend_executable=executable)
        window.resize(1440, 900)
        window.show()  # offscreen: nothing appears, but closeEvent and grabs behave as on screen
        try:
            _drive(app, window, ConnectionState, record, screenshot)
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
            window.shutdown(wait_ms=5000)
            output.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(record, indent=2, sort_keys=True), file=out)
            print(f"local-backend GUI probe: FAIL {record['error']}", file=out)
            return 1
        finally:
            window.deleteLater()
            app.processEvents()
            del settings
    output.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True), file=out)
    print("local-backend GUI probe: PASS", file=out)
    return 0


def _connect_local(app, window, states) -> object:  # noqa: ANN001
    window.bar.mode.setCurrentIndex(window.bar.mode.findData("local"))
    window.connect_backend()
    _wait(
        app,
        lambda: window.session.state is states.CONNECTED and window.session.resources is not None,
        40.0,
        "the Local backend preset to connect",
    )
    process = window.local_backend.process
    if process is None or process.poll() is not None:
        raise ProbeFailure("connected without a running owned backend")
    return process


def _drive(app, window, states, record: dict[str, object], screenshot: Path | None) -> None:  # noqa: ANN001
    session = window.session

    # 1. Connect and show the persistent fidelity indicator.
    process = _connect_local(app, window, states)
    record["connected"] = {
        "backend_pid": process.pid,
        "state_label": window.bar.state_label.text(),
        "status_bar": window.status_text.text(),
        "l0_only": session.l0_only,
    }
    if window.bar.state_label.text() != LOCAL_LABEL or not session.l0_only:
        raise ProbeFailure("the Local backend fidelity indicator is missing")

    # 2. L1 topology: the backend answers 422 and the UI refuses before any deploy call.
    api = ApiClient(session.url, token=session.token)
    api.load_topology(_L1_TOPOLOGY)
    try:
        api.deploy("needs-linux")
    except ApiClientError as error:
        record["backend_refusal"] = {
            "http_status": error.status,
            "code": error.code,
            "message": str(error).split(": ", 1)[-1],
            "details": error.details,
        }
    else:
        raise ProbeFailure("the backend deployed an L1 topology in L0-only mode")
    if record["backend_refusal"]["http_status"] != 422:  # type: ignore[index]
        raise ProbeFailure(f"unexpected refusal status: {record['backend_refusal']}")
    window.refresh_now()
    page = window.pages["deployment"]
    _wait(app, lambda: page.target.findData("needs-linux") >= 0, 15.0, "the L1 topology to list")
    window.navigate("deployment")
    page.target.setCurrentIndex(page.target.findData("needs-linux"))
    page.deploy()
    _wait(app, lambda: page.banner.problem is not None, 5.0, "the UI refusal banner")
    problem = page.banner.problem
    record["ui_refusal"] = {"title": problem.title, "detail": problem.detail}
    if problem.title != LOCAL_LABEL or problem.detail != LOCAL_FIDELITY_MESSAGE:
        raise ProbeFailure(f"unexpected UI refusal: {problem.title!r} {problem.detail!r}")
    if session.deployments:
        raise ProbeFailure("a deployment exists after the refusal")
    if screenshot is not None:
        app.processEvents()
        if not window.grab().save(str(screenshot)):
            raise ProbeFailure(f"could not save {screenshot}")
        record["screenshot"] = screenshot.name

    # 3. Disconnect stops the owned backend.
    window.disconnect_backend()
    _wait(app, lambda: process.poll() is not None, 20.0, "the backend to stop on disconnect")
    _wait(app, lambda: window._local_stop_handle is None, 10.0, "the stop task to finish")
    record["disconnect"] = {"backend_pid": process.pid, "exit_code": process.returncode}

    # 4. Backend killed mid-session: reported with its exit code and log, nothing left behind.
    process = _connect_local(app, window, states)
    process.kill()
    process.wait(timeout=10)
    window.poll()
    _wait(app, lambda: session.state is states.DISCONNECTED, 10.0, "the death to be noticed")
    banner = window.pages["dashboard"].banner.problem
    record["backend_killed"] = {
        "backend_pid": process.pid,
        "exit_code": process.returncode,
        "ui_title": banner.title if banner else None,
        "ui_detail": banner.detail if banner else None,
    }
    if banner is None or banner.title != "Local backend stopped":
        raise ProbeFailure("the killed backend was not reported in the UI")
    if window.local_backend._job is not None or window.local_backend._log is not None:
        raise ProbeFailure("the dead backend was not reaped (job/log still open)")

    # 5. Closing the client window stops the owned backend (closeEvent -> shutdown).
    process = _connect_local(app, window, states)
    window.close()
    _wait(app, lambda: process.poll() is not None, 20.0, "the backend to stop on window close")
    record["window_closed"] = {"backend_pid": process.pid, "exit_code": process.returncode}
