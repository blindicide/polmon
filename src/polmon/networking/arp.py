"""Ethernet/IPv4 ARP request and reply codec."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from ipaddress import IPv4Address

from polmon.networking.ethernet import PacketError, bytes_to_mac, mac_to_bytes

ARP_ETHERNET = 1
ARP_IPV4 = 0x0800
ARP_REQUEST = 1
ARP_REPLY = 2


@dataclass(frozen=True, slots=True)
class ArpPacket:
    operation: int
    sender_mac: str
    sender_ip: IPv4Address
    target_mac: str
    target_ip: IPv4Address

    @classmethod
    def request(cls, sender_mac: str, sender_ip: IPv4Address, target_ip: IPv4Address) -> ArpPacket:
        return cls(ARP_REQUEST, sender_mac, sender_ip, "00:00:00:00:00:00", target_ip)

    @classmethod
    def reply(
        cls,
        sender_mac: str,
        sender_ip: IPv4Address,
        target_mac: str,
        target_ip: IPv4Address,
    ) -> ArpPacket:
        return cls(ARP_REPLY, sender_mac, sender_ip, target_mac, target_ip)

    def to_bytes(self) -> bytes:
        if self.operation not in {ARP_REQUEST, ARP_REPLY}:
            raise PacketError("unsupported ARP operation", message_code="packet.arp_operation")
        return struct.pack(
            "!HHBBH6s4s6s4s",
            ARP_ETHERNET,
            ARP_IPV4,
            6,
            4,
            self.operation,
            mac_to_bytes(self.sender_mac),
            self.sender_ip.packed,
            mac_to_bytes(self.target_mac),
            self.target_ip.packed,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ArpPacket:
        if len(data) != 28:
            raise PacketError(
                "ARP packet must be exactly 28 bytes",
                message_code="packet.arp_length",
            )
        hardware, protocol, hlen, plen, operation, sha, spa, tha, tpa = struct.unpack(
            "!HHBBH6s4s6s4s", data
        )
        if (hardware, protocol, hlen, plen) != (ARP_ETHERNET, ARP_IPV4, 6, 4):
            raise PacketError(
                "unsupported ARP hardware or protocol format",
                message_code="packet.arp_format",
            )
        if operation not in {ARP_REQUEST, ARP_REPLY}:
            raise PacketError("unsupported ARP operation", message_code="packet.arp_operation")
        return cls(
            operation,
            bytes_to_mac(sha),
            IPv4Address(spa),
            bytes_to_mac(tha),
            IPv4Address(tpa),
        )

