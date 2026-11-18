from uuid import UUID

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from polmon.client.i18n import tr
from polmon.client.studio import TopologyStudio, TopologyStudioModel
from polmon.topology import dump_topology, parse_topology


def test_studio_creates_connects_moves_and_round_trips(qtbot) -> None:
    model = TopologyStudioModel("operator-lab")
    qtbot.addWidget(model)
    network_id = model.add_network()
    first = model.add_node("l0", x=13, y=27, name="Front desk")
    second = model.add_node("l1", x=210, y=75, name="Service host")
    model.connect(first, network_id)
    model.connect(second, network_id)
    model.move(first, 53, 68)

    topology = parse_topology(model.source())
    assert topology.id == "operator-lab"
    assert [node.name for node in topology.nodes] == ["Front desk", "Service host"]
    assert topology.nodes[0].layout.model_dump() == {"x": 60.0, "y": 60.0}
    assert len({item.mac for node in topology.nodes for item in node.interfaces}) == 2
    assert len({item.ipv4 for node in topology.nodes for item in node.interfaces}) == 2
    assert all(UUID(str(node.uuid)).version == 4 for node in topology.nodes)


def test_studio_undo_redo_rename_duplicate_and_delete(qtbot) -> None:
    model = TopologyStudioModel()
    qtbot.addWidget(model)
    node = model.add_node("l0")
    model.rename(node, "Reception")
    assert model.document["nodes"][0]["name"] == "Reception"
    model.undo_stack.undo()
    assert model.document["nodes"][0]["name"] == node
    model.undo_stack.redo()
    copied = model.duplicate({node})
    assert len(copied) == 1 and len(model.document["nodes"]) == 2
    model.delete_nodes(set(copied))
    assert [item["id"] for item in model.document["nodes"]] == [node]
    model.undo_stack.undo()
    assert len(model.document["nodes"]) == 2


def test_studio_rejects_duplicate_names_and_links(qtbot) -> None:
    model = TopologyStudioModel()
    qtbot.addWidget(model)
    network = model.add_network()
    first = model.add_node("l0", name="Alpha")
    second = model.add_node("l0", name="Beta")
    with pytest.raises(ValueError, match="duplicate_node_names"):
        model.rename(second, "alpha")
    model.connect(first, network)
    with pytest.raises(ValueError, match="link_duplicate"):
        model.connect(first, network)


def _choose_port(qtbot, studio, device, label):
    view = studio.view
    point = view.mapFromScene(studio.items[device].scenePos())
    assert view.viewport().rect().contains(point)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    menu = studio.findChild(QMenu, "topologyPortMenu")
    assert menu is not None and menu.isVisible()
    port = menu.actions()[0]
    assert port.text() == label
    qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(port).center())
    qtbot.waitUntil(lambda: studio.findChild(QMenu, "topologyPortMenu") is None)


def test_canvas_two_click_links_and_visible_removable_hub(qtbot) -> None:
    studio = TopologyStudio()
    qtbot.addWidget(studio)
    studio.resize(1100, 700)
    studio.show()
    for kind in ("l1", "l1", "l0", "hub"):
        studio.add_button.menu().findChild(QAction, f"topologyAdd-{kind}").trigger()
    studio.fit()
    first, second, third = ("node", "l1-1"), ("node", "l1-2"), ("node", "l0-1")
    hub = ("network", "hub-1")
    assert len(studio.items) == 4
    assert studio.items[hub].isVisible()

    qtbot.mouseClick(studio.link_button, Qt.MouseButton.LeftButton)
    _choose_port(qtbot, studio, first, "eth0")
    _choose_port(qtbot, studio, second, "eth0")
    assert ("link-1", "") in studio.links
    _choose_port(qtbot, studio, third, "eth0")
    _choose_port(qtbot, studio, hub, tr("studio.free_hub_port"))
    assert ("hub-1", "l0-1") in studio.links
    _choose_port(qtbot, studio, first, "eth1")
    _choose_port(qtbot, studio, hub, tr("studio.free_hub_port"))
    topology = parse_topology(studio.model.source())
    networks = {network.id: network.kind for network in topology.networks}
    assert networks == {"hub-1": "hub", "link-1": "direct"}
    assert len(studio.links) == 3
    assert studio.cancel_link()

    studio.scene.clearSelection()
    studio.items[hub].setSelected(True)
    qtbot.mouseClick(studio.delete_button, Qt.MouseButton.LeftButton)
    assert hub not in studio.items
    assert set(studio.links) == {("link-1", "")}
    assert all(
        interface.network != "hub-1"
        for node in parse_topology(studio.model.source()).nodes
        for interface in node.interfaces
    )
    studio.model.undo_stack.undo()
    assert hub in studio.items and len(studio.links) == 3
    round_trip = TopologyStudioModel()
    qtbot.addWidget(round_trip)
    round_trip.load(dump_topology(parse_topology(studio.model.source())))
    assert round_trip.document["networks"] == studio.model.document["networks"]

    studio.scene.clearSelection()
    link = studio.links[("link-1", "")]
    point = studio.view.mapFromScene(link.line().center())
    qtbot.mouseClick(studio.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert link.isSelected()
    qtbot.mouseClick(studio.delete_button, Qt.MouseButton.LeftButton)
    assert ("link-1", "") not in studio.links
    assert {network["id"] for network in studio.model.document["networks"]} == {"hub-1"}


def test_canvas_opens_centered_does_not_rewrite_yaml_and_clear_is_undoable(window, qtbot) -> None:
    available = window.screen().availableGeometry()
    window.resize(min(1050, available.width() - 32), min(700, available.height() - 72))
    window.move(available.center() - window.rect().center())
    window.navigate("topologies")
    page = window.pages["topologies"]
    source = """# keep this comment until the first canvas edit
id: test-topology
networks:
  - {id: test-hub, ipv4_subnet: 192.168.230.0/24}
nodes:
  - {id: first, class: l0, layout: {x: 2400, y: -800}}
  - {id: second, class: l1, layout: {x: 2720, y: -500}}
"""
    page.set_source(source, "test.yml")
    qtbot.mouseClick(page.canvas_button, Qt.MouseButton.LeftButton)
    dialog = page.canvas_dialog
    assert dialog is not None
    qtbot.waitUntil(dialog.isVisible)
    assert page.source() == source
    assert dialog.width() >= min(900, available.width() - 40)
    assert dialog.height() >= min(600, available.height() - 80)
    assert (
        dialog.frameGeometry().center() - window.frameGeometry().center()
    ).manhattanLength() < 90
    studio = dialog.studio
    qtbot.waitUntil(
        lambda: all(
            studio.view.viewport().rect().contains(studio.view.mapFromScene(item.pos()))
            for item in studio.items.values()
        )
    )

    qtbot.mouseClick(studio.link_button, Qt.MouseButton.LeftButton)
    dialog.reject()
    assert dialog.isVisible() and not studio.link_button.isChecked()
    qtbot.mouseClick(studio.clear_button, Qt.MouseButton.LeftButton)
    assert "studio.clear" in window.asked
    assert not studio.items and not studio.links
    topology = parse_topology(page.source())
    assert topology.id == "test-topology" and not topology.nodes and not topology.networks
    studio.model.undo_stack.undo()
    assert len(studio.items) == 3
    assert len(parse_topology(page.source()).nodes) == 2
    dialog.close()
