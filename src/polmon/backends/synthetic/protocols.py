"""Deterministic ARP and ICMP exchange across synthetic endpoints."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from ipaddress import IPv4Address

from polmon.backends.synthetic.engine import (
    SyntheticEndpoint,
    SyntheticEngine,
    SyntheticEngineError,
)
from polmon.networking.arp import ARP_REPLY, ArpPacket
from polmon.networking.ethernet import EthernetFrame
from polmon.networking.icmp import ECHO_REPLY, ECHO_REQUEST, IcmpEcho
from polmon.networking.ipv4 import IP_PROTOCOL_ICMP, IPv4Packet

ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_ARP = 0x0806
BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"


@dataclass(frozen=True, slots=True)
class PingResult:
    source: IPv4Address
    destination: IPv4Address
    sequence: int
    payload: bytes
    arp_resolved: bool
    captured_frames: int


class SyntheticProtocolNetwork:
    """Small supported protocol surface: Ethernet, ARP, IPv4, and ICMP echo."""

    def __init__(self, engine: SyntheticEngine, *, capture_limit: int = 1_024) -> None:
        self.engine = engine
        self.arp_cache: dict[str, dict[IPv4Address, str]] = {}
        self.capture: deque[bytes] = deque(maxlen=capture_limit)
        self._sequence = 0

    def ping(
        self,
        source_id: str,
        destination: str | IPv4Address,
        payload: bytes = b"polmon",
    ) -> PingResult:
        source = self.engine._get(source_id)
        if source.ipv4 is None:
            raise SyntheticEngineError("source endpoint has no IPv4 address")
        target_ip = IPv4Address(destination)
        target = self._find_peer(source, target_ip)
        cache = self.arp_cache.setdefault(source.id, {})
        resolved = target_ip in cache
        if not resolved:
            self._arp_exchange(source, target)
        self._sequence = (self._sequence + 1) & 0xFFFF
        identifier = source.instance_id.int & 0xFFFF
        request = IcmpEcho(ECHO_REQUEST, identifier, self._sequence, bytes(payload))
        request_ip = IPv4Packet(
            source.ipv4,
            target.ipv4,
            IP_PROTOCOL_ICMP,
            request.to_bytes(),
            identification=self._sequence,
        )
        self._send(source, target, ETHERTYPE_IPV4, request_ip.to_bytes())
        parsed_request = IcmpEcho.from_bytes(IPv4Packet.from_bytes(request_ip.to_bytes()).payload)
        reply = IcmpEcho(
            ECHO_REPLY,
            parsed_request.identifier,
            parsed_request.sequence,
            parsed_request.payload,
        )
        reply_ip = IPv4Packet(
            target.ipv4,
            source.ipv4,
            IP_PROTOCOL_ICMP,
            reply.to_bytes(),
            identification=self._sequence,
        )
        self._send(target, source, ETHERTYPE_IPV4, reply_ip.to_bytes())
        parsed_reply = IcmpEcho.from_bytes(IPv4Packet.from_bytes(reply_ip.to_bytes()).payload)
        if parsed_reply.payload != payload:
            raise SyntheticEngineError("ICMP echo payload mismatch")
        return PingResult(
            source.ipv4,
            target.ipv4,
            self._sequence,
            parsed_reply.payload,
            not resolved,
            len(self.capture),
        )

    def _find_peer(self, source: SyntheticEndpoint, address: IPv4Address) -> SyntheticEndpoint:
        for peer_id in sorted(self.engine.networks.get(source.network, ())):
            peer = self.engine.endpoints[peer_id]
            if peer.ipv4 == address:
                return peer
        raise SyntheticEngineError(
            f"no endpoint for IPv4 address '{address}' on '{source.network}'"
        )

    def _arp_exchange(self, source: SyntheticEndpoint, target: SyntheticEndpoint) -> None:
        request = ArpPacket.request(source.mac, source.ipv4, target.ipv4)
        self._send(source, target, ETHERTYPE_ARP, request.to_bytes(), destination_mac=BROADCAST_MAC)
        parsed = ArpPacket.from_bytes(request.to_bytes())
        if parsed.target_ip != target.ipv4:
            raise SyntheticEngineError("ARP target mismatch")
        reply = ArpPacket.reply(target.mac, target.ipv4, source.mac, source.ipv4)
        self._send(target, source, ETHERTYPE_ARP, reply.to_bytes())
        parsed_reply = ArpPacket.from_bytes(reply.to_bytes())
        if parsed_reply.operation != ARP_REPLY:
            raise SyntheticEngineError("ARP reply operation mismatch")
        self.arp_cache.setdefault(source.id, {})[target.ipv4] = target.mac
        self.arp_cache.setdefault(target.id, {})[source.ipv4] = source.mac

    def _send(
        self,
        source: SyntheticEndpoint,
        target: SyntheticEndpoint,
        ethertype: int,
        payload: bytes,
        *,
        destination_mac: str | None = None,
    ) -> None:
        frame = EthernetFrame(destination_mac or target.mac, source.mac, ethertype, payload)
        raw = frame.to_bytes()
        EthernetFrame.from_bytes(raw)
        self.capture.append(raw)
        self.engine.dispatch(source.id, target.id, raw)
