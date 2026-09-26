from ipaddress import IPv4Address

import pytest

from polmon.networking.arp import ARP_REQUEST, ArpPacket
from polmon.networking.checksum import internet_checksum
from polmon.networking.ethernet import EthernetFrame, PacketError
from polmon.networking.icmp import ECHO_REQUEST, IcmpEcho
from polmon.networking.ipv4 import IP_PROTOCOL_ICMP, IPv4Packet


def test_rfc1071_checksum_fixture() -> None:
    assert internet_checksum(bytes.fromhex("0001f203f4f5f6f7")) == 0x220D


def test_ethernet_known_fixture_round_trip() -> None:
    raw = bytes.fromhex("ffffffffffff0200000000010806") + b"payload"
    frame = EthernetFrame.from_bytes(raw)
    assert frame.destination == "ff:ff:ff:ff:ff:ff"
    assert frame.source == "02:00:00:00:00:01"
    assert frame.ethertype == 0x0806
    assert frame.to_bytes() == raw


def test_arp_known_request_fixture() -> None:
    raw = bytes.fromhex(
        "0001080006040001" "0200000000010a000001" "0000000000000a000002"
    )
    packet = ArpPacket.from_bytes(raw)
    assert packet.operation == ARP_REQUEST
    assert packet.target_ip == IPv4Address("10.0.0.2")
    assert packet.to_bytes() == raw


def test_ipv4_known_header_checksum_fixture() -> None:
    raw = bytes.fromhex("45000054000040004001b890c0a80001c0a800c7") + bytes(64)
    packet = IPv4Packet.from_bytes(raw)
    assert packet.protocol == IP_PROTOCOL_ICMP
    assert packet.source == IPv4Address("192.168.0.1")
    assert packet.to_bytes() == raw


def test_icmp_echo_known_checksum_fixture() -> None:
    raw = bytes.fromhex("0800f7fd00010001")
    packet = IcmpEcho.from_bytes(raw)
    assert packet.echo_type == ECHO_REQUEST
    assert packet.identifier == 1
    assert packet.sequence == 1
    assert packet.to_bytes() == raw


@pytest.mark.parametrize(
    "parser,data,message",
    [
        (EthernetFrame.from_bytes, b"short", "truncated Ethernet"),
        (IPv4Packet.from_bytes, bytes(20), "only IPv4"),
        (IcmpEcho.from_bytes, bytes.fromhex("0800000000010001"), "invalid ICMP checksum"),
    ],
)
def test_malformed_packets_fail_predictably(parser, data: bytes, message: str) -> None:
    with pytest.raises(PacketError, match=message):
        parser(data)
