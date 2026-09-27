"""Main window: sidebar navigation, connection header, pages, activity log, status bar, polling.

Every visible string is bound to the catalogs; *View → Language* switches Russian/English at run
time without touching session state (connection, editors, selections, the owned local backend).
"""

from __future__ import annotations

import html
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QByteArray, QSettings, QSize, Qt, QTimer, QUrl, qVersion
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from polmon.client import i18n, theme
from polmon.client.api import DEFAULT_TIMEOUT, DEFAULT_URL, ApiClientError
from polmon.client.errors import Problem, describe
from polmon.client.i18n import Msg, bind, bind_fn, bind_text, bind_tip, tr
from polmon.client.icon import app_icon
from polmon.client.language import apply_language
from polmon.client.local_backend import LocalBackendError, LocalBackendManager
from polmon.client.locales import AUTONYMS
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
from polmon.client.widgets import (
    ActivityIndicator,
    Led,
    OperationProgress,
    button,
    confirm,
    label,
    primary_button,
)
from polmon.version import __version__

ACCESSIBLE_KINDS = (
    QLineEdit,
    QComboBox,
    QAbstractSpinBox,
    QPlainTextEdit,
    QScrollArea,
    QAbstractItemView,
)
POLL_INTERVAL_MS = 3000
MAX_RECENT_URLS = 8
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
LOG_LINES = 5000  # activity-log capacity
# (keys, catalog key of the action): shown in Help → Keyboard shortcuts and docs/CLIENT.md.
SHORTCUTS = (
    ("Ctrl+Return", "shortcut.connect"),
    ("Ctrl+L", "shortcut.focus_url"),
    ("F5", "shortcut.refresh"),
    ("Ctrl+O / Ctrl+Shift+O", "shortcut.open"),
    ("Ctrl+S", "shortcut.save"),
    ("Ctrl+Shift+V", "shortcut.validate"),
    ("Ctrl+D / Ctrl+Shift+D", "shortcut.deploy_destroy"),
    ("Ctrl+Shift+R", "shortcut.reset"),
    ("Ctrl+R", "shortcut.run"),
    ("Esc", "shortcut.cancel"),
    ("Ctrl+1 … Ctrl+7", "shortcut.pages"),
    ("Ctrl+Shift+T", "shortcut.theme"),
    ("Ctrl+Shift+L", "shortcut.log"),
    ("Ctrl+Shift+U", "shortcut.language"),
    ("F1", "shortcut.help"),
    ("Ctrl+Q", "shortcut.quit"),
)
# Backend features an older backend may lack (poll degrades instead of failing).
FEATURE_TOPOLOGIES = "topology_listing"
FEATURE_EXPERIMENTS = "experiment_listing"


