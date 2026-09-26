"""Main window: connection bar, navigation, pages, activity log, status bar, health polling."""

from __future__ import annotations

import html
import time
from datetime import datetime

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer, qVersion
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QWidget,
)

from polmon.client import theme
from polmon.client.api import DEFAULT_TIMEOUT, DEFAULT_URL, ApiClientError
from polmon.client.errors import Problem, describe
from polmon.client.pages import Context, Page
from polmon.client.pages.benchmarks import BenchmarksPage
from polmon.client.pages.dashboard import DashboardPage
from polmon.client.pages.deployment import DeploymentPage
from polmon.client.pages.reports import ReportsPage
from polmon.client.pages.scenarios import ScenariosPage
from polmon.client.pages.telemetry import TelemetryPage
from polmon.client.pages.topologies import TopologiesPage
from polmon.client.state import ConnectionState, Session
from polmon.client.tasks import CancelToken, TaskRunner
from polmon.client.widgets import Led, OperationProgress
from polmon.version import __version__

POLL_INTERVAL_MS = 3000
LOST_POLL_INTERVAL_MS = 5000
PAGES = (
    DashboardPage,
    TopologiesPage,
    DeploymentPage,
    ScenariosPage,
    TelemetryPage,
    ReportsPage,
    BenchmarksPage,
)
STATE_TONES = {
    ConnectionState.DISCONNECTED: "muted",
    ConnectionState.CONNECTING: "warning",
    ConnectionState.CONNECTED: "success",
    ConnectionState.UNAUTHORIZED: "danger",
    ConnectionState.LOST: "danger",
}
SHORTCUTS = (
    ("Ctrl+Return", "Connect / disconnect"),
    ("Ctrl+L", "Focus the backend URL"),
    ("F5", "Refresh backend state now"),
    ("Ctrl+O / Ctrl+Shift+O", "Open topology / scenario"),
    ("Ctrl+Shift+V", "Validate the topology in the editor"),
    ("Ctrl+D / Ctrl+Shift+D", "Deploy / destroy the selected topology"),
    ("Ctrl+Shift+R", "Reset the environment"),
    ("Ctrl+R", "Run the experiment"),
    ("Esc", "Cancel the running operation (twice: abandon)"),
    ("Ctrl+1 … Ctrl+7", "Switch page"),
    ("Ctrl+Shift+T", "Toggle light/dark theme"),
    ("Ctrl+Shift+L", "Show or hide the activity log"),
    ("Ctrl+Q", "Quit"),
)


