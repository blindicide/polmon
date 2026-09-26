from pathlib import Path

import pytest

from polmon.core.errors import ConfigurationError
from polmon.topology import dump_topology, load_topology, parse_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/hybrid-small.yml"


def test_example_round_trips_and_estimates_resources() -> None:
    topology = load_topology(EXAMPLE)
    assert topology.id == "hybrid-small"
    estimate = topology.estimate_resources()
    assert estimate.endpoint_count == 2
    assert estimate.l0_endpoints == 1
    assert estimate.l1_namespaces == 1
    assert estimate.memory_mb == 49
    assert parse_topology(dump_topology(topology)) == topology


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        ("ipv4: 10.88.0.10", "outside"),
        ("mac: '01:00:00:00:00:01'", "multicast"),
        ("network: missing", "unknown network"),
        ("ipv4: 10.77.0.0", "not a usable host"),
    ],
)
def test_invalid_interface_configurations_are_explained(fragment: str, message: str) -> None:
    source = EXAMPLE.read_text(encoding="utf-8")
    if fragment.startswith("ipv4"):
        source = source.replace("ipv4: 10.77.0.10", fragment)
    else:
        source = source.replace('mac: "02:00:00:00:00:01"', fragment)
    if fragment.startswith("network"):
        source = EXAMPLE.read_text(encoding="utf-8").replace("network: lab", fragment, 1)
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert message in str(caught.value.details)


def test_duplicate_node_identifiers_are_rejected() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace("id: service-1", "id: sensor-1")
    with pytest.raises(ConfigurationError, match="topology validation failed") as caught:
        parse_topology(source)
    assert "duplicate node identifiers" in str(caught.value.details)


def test_conflicting_addresses_are_rejected() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace("ipv4: 10.77.0.20", "ipv4: 10.77.0.10")
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert "conflicts" in str(caught.value.details)


def test_overlapping_networks_are_rejected() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace(
        "nodes:\n", "  - id: lab-overlap\n    ipv4_subnet: 10.77.0.128/25\nnodes:\n"
    )
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert "overlapping" in str(caught.value.details)


def test_duplicate_yaml_keys_are_rejected() -> None:
    with pytest.raises(ConfigurationError) as caught:
        parse_topology("id: first\nid: second\nnetworks: []\nnodes: []\n")
    assert "duplicate YAML key" in str(caught.value.details)


def test_l0_services_are_explicitly_unsupported() -> None:
    source = EXAMPLE.read_text(encoding="utf-8")
    service = """    services:
      - id: fake
        protocol: tcp
        port: 80
        implementation: static_http
"""
    source = source.replace("  - id: service-1", service + "  - id: service-1")
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert "unsupported" in str(caught.value.details)
