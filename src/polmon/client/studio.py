"""Topology Studio document commands and Qt graph canvas."""

from __future__ import annotations

from copy import deepcopy
from ipaddress import IPv4Address, IPv4Network
from typing import Literal
from uuid import uuid4

import yaml
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QShortcut,
    QUndoCommand,
    QUndoStack,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from polmon.client.i18n import Msg, tr
from polmon.client.widgets import confirm
from polmon.core.yaml_loader import UniqueKeyLoader

type DeviceKey = tuple[Literal["node", "network"], str]
type LinkKey = tuple[str, str]  # Идентификаторы сегмента и узла; для прямой связи узел пуст.

LAB_NETWORKS = tuple(IPv4Network(f"192.168.{octet}.0/24") for octet in range(230, 241))


def _next_subnet(used: list[str], *, direct: bool = False) -> str:
    occupied = [IPv4Network(item) for item in used]
    candidates = (
        (subnet for block in reversed(LAB_NETWORKS) for subnet in block.subnets(new_prefix=30))
        if direct
        else iter(LAB_NETWORKS)
    )
    for candidate in candidates:
        if not any(candidate.overlaps(other) for other in occupied):
            return str(candidate)
    raise ValueError("studio.error.subnets")


def _next_host(subnet: str, used: list[str]) -> str:
    occupied = {IPv4Address(item) for item in used}
    for candidate in IPv4Network(subnet).hosts():
        if candidate not in occupied:
            return str(candidate)
    raise ValueError("studio.error.addresses")


def _next_mac(used: list[str]) -> str:
    occupied = {mac.lower().replace("-", ":") for mac in used}
    for value in range(1, 1 << 24):
        candidate = f"02:50:4f:{value >> 16:02x}:{(value >> 8) & 255:02x}:{value & 255:02x}"
        if candidate not in occupied:
            return candidate
    raise ValueError("studio.error.addresses")


def _slug(prefix: str, existing: set[str]) -> str:
    index = 1
    while f"{prefix}-{index}" in existing:
        index += 1
    return f"{prefix}-{index}"


def _free_port(node: dict) -> str:
    existing = {interface["id"] for interface in node["interfaces"]}
    index = 0
    while f"eth{index}" in existing:
        index += 1
    return f"eth{index}"


def _read_items(items: object) -> list[dict]:
    if not isinstance(items, list):
        raise ValueError("studio.error.yaml")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("studio.error.yaml")
        if item["id"] in seen:
            raise ValueError("studio.error.yaml")
        seen.add(item["id"])
        layout = item.get("layout")
        if layout is not None and (
            not isinstance(layout, dict)
            or any(
                type(layout.get(axis)) not in (float, int) or not -1e6 <= layout[axis] <= 1e6
                for axis in ("x", "y")
            )
        ):
            raise ValueError("studio.error.yaml")
    return items


class _DocumentCommand(QUndoCommand):
    def __init__(self, model: TopologyStudioModel, label: str, before: dict, after: dict) -> None:
        super().__init__(label)
        self.model, self.before, self.after = model, before, after

    def undo(self) -> None:
        self.model._replace(self.before)

    def redo(self) -> None:
        self.model._replace(self.after)


