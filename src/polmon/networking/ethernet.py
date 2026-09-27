"""Ethernet II framing."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from polmon.core.errors import PolmonError


class PacketError(PolmonError):
    code = "packet_error"
    status_code = 422


def mac_to_bytes(value: str) -> bytes:
    try:
        raw = bytes.fromhex(value.replace(":", "").replace("-", ""))
    except ValueError as error:
        raise PacketError("invalid MAC address", message_code="packet.mac_invalid") from error
    if len(raw) != 6:
        raise PacketError("invalid MAC address length", message_code="packet.mac_length")
    return raw


def bytes_to_mac(value: bytes) -> str:
    if len(value) != 6:
        raise PacketError("invalid MAC address length", message_code="packet.mac_length")
    return ":".join(f"{octet:02x}" for octet in value)


@dataclass(frozen=True, slots=True)
class EthernetFrame:
    destination: str
    source: str
    ethertype: int
    payload: bytes

    def to_bytes(self) -> bytes:
        if not 0 <= self.ethertype <= 0xFFFF:
            raise PacketError("EtherType must fit 16 bits", message_code="packet.ethertype_range")
        return (
            mac_to_bytes(self.destination)
            + mac_to_bytes(self.source)
            + struct.pack("!H", self.ethertype)
            + self.payload
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> EthernetFrame:
        if len(data) < 14:
            raise PacketError("truncated Ethernet frame", message_code="packet.ethernet_truncated")
        return cls(
            destination=bytes_to_mac(data[:6]),
            source=bytes_to_mac(data[6:12]),
            ethertype=struct.unpack("!H", data[12:14])[0],
            payload=data[14:],
        )

