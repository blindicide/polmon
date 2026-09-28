"""Topology Studio document commands and Qt graph canvas."""

from __future__ import annotations

from copy import deepcopy
from ipaddress import IPv4Address, IPv4Network
from uuid import uuid4

import yaml
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QUndoCommand,
    QUndoStack,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from polmon.client.i18n import tr

LAB_NETWORKS = tuple(IPv4Network(f"192.168.{octet}.0/24") for octet in range(230, 241))


def _next_subnet(used: list[str]) -> str:
    occupied = {IPv4Network(item) for item in used}
    return str(next(candidate for candidate in LAB_NETWORKS if candidate not in occupied))


def _next_host(subnet: str, used: list[str]) -> str:
    occupied = {IPv4Address(item) for item in used}
    return str(
        next(candidate for candidate in IPv4Network(subnet).hosts() if candidate not in occupied)
    )


def _next_mac(used: list[str]) -> str:
    occupied = set(used)
    for value in range(1, 1 << 24):
        candidate = f"02:50:4f:{value >> 16:02x}:{(value >> 8) & 255:02x}:{value & 255:02x}"
        if candidate not in occupied:
            return candidate
    raise ValueError("topology.mac_exhausted")


def _slug(prefix: str, existing: set[str]) -> str:
    index = 1
    while f"{prefix}-{index}" in existing:
        index += 1
    return f"{prefix}-{index}"


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
        self.document: dict = {
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
        raw = yaml.safe_load(source)
        if not isinstance(raw, dict):
            raise ValueError("topology document must be a mapping")
        if not isinstance(raw.get("networks"), list) or not isinstance(raw.get("nodes"), list):
            raise ValueError("topology document needs networks and nodes")
        for node in raw["nodes"]:
            node.setdefault("name", node["id"])
            node.setdefault("uuid", str(uuid4()))
            node.setdefault("interfaces", [])
            node.setdefault("services", [])
        raw.setdefault("address_space", "lab-profile")
        self.document = raw
        self.undo_stack.clear()
        self.changed.emit()

    def source(self) -> str:
        return yaml.safe_dump(self.document, sort_keys=False, allow_unicode=True)

    def add_network(self, network_id: str | None = None) -> str:
        existing = {item["id"] for item in self.document["networks"]}
        identifier = network_id or _slug("switch", existing)
        subnet = _next_subnet([item["ipv4_subnet"] for item in self.document["networks"]])
        self._change(
            tr("studio.command.add_network"),
            lambda document: document["networks"].append({"id": identifier, "ipv4_subnet": subnet}),
        )
        return identifier

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

    def connect(self, node_id: str, network_id: str) -> None:
        network = next(item for item in self.document["networks"] if item["id"] == network_id)
        node = next(item for item in self.document["nodes"] if item["id"] == node_id)
        if any(item["network"] == network_id for item in node.get("interfaces", [])):
            raise ValueError("topology.link_duplicate")
        used_ips = [
            interface["ipv4"]
            for item in self.document["nodes"]
            for interface in item.get("interfaces", [])
            if interface["network"] == network_id
        ]
        used_macs = [
            interface["mac"]
            for item in self.document["nodes"]
            for interface in item.get("interfaces", [])
        ]
        interface = {
            "id": f"eth{len(node.get('interfaces', []))}",
            "network": network_id,
            "mac": _next_mac(used_macs),
            "ipv4": _next_host(network["ipv4_subnet"], used_ips),
        }

        def mutate(document: dict) -> None:
            target = next(item for item in document["nodes"] if item["id"] == node_id)
            target.setdefault("interfaces", []).append(interface)

        self._change(tr("studio.command.connect"), mutate)

    def rename(self, node_id: str, name: str) -> None:
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
        if snap:
            x, y = round(x / 20) * 20, round(y / 20) * 20

        def mutate(document: dict) -> None:
            node = next(item for item in document["nodes"] if item["id"] == node_id)
            node["layout"] = {"x": float(x), "y": float(y)}

        self._change(tr("studio.command.move"), mutate)

    def delete_nodes(self, node_ids: set[str]) -> None:
        self._change(
            tr("studio.command.delete"),
            lambda document: document.__setitem__(
                "nodes", [item for item in document["nodes"] if item["id"] not in node_ids]
            ),
        )

    def duplicate(self, node_ids: set[str]) -> list[str]:
        created: list[str] = []
        for node_id in node_ids:
            original = next(item for item in self.document["nodes"] if item["id"] == node_id)
            created.append(
                self.add_node(
                    original["class"],
                    x=float(original.get("layout", {}).get("x", 0)) + 40,
                    y=float(original.get("layout", {}).get("y", 0)) + 40,
                    name=f"{original.get('name', node_id)} copy",
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
    def __init__(self, node: dict, moved) -> None:  # noqa: ANN001
        super().__init__(-55, -30, 110, 60)
        self.node_id = node["id"]
        self._moved = moved
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setBrush(QColor("#26384a"))
        self.setPen(QPen(QColor("#5ba7d1"), 2))
        label = QGraphicsSimpleTextItem(str(node.get("name") or node["id"]), self)
        label.setBrush(QColor("white"))
        label.setPos(-48, -18)
        kind = QGraphicsSimpleTextItem(str(node["class"]).upper(), self)
        kind.setBrush(QColor("#9fc7de"))
        kind.setPos(-48, 4)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        super().mouseReleaseEvent(event)
        self._moved(self.node_id, self.pos().x(), self.pos().y())


class TopologyView(QGraphicsView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setSceneRect(-5000, -5000, 10000, 10000)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        target = max(0.25, min(4.0, self.transform().m11() * factor))
        self.resetTransform()
        self.scale(target, target)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor("#34414d"), 0))
        left = int(rect.left()) - int(rect.left()) % 20
        top = int(rect.top()) - int(rect.top()) % 20
        points = [
            QPointF(x, y)
            for x in range(left, int(rect.right()), 20)
            for y in range(top, int(rect.bottom()), 20)
        ]
        painter.drawPoints(points)


class TopologyStudio(QWidget):
    """Visible palette/canvas/inspector surface backed by :class:`TopologyStudioModel`."""

    source_changed = Signal(str)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(360, 320)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = TopologyStudioModel()
        self.scene = QGraphicsScene(self)
        self.view = TopologyView()
        self.view.setObjectName("topologyCanvas")
        self.view.setScene(self.scene)
        self.snap = True
        self.items: dict[str, DeviceItem] = {}
        self.clipboard: set[str] = set()

        root = QVBoxLayout(self)
        tools = QGridLayout()
        self.translated: list[tuple[QWidget, str]] = []
        for key, callback in (
            ("studio.undo", self.model.undo_stack.undo),
            ("studio.redo", self.model.undo_stack.redo),
            (
                "studio.fit",
                lambda: self.view.fitInView(
                    self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio
                ),
            ),
            ("studio.actual_size", self.view.resetTransform),
            ("studio.zoom_selection", self._zoom_selection),
            ("studio.duplicate", self._duplicate),
            ("studio.delete", self._delete),
        ):
            control = QPushButton(tr(key))
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            control.clicked.connect(callback)
            index = len(self.translated)
            tools.addWidget(control, index // 4, index % 4)
            self.translated.append((control, key))
        self.snap_control = QCheckBox(tr("studio.snap"))
        self.snap_control.setChecked(True)
        self.snap_control.toggled.connect(lambda checked: setattr(self, "snap", checked))
        tools.addWidget(self.snap_control, 2, 0, 1, 2)
        self.translated.append((self.snap_control, "studio.snap"))
        root.addLayout(tools)
        splitter = QSplitter()
        palette = QListWidget()
        self.palette = palette
        palette.setObjectName("devicePalette")
        palette_items = (
            ("studio.palette.endpoints", "heading"),
            ("studio.palette.l0", "l0"),
            ("studio.palette.l1", "l1"),
            ("studio.palette.l2", "l2"),
            ("studio.palette.networks", "heading"),
            ("studio.palette.switch", "switch"),
            ("studio.palette.tools", "heading"),
            ("studio.palette.connection", "connection"),
        )
        self.palette_items = palette_items
        for key, kind in palette_items:
            palette.addItem(tr(key))
            palette.item(palette.count() - 1).setData(Qt.ItemDataRole.UserRole, kind)
        palette.itemDoubleClicked.connect(
            lambda item: self._palette(str(item.data(Qt.ItemDataRole.UserRole)))
        )
        splitter.addWidget(palette)
        palette.setMinimumWidth(0)
        splitter.addWidget(self.view)
        inspector = QWidget()
        form = QFormLayout(inspector)
        self.name = QLineEdit()
        self.name.setAccessibleName(tr("studio.name"))
        self.identifier = QLabel("—")
        self.uuid = QLineEdit()
        self.uuid.setReadOnly(True)
        self.uuid.setAccessibleName(tr("studio.uuid"))
        self.network = QComboBox()
        self.network.setAccessibleName(tr("studio.network"))
        connect = QPushButton(tr("studio.connect"))
        connect.clicked.connect(self._connect)
        copy_uuid = QPushButton(tr("studio.copy_uuid"))
        copy_uuid.clicked.connect(lambda: QApplication.clipboard().setText(self.uuid.text()))
        self.translated.extend([(copy_uuid, "studio.copy_uuid"), (connect, "studio.connect")])
        self.name_label = QLabel(tr("studio.name"))
        self.id_label = QLabel(tr("studio.id"))
        self.uuid_label = QLabel(tr("studio.uuid"))
        self.network_label = QLabel(tr("studio.network"))
        form.addRow(self.name_label, self.name)
        form.addRow(self.id_label, self.identifier)
        form.addRow(self.uuid_label, self.uuid)
        form.addRow("", copy_uuid)
        form.addRow(self.network_label, self.network)
        form.addRow("", connect)
        splitter.addWidget(inspector)
        inspector.setMinimumWidth(0)
        splitter.setSizes([170, 650, 260])
        root.addWidget(splitter, 1)
        self.scene.selectionChanged.connect(self._selection)
        self.name.editingFinished.connect(self._rename)
        self.model.changed.connect(self._render)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.model.undo_stack.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.model.undo_stack.redo)
        QShortcut(QKeySequence.StandardKey.Copy, self, self._copy)
        QShortcut(QKeySequence.StandardKey.Paste, self, self._paste)
        QShortcut(QKeySequence("Ctrl+D"), self, self._duplicate)
        QShortcut(QKeySequence.StandardKey.Delete, self, self._delete)

    def retranslate(self) -> None:
        for widget, key in self.translated:
            widget.setText(tr(key))
        for label, key in (
            (self.name_label, "studio.name"),
            (self.id_label, "studio.id"),
            (self.uuid_label, "studio.uuid"),
            (self.network_label, "studio.network"),
        ):
            label.setText(tr(key))
        self.name.setAccessibleName(tr("studio.name"))
        self.uuid.setAccessibleName(tr("studio.uuid"))
        self.network.setAccessibleName(tr("studio.network"))
        for index, (key, _) in enumerate(self.palette_items):
            self.palette.item(index).setText(tr(key))

    def set_source(self, source: str) -> None:
        self.model.load(source)

    def _palette(self, kind: str) -> None:
        if kind == "l0":
            self.model.add_node("l0")
        elif kind == "l1":
            self.model.add_node("l1")
        elif kind == "l2":
            self.model.add_node("l2")
        elif kind == "switch":
            self.model.add_network()

    def _render(self) -> None:
        self.scene.clear()
        self.items = {}
        networks = {item["id"]: item for item in self.model.document["networks"]}
        network_positions = {
            identifier: QPointF(100 + index * 180, 260) for index, identifier in enumerate(networks)
        }
        for identifier, position in network_positions.items():
            item = self.scene.addEllipse(-35, -20, 70, 40, QPen(QColor("#73c991"), 2))
            item.setPos(position)
            label = self.scene.addSimpleText(identifier)
            label.setPos(position + QPointF(-30, -8))
        for index, node in enumerate(self.model.document["nodes"]):
            item = DeviceItem(
                node,
                lambda node_id, x, y: self.model.move(node_id, x, y, snap=self.snap),
            )
            layout = node.get("layout") or {"x": (index % 4) * 180, "y": (index // 4) * 120}
            item.setPos(float(layout["x"]), float(layout["y"]))
            self.scene.addItem(item)
            self.items[node["id"]] = item
            for interface in node.get("interfaces", []):
                target = network_positions.get(interface["network"])
                if target is not None:
                    line = QGraphicsLineItem(item.pos().x(), item.pos().y(), target.x(), target.y())
                    line.setPen(QPen(QColor("#7f8c98"), 2))
                    line.setZValue(-1)
                    self.scene.addItem(line)
        current = self.network.currentData()
        self.network.clear()
        for identifier in networks:
            self.network.addItem(identifier, identifier)
        if current is not None:
            self.network.setCurrentIndex(self.network.findData(current))
        self.source_changed.emit(self.model.source())

    def _selection(self) -> None:
        selected = [item for item in self.scene.selectedItems() if isinstance(item, DeviceItem)]
        if not selected:
            self.identifier.setText("—")
            self.uuid.clear()
            return
        node = next(
            item for item in self.model.document["nodes"] if item["id"] == selected[0].node_id
        )
        self.identifier.setText(node["id"])
        self.name.setText(str(node.get("name") or node["id"]))
        self.uuid.setText(str(node["uuid"]))

    def _rename(self) -> None:
        if self.identifier.text() != "—":
            self.model.rename(self.identifier.text(), self.name.text())

    def _selected_ids(self) -> set[str]:
        return {item.node_id for item in self.scene.selectedItems() if isinstance(item, DeviceItem)}

    def _delete(self) -> None:
        self.model.delete_nodes(self._selected_ids())

    def _duplicate(self) -> None:
        self.model.duplicate(self._selected_ids())

    def _copy(self) -> None:
        self.clipboard = self._selected_ids()

    def _paste(self) -> None:
        self.model.duplicate(self.clipboard)

    def _zoom_selection(self) -> None:
        selected = self.scene.selectedItems()
        if selected:
            bounds = selected[0].sceneBoundingRect()
            for item in selected[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.view.fitInView(
                bounds.adjusted(-30, -30, 30, 30), Qt.AspectRatioMode.KeepAspectRatio
            )

    def _connect(self) -> None:
        selected = self._selected_ids()
        network = self.network.currentData()
        if len(selected) == 1 and isinstance(network, str):
            self.model.connect(next(iter(selected)), network)
