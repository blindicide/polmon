"""Packet page chooses only managed hostless targets and sends exact editor text."""

from polmon.client.state import ConnectionState


def test_packet_page_target_selection_and_one_shot_send(window, monkeypatch) -> None:
    page = window.pages["packets"]
    frame_hex = "02000088000202000088000188b5414200ff"
    calls: list[tuple[str, str, str, str]] = []

    class Client:
        def topology(self, topology_id):
            assert topology_id == "pair"
            return {
                "topology": {
                    "nodes": [
                        {
                            "id": "client",
                            "name": "Client",
                            "class": "l1",
                            "interfaces": [{"id": "eth0"}],
                        },
                        {"id": "sensor", "class": "l0", "interfaces": []},
                    ]
                }
            }

        def send_packet(self, topology_id, node_id, interface_id, payload):
            calls.append((topology_id, node_id, interface_id, payload))
            return {
                "state": "sent",
                "operation_id": "abc123",
                "interface": "eth0",
                "byte_count": 18,
            }

    client = Client()
    monkeypatch.setattr(window.session, "client", lambda: client)

    def run(name, work, *, on_success, **kwargs):
        on_success(work(None, None))

    monkeypatch.setattr(window.context, "run", run)
    window.session.state = ConnectionState.CONNECTED
    window.session.deployments = {
        "ordinary": {"details": {"hostless_pair": False}},
        "pair": {"details": {"hostless_pair": True}},
    }
    page.activated()
    assert page.topology.count() == 1 and page.topology.currentData() == "pair"
    assert page.node.count() == 1 and page.node.currentData()["id"] == "client"
    assert page.interface.currentData() == "eth0"
    assert not page.send_button.isEnabled()
    page.frame.setPlainText(frame_hex)
    assert page.send_button.isEnabled()
    page.send()
    assert calls == [("pair", "client", "eth0", frame_hex)]
    assert page.last_result["operation_id"] == "abc123"


def test_packet_shortcut_preserves_existing_navigation(window) -> None:
    actions = {action.objectName(): action.shortcut().toString() for action in window.actions()}
    assert actions["navigate.telemetry"] == "Ctrl+6"
    assert actions["navigate.logs"] == "Ctrl+7"
    assert actions["navigate.reports"] == "Ctrl+8"
    assert actions["navigate.packets"] == "Ctrl+9"


def test_packet_result_distinguishes_refusal_from_error(window) -> None:
    page = window.pages["packets"]
    page._sent({"state": "refused", "operation_id": "a1", "message_code": "packet.size"})
    refusal = page.result.text()
    page._sent({"state": "error", "operation_id": "a1", "message_code": "packet.size"})
    error = page.result.text()
    assert refusal != error
    assert "packet.size" in refusal and "packet.size" in error
    assert "a1" in refusal and "a1" in error
