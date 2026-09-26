import sqlite3
import struct

import pytest

from polmon.core.diagnostics import resource_snapshot
from polmon.networking.arp import ArpPacket
from polmon.networking.ethernet import EthernetFrame
from polmon.telemetry.models import EventCategory
from polmon.telemetry.store import TelemetrySession, TelemetryStore


def arp_frame() -> bytes:
    from ipaddress import IPv4Address

    packet = ArpPacket.request(
        "02:00:00:00:00:01", IPv4Address("10.0.0.1"), IPv4Address("10.0.0.2")
    )
    return EthernetFrame(
        "ff:ff:ff:ff:ff:ff", "02:00:00:00:00:01", 0x0806, packet.to_bytes()
    ).to_bytes()


def test_experiment_events_resources_and_capture_are_associated(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    session = TelemetrySession(store, "exp-001", "lab", "recon", tmp_path, max_capture_bytes=1024)
    session.event(EventCategory.SCENARIO, "started", payload={"access_token": "must-not-leak"})
    session.event(EventCategory.NODE_LIFECYCLE, "started", node_id="server")
    session.event(EventCategory.NETWORK_OBSERVATION, "arp", payload={"success": True})
    session.resources(resource_snapshot(active_endpoints=2, active_namespaces=1))
    assert session.packet(arp_frame(), timestamp=1_700_000_000.25)
    summary = session.close("succeeded")
    experiment = store.experiment("exp-001")
    events = store.events("exp-001")
    assert experiment["status"] == "succeeded"
    assert experiment["version"]
    assert experiment["capture"]["frame_count"] == 1
    assert summary.experiment_id == "exp-001"
    assert events[0].payload == {"access_token": "<redacted>"}
    assert all(event.experiment_id == "exp-001" for event in events)
    raw = summary.path.read_bytes()
    assert len(raw) == summary.captured_bytes
    assert struct.unpack("<I", raw[:4])[0] == 0xA1B2C3D4
    store.close()


def test_capture_enforces_snaplen_and_total_byte_limit(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    session = TelemetrySession(
        store, "bounded", "lab", "recon", tmp_path, max_capture_bytes=64, snaplen=10
    )
    assert session.packet(bytes(100), timestamp=1.0)
    assert session.packet(bytes(100), timestamp=2.0) is False
    summary = session.close("succeeded")
    assert summary.frame_count == 1
    assert summary.truncated_frames == 1
    assert summary.dropped_frames == 1
    assert summary.captured_bytes == 50


def test_invalid_or_duplicate_experiment_identifiers_fail(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    with pytest.raises(ValueError, match="invalid experiment"):
        store.begin("../escape", "lab", "recon")
    store.begin("duplicate", "lab", "recon")
    with pytest.raises(sqlite3.IntegrityError):
        store.begin("duplicate", "lab", "recon")


def test_unknown_experiment_queries_fail(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "telemetry.sqlite3")
    with pytest.raises(KeyError):
        store.experiment("missing")
    with pytest.raises(KeyError):
        store.finish("missing", "failed")
