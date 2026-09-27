"""Validated, deployment-independent topology schema."""

from __future__ import annotations

import re
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from polmon.core.errors import CodedValueError

IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
# Controlled laboratory address space (SECURITY.md): RFC 1918 private ranges and the RFC 2544
# benchmarking range. Public, shared (100.64.0.0/10), loopback, link-local, and multicast ranges
# are rejected; Phase I has no configuration that authorises external addresses.
LAB_IPV4_RANGES = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
    IPv4Network("198.18.0.0/15"),
)
MAC_ADDRESS = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")


class StrictModel(BaseModel):
    """Reject misspelled fields and serialize aliases predictably."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class NodeClass(StrEnum):
    L0 = "l0"
    L1 = "l1"
    L2 = "l2"


class Protocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise CodedValueError(
            "must start with a lowercase letter and contain only a-z, 0-9, or '-'",
            "topology.identifier_format",
        )
    return value


class ResourceRequirements(StrictModel):
    memory_mb: int = Field(ge=1, le=1_048_576)
    cpu_millicores: int = Field(ge=1, le=1_000_000)
    disk_mb: int = Field(default=1, ge=0, le=16_777_216)


class ServiceDefinition(StrictModel):
    id: str
    protocol: Protocol
    port: int = Field(ge=1, le=65535)
    implementation: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")

    _validate_id = field_validator("id")(_identifier)


class Network(StrictModel):
    id: str
    ipv4_subnet: IPv4Network

    _validate_id = field_validator("id")(_identifier)

    @field_validator("ipv4_subnet", mode="before")
    @classmethod
    def require_explicit_network(cls, value: object) -> object:
        if isinstance(value, str):
            return IPv4Network(value, strict=True)
        return value

    @field_validator("ipv4_subnet")
    @classmethod
    def require_laboratory_range(cls, value: IPv4Network) -> IPv4Network:
        if not any(value.subnet_of(allowed) for allowed in LAB_IPV4_RANGES):
            allowed = ", ".join(str(item) for item in LAB_IPV4_RANGES)
            raise CodedValueError(
                f"{value} is outside the controlled laboratory ranges ({allowed}); external "
                "addresses are not authorised",
                "topology.address_outside_lab",
                address=value, allowed=allowed,
            )
        return value


class Interface(StrictModel):
    id: str
    network: str
    mac: str
    ipv4: IPv4Address

    _validate_id = field_validator("id", "network")(_identifier)

    @field_validator("mac")
    @classmethod
    def normalize_mac(cls, value: str) -> str:
        normalized = value.lower().replace("-", ":")
        if not MAC_ADDRESS.fullmatch(normalized):
            raise CodedValueError("must be a six-octet unicast MAC address", "topology.mac_format")
        first_octet = int(normalized[:2], 16)
        if first_octet & 1:
            raise CodedValueError(
                "multicast MAC addresses are not valid endpoint identities",
                "topology.mac_multicast",
            )
        return normalized


class Node(StrictModel):
    id: str
    node_class: NodeClass = Field(alias="class")
    interfaces: list[Interface] = Field(default_factory=list)
    resources: ResourceRequirements | None = None
    services: list[ServiceDefinition] = Field(default_factory=list)

    _validate_id = field_validator("id")(_identifier)

    @model_validator(mode="after")
    def validate_node(self) -> Node:
        interface_ids = [interface.id for interface in self.interfaces]
        if len(interface_ids) != len(set(interface_ids)):
            raise CodedValueError(
                f"node '{self.id}' has duplicate interface identifiers",
                "topology.duplicate_interface_ids",
                node=self.id,
            )
        service_ids = [service.id for service in self.services]
        if len(service_ids) != len(set(service_ids)):
            raise CodedValueError(
                f"node '{self.id}' has duplicate service identifiers",
                "topology.duplicate_service_ids",
                node=self.id,
            )
        bindings = [(service.protocol, service.port) for service in self.services]
        if len(bindings) != len(set(bindings)):
            raise CodedValueError(
                f"node '{self.id}' has conflicting service bindings",
                "topology.conflicting_service_bindings",
                node=self.id,
            )
        if self.node_class is NodeClass.L0 and self.services:
            raise CodedValueError(
                "L0 service definitions are unsupported before an application stack exists",
                "topology.l0_services_unsupported",
            )
        return self


class ResourceEstimate(StrictModel):
    endpoint_count: int
    l0_endpoints: int
    l1_namespaces: int
    l2_virtual_machines: int
    memory_mb: int
    cpu_millicores: int
    disk_mb: int


DEFAULT_RESOURCES = {
    NodeClass.L0: ResourceRequirements(memory_mb=1, cpu_millicores=5, disk_mb=0),
    NodeClass.L1: ResourceRequirements(memory_mb=32, cpu_millicores=50, disk_mb=8),
    NodeClass.L2: ResourceRequirements(memory_mb=512, cpu_millicores=500, disk_mb=4096),
}


class Topology(StrictModel):
    id: str
    networks: list[Network]
    nodes: list[Node]

    _validate_id = field_validator("id")(_identifier)

    @model_validator(mode="after")
    def validate_relationships(self) -> Topology:
        network_ids = [network.id for network in self.networks]
        node_ids = [node.id for node in self.nodes]
        if len(network_ids) != len(set(network_ids)):
            raise CodedValueError("duplicate network identifiers", "topology.duplicate_network_ids")
        if len(node_ids) != len(set(node_ids)):
            raise CodedValueError("duplicate node identifiers", "topology.duplicate_node_ids")

        for index, left in enumerate(self.networks):
            for right in self.networks[index + 1 :]:
                if left.ipv4_subnet.overlaps(right.ipv4_subnet):
                    raise CodedValueError(
                        f"networks '{left.id}' and '{right.id}' have overlapping IPv4 subnets",
                        "topology.overlapping_subnets",
                        left=left.id, right=right.id,
                    )

        by_network = {network.id: network for network in self.networks}
        mac_owners: dict[str, str] = {}
        ip_owners: dict[IPv4Address, str] = {}
        for node in self.nodes:
            attached_networks: set[str] = set()
            for interface in node.interfaces:
                owner = f"{node.id}/{interface.id}"
                network = by_network.get(interface.network)
                if network is None:
                    raise CodedValueError(
                        f"interface '{owner}' references unknown network '{interface.network}'",
                        "topology.unknown_network",
                        interface=owner, network=interface.network,
                    )
                if interface.network in attached_networks:
                    raise CodedValueError(
                        f"node '{node.id}' has multiple interfaces on '{interface.network}'",
                        "topology.multiple_interfaces_on_network",
                        node=node.id, network=interface.network,
                    )
                attached_networks.add(interface.network)
                if interface.ipv4 not in network.ipv4_subnet:
                    raise CodedValueError(
                        f"IPv4 address {interface.ipv4} on '{owner}' is outside "
                        f"{network.ipv4_subnet}",
                        "topology.ipv4_outside_subnet",
                        address=interface.ipv4, interface=owner, subnet=network.ipv4_subnet,
                    )
                reserved = {
                    network.ipv4_subnet.network_address,
                    network.ipv4_subnet.broadcast_address,
                }
                if interface.ipv4 in reserved:
                    raise CodedValueError(
                        f"IPv4 address {interface.ipv4} on '{owner}' is not a usable host address",
                        "topology.ipv4_not_host",
                        address=interface.ipv4, interface=owner,
                    )
                if interface.mac in mac_owners:
                    raise CodedValueError(
                        f"MAC address {interface.mac} conflicts with "
                        f"'{mac_owners[interface.mac]}'",
                        "topology.mac_conflict",
                        mac=interface.mac, owner=mac_owners[interface.mac],
                    )
                if interface.ipv4 in ip_owners:
                    raise CodedValueError(
                        f"IPv4 address {interface.ipv4} conflicts with "
                        f"'{ip_owners[interface.ipv4]}'",
                        "topology.ipv4_conflict",
                        address=interface.ipv4, owner=ip_owners[interface.ipv4],
                    )
                mac_owners[interface.mac] = owner
                ip_owners[interface.ipv4] = owner
        return self

    def estimate_resources(self) -> ResourceEstimate:
        resources = [node.resources or DEFAULT_RESOURCES[node.node_class] for node in self.nodes]
        return ResourceEstimate(
            endpoint_count=len(self.nodes),
            l0_endpoints=sum(node.node_class is NodeClass.L0 for node in self.nodes),
            l1_namespaces=sum(node.node_class is NodeClass.L1 for node in self.nodes),
            l2_virtual_machines=sum(node.node_class is NodeClass.L2 for node in self.nodes),
            memory_mb=sum(item.memory_mb for item in resources),
            cpu_millicores=sum(item.cpu_millicores for item in resources),
            disk_mb=sum(item.disk_mb for item in resources),
        )