class ConnectionBar(QFrame):
    """The header above the pages: connection type, remote fields, connect, state.

    A plain frame rather than a QToolBar: tool bars take stylesheet padding as one uniform
    margin and only after a re-polish, which changed the header height on a theme switch.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("connectionBar")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(
            theme.SPACE["md"], theme.SPACE["sm"], theme.SPACE["md"], theme.SPACE["sm"]
        )
        self._layout.setSpacing(theme.SPACE["sm"])
        self.mode = QComboBox()
        self.mode.setObjectName("connectionMode")
        self.mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.mode.setMinimumContentsLength(15)
        self.mode.addItem("", "local")
        self.mode.addItem("", "remote")
        bind_fn(
            self.mode,
            lambda combo: [
                combo.setItemText(index, tr(f"connection.mode.{combo.itemData(index)}"))
                for index in range(combo.count())
            ],
            tag="items",
        )
        bind_tip(self.mode, "connection.mode.tip")
        self.addWidget(self.mode)
        # Remote-only fields (URL, token) and the local-only log button are shown per mode.
        self.remote_actions = [self.addWidget(label("connection.url", name="fieldLabel"))]
        # Editable combo: type a URL or pick one of the recently connected backends.
        self.url_box = QComboBox()
        self.url_box.setObjectName("backendUrl")
        self.url_box.setEditable(True)
        self.url_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Prefers a whole loopback URL (about 24 characters) but shrinks to 140 px, which keeps
        # the window within a 1366-px laptop screen.
        self.url_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.url_box.setMinimumContentsLength(24)
        self.url_box.setMinimumWidth(140)
        self.url_box.setMaximumWidth(280)
        self.url_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind_tip(self.url_box, "connection.url.tip")
        self.url = self.url_box.lineEdit()
        self.url.setText(DEFAULT_URL)
        self.remote_actions.append(self.addWidget(self.url_box))
        self._layout.setStretchFactor(self.url_box, 4)  # spare width goes to the URL first
        self.remote_actions.append(self.addWidget(label("connection.token", name="fieldLabel")))
        self.token = QLineEdit()
        self.token.setObjectName("apiToken")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        bind(self.token, "setPlaceholderText", "connection.token.placeholder")
        bind_tip(self.token, "connection.token.tip")
        self.token.setMinimumWidth(80)
        self.token.setMaximumWidth(104)
        # A long token filled in without focus (restored, pasted by a script) shows its start
        # instead of a clipped tail.
        self.token.textChanged.connect(
            lambda _text: None if self.token.hasFocus() else self.token.setCursorPosition(0)
        )
        self.token.editingFinished.connect(lambda: self.token.setCursorPosition(0))
        self.remote_actions.append(self.addWidget(self.token))
        self.addWidget(label("connection.timeout", name="fieldLabel"))
        self.timeout = QDoubleSpinBox()
        self.timeout.setObjectName("requestTimeout")
        self.timeout.setRange(1.0, 120.0)
        self.timeout.setDecimals(0)
        self.timeout.setSuffix(" s")  # unit symbols are not translated
        self.timeout.setValue(DEFAULT_TIMEOUT)
        self.timeout.setFixedWidth(84)  # "120 s" and the arrows
        bind_tip(self.timeout, "connection.timeout.tip")
        self.addWidget(self.timeout)
        self.connect_button = primary_button(
            "connection.connect", tip="connection.connect.tip", name="connectButton"
        )
        self.connect_button.setMinimumWidth(128)
        self.addWidget(self.connect_button)
        self.log_button = button(
            "connection.backend_log", "quiet", tip="connection.backend_log.tip",
            name="backendLogButton",
        )
        self.log_button.setEnabled(False)
        self.local_actions = [self.addWidget(self.log_button)]
        self._layout.addStretch(0)  # takes only what the URL field (stretch 4) leaves
        self.fidelity = label(name="fidelity")
        self.fidelity.setObjectName("fidelity")
        self.fidelity.hide()
        self.addWidget(self.fidelity)
        self.led = Led()
        self.state_label = QLabel()
        self.state_label.setObjectName("connectionState")
        self.state_label.setMaximumWidth(170)
        self.addWidget(self.led)
        self.addWidget(self.state_label)

    def addWidget(self, widget: QWidget) -> QWidget:  # noqa: N802 - mirrors QToolBar's API
        self._layout.addWidget(widget)
        return widget


class PageHost(QWidget):
    """Holds a page inside its scroll area and reports the page's *minimum* size: a scroll area
    otherwise sizes a wrapping layout by its preferred height for the width and would scroll
    pages that fit."""

    def __init__(self, page: QWidget) -> None:
        super().__init__()
        self.page = page
        page.setParent(self)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.page.minimumSizeHint().expandedTo(self.page.minimumSize())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.minimumSizeHint()

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt API
        self.page.setGeometry(self.rect())
        super().resizeEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
        *,
        backend_executable: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowIcon(app_icon())
        self.settings = settings or QSettings("polmon", "polmon-client")
        self.session = Session(self)
        self.runner = TaskRunner(self)
        self.progress = OperationProgress()
        self.activity = ActivityIndicator()
        self.context = Context(
            self.session, self.runner, self.progress, self.settings, self, activity=self.activity
        )
        self._poll_handle = None
        self._poll_count = 0
        self._closing = False
        self.local_backend = LocalBackendManager(backend_executable)
        self._local_start_handle = None
        self._local_stop_handle = None

        self.bar = ConnectionBar(self)
        self.bar.connect_button.clicked.connect(self.toggle_connection)
        self.bar.mode.currentIndexChanged.connect(self._connection_mode_changed)
        self.bar.log_button.clicked.connect(self.open_backend_log)
        self.bar.url.returnPressed.connect(self.toggle_connection)
        self.bar.token.returnPressed.connect(self.toggle_connection)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(212)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        brand = QLabel("polmon")
        brand.setObjectName("brand")
        side.addWidget(brand)
        side.addWidget(label("app.tagline", name="brandVersion", wrap=True))
        side.addWidget(label("nav.section", name="navSection"))
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        # Polish before adding rows: the item size then includes the theme's padding. Rows added
        # to an unpolished list were laid out 14 px apart but drawn 30 px tall (overlapping).
        self.navigation.ensurePolished()
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()
        self.pages: dict[str, Page] = {}
        self._page_order: list[Page] = []
        self.page_scrolls: dict[str, QScrollArea] = {}
        for page_class in PAGES:
            page = page_class(self.context)
            self.pages[page.key] = page
            self._page_order.append(page)
            # A screen smaller than the page's minimum (below 1440x900) scrolls instead of
            # clipping; at 1440x900 and above no page needs to (tests/gui/test_language.py).
            scroll = QScrollArea()
            scroll.setObjectName("pageScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(PageHost(page))
            self.page_scrolls[page.key] = scroll
            self.stack.addWidget(scroll)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, page.key)
            self.navigation.addItem(item)
        bind_fn(self.navigation, self._retranslate_navigation, tag="items")
        self.navigation.currentRowChanged.connect(self._page_changed)
        side.addWidget(self.navigation, 1)
        self.sidebar_footer = QLabel()
        self.sidebar_footer.setObjectName("sidebarFooter")
        self.sidebar_footer.setWordWrap(True)
        side.addWidget(self.sidebar_footer)
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self.bar)
        content.addWidget(self.stack, 1)
        layout.addLayout(content, 1)
        self.setCentralWidget(central)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("activityLog")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_LINES)
        # (time, level, message) of every line, kept to re-render the log in another language
        # or theme; messages are Msg/Problem values rendered on display.
        self._log_entries: deque[tuple[str, str, object]] = deque(maxlen=LOG_LINES)
        self.log_dock = QDockWidget(self)
        bind(self.log_dock, "setWindowTitle", "log.dock")
        self.log_dock.setObjectName("activityDock")
        self.log_dock.setWidget(self.log_view)
        self.log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.resizeDocks([self.log_dock], [110], Qt.Orientation.Vertical)

        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self.status_text = QLabel()
        self.status_text.setObjectName("statusText")
        self.status_version = QLabel()
        self.status_version.setObjectName("muted")
        bind_text(self.status_version, "statusbar.client_version", version=__version__)
        status.addWidget(self.status_text)
        status.addWidget(self.progress, 1)
        status.addPermanentWidget(self.activity)
        status.addPermanentWidget(self.status_version)
        self.progress.cancel_requested.connect(self.context.cancel_operation)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self.poll)

        self.session.logged.connect(self._append_log)
        self.session.connection_changed.connect(self._connection_changed)
        self.context.navigate_requested.connect(self.navigate)
        self.context.notified.connect(self._notified)
        self.context.operation_changed.connect(self._update_actions)
        self._build_menus()
        self._name_for_assistive_technology()
        self._restore()
        self._connection_changed()
        last_page = str(self.settings.value("window/page", "dashboard"))
        keys = list(self.pages)
        self.navigation.setCurrentRow(keys.index(last_page) if last_page in keys else 0)
        i18n.on_language_changed(self)
        self.session.log(
            Msg("log.client_started", version=__version__, qt=qVersion(), pyside=pyside_version)
        )

    # -- language -----------------------------------------------------------------------------

    def set_language(self, language: str) -> None:
        """Switch the UI language now; nothing else changes (no restart, no lost state)."""
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        if not apply_language(app, language):
            return
        self.settings.setValue("view/language", language)
        if language in self.language_actions:
            self.language_actions[language].setChecked(True)
        self.session.log(Msg("log.language", language=AUTONYMS[language]))

    def toggle_language(self) -> None:
        languages = i18n.languages()
        index = languages.index(i18n.language())
        self.set_language(languages[(index + 1) % len(languages)])

    def retranslate(self) -> None:
        """Computed window text: status line, window title, dynamic action names, the log."""
        self._rerender_log()
        self._update_status()
        self._update_actions()
        self._name_for_assistive_technology()
        for code, action in self.language_actions.items():
            action.setChecked(code == i18n.language())
        notice = getattr(self, "_notice", None)
        if notice is not None and self.statusBar().currentMessage() == notice[1]:
            self._notice = (notice[0], str(notice[0]))  # still showing: re-render it
            self.statusBar().showMessage(self._notice[1], 15_000)

    def _retranslate_navigation(self, navigation: QListWidget) -> None:
        for index in range(navigation.count()):
            item = navigation.item(index)
            key = str(item.data(Qt.ItemDataRole.UserRole))
            item.setText(tr(f"page.{key}.title"))
            item.setToolTip(f"{tr(f'page.{key}.subtitle')} (Ctrl+{index + 1})")

    # -- menus and shortcuts ------------------------------------------------------------------

    def _action(self, menu, key: str, shortcut: str | None, slot, tip: str = "") -> QAction:  # noqa: ANN001
        action = QAction(self)
        action.setObjectName(key)
        bind(action, "setText", key)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            bind(action, "setStatusTip", tip)
        action.triggered.connect(slot)
        menu.addAction(action)
        self.addAction(action)  # shortcuts work even with the menu bar hidden
        return action

    def _menu(self, key: str):  # noqa: ANN202
        menu = self.menuBar().addMenu("")
        menu.setObjectName(key)
        bind(menu, "setTitle", key)
        return menu

    def _build_menus(self) -> None:
        file_menu = self._menu("menu.file")
        topologies = self.pages["topologies"]
        scenarios = self.pages["scenarios"]
        self._action(
            file_menu,
            "action.open_topology",
            "Ctrl+O",
            lambda: (self.navigate("topologies"), topologies.open_dialog()),  # type: ignore[attr-defined]
        )
        self._action(
            file_menu,
            "action.open_scenario",
            "Ctrl+Shift+O",
            lambda: (self.navigate("scenarios"), scenarios.open_dialog()),  # type: ignore[attr-defined]
        )
        self._action(file_menu, "action.save", "Ctrl+S", self.save_document)
        file_menu.addSeparator()
        self._action(file_menu, "action.quit", "Ctrl+Q", self.close)

        backend = self._menu("menu.backend")
        self.connect_action = self._action(
            backend, "action.connect", "Ctrl+Return", self.toggle_connection
        )
        self._action(backend, "action.focus_url", "Ctrl+L", self._focus_url)
        self.refresh_action = self._action(backend, "action.refresh", "F5", self.refresh_now)
        self.backend_log_action = self._action(
            backend, "action.backend_log", None, self.open_backend_log
        )
        backend.addSeparator()
        deployment = self.pages["deployment"]
        self.deploy_action = self._action(
            backend,
            "action.deploy",
            "Ctrl+D",
            lambda: (self.navigate("deployment"), deployment.deploy()),  # type: ignore[attr-defined]
        )
        self.destroy_action = self._action(
            backend,
            "action.destroy",
            "Ctrl+Shift+D",
            lambda: (self.navigate("deployment"), deployment.destroy()),  # type: ignore[attr-defined]
        )
        self.reset_action = self._action(
            backend,
            "action.reset",
            "Ctrl+Shift+R",
            lambda: (self.navigate("deployment"), deployment.reset()),  # type: ignore[attr-defined]
        )

        experiment = self._menu("menu.experiment")
        self.run_action = self._action(
            experiment,
            "action.run",
            "Ctrl+R",
            lambda: (self.navigate("scenarios"), scenarios.run()),  # type: ignore[attr-defined]
        )
        self.cancel_action = self._action(
            experiment, "action.cancel", "Esc", self.context.cancel_operation
        )

        view = self._menu("menu.view")
        for index, page in enumerate(self.pages.values()):
            action = self._action(
                view,
                f"page.{page.key}.title",
                f"Ctrl+{index + 1}",
                lambda checked=False, key=page.key: self.navigate(key),
            )
            action.setObjectName(f"navigate.{page.key}")
        view.addSeparator()
        language_menu = view.addMenu("")
        language_menu.setObjectName("menu.language")
        bind(language_menu, "setTitle", "menu.language")
        languages = QActionGroup(self)
        self.language_actions: dict[str, QAction] = {}
        for code in i18n.languages():
            action = QAction(AUTONYMS[code], self, checkable=True)  # autonyms: never translated
            action.setObjectName(f"language.{code}")
            action.triggered.connect(lambda checked=False, value=code: self.set_language(value))
            languages.addAction(action)
            language_menu.addAction(action)
            self.language_actions[code] = action
        self._action(view, "action.toggle_language", "Ctrl+Shift+U", self.toggle_language)
        theme_menu = view.addMenu("")
        theme_menu.setObjectName("menu.theme")
        bind(theme_menu, "setTitle", "menu.theme")
        group = QActionGroup(self)
        self.theme_actions: dict[str, QAction] = {}
        for name in theme.THEMES:
            action = QAction(self, checkable=True)
            action.setObjectName(f"theme.{name}")
            bind(action, "setText", f"theme.{name}")
            action.triggered.connect(lambda checked=False, value=name: self.set_theme(value))
            group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[name] = action
        self._action(view, "action.toggle_theme", "Ctrl+Shift+T", self.toggle_theme)
        log_action = self.log_dock.toggleViewAction()
        log_action.setObjectName("action.toggle_log")
        bind(log_action, "setText", "action.toggle_log")
        log_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        view.addAction(log_action)
        self.addAction(log_action)

        help_menu = self._menu("menu.help")
        self._action(help_menu, "action.shortcuts", "F1", self.show_shortcuts)
        self._action(help_menu, "action.about", None, self.show_about)

    def _name_for_assistive_technology(self) -> None:
        """Give every input, editor and view an accessible name (screen readers, UI tests)."""
        explicit = {
            self.bar.mode: "a11y.connection_mode",
            self.bar.url_box: "a11y.backend_url",
            self.bar.token: "a11y.api_token",
            self.bar.timeout: "a11y.timeout",
            self.navigation: "a11y.pages",
            self.log_view: "a11y.activity_log",
            self.progress.bar: "a11y.progress",
        }
        for widget, key in explicit.items():
            widget.setAccessibleName(tr(key))
        for page in self.pages.values():
            page.setAccessibleName(tr("a11y.page", page=page.title))
            for widget in page.findChildren(QWidget):
                if not isinstance(widget, ACCESSIBLE_KINDS) or widget.property("namedByPage"):
                    continue
                name = widget.toolTip() or getattr(widget, "placeholderText", lambda: "")()
                if not name and isinstance(widget, QAbstractItemView):
                    name = tr("a11y.view", page=page.title)
                if name:
                    widget.setAccessibleName(name.split(" (")[0])

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

    def save_document(self) -> None:
        """Ctrl+S: save the YAML document of the current page (topologies or scenarios)."""
        save = getattr(self.current_page, "save", None)
        if callable(save):
            save()

    def _page_changed(self, index: int) -> None:
        if index < 0:
            return
        page = self._page_order[index]
        self.settings.setValue("window/page", page.key)
        self.stack.setCurrentIndex(index)
        page.activated()

    @property
    def current_page(self) -> Page:
        return self._page_order[self.stack.currentIndex()]

    def minimum_size_for(self, page: Page) -> QSize:
        """The smallest window that shows ``page`` without scrolling: Qt's own layout answer
        with the page area held at the page's minimum (sidebar, header, menus, log dock and
        status bar at theirs)."""
        needed = page.minimumSizeHint().expandedTo(page.minimumSize())
        previous = self.stack.minimumSize()
        self.stack.setMinimumSize(needed)
        for layout in (self.centralWidget().layout(), self.layout()):
            layout.invalidate()
            layout.activate()
        size = self.minimumSizeHint().expandedTo(self.minimumSize())
        self.stack.setMinimumSize(previous)
        for layout in (self.centralWidget().layout(), self.layout()):
            layout.invalidate()
            layout.activate()
        return size

    # -- connection ---------------------------------------------------------------------------

    def _focus_url(self) -> None:
        if self.bar.mode.currentData() == "local":
            self.bar.mode.setCurrentIndex(self.bar.mode.findData("remote"))
        self.bar.url.setFocus()
        self.bar.url.selectAll()

    def toggle_connection(self) -> None:
        if self.session.state in {ConnectionState.DISCONNECTED, ConnectionState.UNAUTHORIZED}:
            self.connect_backend()
        else:
            # Disconnecting from the owned local backend stops it: its deployments are lost.
            count = len(self.session.deployments)
            if self.session.local_backend and count and not confirm(
                self,
                "connection.stop_local.confirm_title",
                Msg("connection.stop_local.confirm", count=count),
                "connection.stop_local.confirm_accept",
            ):
                return
            self.disconnect_backend()

    def connect_backend(self) -> None:
        session = self.session
        session.connection_kind = str(self.bar.mode.currentData())
        if session.local_backend:
            self._start_local_backend()
            return
        session.url = self.bar.url.text().strip()
        session.token = self.bar.token.text().strip()
        session.timeout = float(self.bar.timeout.value())
        try:
            session.client()
        except ValueError as error:
            problem = describe(error)
            session.set_state(ConnectionState.DISCONNECTED, problem)
            self.pages["dashboard"].banner.show_problem(problem)
            session.log(Msg("log.connect_failed", problem=problem), "error")
            return
        self.settings.setValue("connection/url", session.url)
        self.settings.setValue("connection/timeout", session.timeout)
        session.set_state(ConnectionState.CONNECTING)
        session.log(Msg("log.connecting", url=session.url))
        self.poll(initial=True)

    def _start_local_backend(self) -> None:
        if self._local_start_handle is not None or self._local_stop_handle is not None:
            self.session.log(Msg("log.local.busy"), "warning")
            return
        session = self.session
        session.connection_kind = "local"
        session.url = "http://127.0.0.1"
        session.token = ""
        session.timeout = float(self.bar.timeout.value())
        session.set_state(ConnectionState.CONNECTING)
        session.log(Msg("log.local.starting"))

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            return self.local_backend.start(cancelled=lambda: token.cancelled)

        self._local_start_handle = self.runner.submit(
            "local-start",
            work,
            on_success=self._local_started,
            on_failure=self._local_start_failed,
        )
        self._local_start_handle.released.connect(self._local_start_released)
        self._connection_changed()

    def _local_started(self, result: object) -> None:
        if self.session.state is not ConnectionState.CONNECTING or not isinstance(result, dict):
            self.local_backend.stop()
            return
        self.session.url = str(result["url"])
        self.session.token = str(result["token"])
        self.bar.log_button.setEnabled(True)
        self.backend_log_action.setEnabled(True)
        self.session.log(
            Msg("log.local.started", url=self.session.url, log=result.get("log_path"))
        )
        self.poll(initial=True)

    def _local_start_failed(self, error: BaseException) -> None:
        if self.session.state is ConnectionState.DISCONNECTED:
            return
        detail = error.problem.detail if isinstance(error, LocalBackendError) else str(error)
        problem = Problem(
            "problem.local_start",
            Msg.raw(detail),
            Msg("problem.local_start.hint", log=self.local_backend.log_path or "—"),
        )
        self.session.set_state(ConnectionState.DISCONNECTED, problem)
        self.pages["dashboard"].banner.show_problem(problem)
        self.session.log(problem, "error")

    def _local_start_released(self) -> None:
        self._local_start_handle = None
        self._connection_changed()

    def _connection_mode_changed(self) -> None:
        local = self.bar.mode.currentData() == "local"
        editable = self.session.state in {
            ConnectionState.DISCONNECTED,
            ConnectionState.UNAUTHORIZED,
        }
        self.bar.url_box.setEnabled(editable and not local)
        self.bar.token.setEnabled(editable and not local)
        for widget in self.bar.remote_actions:
            widget.setVisible(not local)
        for widget in self.bar.local_actions:
            widget.setVisible(local)
        self.bar.timeout.setEnabled(editable)
        self.settings.setValue("connection/kind", "local" if local else "remote")

    def open_backend_log(self) -> None:
        path = self.local_backend.log_path
        if path is not None and path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _remember_url(self, url: str) -> None:
        recent = [item for item in self.recent_urls() if item != url]
        recent = [url, *recent][:MAX_RECENT_URLS]
        self.settings.setValue("connection/recent", recent)
        self._fill_recent(recent, current=url)

    def recent_urls(self) -> list[str]:
        value = self.settings.value("connection/recent", [])
        if isinstance(value, str):  # QSettings returns a bare string for one-element lists
            value = [value]
        return [str(item) for item in value or [] if str(item).strip()]

    def _fill_recent(self, recent: list[str], *, current: str) -> None:
        box = self.bar.url_box
        box.blockSignals(True)
        box.clear()
        box.addItems(recent)
        self.bar.url.setText(current)
        self.bar.url.setCursorPosition(0)
        box.blockSignals(False)

    def disconnect_backend(self) -> None:
        self.poll_timer.stop()
        if self._poll_handle is not None:
            self._poll_handle.cancel()
            self._poll_handle = None
        was_local = self.session.local_backend
        self.session.set_state(ConnectionState.DISCONNECTED)
        self.session.log(Msg("log.disconnected"))
        if was_local:
            if self._local_start_handle is not None:
                self._local_start_handle.cancel()
            elif self.local_backend.process is not None:
                self._stop_local_backend()

    def _stop_local_backend(self) -> None:
        if self._local_stop_handle is not None:
            return
        log_path = self.local_backend.log_path
        self.session.log(Msg("log.local.stopping", log=log_path))
        self._local_stop_handle = self.runner.submit(
            "local-stop",
            lambda token, report: self.local_backend.stop(),
            on_success=lambda result: self.session.log(Msg("log.local.stopped", code=result)),
            on_failure=lambda error: self.session.log(
                Msg("log.local.stop_failed", kind=type(error).__name__), "error"
            ),
        )
        self._local_stop_handle.released.connect(self._local_stop_released)
        self._connection_changed()

    def _local_stop_released(self) -> None:
        self._local_stop_handle = None
        self._connection_changed()

    def refresh_now(self) -> None:
        if self.session.state in {ConnectionState.CONNECTED, ConnectionState.LOST}:
            self.poll()

    def poll(self, *, initial: bool = False) -> None:
        if self._poll_handle is not None:
            return
        if self.session.local_backend and not self.local_backend.running:
            self._local_backend_died()
            return
        client = self.session.client()
        known = sorted(self.session.known_topologies)
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
            missing: set[str] = set()

            def optional(feature: str, call):  # noqa: ANN001, ANN202
                """Older backends lack the v0.2.0 listing routes: degrade, never fail."""
                try:
                    return call()
                except ApiClientError as error:
                    if error.status in {404, 405}:
                        missing.add(feature)
                        return None
                    raise

            topologies = optional(FEATURE_TOPOLOGIES, client.topologies)
            if topologies is None:
                topologies = [{"topology_id": item, "deployed": True} for item in known]
            deployments: dict[str, dict[str, object]] = {}
            for item in topologies:
                if item.get("deployed"):
                    topology_id = str(item["topology_id"])
                    try:
                        deployments[topology_id] = client.deployment(topology_id)
                    except ApiClientError as error:
                        if error.status is None:
                            raise
                        # not (or no longer) deployed: the next poll settles it
            if FEATURE_TOPOLOGIES in missing:
                topologies = [
                    {"topology_id": item, "deployed": item in deployments} for item in known
                ]
            experiments = (
                optional(FEATURE_EXPERIMENTS, client.experiments) if include_experiments else None
            )
            return {
                "health": health,
                "latency": latency,
                "resources": resources,
                "topologies": topologies,
                "deployments": deployments,
                "experiments": experiments,
                "missing": missing,
            }

        self._poll_handle = self.runner.submit(
            "poll",
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
        capabilities = health.get("capabilities") or {}
        session.capabilities = capabilities if isinstance(capabilities, dict) else {}
        if session.local_backend and session.capabilities.get("fidelity") != "l0_only":
            self._poll_failed(
                LocalBackendError(
                    "owned backend did not advertise its L0-only boundary", "not_l0_only"
                ),
                initial,
            )
            return
        session.latency = result["latency"]  # type: ignore[assignment]
        if previous is not ConnectionState.CONNECTED:
            session.set_state(ConnectionState.CONNECTED)
            if previous is ConnectionState.LOST:
                session.log(Msg("log.reachable_again"), "info")
            else:
                session.log(
                    Msg("log.connected", url=session.url, version=session.backend_version)
                )
                self._remember_url(session.url)
                if session.backend_version != __version__:
                    session.log(
                        Msg(
                            "log.version_differs",
                            backend=session.backend_version,
                            client=__version__,
                        ),
                        "warning",
                    )
            self.pages["dashboard"].banner.clear()
        missing = result.get("missing") or set()
        assert isinstance(missing, set)
        if missing - session.unsupported:
            session.unsupported |= missing
            features = ", ".join(tr(f"feature.{item}") for item in sorted(session.unsupported))
            problem = Problem(
                "problem.older_backend",
                Msg("problem.older_backend.detail", version=session.backend_version,
                    features=features),
                Msg("problem.older_backend.hint", version=__version__),
            )
            session.log(problem, "warning")
            self.pages["dashboard"].banner.show_problem(problem, "warning")
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
        if session.local_backend and not self.local_backend.running:
            self._local_backend_died()
            return
        problem = describe(error, url=session.url, timeout=session.timeout)
        banner = self.pages["dashboard"].banner
        if isinstance(error, ApiClientError) and error.status == 401:
            self.poll_timer.stop()
            session.set_state(ConnectionState.UNAUTHORIZED, problem)
            banner.show_problem(problem)
            session.log(Msg("log.connection_refused", problem=problem), "error")
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
            session.log(Msg("log.connect_failed", problem=problem), "error")
            return
        if session.state is not ConnectionState.LOST:
            session.set_state(ConnectionState.LOST, problem)
            session.log(Msg("log.lost", problem=problem), "error")
            banner.show_problem(
                Problem(
                    "problem.lost",
                    Msg(
                        "problem.lost.detail",
                        detail=problem.detail,
                        seconds=LOST_POLL_INTERVAL_MS // 1000,
                    ),
                    problem.hint,
                )
            )
        self.poll_timer.setInterval(LOST_POLL_INTERVAL_MS)
        if not self.poll_timer.isActive():
            self.poll_timer.start()

    def _local_backend_died(self) -> None:
        self._poll_handle = None
        self.poll_timer.stop()
        code = self.local_backend.exit_code
        # Reap now: closes the kill-on-close job, so no helper process of the dead backend (e.g.
        # the Python child of a one-file launcher) outlives it, and releases the log file.
        self.local_backend.stop(timeout=1.0)
        problem = Problem(
            "problem.local_stopped",
            Msg("problem.local_stopped.detail", code=code),
            Msg("problem.local_stopped.hint", log=self.local_backend.log_path or "—"),
        )
        self.session.set_state(ConnectionState.DISCONNECTED, problem)
        self.pages["dashboard"].banner.show_problem(problem)
        self.session.log(problem, "error")

    def _connection_changed(self) -> None:
        state = self.session.state
        tone = STATE_TONES[state]
        self.bar.led.set_tone(tone)
        editable = state in {ConnectionState.DISCONNECTED, ConnectionState.UNAUTHORIZED}
        bind(
            self.bar.connect_button,
            "setText",
            "connection.connect" if editable else "connection.disconnect",
        )
        teardown = not editable and self.session.local_backend  # stops the owned backend
        role = "primary" if editable else "danger" if teardown else "secondary"
        self.bar.connect_button.setProperty("role", role)
        bind_tip(
            self.bar.connect_button,
            "connection.disconnect_local.tip" if teardown else "connection.connect.tip",
        )
        self.bar.connect_button.style().unpolish(self.bar.connect_button)
        self.bar.connect_button.style().polish(self.bar.connect_button)
        lifecycle_busy = self._local_start_handle is not None or self._local_stop_handle is not None
        self.bar.mode.setEnabled(editable and not lifecycle_busy)
        self.bar.connect_button.setEnabled(not lifecycle_busy)
        self._connection_mode_changed()
        self._update_status()
        self._update_actions()

    def _update_status(self) -> None:
        session = self.session
        state = session.state
        if state is ConnectionState.CONNECTED:
            prefix = tr("connection.local_label") if session.local_backend else tr(
                "connection.state.connected"
            )
            text = tr(
                "statusbar.connected", prefix=prefix, url=session.url,
                version=session.backend_version,
            )
            short = tr("connection.state.connected")  # the pill beside it names the fidelity
        elif state is ConnectionState.LOST and session.lost_since:
            since = datetime.fromtimestamp(session.lost_since).strftime("%H:%M:%S")
            text = tr("statusbar.lost", since=since)
            short = tr("connection.state.lost")
        elif state is ConnectionState.UNAUTHORIZED:
            text = tr("statusbar.unauthorized")
            short = tr("connection.state.unauthorized")
        elif state is ConnectionState.CONNECTING:
            text = tr("statusbar.connecting", url=session.url)
            short = tr("connection.state.connecting")
        else:
            text = short = tr("connection.state.disconnected")
        self.bar.state_label.setText(short)
        self.status_text.setText(f"{theme.STATUS_GLYPHS[STATE_TONES[state]]} {text}")
        fidelity = session.capabilities.get("fidelity") if session.connected else None
        self.bar.fidelity.setVisible(fidelity in {"l0_only", "linux_lab"})
        if fidelity in {"l0_only", "linux_lab"}:
            self.bar.fidelity.setText(tr(f"fidelity.badge.{fidelity}"))
            self.bar.fidelity.setToolTip(tr(f"fidelity.badge.{fidelity}.tip"))
        self.sidebar_footer.setText(
            tr("sidebar.connected", url=session.url) if session.connected
            else tr("sidebar.disconnected")
        )
        backend = f" ({tr('title.backend', version=session.backend_version)})" if (
            session.backend_version
        ) else ""
        where = (
            f" — {tr(f'connection.state.{state.value}')}: {session.url}{backend}"
            if state is not ConnectionState.DISCONNECTED
            else ""
        )
        self.setWindowTitle(f"polmon {__version__}{where}")

    def _update_actions(self) -> None:
        connected = self.session.connected
        busy = self.context.busy
        editable = self.session.state in {
            ConnectionState.DISCONNECTED,
            ConnectionState.UNAUTHORIZED,
        }
        bind(self.connect_action, "setText", "action.connect" if editable else "action.disconnect")
        self.refresh_action.setEnabled(connected or self.session.state is ConnectionState.LOST)
        for action in (self.deploy_action, self.destroy_action, self.reset_action, self.run_action):
            action.setEnabled(connected and not busy)
        self.cancel_action.setEnabled(busy)

    def _notified(self, tone: str, message: Msg | str) -> None:
        self._notice = (message, str(message))
        self.statusBar().showMessage(str(message), 15_000)
        if not self.isActiveWindow():
            QApplication.alert(self)  # task-bar flash / attention hint until focused

    # -- log ----------------------------------------------------------------------------------

    def _append_log(self, level: str, message: object) -> None:
        entry = (datetime.now().strftime("%H:%M:%S"), level, message)
        self._log_entries.append(entry)
        self.log_view.appendHtml(self._log_html(*entry))

    @staticmethod
    def _log_html(stamp: str, level: str, message: object) -> str:
        tone = {"error": "danger", "warning": "warning"}.get(level)
        glyph = {"error": "✕ ", "warning": "! "}.get(level, "")
        text = html.escape(glyph + str(message)).replace("\n", "<br>&nbsp;&nbsp;")
        body = f"<span style='color:{theme.hex_color(tone)}'>{text}</span>" if tone else text
        return f"<span style='color:{theme.hex_color('muted')}'>{stamp}</span> {body}"

    def _rerender_log(self) -> None:
        """Show the whole log again in the current language and theme colours."""
        view = self.log_view
        bar = view.verticalScrollBar()
        at_end = bar.value() == bar.maximum()
        view.setUpdatesEnabled(False)
        view.clear()
        for entry in self._log_entries:
            view.appendHtml(self._log_html(*entry))
        if at_end:
            bar.setValue(bar.maximum())
        view.setUpdatesEnabled(True)

    # -- theme --------------------------------------------------------------------------------

    def set_theme(self, preference: str) -> None:
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        effective = theme.apply(app, preference)
        self.settings.setValue("view/theme", preference)
        if preference in self.theme_actions:
            self.theme_actions[preference].setChecked(True)
        if preference == "system":
            self.session.log(
                Msg(
                    "log.theme_system",
                    theme=Msg("theme.system"),
                    effective=Msg(f"theme.{effective}"),
                )
            )
        else:
            self.session.log(Msg("log.theme", theme=Msg(f"theme.{preference}")))
        for widget in self.findChildren(QWidget):
            widget.update()
        self._rerender_log()  # tone colours of the new theme

    def toggle_theme(self) -> None:
        self.set_theme("light" if theme.current() == "dark" else "dark")

    # -- dialogs ------------------------------------------------------------------------------

    def show_shortcuts(self) -> None:
        rows = "".join(
            f"<tr><td style='padding:2px 16px 2px 0'><b>{html.escape(keys)}</b></td>"
            f"<td>{html.escape(tr(key))}</td></tr>"
            for keys, key in SHORTCUTS
        )
        box = QMessageBox(self)
        box.setObjectName("shortcutsDialog")
        box.setWindowTitle(tr("dialog.shortcuts.title"))
        box.setText(f"<table>{rows}</table>")
        box.addButton(tr("common.close"), QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def show_about(self) -> None:
        box = QMessageBox(self)
        box.setObjectName("aboutDialog")
        box.setWindowTitle(tr("dialog.about.title"))
        box.setText(  # i18n: allow (product names and the licence)
            f"<h3>polmon {__version__}</h3><p>{html.escape(tr('dialog.about.body'))}</p>"
            f"<p>Qt {qVersion()} · PySide6 {pyside_version} (Qt for Python, LGPLv3)</p>"
        )
        box.setIconPixmap(app_icon().pixmap(64, 64))
        box.addButton(tr("common.close"), QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    # -- persistence and shutdown -------------------------------------------------------------

    def _restore(self) -> None:
        settings = self.settings
        default_kind = "local" if sys.platform == "win32" else "remote"
        kind = str(settings.value("connection/kind", default_kind))
        restored_kind = kind if kind in {"local", "remote"} else default_kind
        self.bar.mode.setCurrentIndex(self.bar.mode.findData(restored_kind))
        self._fill_recent(
            self.recent_urls(), current=str(settings.value("connection/url", DEFAULT_URL))
        )
        try:
            self.bar.timeout.setValue(float(settings.value("connection/timeout", DEFAULT_TIMEOUT)))
        except (TypeError, ValueError):
            self.bar.timeout.setValue(DEFAULT_TIMEOUT)
        preference = str(settings.value("view/theme", "system"))
        if preference not in theme.THEMES:
            preference = "system"
        self.theme_actions[preference].setChecked(True)
        self.language_actions[i18n.language()].setChecked(True)
        geometry = settings.value("window/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        else:
            self.resize(1440, 900)
        state = settings.value("window/state")
        if isinstance(state, QByteArray):
            self.restoreState(state)
        else:  # a compact log (five lines) leaves the page area its room; the operator can grow it
            lines = self.log_view.fontMetrics().lineSpacing() * 5 + 2 * theme.SPACE["md"]
            self.resizeDocks([self.log_dock], [lines], Qt.Orientation.Vertical)
        self._connection_mode_changed()

    def shutdown(self, wait_ms: int = 2000) -> bool:
        """Stop timers, cancel work and wait briefly; returns False if workers remain."""
        self._closing = True
        self.poll_timer.stop()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.settings.sync()
        self.runner.close()
        self.local_backend.stop(timeout=max(2.0, wait_ms / 1000))
        return self.runner.wait(wait_ms)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self.context.busy and not self._closing and not confirm(
            self,
            "dialog.quit_busy.title",
            Msg("dialog.quit_busy.text", operation=self.context.operation_name),
            "dialog.quit_busy.accept",
        ):
            event.ignore()
            return
        self.clean_exit = self.shutdown()
        event.accept()

