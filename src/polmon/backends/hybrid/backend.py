"""Hybrid orchestration and L0-to-L1 ARP/ICMP transport over shared TAPs."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict
from ipaddress import IPv4Address
from typing import Protocol

from polmon.backends.hybrid.tap import TapPort
from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.namespace.runner import CommandRunner
from polmon.backends.synthetic.backend import SyntheticBackend
from polmon.backends.synthetic.engine import SyntheticEngineError
from polmon.networking.arp import ARP_REPLY, ArpPacket
from polmon.networking.ethernet import EthernetFrame
from polmon.networking.icmp import ECHO_REPLY, ECHO_REQUEST, IcmpEcho
from polmon.networking.ipv4 import IP_PROTOCOL_ICMP, IPv4Packet
from polmon.orchestration.base import BackendInspection
from polmon.topology.models import NodeClass, Topology

ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_ARP = 0x0806
BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"


class TapLike(Protocol):
    name: str

    def write(self, frame: bytes) -> None: ...

    def read(self, timeout: float) -> bytes | None: ...

    def close(self) -> None: ...


class TapFactory(Protocol):
    def __call__(self, name: str) -> TapLike: ...


class HybridBackend:
    name = "hybrid"

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        tap_factory: TapFactory = TapPort.attach,
        capture_limit: int = 1_024,
        require_linux: bool = True,
        owner_uid: int | None = None,
        owner_gid: int | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.namespace = NamespaceBackend(
            runner=self.runner,
            require_linux=require_linux,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        self.synthetic = SyntheticBackend()
        self.tap_factory = tap_factory
        self.taps: dict[str, TapLike] = {}
        self.tap_names: dict[str, str] = {}
        self.capture: deque[bytes] = deque(maxlen=capture_limit)
        self.topology: Topology | None = None
        self._l1_topology: Topology | None = None
        self._l0_topology: Topology | None = None
        self.running = False
        self._sequence = 0

    def validate(self, topology: Topology) -> None:
        classes = {node.node_class for node in topology.nodes}
        if NodeClass.L0 not in classes or NodeClass.L1 not in classes:
            raise ValueError("hybrid backend requires at least one L0 and one L1 node")
        if NodeClass.L2 in classes:
            raise ValueError("L2 nodes are unsupported by the hybrid backend")
        self._l0_topology = Topology(
            id=topology.id,
            networks=topology.networks,
            nodes=[node for node in topology.nodes if node.node_class is NodeClass.L0],
        )
        self._l1_topology = Topology(
            id=topology.id,
            networks=topology.networks,
            nodes=[node for node in topology.nodes if node.node_class is NodeClass.L1],
        )
        self.synthetic.validate(self._l0_topology)
        self.namespace.validate(self._l1_topology)
        self.topology = topology

    def create(self, topology: Topology) -> set[str]:
        if self._l0_topology is None or self._l1_topology is None:
            self.validate(topology)
        resources: set[str] = set()
        try:
            resources.update(self.namespace.create(self._l1_topology))  # type: ignore[arg-type]
            resources.update(self.synthetic.create(self._l0_topology))  # type: ignore[arg-type]
            l0_networks = {
                interface.network
                for node in self._l0_topology.nodes  # type: ignore[union-attr]
                for interface in node.interfaces
            }
            for network_id in sorted(l0_networks):
                name = NamespaceBackend._name("polmon", f"{topology.id}:{network_id}:tap", "t")
                self.runner.run(
                    [
                        "ip",
                        "tuntap",
                        "add",
                        "dev",
                        name,
                        "mode",
                        "tap",
                        "user",
                        str(self.namespace.owner_uid),
                    ],
                    privileged=True,
                )
                self.tap_names[network_id] = name
                resources.add(f"tap:{name}")
                bridge = self.namespace.names.bridges[network_id]  # type: ignore[union-attr]
                self.runner.run(
                    ["ip", "link", "set", name, "master", bridge], privileged=True
                )
                self.runner.run(["ip", "link", "set", "dev", name, "up"], privileged=True)
                self.taps[network_id] = self.tap_factory(name)
        except Exception:
            self.destroy()
            raise
        return resources

    def start(self) -> None:
        self.namespace.start()
        self.synthetic.start()
        self.running = True

    def stop(self) -> None:
        self.namespace.stop()
        self.synthetic.stop()
        self.running = False

    def destroy(self) -> None:
        self.stop()
        for tap in list(self.taps.values()):
            tap.close()
        self.taps.clear()
        for name in list(self.tap_names.values()):
            self.runner.run(
                ["ip", "link", "del", "dev", name], privileged=True, check=False
            )
        self.tap_names.clear()
        self.synthetic.destroy()
        self.namespace.destroy()
        self.running = False

    def inspect(self) -> BackendInspection:
        resources = {
            *(f"tap:{name}" for name in self.tap_names.values()),
            *self.namespace.inspect().resources,
            *self.synthetic.inspect().resources,
        }
        return BackendInspection(
            backend=self.name,
            resources=frozenset(resources),
            details={
                "running": self.running,
                "tap_count": len(self.taps),
                "capture_frames": len(self.capture),
                "synthetic": asdict(self.synthetic.engine.stats()),
            },
        )

    def ping_l1(
        self,
        source_id: str,
        destination: str | IPv4Address,
        payload: bytes = b"polmon-hybrid",
        *,
        timeout: float = 2.0,
    ) -> bool:
        source = self.synthetic.engine._get(source_id)
        if source.ipv4 is None:
            raise SyntheticEngineError("source endpoint has no IPv4 address")
        tap = self.taps.get(source.network)
        if tap is None:
            raise SyntheticEngineError("source endpoint has no TAP boundary")
        destination_ip = IPv4Address(destination)
        arp = ArpPacket.request(source.mac, source.ipv4, destination_ip)
        request = EthernetFrame(BROADCAST_MAC, source.mac, ETHERTYPE_ARP, arp.to_bytes()).to_bytes()
        self._write(tap, request)
        reply_frame = self._receive_arp(tap, destination_ip, timeout)
        arp_reply = ArpPacket.from_bytes(reply_frame.payload)
        self._sequence = (self._sequence + 1) & 0xFFFF
        echo = IcmpEcho(ECHO_REQUEST, source.instance_id.int & 0xFFFF, self._sequence, payload)
        packet = IPv4Packet(
            source.ipv4,
            destination_ip,
            IP_PROTOCOL_ICMP,
            echo.to_bytes(),
            identification=self._sequence,
        )
        frame = EthernetFrame(arp_reply.sender_mac, source.mac, ETHERTYPE_IPV4, packet.to_bytes())
        self._write(tap, frame.to_bytes())
        return self._receive_echo(tap, source.ipv4, echo, timeout)

    def _write(self, tap: TapLike, frame: bytes) -> None:
        self.capture.append(frame)
        tap.write(frame)

    def _read_matching(self, tap: TapLike, timeout: float, matcher) -> EthernetFrame:
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            raw = tap.read(remaining)
            if raw is None:
                break
            self.capture.append(raw)
            try:
                frame = EthernetFrame.from_bytes(raw)
                if matcher(frame):
                    return frame
            except Exception:
                continue
        raise SyntheticEngineError("timed out waiting for hybrid network response")

    def _receive_arp(self, tap: TapLike, destination: IPv4Address, timeout: float) -> EthernetFrame:
        def matches(frame: EthernetFrame) -> bool:
            if frame.ethertype != ETHERTYPE_ARP:
                return False
            packet = ArpPacket.from_bytes(frame.payload)
            return packet.operation == ARP_REPLY and packet.sender_ip == destination

        return self._read_matching(tap, timeout, matches)

    def _receive_echo(
        self,
        tap: TapLike,
        destination: IPv4Address,
        request: IcmpEcho,
        timeout: float,
    ) -> bool:
        def matches(frame: EthernetFrame) -> bool:
            if frame.ethertype != ETHERTYPE_IPV4:
                return False
            packet = IPv4Packet.from_bytes(frame.payload)
            if packet.destination != destination or packet.protocol != IP_PROTOCOL_ICMP:
                return False
            echo = IcmpEcho.from_bytes(packet.payload)
            return (
                echo.echo_type == ECHO_REPLY
                and echo.identifier == request.identifier
                and echo.sequence == request.sequence
                and echo.payload == request.payload
            )

        self._read_matching(tap, timeout, matches)
        return True
