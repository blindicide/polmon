import shutil
import subprocess

import pytest

from polmon.networking.arp import ArpPacket
from polmon.networking.ethernet import EthernetFrame
from polmon.telemetry.models import EventCategory
from polmon.telemetry.store import TelemetrySession, TelemetryStore


def arp_frame() -> bytes:
    from ipaddress import IPv4Address

    packet = ArpPacket.request(
        "02:00:00:00:00:01", IPv4Address("192.168.230.1"), IPv4Address("192.168.230.2")
    )
    return EthernetFrame(
        "ff:ff:ff:ff:ff:ff", "02:00:00:00:00:01", 0x0806, packet.to_bytes()
    ).to_bytes()


@pytest.mark.integration
def test_bounded_capture_is_inspectable_with_tcpdump(tmp_path) -> None:
    if shutil.which("tcpdump") is None:
        pytest.skip("NOT RUN — environment unavailable: tcpdump is not installed")
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    session = TelemetrySession(store, "inspectable", "lab", "recon", tmp_path)
    session.event(EventCategory.NETWORK_OBSERVATION, "arp")
    session.packet(arp_frame(), timestamp=1_700_000_000.0)
    summary = session.close("succeeded")
    result = subprocess.run(
        ["tcpdump", "-nn", "-r", "-"],
        check=False,
        input=summary.path.read_bytes(),
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert b"ARP, Request who-has 192.168.230.2 tell 192.168.230.1" in result.stdout
