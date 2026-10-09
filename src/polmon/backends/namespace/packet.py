"""Bounded Ethernet frame validation for an isolated managed lab network."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

from polmon.core.errors import ConfigurationError

MIN_FRAME_BYTES = 14
MAX_FRAME_BYTES = 1514


def parse_frame(frame_hex: str) -> bytes:
    if len(frame_hex) > 8192:
        raise ConfigurationError("invalid Ethernet frame length", message_code="packet.size")
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError as error:
        raise ConfigurationError("frame must be hexadecimal", message_code="packet.hex") from error
    if not MIN_FRAME_BYTES <= len(frame) <= MAX_FRAME_BYTES:
        raise ConfigurationError("invalid Ethernet frame length", message_code="packet.size")
    return frame


def require_lab_destination(frame: bytes, subnet: IPv4Network) -> None:
    """Reject routable IPv4/ARP targets outside this physical lab fabric.

    Opaque EtherTypes stay usable for malformed protocol experiments. They cannot leave
    the lab because the sender is bound to an owned interface with no external uplink.
    """
    offset = 12
    kind = int.from_bytes(frame[offset : offset + 2], "big")
    for _ in range(2):
        if kind not in {0x8100, 0x88A8}:
            break
        offset += 4
        if len(frame) < offset + 2:
            raise ConfigurationError("truncated VLAN header", message_code="packet.vlan_header")
        kind = int.from_bytes(frame[offset : offset + 2], "big")
    if kind == 0x86DD:
        raise ConfigurationError(
            "IPv6 is not configured in this lab", message_code="packet.ipv6_unconfigured"
        )
    start = offset + 2
    if kind == 0x0800:
        if len(frame) < start + 20 or frame[start] >> 4 != 4:
            raise ConfigurationError("malformed IPv4 header", message_code="packet.ipv4_header")
        target = IPv4Address(frame[start + 16 : start + 20])
    elif kind == 0x0806:
        if len(frame) < start + 28 or frame[start : start + 6] != b"\x00\x01\x08\x00\x06\x04":
            raise ConfigurationError("malformed ARP header", message_code="packet.arp_header")
        target = IPv4Address(frame[start + 24 : start + 28])
    else:
        return
    if (
        target not in subnet
        and target != IPv4Address("255.255.255.255")
        and not target.is_multicast
    ):
        raise ConfigurationError(
            "packet target is outside the selected lab network",
            message_code="packet.off_lab_target",
        )
