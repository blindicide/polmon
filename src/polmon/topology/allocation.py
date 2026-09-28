"""Deterministic address allocation and v0.4 topology migration helpers."""

from __future__ import annotations

from collections.abc import Iterable
from ipaddress import IPv4Address, IPv4Network

from polmon.core.errors import CodedValueError
from polmon.topology.models import LAB_ADDRESS_PROFILE, AddressSpace, Topology

LAB_MAC_PREFIX = (0x02, 0x50, 0x4F)  # locally administered unicast: 02 + ASCII "PO"


def next_free_subnet(used: Iterable[IPv4Network | str] = ()) -> IPv4Network:
    occupied = {IPv4Network(str(item)) for item in used}
    for candidate in LAB_ADDRESS_PROFILE:
        if not any(candidate.overlaps(item) for item in occupied):
            return candidate
    raise CodedValueError("laboratory address profile is exhausted", "topology.subnet_exhausted")


def next_free_host(
    subnet: IPv4Network | str, used: Iterable[IPv4Address | str] = ()
) -> IPv4Address:
    network = IPv4Network(str(subnet))
    occupied = {IPv4Address(str(item)) for item in used}
    for candidate in network.hosts():
        if candidate not in occupied:
            return candidate
    raise CodedValueError(f"no host address remains in {network}", "topology.host_exhausted")


def next_free_mac(used: Iterable[str] = ()) -> str:
    occupied = {item.lower().replace("-", ":") for item in used}
    for suffix in range(1, 1 << 24):
        octets = (*LAB_MAC_PREFIX, suffix >> 16, (suffix >> 8) & 0xFF, suffix & 0xFF)
        candidate = ":".join(f"{octet:02x}" for octet in octets)
        if candidate not in occupied:
            return candidate
    raise CodedValueError("laboratory MAC prefix is exhausted", "topology.mac_exhausted")


def migrate_to_lab_profile(topology: Topology) -> Topology:
    """Return a profile-addressed copy, preserving IDs, UUIDs, host order and MACs."""
    payload = topology.model_dump(mode="json", by_alias=True, exclude_none=True)
    mappings: dict[str, tuple[IPv4Network, IPv4Network]] = {}
    occupied: list[IPv4Network] = []
    for network in payload["networks"]:
        old = IPv4Network(network["ipv4_subnet"])
        new = old if old in LAB_ADDRESS_PROFILE else next_free_subnet(occupied)
        occupied.append(new)
        mappings[network["id"]] = (old, new)
        network["ipv4_subnet"] = str(new)

    used_by_network: dict[str, set[IPv4Address]] = {key: set() for key in mappings}
    for node in payload["nodes"]:
        for interface in node.get("interfaces", []):
            network_id = interface["network"]
            old_network, new_network = mappings[network_id]
            old_address = IPv4Address(interface["ipv4"])
            offset = int(old_address) - int(old_network.network_address)
            candidate = IPv4Address(int(new_network.network_address) + offset)
            used = used_by_network[network_id]
            if candidate not in new_network or candidate in {
                new_network.network_address,
                new_network.broadcast_address,
            } or candidate in used:
                candidate = next_free_host(new_network, used)
            interface["ipv4"] = str(candidate)
            used.add(candidate)
    payload["address_space"] = AddressSpace.LAB_PROFILE.value
    return Topology.model_validate(payload)
