"""ICMPv4 echo request/reply only."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from polmon.networking.checksum import internet_checksum
from polmon.networking.ethernet import PacketError

ECHO_REPLY = 0
ECHO_REQUEST = 8


@dataclass(frozen=True, slots=True)
class IcmpEcho:
    echo_type: int
    identifier: int
    sequence: int
    payload: bytes = b""

    def to_bytes(self) -> bytes:
        if self.echo_type not in {ECHO_REQUEST, ECHO_REPLY}:
            raise PacketError("only ICMP echo is supported", message_code="packet.icmp_echo_only")
        header = struct.pack("!BBHHH", self.echo_type, 0, 0, self.identifier, self.sequence)
        checksum = internet_checksum(header + self.payload)
        return struct.pack(
            "!BBHHH", self.echo_type, 0, checksum, self.identifier, self.sequence
        ) + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> IcmpEcho:
        if len(data) < 8:
            raise PacketError("truncated ICMP packet", message_code="packet.icmp_truncated")
        echo_type, code, _, identifier, sequence = struct.unpack("!BBHHH", data[:8])
        if echo_type not in {ECHO_REQUEST, ECHO_REPLY} or code != 0:
            raise PacketError(
                "only ICMP echo request/reply is supported",
                message_code="packet.icmp_echo_only",
            )
        if internet_checksum(data) != 0:
            raise PacketError("invalid ICMP checksum", message_code="packet.icmp_checksum")
        return cls(echo_type, identifier, sequence, data[8:])

