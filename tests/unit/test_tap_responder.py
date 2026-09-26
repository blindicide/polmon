import time
from collections import deque
from ipaddress import IPv4Address

from polmon.backends.hybrid.responder import TapResponder
from polmon.networking.arp import ARP_REPLY, ArpPacket
from polmon.networking.ethernet import EthernetFrame
from polmon.networking.icmp import ECHO_REPLY, ECHO_REQUEST, IcmpEcho
from polmon.networking.ipv4 import IPv4Packet

L0_IP, L0_MAC = IPv4Address("10.89.0.10"), "02:00:00:89:00:01"
L1_IP, L1_MAC = IPv4Address("10.89.0.20"), "02:00:00:89:00:02"


class QueueTap:
    def __init__(self, frames) -> None:
        self.incoming = deque(frames)
        self.written = []

    def read(self, timeout: float):
        if self.incoming:
            return self.incoming.popleft()
        time.sleep(min(timeout, 0.01))
        return None

    def write(self, frame: bytes) -> None:
        self.written.append(frame)


def arp_request(target: IPv4Address) -> bytes:
    request = ArpPacket.request(L1_MAC, L1_IP, target)
    return EthernetFrame("ff:ff:ff:ff:ff:ff", L1_MAC, 0x0806, request.to_bytes()).to_bytes()


def echo_request(destination_mac: str, destination: IPv4Address) -> bytes:
    echo = IcmpEcho(ECHO_REQUEST, 7, 3, b"kernel-ping")
    packet = IPv4Packet(L1_IP, destination, 1, echo.to_bytes(), identification=99)
    return EthernetFrame(destination_mac, L1_MAC, 0x0800, packet.to_bytes()).to_bytes()


def responder_for(tap) -> TapResponder:
    return TapResponder(tap, lambda: {L0_IP: L0_MAC})


def test_answers_arp_and_echo_for_l0_endpoints_with_valid_packets() -> None:
    tap = QueueTap([])
    responder = responder_for(tap)
    assert responder.handle(arp_request(L0_IP)) is True
    reply = EthernetFrame.from_bytes(tap.written[-1])
    arp = ArpPacket.from_bytes(reply.payload)
    assert (reply.destination, arp.operation, arp.sender_ip, arp.sender_mac) == (
        L1_MAC,
        ARP_REPLY,
        L0_IP,
        L0_MAC,
    )
    assert responder.handle(echo_request(L0_MAC, L0_IP)) is True
    frame = EthernetFrame.from_bytes(tap.written[-1])
    packet = IPv4Packet.from_bytes(frame.payload)  # validates the IPv4 checksum
    echo = IcmpEcho.from_bytes(packet.payload)  # validates the ICMP checksum
    assert (packet.source, packet.destination) == (L0_IP, L1_IP)
    assert (echo.echo_type, echo.identifier, echo.sequence, echo.payload) == (
        ECHO_REPLY,
        7,
        3,
        b"kernel-ping",
    )
    assert responder.answered == {"arp": 1, "icmp_echo": 1}


def test_ignores_frames_it_must_not_answer() -> None:
    tap = QueueTap([])
    responder = responder_for(tap)
    ignored = [
        arp_request(IPv4Address("10.89.0.99")),  # not an L0 address
        echo_request(L0_MAC, IPv4Address("10.89.0.99")),
        echo_request("02:00:00:89:00:77", L0_IP),  # addressed to another MAC
        b"\x00" * 10,  # malformed
    ]
    assert [responder.handle(frame) for frame in ignored] == [False] * 4
    assert tap.written == []


def test_reader_thread_answers_and_forwards_everything_else() -> None:
    other = arp_request(IPv4Address("10.89.0.99"))
    tap = QueueTap([arp_request(L0_IP), other])
    captured = []
    responder = TapResponder(tap, lambda: {L0_IP: L0_MAC}, on_frame=captured.append)
    responder.start()
    try:
        assert responder.read(2.0) == other
        assert responder.answered["arp"] == 1
        assert len(captured) == 3  # two inbound frames and one reply
    finally:
        responder.stop()
    assert not responder.running


def test_stop_interrupts_a_blocked_read_immediately() -> None:
    import threading

    class BlockingTap:
        def __init__(self) -> None:
            self.woken = threading.Event()

        def read(self, timeout: float):
            self.woken.wait(timeout)  # blocks for the whole poll unless interrupted
            return None

        def write(self, frame: bytes) -> None:
            pass

        def interrupt(self) -> None:
            self.woken.set()

    responder = TapResponder(BlockingTap(), dict)
    responder.start()
    time.sleep(0.05)
    started = time.monotonic()
    responder.stop()
    assert time.monotonic() - started < 0.5  # the poll is 1 s; stop must not wait for it
    assert not responder.running
