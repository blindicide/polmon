"""The main window: identity, theming, shortcuts, and connection behaviour under failure."""

import io
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
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
    for keys in (
        "Ctrl+O",
        "Ctrl+Shift+O",
        "Ctrl+Return",
        "F5",
        "Ctrl+D",
        "Ctrl+Shift+D",
        "Ctrl+Shift+R",
        "Ctrl+R",
        "Esc",
        "Ctrl+1",
        "Ctrl+7",
        "Ctrl+Shift+T",
        "Ctrl+Q",
    ):
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


def test_local_preset_starts_connects_and_reaps_owned_backend(window, qtbot) -> None:
    window.bar.mode.setCurrentIndex(window.bar.mode.findData("local"))
    window.connect_backend()
    wait_connected(qtbot, window, timeout=20_000)
    process = window.local_backend.process
    assert process is not None and process.poll() is None
    assert window.session.l0_only
    assert window.bar.state_label.text() == "Local backend — L0 only"
    assert "Local backend — L0 only" in window.status_text.text()
    assert window.bar.log_button.isEnabled()
    window.disconnect_backend()
    qtbot.waitUntil(lambda: process.poll() is not None, timeout=20_000)
    assert process.returncode is not None
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)


def test_local_backend_death_is_actionable(window, qtbot) -> None:
    window.bar.mode.setCurrentIndex(window.bar.mode.findData("local"))
    window.connect_backend()
    wait_connected(qtbot, window, timeout=20_000)
    process = window.local_backend.process
    assert process is not None
    process.kill()
    process.wait(timeout=10)
    window.poll()
    qtbot.waitUntil(lambda: window.session.state is ConnectionState.DISCONNECTED, timeout=5_000)
    problem = window.pages["dashboard"].banner.problem
    assert problem.title == "Local backend stopped"
    assert str(window.local_backend.log_path) in problem.hint


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


def test_application_icon_is_drawn_and_exportable(window, tmp_path) -> None:
    from polmon.client.icon import SIZES, main

    icon = window.windowIcon()
    assert not icon.isNull()
    assert {size.width() for size in icon.availableSizes()} >= set(SIZES)
    target = tmp_path / "polmon.ico"
    assert main([str(target)]) == 0
    assert target.read_bytes()[:4] == b"\x00\x00\x01\x00"  # ICO header


def test_connected_backends_are_remembered(window, qtbot, live_backend) -> None:
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    assert window.recent_urls()[0] == live_backend.url
    box = window.bar.url_box
    assert box.findText(live_backend.url) == 0
    window.disconnect_backend()
    window.bar.url.setText("http://10.0.0.9:8080")
    box.setCurrentIndex(0)  # picking a recent entry fills the field
    assert window.bar.url.text() == live_backend.url


def test_desktop_entry_is_installed_for_the_user(tmp_path, monkeypatch, capsys) -> None:
    import sys

    import pytest

    if not sys.platform.startswith("linux"):
        pytest.skip("NOT RUN — environment unavailable: desktop entries are a Linux feature")
    from polmon.client.app import main

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert main(["--install-desktop-entry"]) == 0
    entry = (tmp_path / "applications/polmon-client.desktop").read_text(encoding="utf-8")
    assert "Exec=" in entry and "Icon=polmon-client" in entry
    assert (tmp_path / "icons/hicolor/256x256/apps/polmon-client.png").stat().st_size > 1000
    assert "wrote" in capsys.readouterr().out


def test_inputs_editors_and_views_have_accessible_names(window) -> None:
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QAbstractSpinBox,
        QComboBox,
        QLineEdit,
        QPlainTextEdit,
        QWidget,
    )

    kinds = (QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QAbstractItemView)
    unnamed = []
    for key in window.pages:
        window.navigate(key)
        for widget in window.findChildren(QWidget):
            if not isinstance(widget, kinds) or not widget.isVisibleTo(window):
                continue
            owner = widget.parent()
            if isinstance(widget, QLineEdit) and isinstance(owner, QComboBox | QAbstractSpinBox):
                continue  # the owning combo box / spin box carries the name
            if not widget.accessibleName():
                unnamed.append(f"{key}: {type(widget).__name__} ({widget.toolTip()!r})")
    assert not unnamed, sorted(set(unnamed))
    assert window.bar.token.accessibleName() == "API token"


def test_client_guide_lists_exactly_the_bound_shortcuts() -> None:
    import re
    from pathlib import Path

    from polmon.client.mainwindow import SHORTCUTS

    guide = (Path(__file__).parents[2] / "docs/CLIENT.md").read_text(encoding="utf-8")
    section = guide.split("## Keyboard shortcuts", 1)[1].split("##", 1)[0]
    rows = re.findall(r"^\| ([^|]+?) \| ([^|]+?) \|$", section, re.M)
    documented = [(keys, action) for keys, action in rows if keys not in {"Keys", "---"}]
    assert documented == list(SHORTCUTS)


def test_smoke_start_shows_the_window_and_reports(qapp) -> None:
    from polmon.client.selftest import smoke_start

    stream = io.StringIO()
    # 0.5 s was too short on a loaded Windows runner (Build Windows 36283869533): the window was
    # not yet exposed when the smoke start ended. Exposure is what is under test, not speed.
    code = smoke_start(2.0, ["polmon-client"], stream)
    output = stream.getvalue()
    assert code == 0, output
    assert "exposed after" in output
    platform = QApplication.platformName()
    assert f"polmon {__version__} smoke-start: PASS platform={platform}" in output


def test_gui_entry_point_builds_and_runs_the_main_window(qapp, monkeypatch, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from polmon.client import app as client_app
    from polmon.client import mainwindow

    shown = []
    real_window = mainwindow.MainWindow

    def isolated_window(settings=None, parent=None, **kwargs):
        window = real_window(QSettings(str(tmp_path / "gui.ini"), QSettings.Format.IniFormat))
        shown.append(window)
        return window

    monkeypatch.setattr(mainwindow, "MainWindow", isolated_window)
    monkeypatch.setattr(type(qapp), "exec", lambda self: 0)
    assert client_app.main(["--url", "http://10.1.2.3:8080", "--theme", "dark"]) == 0
    assert shown and shown[0].bar.url.text() == "http://10.1.2.3:8080"
    assert shown[0].isVisible()
    shown[0].shutdown(wait_ms=1000)
    shown[0].close()


def test_navigation_rows_are_laid_out_with_the_themed_item_size(window, qtbot) -> None:
    # The theme is applied before the window exists (as in the real app): rows added before the
    # list was polished used to be laid out 14 px apart while being drawn 30 px tall.
    qtbot.waitExposed(window)
    navigation = window.navigation
    step = navigation.sizeHintForRow(0)
    rows = range(navigation.count())
    tops = [navigation.visualItemRect(navigation.item(row)).top() for row in rows]
    assert step >= 24
    gaps = [later - earlier for earlier, later in zip(tops, tops[1:], strict=False)]
    assert gaps == [step] * (len(tops) - 1)