class TopologyStudioModel(QWidget):
    """Editable topology document with a genuine Qt undo command stack."""

    changed = Signal()

    def __init__(self, topology_id: str = "new-topology") -> None:
        super().__init__()
        self.undo_stack = QUndoStack(self)
        self.document = self.empty_document(topology_id)

    @staticmethod
    def empty_document(topology_id: str = "new-topology") -> dict:
        return {
            "id": topology_id,
            "address_space": "lab-profile",
            "networks": [],
            "nodes": [],
        }

    def _replace(self, document: dict) -> None:
        self.document = deepcopy(document)
        self.changed.emit()

    def _change(self, label: str, mutate) -> None:  # noqa: ANN001
        before, after = deepcopy(self.document), deepcopy(self.document)
        mutate(after)
        if before != after:
            self.undo_stack.push(_DocumentCommand(self, label, before, after))

    def load(self, source: str) -> None:
        raw = yaml.load(source, Loader=UniqueKeyLoader)
        if not isinstance(raw, dict):
            raise ValueError("studio.error.yaml")
        networks = _read_items(raw.get("networks"))
        network_ids = {item["id"] for item in networks}
        for network in networks:
            if not isinstance(network.get("ipv4_subnet"), str):
                raise ValueError("studio.error.yaml")
            IPv4Network(network["ipv4_subnet"])
        for node in _read_items(raw.get("nodes")):
            if node.get("class") not in ("l0", "l1", "l2"):
                raise ValueError("studio.error.yaml")
            node.setdefault("name", node["id"])
            node.setdefault("uuid", str(uuid4()))
            node.setdefault("interfaces", [])
            node.setdefault("services", [])
            if not isinstance(node["uuid"], str):
                raise ValueError("studio.error.yaml")
            for interface in _read_items(node["interfaces"]):
                if interface.get("network") not in network_ids or not isinstance(
                    interface.get("mac"), str
                ):
                    raise ValueError("studio.error.yaml")
                IPv4Address(interface.get("ipv4"))
        raw.setdefault("address_space", "lab-profile")
        self.document = raw
        self.undo_stack.clear()
        self.changed.emit()

    def source(self) -> str:
        return yaml.safe_dump(self.document, sort_keys=False, allow_unicode=True)

    def add_network(self, network_id: str | None = None, *, x: float = 0, y: float = 0) -> str:
        network = self._new_network(self.document, "hub", network_id=network_id)
        network["layout"] = {"x": float(x), "y": float(y)}
        self._change(
            tr("studio.command.add_network"),
            lambda document: document["networks"].append(network),
        )
        return network["id"]

    @staticmethod
    def _new_network(document: dict, kind: str, *, network_id: str | None = None) -> dict:
        networks = document["networks"]
        identifier = network_id or _slug(
            "hub" if kind == "hub" else "link", {item["id"] for item in networks}
        )
        return {
            "id": identifier,
            "kind": kind,
            "ipv4_subnet": _next_subnet(
                [item["ipv4_subnet"] for item in networks], direct=kind == "direct"
            ),
        }

    def add_node(
        self, node_class: str, *, x: float = 0, y: float = 0, name: str | None = None
    ) -> str:
        value = str(node_class)
        if value not in {"l0", "l1", "l2"}:
            raise ValueError("topology.node_class")
        existing = {item["id"] for item in self.document["nodes"]}
        identifier = _slug(value, existing)
        node = {
            "id": identifier,
            "name": name or identifier,
            "uuid": str(uuid4()),
            "class": value,
            "layout": {"x": float(x), "y": float(y)},
            "interfaces": [],
            "services": [],
        }
        self._change(tr("studio.command.add_node"), lambda document: document["nodes"].append(node))
        return identifier

    @staticmethod
    def _attach(document: dict, node_id: str, network_id: str, port: str | None) -> None:
        network = next(item for item in document["networks"] if item["id"] == network_id)
        node = next(item for item in document["nodes"] if item["id"] == node_id)
        if any(item["network"] == network_id for item in node["interfaces"]):
            raise ValueError("topology.link_duplicate")
        port = port or _free_port(node)
        if (node["class"] == "l0" and node["interfaces"]) or any(
            item["id"] == port for item in node["interfaces"]
        ):
            raise ValueError("studio.error.port_busy")
        used_ips = [
            interface["ipv4"]
            for item in document["nodes"]
            for interface in item.get("interfaces", [])
            if interface["network"] == network_id
        ]
        used_macs = [
            interface["mac"]
            for item in document["nodes"]
            for interface in item.get("interfaces", [])
        ]
        node["interfaces"].append(
            {
                "id": port,
                "network": network_id,
                "mac": _next_mac(used_macs),
                "ipv4": _next_host(network["ipv4_subnet"], used_ips),
            }
        )

    def connect(self, node_id: str, network_id: str, port: str | None = None) -> None:
        self._change(
            tr("studio.command.connect"),
            lambda document: self._attach(document, node_id, network_id, port),
        )

    def connect_devices(self, first: DeviceKey, second: DeviceKey, a: str, b: str) -> None:
        if first == second:
            raise ValueError("studio.error.same_device")
        if first[0] == "network" and second[0] == "network":
            raise ValueError("studio.error.hub_to_hub")
        if first[0] == "network":
            self.connect(second[1], first[1], b)
        elif second[0] == "network":
            self.connect(first[1], second[1], a)
        else:

            def mutate(document: dict) -> None:
                network = self._new_network(document, "direct")
                document["networks"].append(network)
                for device, port in ((first, a), (second, b)):
                    self._attach(document, device[1], network["id"], port)

            self._change(tr("studio.command.connect"), mutate)

    def port_label(self, key: DeviceKey) -> str | None:
        if key[0] == "node":
            node = next(item for item in self.document["nodes"] if item["id"] == key[1])
            if node["class"] == "l0" and node["interfaces"]:
                return None
            return _free_port(node)
        return tr("studio.free_hub_port")

    def rename(self, node_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("studio.error.name")
        folded = name.casefold()
        if any(
            item["id"] != node_id and str(item.get("name", item["id"])).casefold() == folded
            for item in self.document["nodes"]
        ):
            raise ValueError("topology.duplicate_node_names")

        def mutate(document: dict) -> None:
            next(item for item in document["nodes"] if item["id"] == node_id)["name"] = name

        self._change(tr("studio.command.rename"), mutate)

    def move(self, node_id: str, x: float, y: float, *, snap: bool = True) -> None:
        self.move_device(("node", node_id), x, y, snap=snap)

    def move_device(self, key: DeviceKey, x: float, y: float, *, snap: bool = True) -> None:
        if snap:
            x, y = round(x / 20) * 20, round(y / 20) * 20

        def mutate(document: dict) -> None:
            collection = "nodes" if key[0] == "node" else "networks"
            target = next((item for item in document[collection] if item["id"] == key[1]), None)
            if target is not None:
                target["layout"] = {"x": float(x), "y": float(y)}

        self._change(tr("studio.command.move"), mutate)

    def delete_nodes(self, node_ids: set[str]) -> None:
        self.delete({("node", node_id) for node_id in node_ids}, set())

    def delete(self, devices: set[DeviceKey], links: set[LinkKey]) -> None:
        def mutate(document: dict) -> None:
            nodes = {identifier for kind, identifier in devices if kind == "node"}
            networks = {identifier for kind, identifier in devices if kind == "network"}
            networks.update(network for network, node in links if not node)
            direct_segments = {
                network["id"] for network in document["networks"] if network.get("kind") == "direct"
            }
            networks.update(
                interface["network"]
                for node in document["nodes"]
                if node["id"] in nodes
                for interface in node["interfaces"]
                if interface["network"] in direct_segments
            )
            document["nodes"] = [node for node in document["nodes"] if node["id"] not in nodes]
            document["networks"] = [
                network for network in document["networks"] if network["id"] not in networks
            ]
            for node in document["nodes"]:
                node["interfaces"] = [
                    interface
                    for interface in node["interfaces"]
                    if interface["network"] not in networks
                    and (interface["network"], node["id"]) not in links
                ]

        self._change(tr("studio.command.delete"), mutate)

    def clear(self) -> None:
        def mutate(document: dict) -> None:
            document["nodes"].clear()
            document["networks"].clear()

        self._change(tr("studio.clear"), mutate)

    def duplicate(self, node_ids: set[str]) -> list[str]:
        created: list[str] = []
        for node_id in node_ids:
            original = next(
                (item for item in self.document["nodes"] if item["id"] == node_id), None
            )
            if original is None:
                continue
            created.append(
                self.add_node(
                    original["class"],
                    x=float(original.get("layout", {}).get("x", 0)) + 40,
                    y=float(original.get("layout", {}).get("y", 0)) + 40,
                )
            )
        return created

    def auto_layout(self) -> None:
        def mutate(document: dict) -> None:
            for index, node in enumerate(document["nodes"]):
                node.setdefault(
                    "layout", {"x": float((index % 4) * 180), "y": float((index // 4) * 120)}
                )

        self._change(tr("studio.command.auto_layout"), mutate)


class DeviceItem(QGraphicsRectItem):
    def __init__(self, key: DeviceKey, title: str, kind: str, moved) -> None:  # noqa: ANN001
        super().__init__(-78, -27, 156, 54)
        self.key = key
        self._moved = moved
        self.link_lines: list[LinkItem] = []
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.border = "#73c991" if key[0] == "network" else "#5ba7d1"
        self.setBrush(QColor("#24333e"))
        self.setPen(QPen(QColor(self.border), 2))
        self.setToolTip(f"{title}\n{kind}")
        label = QGraphicsSimpleTextItem(title, self)
        label.setText(
            QFontMetrics(label.font()).elidedText(title, Qt.TextElideMode.ElideRight, 139)
        )
        label.setBrush(QColor("white"))
        label.setPos(-70, -20)
        kind_label = QGraphicsSimpleTextItem(kind, self)
        kind_label.setBrush(QColor("#b7d4e6"))
        kind_label.setPos(-70, 2)

    def itemChange(self, change, value):  # noqa: ANN001, N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for line in self.link_lines:
                line.update_position()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        super().mouseReleaseEvent(event)
        self._moved()


class LinkItem(QGraphicsLineItem):
    def __init__(self, key: LinkKey, first: DeviceItem, second: DeviceItem) -> None:
        super().__init__()
        self.key = key
        self.first = first
        self.second = second
        first.link_lines.append(self)
        second.link_lines.append(self)
        self.setPen(QPen(QColor("#8ba0ad"), 2))
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.update_position()

    def update_position(self) -> None:
        a, b = self.first.pos(), self.second.pos()
        self.setLine(a.x(), a.y(), b.x(), b.y())

    def shape(self) -> QPainterPath:
        path = QPainterPath(self.line().p1())
        path.lineTo(self.line().p2())
        stroke = QPainterPathStroker()
        stroke.setWidth(12)
        return stroke.createStroke(path)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return super().boundingRect().adjusted(-6, -6, 6, 6)


class TopologyView(QGraphicsView):
    device_clicked = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.linking = False
        self.setBackgroundBrush(QColor("#1d2832"))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if self.linking and event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            while item is not None and not isinstance(item, DeviceItem):
                item = item.parentItem()
            self.device_clicked.emit(
                item.key if isinstance(item, DeviceItem) else None, event.globalPosition().toPoint()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current = self.transform().m11()
        target = max(0.05, min(4.0, current * factor))
        self.scale(target / current, target / current)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor("#34414d"), 0))
        step = 100 if self.transform().m11() < 0.4 else 20
        if self.transform().m11() < 0.15:
            return
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        points = [
            QPointF(x, y)
            for x in range(left, int(rect.right()), step)
            for y in range(top, int(rect.bottom()), step)
        ]
        painter.drawPoints(points)


class TopologyStudio(QWidget):
    source_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = TopologyStudioModel()
        self.scene = QGraphicsScene(self)
        self.view = TopologyView()
        self.view.setObjectName("topologyCanvas")
        self.view.setScene(self.scene)
        self.items: dict[DeviceKey, DeviceItem] = {}
        self.links: dict[LinkKey, LinkItem] = {}
        self.positions: dict[DeviceKey, QPointF] = {}
        self._start: tuple[DeviceKey, str] | None = None
        self._menu: QMenu | None = None
        self._loading = False
        self._hint_key = ""

        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.add_button = QPushButton()
        self.add_button.setObjectName("topologyAddDevice")
        add_menu = QMenu(self.add_button)
        self.actions = []
        for key, kind in (
            ("studio.palette.l0", "l0"),
            ("studio.palette.l1", "l1"),
            ("studio.palette.hub", "hub"),
        ):
            action = add_menu.addAction(tr(key))
            action.setObjectName(f"topologyAdd-{kind}")
            action.triggered.connect(lambda checked=False, value=kind: self._add(value))
            self.actions.append((action, key))
        self.add_button.setMenu(add_menu)
        tools.addWidget(self.add_button)
        self.link_button = QPushButton()
        self.link_button.setObjectName("topologyAddLink")
        self.link_button.setCheckable(True)
        self.link_button.toggled.connect(self._link_mode)
        tools.addWidget(self.link_button)
        self.translated = [(self.add_button, "studio.add"), (self.link_button, "studio.connect")]
        edit_button = QPushButton()
        edit_menu = QMenu(edit_button)
        for key, callback, signal in (
            ("studio.undo", self.model.undo_stack.undo, self.model.undo_stack.canUndoChanged),
            ("studio.redo", self.model.undo_stack.redo, self.model.undo_stack.canRedoChanged),
        ):
            action = edit_menu.addAction(tr(key), callback)
            action.setEnabled(False)
            signal.connect(action.setEnabled)
            self.actions.append((action, key))
        edit_menu.addSeparator()
        self.snap_action = edit_menu.addAction(tr("studio.snap"))
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        self.actions.append((self.snap_action, "studio.snap"))
        edit_button.setMenu(edit_menu)
        self.translated.append((edit_button, "studio.edit"))
        tools.addWidget(edit_button)
        for key, callback in (
            ("studio.fit", self.fit),
            ("studio.delete", self._delete),
        ):
            control = QPushButton(tr(key))
            control.clicked.connect(callback)
            tools.addWidget(control)
            self.translated.append((control, key))
            if key == "studio.delete":
                self.delete_button = control
                control.setObjectName("topologyDelete")
        tools.addStretch(1)
        self.clear_button = QPushButton()
        self.clear_button.setObjectName("topologyClear")
        self.clear_button.clicked.connect(self._clear)
        tools.addWidget(self.clear_button)
        self.translated.append((self.clear_button, "studio.clear"))
        root.addLayout(tools)
        self.hint = QLabel()
        self.hint.setObjectName("topologyHint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        root.addWidget(self.view, 1)

        self.inspector = QWidget()
        details = QHBoxLayout(self.inspector)
        details.setContentsMargins(0, 0, 0, 0)
        self.selected_label = QLabel()
        self.selected_label.setTextFormat(Qt.TextFormat.PlainText)
        details.addWidget(self.selected_label)
        self.name = QLineEdit()
        self.name.setMaxLength(64)
        details.addWidget(self.name, 1)
        self.copy_uuid = QPushButton()
        self.translated.append((self.copy_uuid, "studio.copy_uuid"))
        self.copy_uuid.clicked.connect(self._copy_uuid)
        details.addWidget(self.copy_uuid)
        root.addWidget(self.inspector)
        self.scene.selectionChanged.connect(self._selection)
        self.name.editingFinished.connect(self._rename)
        self.model.changed.connect(self._render)
        self.view.device_clicked.connect(self._choose_port)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.model.undo_stack.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.model.undo_stack.redo)
        shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.view, self._delete)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        duplicate = QShortcut(QKeySequence("Ctrl+D"), self.view, self._duplicate)
        duplicate.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.retranslate()
        self._render()

    def retranslate(self) -> None:
        for widget, key in self.translated:
            widget.setText(tr(key))
        for action, key in self.actions:
            action.setText(tr(key))
        self.name.setAccessibleName(tr("studio.name"))
        self._set_hint(self._hint_key)
        self._selection()

    def set_source(self, source: str) -> None:
        self.cancel_link()
        self._loading = True
        try:
            if source.strip():
                self.model.load(source)
            else:
                self.model.load(yaml.safe_dump(self.model.empty_document()))
        finally:
            self._loading = False

    def fit(self) -> None:
        if not self.items:
            self.view.resetTransform()
            self.view.centerOn(QPointF())
            return
        bounds = self.scene.itemsBoundingRect().adjusted(-55, -55, 55, 55)
        self.view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        scale = self.view.transform().m11()
        if scale > 1.35:
            self.view.scale(1.35 / scale, 1.35 / scale)
        self.view.centerOn(bounds.center())

    def _add(self, kind: str) -> None:
        self.cancel_link()
        center = self.view.mapToScene(self.view.viewport().rect().center())
        x, y = round(center.x() / 20) * 20, round(center.y() / 20) * 20
        occupied = [
            item.sceneBoundingRect().adjusted(-15, -15, 15, 15) for item in self.items.values()
        ]
        while any(area.intersects(QRectF(x - 78, y - 27, 156, 54)) for area in occupied):
            x += 180
            if x > center.x() + 540:
                x = round(center.x() / 20) * 20
                y += 100
        try:
            if kind == "hub":
                key = ("network", self.model.add_network(x=x, y=y))
            else:
                key = ("node", self.model.add_node(kind, x=x, y=y))
        except ValueError as error:
            self._show_error(error)
            return
        self.scene.clearSelection()
        self.items[key].setSelected(True)
        self.view.ensureVisible(self.items[key])

    def _render(self) -> None:
        selected_devices, selected_links = self._selected()
        self.scene.blockSignals(True)
        self.scene.clear()
        self.items.clear()
        self.links.clear()
        self.positions.clear()
        document = self.model.document

        def add(key: DeviceKey, title: str, kind: str, x: float, y: float) -> None:
            item = DeviceItem(key, title, kind, self._queue_move)
            item.setPos(x, y)
            self.scene.addItem(item)
            self.items[key] = item
            self.positions[key] = item.pos()
            item.setSelected(key in selected_devices)

        def link(key: LinkKey, a: DeviceKey, b: DeviceKey) -> None:
            line = LinkItem(key, self.items[a], self.items[b])
            self.scene.addItem(line)
            self.links[key] = line
            line.setSelected(key in selected_links)

        members: dict[str, list[str]] = {}
        for index, node in enumerate(document["nodes"]):
            layout = node.get("layout") or {"x": (index % 4) * 200, "y": (index // 4) * 120}
            key = ("node", node["id"])
            add(
                key,
                str(node.get("name") or node["id"]),
                str(node["class"]).upper(),
                float(layout["x"]),
                float(layout["y"]),
            )
            for interface in node["interfaces"]:
                members.setdefault(interface["network"], []).append(node["id"])
        bottom = max((position.y() for position in self.positions.values()), default=-150) + 150
        for index, network in enumerate(document["networks"]):
            identifier = network["id"]
            attached = members.get(identifier, [])
            if network.get("kind") == "direct" and len(attached) == 2:
                link((identifier, ""), ("node", attached[0]), ("node", attached[1]))
                continue
            key = ("network", identifier)
            layout = network.get("layout") or {
                "x": (index % 4) * 200,
                "y": bottom + (index // 4) * 120,
            }
            add(key, identifier, tr("studio.hub"), float(layout["x"]), float(layout["y"]))
            for member in attached:
                link((identifier, member), ("node", member), key)
        bounds = self.scene.itemsBoundingRect().united(QRectF(-450, -350, 900, 700))
        self.view.setSceneRect(bounds.adjusted(-500, -350, 500, 350))
        self.scene.blockSignals(False)
        self.clear_button.setEnabled(bool(self.items))
        self._selection()
        self._highlight()
        if not self._loading:
            self.source_changed.emit(self.model.source())

    def _selection(self) -> None:
        devices, links = self._selected()
        self.delete_button.setEnabled(bool(devices or links))
        self.inspector.setVisible(len(devices) + len(links) == 1)
        node_id = None
        if len(devices) == 1 and not links:
            kind, identifier = next(iter(devices))
            if kind == "node":
                node_id = identifier
                node = next(item for item in self.model.document["nodes"] if item["id"] == node_id)
                self.selected_label.setText(identifier)
                self.name.setText(str(node.get("name") or identifier))
            else:
                network = next(
                    item for item in self.model.document["networks"] if item["id"] == identifier
                )
                self.selected_label.setText(f"{identifier} · {network['ipv4_subnet']}")
        elif len(links) == 1 and not devices:
            network, member = next(iter(links))
            self.selected_label.setText(f"{network} · {member}" if member else network)
        self.name.setVisible(node_id is not None)
        self.copy_uuid.setVisible(node_id is not None)
        self.name.setProperty("topologyNode", node_id)

    def _rename(self) -> None:
        node_id = self.name.property("topologyNode")
        if not node_id:
            return
        try:
            self.model.rename(node_id, self.name.text())
        except ValueError as error:
            self._show_error(error)

    def _copy_uuid(self) -> None:
        node_id = self.name.property("topologyNode")
        if node_id:
            node = next(item for item in self.model.document["nodes"] if item["id"] == node_id)
            QApplication.clipboard().setText(node["uuid"])

    def _selected(self) -> tuple[set[DeviceKey], set[LinkKey]]:
        items = self.scene.selectedItems()
        return (
            {item.key for item in items if isinstance(item, DeviceItem)},
            {item.key for item in items if isinstance(item, LinkItem)},
        )

    def _delete(self) -> None:
        self.cancel_link()
        self.model.delete(*self._selected())

    def _duplicate(self) -> None:
        self.cancel_link()
        devices, _ = self._selected()
        self.model.duplicate({identifier for kind, identifier in devices if kind == "node"})

    def _clear(self) -> None:
        if confirm(
            self,
            "studio.clear",
            Msg("studio.clear_confirm"),
            "studio.clear",
        ):
            self.cancel_link()
            self.model.clear()
            self.fit()

    def _queue_move(self) -> None:
        QTimer.singleShot(0, self, self._commit_moves)

    def _commit_moves(self) -> None:
        moved = {
            key: item.pos() for key, item in self.items.items() if item.pos() != self.positions[key]
        }
        if moved:
            self.model.undo_stack.beginMacro(tr("studio.command.move"))
            try:
                for key, position in moved.items():
                    self.model.move_device(
                        key, position.x(), position.y(), snap=self.snap_action.isChecked()
                    )
            finally:
                self.model.undo_stack.endMacro()
            # При округлении координаты могут остаться прежними, не создавая команды.
            self._render()

    def _set_hint(self, key: str) -> None:
        self._hint_key = key
        self.hint.setVisible(bool(key))
        self.hint.setText(tr(key) if key else "")

    def _show_error(self, error: ValueError) -> None:
        key = {
            "topology.link_duplicate": "studio.error.duplicate_link",
            "topology.duplicate_node_names": "studio.error.duplicate_name",
        }.get(str(error), str(error))
        self._set_hint(key if key.startswith("studio.error.") else "studio.error.yaml")

    def cancel_link(self) -> bool:
        if not self.link_button.isChecked():
            return False
        self.link_button.setChecked(False)
        return True

    def _link_mode(self, enabled: bool) -> None:
        if self._menu is not None:
            self._menu.close()
        self._start = None
        self.view.linking = enabled
        self.view.viewport().setCursor(
            Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self._set_hint("studio.link_first" if enabled else "")
        self._highlight()

    def _highlight(self) -> None:
        if self._start and self._start[0] not in self.items:
            self._start = None
            self._set_hint("studio.link_first")
        for key, item in self.items.items():
            source = self._start and self._start[0] == key
            eligible = (
                self.view.linking
                and self.model.port_label(key) is not None
                and not (self._start and self._start[0][0] == key[0] == "network")
            )
            item.setPen(
                QPen(
                    QColor("#ffd07a" if source else "#b2f2b7" if eligible else item.border),
                    3 if source else 2,
                )
            )

    def _choose_port(self, device: DeviceKey | None, position) -> None:  # noqa: ANN001
        if device is None:
            self._set_hint("studio.link_second" if self._start else "studio.link_first")
            return
        if self._start is not None:
            if device == self._start[0]:
                self._set_hint("studio.error.same_device")
                return
            if device[0] == self._start[0][0] == "network":
                self._set_hint("studio.error.hub_to_hub")
                return
        port = self.model.port_label(device)
        if port is None:
            self._set_hint("studio.error.port_busy")
            return
        menu = QMenu(self)
        self._menu = menu
        menu.setObjectName("topologyPortMenu")
        menu.addAction(port, lambda: self._port_selected(device, port))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.destroyed.connect(lambda: setattr(self, "_menu", None))
        menu.popup(position)

    def _port_selected(self, device: DeviceKey, port: str) -> None:
        if self._start is None:
            self._start = device, port
            self._set_hint("studio.link_second")
            self._highlight()
            return
        first, source_port = self._start
        try:
            self.model.connect_devices(first, device, source_port, port)
        except ValueError as error:
            self._show_error(error)
        else:
            self._start = None
            self._set_hint("studio.link_first")
            self._highlight()
