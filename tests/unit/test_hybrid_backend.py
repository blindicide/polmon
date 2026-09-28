from pathlib import Path

import pytest

from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.namespace.runner import CommandResult
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/hybrid-tap.yml"


class FakeProcess:
    pid = 1

    def poll(self):
        return 0


class FakeRunner:
    def __init__(self) -> None:
        self.commands = []

    def run(self, command, *, privileged=False, check=True, timeout=10, input=None):
        if input is not None:  # expand `ip [-n NS] [-force] -batch -` into per-line commands
            base = [part for part in command if part not in ("-batch", "-", "-force")]
            for line in input.splitlines():
                self.commands.append([*base, *line.split()])
            return CommandResult("", "", 0)
        self.commands.append(command)
        return CommandResult("", "", 0)

    def start(self, command, *, privileged=False):
        self.commands.append(command)
        return FakeProcess()


class FakeTap:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    def write(self, frame: bytes) -> None:
        pass

    def read(self, timeout: float):
        return None

    def close(self) -> None:
        self.closed = True


def test_hybrid_uses_one_shared_tap_and_tears_it_down_first() -> None:
    runner = FakeRunner()
    taps = []

    def factory(name):
        tap = FakeTap(name)
        taps.append(tap)
        return tap

    backend = HybridBackend(
        runner=runner,
        tap_factory=factory,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1001,
        bridge_port_states=lambda bridge: {tap.name: "3" for tap in taps},
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    resources = backend.create(topology)
    assert any(command[-2:] == ["user", "1000"] for command in runner.commands)
    assert len([resource for resource in resources if resource.startswith("tap:")]) == 1
    assert len(backend.synthetic.engine.endpoints) == 1
    backend.destroy()
    assert taps[0].closed
    link_deletes = [
        (index, command)
        for index, command in enumerate(runner.commands)
        if command[:4] == ["ip", "link", "del", "dev"]
    ]
    tap_delete_index = next(
        index for index, command in link_deletes if command[-1] == taps[0].name
    )
    bridge_delete_index = max(index for index, _ in link_deletes)
    assert tap_delete_index < bridge_delete_index


def test_hybrid_create_waits_until_bridge_ports_forward() -> None:
    runner = FakeRunner()
    polls = []

    def states(bridge: str) -> dict[str, str]:
        polls.append(bridge)
        tap_name = next(iter(backend.tap_names.values()))
        # First two polls: the TAP port is still disabled after attach (linkwatch race).
        return {tap_name: "0" if len(polls) <= 2 else "3", "vethpeer": "3"}

    backend = HybridBackend(
        runner=runner,
        tap_factory=FakeTap,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1001,
        bridge_port_states=states,
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    backend.create(topology)
    assert len(polls) == 3
    backend.destroy()


def test_hybrid_create_fails_closed_and_cleans_up_when_port_never_forwards() -> None:
    runner = FakeRunner()
    taps = []

    def factory(name):
        tap = FakeTap(name)
        taps.append(tap)
        return tap

    backend = HybridBackend(
        runner=runner,
        tap_factory=factory,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1001,
        bridge_port_states=lambda bridge: {tap.name: "0" for tap in taps},
        port_ready_timeout=0.05,
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    with pytest.raises(Exception, match="forwarding state"):
        backend.create(topology)
    assert taps[0].closed
    assert not backend.taps and not backend.tap_names
    assert any(
        command[:4] == ["ip", "link", "del", "dev"] and command[-1] == taps[0].name
        for command in runner.commands
    )


class PeerTap(FakeTap):
    """A TAP whose far side behaves like one L1 host: answers ARP and ICMP echo requests."""

    def __init__(
        self, name: str, *, peer_ip: str = "192.168.237.20", peer_mac: str = "02:00:00:89:00:02"
    ):
        super().__init__(name)
        from collections import deque
        from ipaddress import IPv4Address

        self.peer_ip = IPv4Address(peer_ip)
        self.peer_mac = peer_mac
        self.pending = deque()
        self.written = []

    def write(self, frame: bytes) -> None:
        from polmon.networking.arp import ArpPacket
        from polmon.networking.ethernet import EthernetFrame
        from polmon.networking.icmp import ECHO_REPLY, ECHO_REQUEST, IcmpEcho
        from polmon.networking.ipv4 import IPv4Packet

        self.written.append(frame)
        ethernet = EthernetFrame.from_bytes(frame)
        # Unrelated traffic first, as a real bridge would deliver it.
        noise = EthernetFrame("ff:ff:ff:ff:ff:ff", "02:aa:00:00:00:01", 0x86DD, b"\x00" * 46)
        self.pending.append(noise.to_bytes())
        if ethernet.ethertype == 0x0806:
            request = ArpPacket.from_bytes(ethernet.payload)
            if request.target_ip == self.peer_ip:
                reply = ArpPacket.reply(
                    self.peer_mac, self.peer_ip, request.sender_mac, request.sender_ip
                )
                frame = EthernetFrame(request.sender_mac, self.peer_mac, 0x0806, reply.to_bytes())
                self.pending.append(frame.to_bytes())
        elif ethernet.ethertype == 0x0800:
            packet = IPv4Packet.from_bytes(ethernet.payload)
            echo = IcmpEcho.from_bytes(packet.payload)
            if packet.destination == self.peer_ip and echo.echo_type == ECHO_REQUEST:
                answer = IcmpEcho(ECHO_REPLY, echo.identifier, echo.sequence, echo.payload)
                reply = IPv4Packet(self.peer_ip, packet.source, 1, answer.to_bytes())
                frame = EthernetFrame(ethernet.source, self.peer_mac, 0x0800, reply.to_bytes())
                self.pending.append(frame.to_bytes())

    def read(self, timeout: float):
        return self.pending.popleft() if self.pending else None


def hybrid_with(tap_factory) -> HybridBackend:
    backend = HybridBackend(
        runner=FakeRunner(),
        tap_factory=tap_factory,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1000,
        bridge_port_states=lambda bridge: {name: "3" for name in backend.tap_names.values()},
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    backend.create(topology)
    return backend


def test_ping_l1_completes_arp_and_icmp_across_the_tap_and_captures_frames() -> None:
    taps = []

    def factory(name):
        taps.append(PeerTap(name))
        return taps[-1]

    backend = hybrid_with(factory)
    assert backend.ping_l1("synthetic", "192.168.237.20") is True
    # ARP request, ICMP request written; unrelated frames were skipped while matching replies.
    assert len(taps[0].written) == 2
    assert len(backend.capture) >= 4
    assert backend.ping_l1("synthetic", "192.168.237.20") is True  # repeatable
    backend.destroy()


def test_ping_l1_times_out_without_an_answer_and_rejects_unknown_sources() -> None:
    import pytest

    from polmon.backends.synthetic.engine import SyntheticEngineError

    backend = hybrid_with(lambda name: PeerTap(name, peer_ip="192.168.237.99"))
    with pytest.raises(SyntheticEngineError, match="timed out"):
        backend.ping_l1("synthetic", "192.168.237.20", timeout=0.05)
    with pytest.raises(SyntheticEngineError):
        backend.ping_l1("no-such-endpoint", "192.168.237.20")
    backend.destroy()


def test_create_refuses_an_existing_tap_name() -> None:
    import pytest

    class Occupied(FakeRunner):
        def run(self, command, *, privileged=False, check=True, timeout=10, input=None):
            if command == ["ip", "-o", "link", "show"]:
                return CommandResult(self.listing, "", 0)
            return super().run(
                command, privileged=privileged, check=check, timeout=timeout, input=input
            )

    from polmon.backends.namespace.backend import NamespaceBackend

    topology = load_topology(EXAMPLE)
    tap = NamespaceBackend._name("polmon", f"{topology.id}:lab:tap", "t")
    runner = Occupied()
    runner.listing = f"42: {tap}: <BROADCAST> mtu 1500\n"
    backend = HybridBackend(
        runner=runner, tap_factory=FakeTap, require_linux=False, owner_uid=1, owner_gid=1
    )
    backend.validate(topology)
    with pytest.raises(RuntimeError, match="already exist"):
        backend.create(topology)
    assert not backend.tap_names and not backend.taps
    assert not any("tuntap" in command for command in runner.commands)
