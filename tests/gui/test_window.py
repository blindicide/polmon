"""The main window: identity, theming, shortcuts, and connection behaviour under failure."""

import io
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from conftest import connect, free_port, log_text, wait_connected
from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QPalette
from PySide6.QtWidgets import QApplication

from polmon.client.state import ConnectionState
from polmon.version import __version__


def test_version_contract_and_headless_self_test(capsys) -> None:
    from polmon.client.app import main
    from polmon.client.selftest import self_test

    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"polmon {__version__}\n"
    visible_before = [widget for widget in QApplication.topLevelWidgets() if widget.isVisible()]
    stream = io.StringIO()
    assert self_test(stream) == 0
    report = stream.getvalue()
    for check in ("Qt imports", "platform plugins", "QApplication", "main window", "API client"):
        assert f"PASS {check}" in report
    assert report.rstrip().endswith(f"polmon {__version__} self-test: PASS")
    visible_after = [widget for widget in QApplication.topLevelWidgets() if widget.isVisible()]
    assert len(visible_after) <= len(visible_before)  # nothing new was shown


def test_title_shows_version_and_theme_toggles(window, qtbot) -> None:
    assert window.windowTitle() == f"polmon {__version__}"
    light = QApplication.palette().color(QPalette.ColorRole.Window).name()
    window.toggle_theme()
    dark = QApplication.palette().color(QPalette.ColorRole.Window).name()
    assert light != dark
    assert window.settings.value("view/theme") == "dark"
    window.set_theme("light")
    assert QApplication.palette().color(QPalette.ColorRole.Window).name() == light


def test_documented_shortcuts_are_bound(window) -> None:
    bound = {action.shortcut().toString() for action in window.actions()}
    for keys in ("Ctrl+O", "Ctrl+Shift+O", "Ctrl+Return", "F5", "Ctrl+D", "Ctrl+Shift+D",
                 "Ctrl+Shift+R", "Ctrl+R", "Esc", "Ctrl+1", "Ctrl+7", "Ctrl+Shift+T", "Ctrl+Q"):
        assert QKeySequence(keys).toString() in bound, keys


def test_pages_switch_with_navigation(window) -> None:
    for index, key in enumerate(window.pages):
        window.navigation.setCurrentRow(index)
        assert window.current_page.key == key


def test_unreachable_backend_is_explained_and_ui_stays_live(window, qtbot) -> None:
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(20)
    connect(qtbot, window, url=f"http://127.0.0.1:{free_port()}", token="")
    qtbot.waitUntil(lambda: window.session.state is ConnectionState.DISCONNECTED, timeout=10_000)
    timer.stop()
    banner = window.pages["dashboard"].banner
    assert banner.isVisible() and banner.problem.title == "Backend unreachable"
    assert "connection refused" in banner.problem.detail.lower()
    assert ticks, "the event loop must keep running while connecting"
    assert "Traceback" not in log_text(window)


def test_slow_backend_times_out_without_blocking(window, qtbot) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)  # accepts connections, never answers
    try:
        window.bar.timeout.setValue(2)
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(50)
        connect(qtbot, window, url=f"http://127.0.0.1:{listener.getsockname()[1]}", token="")
        qtbot.wait(1000)
        assert window.session.state is ConnectionState.CONNECTING
        assert len(ticks) >= 10, "GUI thread was blocked while the request was pending"
        qtbot.waitUntil(
            lambda: window.session.state is ConnectionState.DISCONNECTED, timeout=10_000
        )
        timer.stop()
        problem = window.pages["dashboard"].banner.problem
        assert problem.title == "Backend did not respond" and "2 s timeout" in problem.detail
    finally:
        listener.close()


class NotPolmon(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"<html>router login</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


def test_malformed_responses_are_reported(window, qtbot) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), NotPolmon)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connect(qtbot, window, url=f"http://127.0.0.1:{server.server_port}", token="")
        qtbot.waitUntil(
            lambda: window.session.state is ConnectionState.DISCONNECTED, timeout=10_000
        )
        problem = window.pages["dashboard"].banner.problem
        assert problem.title == "Unexpected response"
    finally:
        server.shutdown()
        server.server_close()


def test_token_is_required_used_and_never_shown(window, qtbot, live_backend) -> None:
    connect(qtbot, window, live_backend, token="")
    qtbot.waitUntil(lambda: window.session.state is ConnectionState.UNAUTHORIZED, timeout=10_000)
    assert window.pages["dashboard"].banner.problem.title == "API token required"
    assert window.bar.token.isEnabled()  # the operator can now enter it
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    assert window.session.backend_version == __version__
    assert live_backend.token not in log_text(window)
    assert live_backend.token not in window.windowTitle()
    assert window.settings.value("connection/token") is None
    limits = window.pages["dashboard"].limits
    assert limits.item(0, 1).text() == "250"
    window.disconnect_backend()
    assert window.session.state is ConnectionState.DISCONNECTED and window.session.resources is None


def test_backend_loss_is_detected_and_recovered_from(window, qtbot, backend_factory) -> None:
    backend = backend_factory()
    connect(qtbot, window, backend)
    wait_connected(qtbot, window)
    backend.stop()
    qtbot.waitUntil(lambda: window.session.state is ConnectionState.LOST, timeout=15_000)
    assert "unreachable" in window.status_text.text().lower()
    assert not window.run_action.isEnabled() and not window.deploy_action.isEnabled()
