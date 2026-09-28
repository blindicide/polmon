import pytest

from polmon.backends.synthetic.engine import SyntheticEngine, SyntheticEngineError
from polmon.backends.synthetic.protocols import SyntheticProtocolNetwork
from polmon.networking.arp import ARP_REPLY, ArpPacket
from polmon.networking.ethernet import EthernetFrame
from polmon.networking.icmp import ECHO_REPLY, IcmpEcho
from polmon.networking.ipv4 import IPv4Packet


def configured_engine() -> SyntheticEngine:
    engine = SyntheticEngine()
    engine.create_endpoint("alpha", network="lab", mac="02:00:00:00:00:01", ipv4="192.168.230.1")
    engine.create_endpoint("bravo", network="lab", mac="02:00:00:00:00:02", ipv4="192.168.230.2")
    engine.create_endpoint("other", network="other", mac="02:00:00:00:00:03", ipv4="192.168.231.1")
    return engine


def test_ping_resolves_arp_and_exchanges_valid_icmp() -> None:
    network = SyntheticProtocolNetwork(configured_engine())
    result = network.ping("alpha", "192.168.230.2", b"fixture")
    assert result.payload == b"fixture"
    assert result.arp_resolved is True
    assert result.captured_frames == 4
    arp_reply = ArpPacket.from_bytes(EthernetFrame.from_bytes(network.capture[1]).payload)
    assert arp_reply.operation == ARP_REPLY
    ip_reply = IPv4Packet.from_bytes(EthernetFrame.from_bytes(network.capture[3]).payload)
    assert IcmpEcho.from_bytes(ip_reply.payload).echo_type == ECHO_REPLY


def test_cached_ping_skips_arp_and_dispatch_order_is_deterministic() -> None:
    network = SyntheticProtocolNetwork(configured_engine())
    network.ping("alpha", "192.168.230.2")
    first_count = len(network.capture)
    result = network.ping("alpha", "192.168.230.2")
    assert result.arp_resolved is False
    assert len(network.capture) == first_count + 2
    assert result.sequence == 2


def test_ping_rejects_unknown_or_cross_network_address() -> None:
    network = SyntheticProtocolNetwork(configured_engine())
    with pytest.raises(SyntheticEngineError, match="no endpoint"):
        network.ping("alpha", "192.168.231.1")



def test_sustained_traffic_does_not_exhaust_bounded_receive_queues() -> None:
    from polmon.benchmarks.synthetic import build_topology

    topology = build_topology(250)
    engine = SyntheticEngine()
    for node in topology.nodes:
        interface = node.interfaces[0]
        engine.create_endpoint(
            node.id, network=interface.network, mac=interface.mac, ipv4=interface.ipv4
        )
    network = SyntheticProtocolNetwork(engine)
    source = topology.nodes[0].id
    for _ in range(2):  # 2 x 249 echoes + 249 ARP exchanges exceed the 256-frame queue
        for target in topology.nodes[1:]:
            network.ping(source, target.interfaces[0].ipv4)
    assert engine.stats().queued_packet_count == 0
    engine.destroy_all()
