from polmon.backends.synthetic.backend import SyntheticBackend
from polmon.orchestration import LifecycleState, Orchestrator
from polmon.topology import parse_topology


def l0_topology(count: int = 3):
    nodes = []
    for index in range(1, count + 1):
        nodes.append(
            {
                "id": f"node-{index}",
                "class": "l0",
                "interfaces": [
                    {
                        "id": "eth0",
                        "network": "lab",
                        "mac": f"02:00:00:00:00:{index:02x}",
                        "ipv4": f"192.168.233.{index}",
                    }
                ],
            }
        )
    import yaml

    return parse_topology(
        yaml.safe_dump(
            {
                "id": "l0-only",
                "networks": [{"id": "lab", "ipv4_subnet": "192.168.233.0/24"}],
                "nodes": nodes,
            }
        )
    )


def test_synthetic_backend_obeys_orchestration_contract() -> None:
    backend = SyntheticBackend(max_endpoints=5)
    control = Orchestrator(l0_topology(), backend)
    control.validate()
    control.create()
    control.start()
    assert control.state is LifecycleState.RUNNING
    assert backend.engine.stats().endpoint_count == 3
    control.destroy()
    assert not backend.engine.endpoints

