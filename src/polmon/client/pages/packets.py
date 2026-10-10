"""One-shot Ethernet frame editor for an isolated pair of deployed L1 namespaces."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPlainTextEdit, QWidget

from polmon.client.i18n import Msg, tr
from polmon.client.pages import Context, Page
from polmon.client.widgets import Card, label, monospace_font, primary_button


class PacketsPage(Page):
    key = "packets"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.last_result: dict[str, object] | None = None
        targets = Card("packet.target", name="packetTarget")
        row = QHBoxLayout()
        self.topology = QComboBox()
        self.node = QComboBox()
        self.interface = QComboBox()
        for widget in (self.topology, self.node, self.interface):
            row.addWidget(widget)
        targets.body.addLayout(row)
        self.root.addWidget(targets)

        editor = Card("packet.editor", hint="packet.hex_hint", name="packetEditor")
        self.frame = QPlainTextEdit()
        self.frame.setObjectName("packetHex")
        self.frame.setFont(monospace_font())
        self.frame.setMaximumBlockCount(200)
        editor.body.addWidget(self.frame)
        self.root.addWidget(editor, 1)

        self.send_button = primary_button("packet.send", name="sendPacket")
        self.root.addWidget(self.send_button)
        self.result = label("packet.ready", name="packetResult", wrap=True)
        self.root.addWidget(self.result)

        self.topology.currentIndexChanged.connect(self._load_nodes)
        self.node.currentIndexChanged.connect(self._load_interfaces)
        self.send_button.clicked.connect(self.send)
        self.frame.textChanged.connect(self.refresh_actions)
        self.session.deployments_changed.connect(self._refresh_targets)
        self.retranslate()
        self.refresh_actions()

    def retranslate(self) -> None:
        self.topology.setAccessibleName(tr("packet.topology"))
        self.node.setAccessibleName(tr("packet.node"))
        self.interface.setAccessibleName(tr("packet.interface"))
        self.frame.setAccessibleName(tr("packet.editor"))
        self.frame.setPlaceholderText(tr("packet.placeholder"))
        self._render_result()

    def activated(self, argument: object = None) -> None:
        del argument
        self._refresh_targets()

    def _refresh_targets(self) -> None:
        selected = self.topology.currentData()
        self.topology.blockSignals(True)
        self.topology.clear()
        for topology_id, deployment in sorted(self.session.deployments.items()):
            details = deployment.get("details")
            if isinstance(details, dict) and details.get("hostless_pair") is True:
                self.topology.addItem(topology_id, topology_id)
        index = self.topology.findData(selected)
        if index >= 0:
            self.topology.setCurrentIndex(index)
        self.topology.blockSignals(False)
        self._load_nodes()

    def _load_nodes(self) -> None:
        topology_id = self.topology.currentData()
        self.node.clear()
        self.interface.clear()
        self.refresh_actions()
        if not isinstance(topology_id, str) or not self.session.connected:
            return
        client = self.session.client()
        self.context.run(
            Msg("packet.loading"),
            lambda token, report: client.topology(topology_id),
            on_success=self._show_nodes,
            banner=self.banner,
            quiet=True,
        )

    def _show_nodes(self, result: object) -> None:
        topology = result.get("topology") if isinstance(result, dict) else None
        nodes = topology.get("nodes") if isinstance(topology, dict) else None
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if isinstance(node, dict) and node.get("class") == "l1":
                self.node.addItem(str(node.get("name") or node["id"]), node)
        self._load_interfaces()

    def _load_interfaces(self) -> None:
        node = self.node.currentData()
        self.interface.clear()
        if isinstance(node, dict):
            for item in node.get("interfaces", []):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    self.interface.addItem(item["id"], item["id"])
        self.refresh_actions()

    def refresh_actions(self) -> None:
        self.send_button.setEnabled(
            self.session.connected
            and not self.context.busy
            and isinstance(self.topology.currentData(), str)
            and isinstance(self.node.currentData(), dict)
            and isinstance(self.interface.currentData(), str)
            and bool(self.frame.toPlainText().strip())
        )

    def send(self) -> None:
        topology_id = self.topology.currentData()
        node = self.node.currentData()
        interface_id = self.interface.currentData()
        if (
            not isinstance(topology_id, str)
            or not isinstance(node, dict)
            or not isinstance(interface_id, str)
        ):
            return
        node_id = str(node["id"])
        frame_hex = self.frame.toPlainText()
        client = self.session.client()
        self.context.run(
            Msg("packet.sending"),
            lambda token, report: client.send_packet(topology_id, node_id, interface_id, frame_hex),
            on_success=self._sent,
            banner=self.banner,
            operation=True,
            cancellable=False,
            kind="packet",
        )

    def _sent(self, result: object) -> None:
        if isinstance(result, dict):
            self.last_result = result
            self._render_result()
        self.refresh_actions()

    def _render_result(self) -> None:
        if self.last_result is None:
            self.result.setText(tr("packet.ready"))
        elif self.last_result.get("state") == "sent":
            self.result.setText(
                tr(
                    "packet.sent",
                    operation_id=self.last_result.get("operation_id", ""),
                    count=self.last_result.get("byte_count", 0),
                    interface=self.last_result.get("interface", ""),
                )
            )
        elif self.last_result.get("state") == "refused":
            self.result.setText(
                tr(
                    "packet.refused",
                    operation_id=self.last_result.get("operation_id", ""),
                    code=self.last_result.get("message_code", ""),
                )
            )
        else:
            self.result.setText(
                tr(
                    "packet.error",
                    operation_id=self.last_result.get("operation_id", ""),
                    code=self.last_result.get("message_code", ""),
                )
            )