class ConnectionBar(QToolBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Connection", parent)
        self.setObjectName("connectionBar")
        self.setMovable(False)
        self.addWidget(QLabel(" Backend "))
        self.url = QLineEdit(DEFAULT_URL)
        self.url.setMinimumWidth(260)
        self.url.setToolTip("Backend base URL, e.g. http://192.168.1.10:8080 (Ctrl+L)")
        self.addWidget(self.url)
        self.addWidget(QLabel("  Token "))
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("API token (if required)")
        self.token.setToolTip("Kept in memory only: never saved, logged or displayed")
        self.token.setMinimumWidth(170)
        self.addWidget(self.token)
        self.addWidget(QLabel("  Timeout "))
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(1.0, 120.0)
        self.timeout.setDecimals(0)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(DEFAULT_TIMEOUT)
        self.timeout.setToolTip("Timeout for ordinary requests (deploy/reset allow at least 30 s)")
        self.addWidget(self.timeout)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primary")
        self.connect_button.setToolTip("Connect or disconnect (Ctrl+Return)")
        self.addWidget(self.connect_button)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)
        self.led = Led()
        self.state_label = QLabel("Disconnected")
        self.addWidget(self.led)
        self.addWidget(self.state_label)
        self.addWidget(QLabel(" "))


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.settings = settings or QSettings("polmon", "polmon-client")
        self.session = Session(self)
        self.runner = TaskRunner(self)
        self.progress = OperationProgress()
        self.context = Context(self.session, self.runner, self.progress, self.settings, self)
        self._poll_handle = None
        self._poll_count = 0
        self._closing = False

        self.bar = ConnectionBar(self)
        self.addToolBar(self.bar)
        self.bar.connect_button.clicked.connect(self.toggle_connection)
        self.bar.url.returnPressed.connect(self.toggle_connection)
        self.bar.token.returnPressed.connect(self.toggle_connection)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFixedWidth(170)
        self.stack = QStackedWidget()
        self.pages: dict[str, Page] = {}
        for index, page_class in enumerate(PAGES):
            page = page_class(self.context)
            self.pages[page.key] = page
            self.stack.addWidget(page)
            item = QListWidgetItem(page.title)
            item.setToolTip(f"{page.title} (Ctrl+{index + 1})")
            self.navigation.addItem(item)
        self.navigation.currentRowChanged.connect(self._page_changed)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_dock = QDockWidget("Activity", self)
        self.log_dock.setObjectName("activityDock")
        self.log_dock.setWidget(self.log_view)
        self.log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.resizeDocks([self.log_dock], [110], Qt.Orientation.Vertical)

        status = self.statusBar()
        self.status_led = Led()
        self.status_text = QLabel("Disconnected")
        self.status_version = QLabel(f"client {__version__}")
        self.status_version.setObjectName("muted")
        status.addWidget(self.status_led)
        status.addWidget(self.status_text)
        status.addWidget(self.progress, 1)
        status.addPermanentWidget(self.status_version)
        self.progress.cancel_requested.connect(self.context.cancel_operation)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self.poll)

        self.session.logged.connect(self._append_log)
        self.session.connection_changed.connect(self._connection_changed)
        self.context.navigate_requested.connect(self.navigate)
        self.context.operation_changed.connect(self._update_actions)
        self._build_menus()
        self._restore()
        self._connection_changed()
        self.navigation.setCurrentRow(0)
        self.session.log(f"polmon client {__version__} (Qt {qVersion()}, PySide6 {pyside_version})")

    # -- menus and shortcuts ------------------------------------------------------------------

    def _action(self, menu, text: str, shortcut: str | None, slot, tip: str = "") -> QAction:  # noqa: ANN001
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setStatusTip(tip)
        action.triggered.connect(slot)
        menu.addAction(action)
        self.addAction(action)  # shortcuts work even with the menu bar hidden
        return action

    def _build_menus(self) -> None:
        menus = self.menuBar()
        file_menu = menus.addMenu("&File")
        topologies = self.pages["topologies"]
        scenarios = self.pages["scenarios"]
        self._action(
            file_menu,
            "Open &topology…",
            "Ctrl+O",
            lambda: (self.navigate("topologies"), topologies.open_dialog()),
        )  # type: ignore[attr-defined]
        self._action(
            file_menu,
            "Open &scenario…",
            "Ctrl+Shift+O",
            lambda: (self.navigate("scenarios"), scenarios.open_dialog()),
        )  # type: ignore[attr-defined]
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", "Ctrl+Q", self.close)

        backend = menus.addMenu("&Backend")
        self.connect_action = self._action(
            backend, "&Connect", "Ctrl+Return", self.toggle_connection
        )
        self._action(backend, "Focus backend &URL", "Ctrl+L", self._focus_url)
        self.refresh_action = self._action(backend, "&Refresh now", "F5", self.refresh_now)
        backend.addSeparator()
        deployment = self.pages["deployment"]
        self.deploy_action = self._action(
            backend,
            "&Deploy selected topology",
            "Ctrl+D",
            lambda: (self.navigate("deployment"), deployment.deploy()),  # type: ignore[attr-defined]
        )
        self.destroy_action = self._action(
            backend,
            "D&estroy selected deployment",
            "Ctrl+Shift+D",
            lambda: (self.navigate("deployment"), deployment.destroy()),  # type: ignore[attr-defined]
        )
        self.reset_action = self._action(
            backend,
            "Reset &environment…",
            "Ctrl+Shift+R",
            lambda: (self.navigate("deployment"), deployment.reset()),  # type: ignore[attr-defined]
        )

        experiment = menus.addMenu("E&xperiment")
        self.run_action = self._action(
            experiment,
            "&Run experiment",
            "Ctrl+R",
            lambda: (self.navigate("scenarios"), scenarios.run()),  # type: ignore[attr-defined]
        )
        self.cancel_action = self._action(
            experiment, "&Cancel running operation", "Esc", self.context.cancel_operation
        )

        view = menus.addMenu("&View")
        for index, page in enumerate(self.pages.values()):
            self._action(
                view,
                page.title,
                f"Ctrl+{index + 1}",
                lambda checked=False, key=page.key: self.navigate(key),
            )
        view.addSeparator()
        theme_menu = view.addMenu("&Theme")
        group = QActionGroup(self)
        self.theme_actions: dict[str, QAction] = {}
        for name in theme.THEMES:
            action = QAction(name.capitalize(), self, checkable=True)
            action.triggered.connect(lambda checked=False, value=name: self.set_theme(value))
            group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[name] = action
        self._action(view, "Toggle light/dark", "Ctrl+Shift+T", self.toggle_theme)
        log_action = self.log_dock.toggleViewAction()
        log_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        view.addAction(log_action)
        self.addAction(log_action)

        help_menu = menus.addMenu("&Help")
        self._action(help_menu, "&Keyboard shortcuts", "F1", self.show_shortcuts)
        self._action(help_menu, "&About polmon", None, self.show_about)

    # -- navigation ---------------------------------------------------------------------------

    def navigate(self, key: str, argument: object = None) -> None:
        if key == "refresh":
            self.refresh_now()
            return
        keys = list(self.pages)
        if key not in self.pages:
            return
        index = keys.index(key)
        if self.navigation.currentRow() != index:
            self.navigation.setCurrentRow(index)
        self.pages[key].activated(argument)

    def _page_changed(self, index: int) -> None:
        if index < 0:
            return
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        if isinstance(page, Page):
            page.activated()

    @property
    def current_page(self) -> Page:
        page = self.stack.currentWidget()
        assert isinstance(page, Page)
        return page

    # -- connection ---------------------------------------------------------------------------

    def _focus_url(self) -> None:
        self.bar.url.setFocus()
        self.bar.url.selectAll()

    def toggle_connection(self) -> None:
        if self.session.state in {ConnectionState.DISCONNECTED, ConnectionState.UNAUTHORIZED}:
            self.connect_backend()
        else:
            self.disconnect_backend()

    def connect_backend(self) -> None:
        session = self.session
        session.url = self.bar.url.text().strip()
        session.token = self.bar.token.text().strip()
        session.timeout = float(self.bar.timeout.value())
        try:
            session.client()
        except ValueError as error:
            problem = describe(error)
            session.set_state(ConnectionState.DISCONNECTED, problem)
            self.pages["dashboard"].banner.show_problem(problem)
            session.log(f"Connect failed — {problem.text()}", "error")
            return
        self.settings.setValue("connection/url", session.url)
        self.settings.setValue("connection/timeout", session.timeout)
        session.set_state(ConnectionState.CONNECTING)
        session.log(f"Connecting to {session.url}…")
        self.poll(initial=True)

    def disconnect_backend(self) -> None:
        self.poll_timer.stop()
        if self._poll_handle is not None:
            self._poll_handle.cancel()
            self._poll_handle = None
        self.session.set_state(ConnectionState.DISCONNECTED)
        self.session.log("Disconnected")

    def refresh_now(self) -> None:
        if self.session.state in {ConnectionState.CONNECTED, ConnectionState.LOST}:
            self.poll()

    def poll(self, *, initial: bool = False) -> None:
        if self._poll_handle is not None:
            return
        client = self.session.client()
        include_experiments = initial or self._poll_count % 3 == 0
        self._poll_count += 1

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            started = time.monotonic()
            health = client.health()
            latency = time.monotonic() - started
            if health.get("name") != "polmon":
                raise ApiClientError(
                    "the server answered, but it is not a polmon backend",
                    code="malformed_response",
                )
            resources = client.resources()
            topologies = client.topologies()
            deployments: dict[str, dict[str, object]] = {}
            for item in topologies:
                if item.get("deployed"):
                    topology_id = str(item["topology_id"])
                    try:
                        deployments[topology_id] = client.deployment(topology_id)
                    except ApiClientError as error:
                        if error.status is None:
                            raise
                        # destroyed between the two calls: the next poll settles it
            experiments = client.experiments() if include_experiments else None
            return {
                "health": health,
                "latency": latency,
                "resources": resources,
                "topologies": topologies,
                "deployments": deployments,
                "experiments": experiments,
            }

        self._poll_handle = self.runner.submit(
            "Poll backend",
            work,
            on_success=lambda result: self._polled(result, initial),  # type: ignore[arg-type]
            on_failure=lambda error: self._poll_failed(error, initial),
        )

    def _polled(self, result: dict[str, object], initial: bool) -> None:
        self._poll_handle = None
        session = self.session
        if session.state is ConnectionState.DISCONNECTED:
            return  # disconnected while the poll was in flight
        health = result["health"]
        assert isinstance(health, dict)
        previous = session.state
        session.backend_version = str(health.get("version"))
        session.latency = result["latency"]  # type: ignore[assignment]
        if previous is not ConnectionState.CONNECTED:
            session.set_state(ConnectionState.CONNECTED)
            if previous is ConnectionState.LOST:
                session.log("Backend reachable again", "info")
            else:
                session.log(f"Connected to {session.url} (backend {session.backend_version})")
                if session.backend_version != __version__:
                    session.log(
                        f"Backend version {session.backend_version} differs from client "
                        f"{__version__}; some features may be unavailable",
                        "warning",
                    )
            self.pages["dashboard"].banner.clear()
        session.set_resources(result["resources"])  # type: ignore[arg-type]
        session.set_topologies(result["topologies"])  # type: ignore[arg-type]
        session.set_deployments(result["deployments"])  # type: ignore[arg-type]
        if result.get("experiments") is not None:
            session.set_experiments(result["experiments"])  # type: ignore[arg-type]
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        if not self.poll_timer.isActive():
            self.poll_timer.start()
        self._update_status()

    def _poll_failed(self, error: BaseException, initial: bool) -> None:
        self._poll_handle = None
        session = self.session
        if session.state is ConnectionState.DISCONNECTED:
            return
        problem = describe(error, url=session.url, timeout=session.timeout)
        banner = self.pages["dashboard"].banner
        if isinstance(error, ApiClientError) and error.status == 401:
            self.poll_timer.stop()
            session.set_state(ConnectionState.UNAUTHORIZED, problem)
            banner.show_problem(problem)
            session.log(f"Connection refused — {problem.text()}", "error")
            return
        transport = (
            isinstance(error, ApiClientError)
            and error.status is None
            and (error.code != "malformed_response")
        )
        if initial or not transport:
            self.poll_timer.stop()
            session.set_state(ConnectionState.DISCONNECTED, problem)
            banner.show_problem(problem)
            session.log(f"Connect failed — {problem.text()}", "error")
            return
        if session.state is not ConnectionState.LOST:
            session.set_state(ConnectionState.LOST, problem)
            session.log(f"Lost contact with the backend — {problem.text()}", "error")
            banner.show_problem(
                Problem(
                    "Backend unreachable",
                    f"{problem.detail} Retrying every {LOST_POLL_INTERVAL_MS // 1000} s; actions "
                    "are disabled until it answers again.",
                    problem.hint,
                )
            )
        self.poll_timer.setInterval(LOST_POLL_INTERVAL_MS)
        if not self.poll_timer.isActive():
            self.poll_timer.start()

    def _connection_changed(self) -> None:
        state = self.session.state
        tone = STATE_TONES[state]
        for led in (self.bar.led, self.status_led):
            led.set_tone(tone)
        self.bar.connect_button.setText(
            "Connect"
            if state in {ConnectionState.DISCONNECTED, ConnectionState.UNAUTHORIZED}
            else "Disconnect"
        )
        editable = state in {ConnectionState.DISCONNECTED, ConnectionState.UNAUTHORIZED}
        for widget in (self.bar.url, self.bar.token, self.bar.timeout):
            widget.setEnabled(editable)
        self._update_status()
        self._update_actions()

    def _update_status(self) -> None:
        session = self.session
        state = session.state
        if state is ConnectionState.CONNECTED:
            text = f"Connected · {session.url} · backend {session.backend_version}"
        elif state is ConnectionState.LOST and session.lost_since:
            since = datetime.fromtimestamp(session.lost_since).strftime("%H:%M:%S")
            text = f"Backend unreachable since {since} · retrying"
        elif state is ConnectionState.UNAUTHORIZED:
            text = "API token required or rejected"
        elif state is ConnectionState.CONNECTING:
            text = f"Connecting to {session.url}…"
        else:
            text = "Disconnected"
        self.bar.state_label.setText(text.split(" · ")[0])
        self.status_text.setText(text)
        backend = f" (backend {session.backend_version})" if session.backend_version else ""
        where = f" — {state.value}: {session.url}{backend}" if state.value != "disconnected" else ""
        self.setWindowTitle(f"polmon {__version__}{where}")

    def _update_actions(self) -> None:
        connected = self.session.connected
        busy = self.context.busy
        self.connect_action.setText(
            "&Connect"
            if self.session.state in {ConnectionState.DISCONNECTED, ConnectionState.UNAUTHORIZED}
            else "Dis&connect"
        )
        self.refresh_action.setEnabled(connected or self.session.state is ConnectionState.LOST)
        for action in (self.deploy_action, self.destroy_action, self.reset_action, self.run_action):
            action.setEnabled(connected and not busy)
        self.cancel_action.setEnabled(busy)

    # -- log ----------------------------------------------------------------------------------

    def _append_log(self, level: str, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        tone = {"error": "danger", "warning": "warning"}.get(level)
        text = html.escape(message).replace("\n", "<br>&nbsp;&nbsp;")
        # Ordinary lines carry no colour so they follow the palette when the theme changes.
        body = f"<span style='color:{theme.hex_color(tone)}'>{text}</span>" if tone else text
        self.log_view.appendHtml(
            f"<span style='color:{theme.hex_color('muted')}'>{stamp}</span> {body}"
        )

    # -- theme --------------------------------------------------------------------------------

    def set_theme(self, preference: str) -> None:
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        effective = theme.apply(app, preference)
        self.settings.setValue("view/theme", preference)
        if preference in self.theme_actions:
            self.theme_actions[preference].setChecked(True)
        self.session.log(f"Theme: {preference} ({effective})")
        for widget in self.findChildren(QWidget):
            widget.update()

    def toggle_theme(self) -> None:
        self.set_theme("light" if theme.current() == "dark" else "dark")

    # -- dialogs ------------------------------------------------------------------------------

    def show_shortcuts(self) -> None:
        rows = "".join(
            f"<tr><td><b>{html.escape(keys)}</b></td><td>&nbsp;&nbsp;{html.escape(text)}</td></tr>"
            for keys, text in SHORTCUTS
        )
        QMessageBox.information(self, "Keyboard shortcuts", f"<table>{rows}</table>")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About polmon",
            f"<h3>polmon {__version__}</h3>"
            "<p>Operator console for the resource-efficient isolated network attack simulation "
            "platform. The client talks to a polmon Linux backend over its documented HTTP API "
            "and never runs laboratory networking itself.</p>"
            f"<p>Qt {qVersion()} · PySide6 {pyside_version} (Qt for Python, LGPLv3)</p>",
        )

    # -- persistence and shutdown -------------------------------------------------------------

    def _restore(self) -> None:
        settings = self.settings
        self.bar.url.setText(str(settings.value("connection/url", DEFAULT_URL)))
        try:
            self.bar.timeout.setValue(float(settings.value("connection/timeout", DEFAULT_TIMEOUT)))
        except (TypeError, ValueError):
            self.bar.timeout.setValue(DEFAULT_TIMEOUT)
        preference = str(settings.value("view/theme", "system"))
        if preference not in theme.THEMES:
            preference = "system"
        self.theme_actions[preference].setChecked(True)
        geometry = settings.value("window/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        else:
            self.resize(1280, 800)
        state = settings.value("window/state")
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def shutdown(self, wait_ms: int = 2000) -> bool:
        """Stop timers, cancel work and wait briefly; returns False if workers remain."""
        self._closing = True
        self.poll_timer.stop()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.settings.sync()
        self.runner.close()
        return self.runner.wait(wait_ms)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self.context.busy and not self._closing:
            answer = QMessageBox.question(
                self,
                "Operation in progress",
                f"'{self.context.operation_name}' is still running. Quit anyway? Work already "
                "sent to the backend continues there; reconnect later and use Reset if needed.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.clean_exit = self.shutdown()
        event.accept()
