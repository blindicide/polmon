from uuid import UUID

import pytest

from polmon.client.studio import TopologyStudioModel
from polmon.topology import parse_topology


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
