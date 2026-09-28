"""Interactive SSH console page backed exclusively by the authenticated HTTP API."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from polmon.client.i18n import Msg, tr
from polmon.client.pages import Context, Page
from polmon.client.vnc import VncViewer
from polmon.client.widgets import Card, button, monospace_font, primary_button

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
BASIC_COMMANDS = (
    "hostname",
    "cat /etc/hostname",
    "ip -o -4 addr",
    "ip route",
    "ip neigh",
    "arp -n",
    "ping -c 4 192.168.230.1",
    "ss -tlnp",  # i18n: allow - literal argv shown in the command palette
    "netstat -tlnp",  # i18n: allow - literal argv shown in the command palette
    "ps",
    "uptime",
    "nc -z 192.168.230.1 22",
)


class HistoryInput(QLineEdit):
    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []
        self.position = 0

    def remember(self, command: str) -> None:
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)
            self.history = self.history[-200:]
        self.position = len(self.history)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down} and self.history:
            delta = -1 if event.key() == Qt.Key.Key_Up else 1
            self.position = max(0, min(len(self.history), self.position + delta))
            self.setText(self.history[self.position] if self.position < len(self.history) else "")
            return
        super().keyPressEvent(event)


class ConsoleTab(QWidget):
    def __init__(self, topology_id: str, node: dict[str, object]) -> None:
        super().__init__()
        self.topology_id = topology_id
        self.node_id = str(node["id"])
        self.session_id = ""
        self.cursor = 0
        layout = QVBoxLayout(self)
        identity = QLabel(
            tr(
                "console.identity",
                name=node.get("name") or node["id"],
                id=node["id"],
                uuid=node.get("uuid") or "—",
            )
        )
        identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(identity)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(monospace_font())
        self.output.setMaximumBlockCount(10_000)
        self.output.setAccessibleName(tr("console.output"))
        layout.addWidget(self.output, 1)
        row = QHBoxLayout()
        self.input = HistoryInput()
        self.input.setAccessibleName(tr("console.input"))
        self.commands = QComboBox()
        self.commands.setEditable(False)
        self.commands.setAccessibleName(tr("console.basic_commands"))
        self.commands.addItems(BASIC_COMMANDS)
        self.commands.activated.connect(lambda: self.input.setText(self.commands.currentText()))
        row.addWidget(self.commands)
        row.addWidget(self.input, 1)
        layout.addLayout(row)


class ConsolePage(Page):
    key = "console"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.node_documents: dict[str, dict[str, object]] = {}
        self._polling = False
        self.vnc_windows: list[VncViewer] = []
        controls = Card("console.target", name="consoleTarget")
        row = QHBoxLayout()
        self.topology = QComboBox()
        self.topology.setAccessibleName(tr("console.topology"))
        self.node = QComboBox()
        self.node.setAccessibleName(tr("console.node"))
        self.open_button = primary_button("console.open", name="openConsole")
        self.interrupt_button = button("console.interrupt", "quiet", name="interruptConsole")
        self.clear_button = button("console.clear", "quiet", name="clearConsole")
        self.close_button = button("console.close", "quiet", name="closeConsole")
        self.vnc_button = button("console.vnc", "quiet", name="vncButton")
        for widget in (
            self.topology,
            self.node,
            self.open_button,
            self.interrupt_button,
            self.clear_button,
            self.close_button,
            self.vnc_button,
        ):
            row.addWidget(widget)
        row.addStretch(1)
        controls.body.addLayout(row)
        self.root.addWidget(controls)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("consoleTabs")
        self.root.addWidget(self.tabs, 1)

        self.topology.currentIndexChanged.connect(self._fetch_topology)
        self.open_button.clicked.connect(self.open_session)
        self.interrupt_button.clicked.connect(lambda: self.send("\x03"))
        self.clear_button.clicked.connect(self.clear)
        self.close_button.clicked.connect(self.close_session)
        self.vnc_button.clicked.connect(self.open_vnc)
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.session.deployments_changed.connect(self._refresh_targets)
        self._refresh_targets()

    def _refresh_targets(self) -> None:
        current = self.topology.currentData()
        self.topology.clear()
        for topology_id in sorted(self.session.deployments):
            self.topology.addItem(topology_id, topology_id)
        if current is not None:
            self.topology.setCurrentIndex(self.topology.findData(current))
        self.refresh_actions()

    def _fetch_topology(self) -> None:
        topology_id = self.topology.currentData()
        if not isinstance(topology_id, str) or not self.session.connected:
            self.node.clear()
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.fetch_topology", topology=topology_id),
            lambda token, report: client.topology(topology_id),
            on_success=lambda result: self._set_nodes(topology_id, result),
            banner=self.banner,
            quiet=True,
        )

    def _set_nodes(self, topology_id: str, result: object) -> None:
        if not isinstance(result, dict) or topology_id != self.topology.currentData():
            return
        topology = result.get("topology")
        if not isinstance(topology, dict):
            return
        nodes = topology.get("nodes")
        if not isinstance(nodes, list):
            return
        self.node.clear()
        self.node_documents = {}
        for raw in nodes:
            if not isinstance(raw, dict):
                continue
            node_id = str(raw.get("id"))
            self.node_documents[node_id] = raw
            self.node.addItem(str(raw.get("name") or node_id), node_id)
        self.refresh_actions()

    def current_tab(self) -> ConsoleTab | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, ConsoleTab) else None

    def open_session(self) -> None:
        topology_id, node_id = self.topology.currentData(), self.node.currentData()
        if not isinstance(topology_id, str) or not isinstance(node_id, str):
            return
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if (
                isinstance(tab, ConsoleTab)
                and tab.topology_id == topology_id
                and tab.node_id == node_id
            ):
                self.tabs.setCurrentIndex(index)
                return
        node = self.node_documents[node_id]
        tab = ConsoleTab(topology_id, node)
        tab.input.returnPressed.connect(self.submit)
        self.tabs.addTab(tab, str(node.get("name") or node_id))
        self.tabs.setCurrentWidget(tab)
        client = self.session.client()
        self.context.run(
            Msg("console.opening", node=node.get("name") or node_id),
            lambda token, report: client.console_session_create(topology_id, node_id),
            on_success=lambda result: self._opened(tab, result),
            banner=self.banner,
        )

    def _opened(self, tab: ConsoleTab, result: object) -> None:
        if isinstance(result, dict):
            tab.session_id = str(result.get("session_id") or "")
            tab.output.appendPlainText(tr("console.connected"))
        self.refresh_actions()

    def submit(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        command = tab.input.text().strip()
        if command:
            tab.input.remember(command)
            tab.input.clear()
            self.send(command + "\n")

    def send(self, data: str) -> None:
        tab = self.current_tab()
        if tab is None or not tab.session_id:
            return
        client = self.session.client()
        self.context.run(
            Msg("console.sending"),
            lambda token, report: client.console_input(
                tab.topology_id, tab.node_id, tab.session_id, data
            ),
            on_success=lambda result: self._show_vnc(result),
            banner=self.banner,
            quiet=True,
        )

    def _show_vnc(self, result: object) -> None:
        if not isinstance(result, dict) or not isinstance(result.get("relay_path"), str):
            return
        client = self.session.client()
        viewer = VncViewer(client.console_vnc_url(result["relay_path"]), client.token)
        viewer.setWindowTitle(tr("console.vnc_title"))
        viewer.resize(1024, 768)
        viewer.show()
        self.vnc_windows.append(viewer)

    def poll(self) -> None:
        tab = self.current_tab()
        if self._polling or tab is None or not tab.session_id or not self.session.connected:
            return
        self._polling = True
        client = self.session.client()
        handle = self.context.run(
            Msg("console.following"),
            lambda token, report: client.console_session(
                tab.topology_id, tab.node_id, tab.session_id, tab.cursor
            ),
            on_success=lambda result: self._polled(tab, result),
            on_failure=lambda error: self._poll_done(),
            banner=None,
            quiet=True,
        )
        if handle is None:
            self._polling = False

    def _polled(self, tab: ConsoleTab, result: object) -> None:
        if isinstance(result, dict):
            output = ANSI.sub("", str(result.get("output") or "")).replace("\r", "")
            if output:
                tab.output.moveCursor(QTextCursor.MoveOperation.End)
                tab.output.insertPlainText(output)
            tab.cursor = int(result.get("cursor") or tab.cursor)
        self._poll_done()

    def _poll_done(self) -> None:
        self._polling = False

    def clear(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.output.clear()

    def close_session(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        index = self.tabs.indexOf(tab)
        if tab.session_id:
            client = self.session.client()
            self.context.run(
                Msg("console.closing"),
                lambda token, report: client.console_session_delete(
                    tab.topology_id, tab.node_id, tab.session_id
                ),
                on_success=lambda result: None,
                banner=self.banner,
                quiet=True,
            )
        self.tabs.removeTab(index)
        tab.deleteLater()
        self.refresh_actions()

    def open_vnc(self) -> None:
        topology_id, node_id = self.topology.currentData(), self.node.currentData()
        if not isinstance(topology_id, str) or not isinstance(node_id, str):
            return
        client = self.session.client()
        self.context.run(
            Msg("console.vnc_opening"),
            lambda token, report: client.console_vnc(topology_id, node_id),
            on_success=lambda result: None,
            banner=self.banner,
        )

    def refresh_actions(self) -> None:
        connected = self.session.connected
        selected = self.topology.currentData() is not None and self.node.currentData() is not None
        active = self.current_tab() is not None
        self.open_button.setEnabled(connected and selected)
        self.interrupt_button.setEnabled(connected and active)
        self.clear_button.setEnabled(active)
        self.close_button.setEnabled(active)
        self.vnc_button.setEnabled(connected and selected)

    def activated(self, argument: object = None) -> None:
        del argument
        self._refresh_targets()
