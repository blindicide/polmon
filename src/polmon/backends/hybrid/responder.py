"""Answer inbound ARP and ICMP echo for L0 endpoints on a shared TAP.

One reader thread per TAP owns every read from it. Frames addressed to L0 endpoints that the
synthetic protocol set can answer (ARP requests, ICMP echo requests) are answered in place; every
other frame goes to ``inbox`` for callers such as ``HybridBackend.ping_l1``. Nothing else is
emulated: other protocols to L0 endpoints get no reply, exactly as if the port were closed.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from ipaddress import IPv4Address
from typing import Protocol

from polmon.networking.arp import ARP_REQUEST, ArpPacket
from polmon.networking.ethernet import EthernetFrame
from polmon.networking.icmp import ECHO_REPLY, ECHO_REQUEST, IcmpEcho
from polmon.networking.ipv4 import IP_PROTOCOL_ICMP, IPv4Packet

ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_ARP = 0x0806
BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"
INBOX_LIMIT = 1_024
POLL_SECONDS = 0.1


class ReadableTap(Protocol):
    def write(self, frame: bytes) -> None: ...

    def read(self, timeout: float) -> bytes | None: ...


class TapResponder:
    """Reader thread for one TAP; ``endpoints`` maps L0 IPv4 addresses to their MACs."""

    def __init__(
        self,
        tap: ReadableTap,
        endpoints: Callable[[], dict[IPv4Address, str]],
        *,
        on_frame: Callable[[bytes], None] | None = None,
    ) -> None:
        self.tap = tap
        self.endpoints = endpoints
        self.on_frame = on_frame
        self.inbox: queue.Queue[bytes] = queue.Queue(maxsize=INBOX_LIMIT)
        self.answered = {"arp": 0, "icmp_echo": 0}
        self.dropped = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="polmon-tap-responder", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def read(self, timeout: float) -> bytes | None:
        """Next frame not consumed by the responder (same contract as ``TapLike.read``)."""
        try:
            return self.inbox.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self.tap.read(POLL_SECONDS)
            except OSError:
                return  # the TAP was closed during teardown
            if raw is None:
                continue
            if self.on_frame is not None:
                self.on_frame(raw)
            if self.handle(raw):
                continue
            try:
                self.inbox.put_nowait(raw)
            except queue.Full:
                self.dropped += 1

    def handle(self, raw: bytes) -> bool:
        """Answer ``raw`` if it is ARP or ICMP echo for an L0 endpoint; return True if answered."""
        try:
            frame = EthernetFrame.from_bytes(raw)
        except Exception:
            return False
        endpoints = self.endpoints()
        try:
            if frame.ethertype == ETHERTYPE_ARP:
                return self._answer_arp(frame, endpoints)
            if frame.ethertype == ETHERTYPE_IPV4:
                return self._answer_echo(frame, endpoints)
        except Exception:
            return False  # malformed payloads are never answered
        return False

    def _answer_arp(self, frame: EthernetFrame, endpoints: dict[IPv4Address, str]) -> bool:
        request = ArpPacket.from_bytes(frame.payload)
        mac = endpoints.get(request.target_ip)
        if request.operation != ARP_REQUEST or mac is None:
            return False
        reply = ArpPacket.reply(mac, request.target_ip, request.sender_mac, request.sender_ip)
        self._send(EthernetFrame(request.sender_mac, mac, ETHERTYPE_ARP, reply.to_bytes()))
        self.answered["arp"] += 1
        return True

    def _answer_echo(self, frame: EthernetFrame, endpoints: dict[IPv4Address, str]) -> bool:
        packet = IPv4Packet.from_bytes(frame.payload)
        mac = endpoints.get(packet.destination)
        if mac is None or packet.protocol != IP_PROTOCOL_ICMP:
            return False
        if frame.destination not in (mac, BROADCAST_MAC):
            return False
        echo = IcmpEcho.from_bytes(packet.payload)
        if echo.echo_type != ECHO_REQUEST:
            return False
        answer = IcmpEcho(ECHO_REPLY, echo.identifier, echo.sequence, echo.payload)
        reply = IPv4Packet(
            packet.destination,
            packet.source,
            IP_PROTOCOL_ICMP,
            answer.to_bytes(),
            identification=packet.identification,
        )
        self._send(EthernetFrame(frame.source, mac, ETHERTYPE_IPV4, reply.to_bytes()))
        self.answered["icmp_echo"] += 1
        return True

    def _send(self, frame: EthernetFrame) -> None:
        raw = frame.to_bytes()
        if self.on_frame is not None:
            self.on_frame(raw)
        self.tap.write(raw)
