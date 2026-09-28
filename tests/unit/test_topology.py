from pathlib import Path
from uuid import UUID

import pytest

from polmon.core.errors import ConfigurationError
from polmon.topology import (
    dump_topology,
    load_topology,
    migrate_to_lab_profile,
    next_free_host,
    next_free_mac,
    next_free_subnet,
    parse_topology,
)

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
    assert topology.address_space == "lab-profile"
    assert all(node.name == node.id and node.uuid.version == 4 for node in topology.nodes)
    assert all(str(UUID(str(node.uuid))) == str(node.uuid) for node in topology.nodes)


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        ("ipv4: 192.168.236.10", "outside"),
        ("mac: '01:00:00:00:00:01'", "multicast"),
        ("network: missing", "unknown network"),
        ("ipv4: 192.168.235.0", "not a usable host"),
    ],
)
def test_invalid_interface_configurations_are_explained(fragment: str, message: str) -> None:
    source = EXAMPLE.read_text(encoding="utf-8")
    if fragment.startswith("ipv4"):
        source = source.replace("ipv4: 192.168.235.10", fragment)
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
    source = EXAMPLE.read_text(encoding="utf-8").replace(
        "ipv4: 192.168.235.20", "ipv4: 192.168.235.10"
    )
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert "conflicts" in str(caught.value.details)


def test_overlapping_networks_are_rejected() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace(
        "nodes:\n", "  - id: lab-overlap\n    ipv4_subnet: 192.168.235.128/25\nnodes:\n"
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


@pytest.mark.parametrize(
    "subnet",
    ["8.8.8.0/24", "100.64.0.0/24", "127.0.0.0/24", "169.254.1.0/24", "224.0.0.0/24", "11.0.0.0/8"],
)
def test_external_and_special_address_ranges_are_rejected(subnet: str) -> None:
    source = f"""id: outside
networks:
  - id: lab
    ipv4_subnet: {subnet}
nodes: []
"""
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert "outside address space" in str(caught.value.details)


@pytest.mark.parametrize("subnet", ["192.168.230.0/24", "192.168.235.0/25", "192.168.240.0/24"])
def test_default_profile_address_ranges_are_accepted(subnet: str) -> None:
    source = f"""id: inside
networks:
  - id: lab
    ipv4_subnet: {subnet}
nodes: []
"""
    assert str(parse_topology(source).networks[0].ipv4_subnet) == subnet


@pytest.mark.parametrize(
    "subnet", ["10.1.0.0/24", "172.20.0.0/16", "192.168.5.0/24", "198.18.0.0/24"]
)
def test_explicit_rfc1918_compatibility_space_is_accepted(subnet: str) -> None:
    source = f"""id: compatible
address_space: rfc1918
networks: [{{id: lab, ipv4_subnet: {subnet}}}]
nodes: []
"""
    assert str(parse_topology(source).networks[0].ipv4_subnet) == subnet


def test_machine_names_are_utf8_bounded_and_unique_ignoring_case() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace(
        "id: sensor-1", "id: sensor-1\n    name: Датчик"
    ).replace("id: service-1", "id: service-1\n    name: датчик")
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert "duplicate_node_names" in str(caught.value.details)


def test_machine_uuids_are_v4_and_unique() -> None:
    source = EXAMPLE.read_text(encoding="utf-8").replace(
        "id: sensor-1", "id: sensor-1\n    uuid: 6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    )
    with pytest.raises(ConfigurationError) as caught:
        parse_topology(source)
    assert "uuid_not_v4" in str(caught.value.details)


def test_deterministic_allocators_and_exhaustion() -> None:
    assert str(next_free_subnet(["192.168.230.0/24"])) == "192.168.231.0/24"
    assert str(next_free_host("192.168.230.0/30", ["192.168.230.1"])) == "192.168.230.2"
    assert next_free_mac(["02:50:4f:00:00:01"]) == "02:50:4f:00:00:02"
    with pytest.raises(ValueError, match="exhausted"):
        next_free_subnet([f"192.168.{octet}.0/24" for octet in range(230, 241)])
    with pytest.raises(ValueError, match="no host"):
        next_free_host("192.168.230.0/30", ["192.168.230.1", "192.168.230.2"])


def test_migration_renumbers_deterministically_and_preserves_identity() -> None:
    legacy = parse_topology(
        EXAMPLE.read_text(encoding="utf-8")
        .replace("192.168.235", "10.77.0")
        .replace("id: hybrid-small", "id: hybrid-small\naddress_space: rfc1918")
    )
    migrated = migrate_to_lab_profile(legacy)
    assert str(migrated.networks[0].ipv4_subnet) == "192.168.230.0/24"
    assert [str(item.interfaces[0].ipv4) for item in migrated.nodes] == [
        "192.168.230.10",
        "192.168.230.20",
    ]
    assert [item.uuid for item in migrated.nodes] == [item.uuid for item in legacy.nodes]
    assert [item.interfaces[0].mac for item in migrated.nodes] == [
        item.interfaces[0].mac for item in legacy.nodes
    ]
