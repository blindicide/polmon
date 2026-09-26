"""Minimal IPv4 packets without options or fragmentation."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from ipaddress import IPv4Address

from polmon.networking.checksum import internet_checksum
from polmon.networking.ethernet import PacketError

IP_PROTOCOL_ICMP = 1


@dataclass(frozen=True, slots=True)
class IPv4Packet:
    source: IPv4Address
    destination: IPv4Address
    protocol: int
    payload: bytes
    identification: int = 0
    ttl: int = 64
    dont_fragment: bool = False

    def to_bytes(self) -> bytes:
        if len(self.payload) > 65515:
            raise PacketError("IPv4 payload is too large")
        if not 1 <= self.ttl <= 255:
            raise PacketError("IPv4 TTL must be between 1 and 255")
        total_length = 20 + len(self.payload)
        initial = struct.pack(
            "!BBHHHBBH4s4s",
            0x45,
            0,
            total_length,
            self.identification,
            0x4000 if self.dont_fragment else 0,
            self.ttl,
            self.protocol,
            0,
            self.source.packed,
            self.destination.packed,
        )
        checksum = internet_checksum(initial)
        header = initial[:10] + struct.pack("!H", checksum) + initial[12:]
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> IPv4Packet:
        if len(data) < 20:
            raise PacketError("truncated IPv4 packet")
        version_ihl, _, total, identification, flags_fragment, ttl, protocol, _, src, dst = (
            struct.unpack("!BBHHHBBH4s4s", data[:20])
        )
        if version_ihl != 0x45:
            raise PacketError("only IPv4 without options is supported")
        if total != len(data):
            raise PacketError("IPv4 total length does not match packet")
        if flags_fragment & 0xBFFF:
            raise PacketError("IPv4 fragmentation or reserved flags are unsupported")
        if internet_checksum(data[:20]) != 0:
            raise PacketError("invalid IPv4 header checksum")
        return cls(
            IPv4Address(src),
            IPv4Address(dst),
            protocol,
            data[20:],
            identification,
            ttl,
            bool(flags_fragment & 0x4000),
        )
