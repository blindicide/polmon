from ipaddress import IPv4Address

import pytest

from polmon.backends.synthetic.engine import SyntheticEngine, SyntheticEngineError


def mac(index: int) -> str:
    return f"02:00:00:{(index >> 16) & 255:02x}:{(index >> 8) & 255:02x}:{index & 255:02x}"


def populate(engine: SyntheticEngine, count: int = 50) -> set[object]:
    identities: set[object] = set()
    for index in range(1, count + 1):
        endpoint = engine.create_endpoint(
            f"node-{index}", network="lab", mac=mac(index), ipv4=f"192.168.233.{index}"
        )
        identities.add(endpoint.instance_id)
    return identities


def test_repeated_fifty_endpoint_lifecycle_has_unique_identities_and_cleanup() -> None:
    engine = SyntheticEngine(max_endpoints=50)
    all_identities: set[object] = set()
    for _ in range(5):
        identities = populate(engine)
        assert len(identities) == 50
        assert all_identities.isdisjoint(identities)
        all_identities.update(identities)
        assert engine.stats().endpoint_count == 50
        engine.destroy_all()
        assert engine.stats().endpoint_count == 0
        assert engine.stats().network_count == 0
        assert engine.stats().scheduled_event_count == 0
    assert len(all_identities) == 250


def test_dispatch_is_copying_deterministic_and_network_isolated() -> None:
    engine = SyntheticEngine()
    left = engine.create_endpoint("left", network="lab", mac=mac(1), ipv4="192.168.233.1")
    right = engine.create_endpoint("right", network="lab", mac=mac(2), ipv4="192.168.233.2")
    outside = engine.create_endpoint("outside", network="other", mac=mac(3), ipv4="192.168.234.1")
    payload = bytearray(b"hello")
    engine.dispatch(left.id, right.id, payload)
    payload[:] = b"xxxxx"
    assert right.inbox.popleft() == b"hello"
    with pytest.raises(SyntheticEngineError, match="not on the same"):
        engine.dispatch(left.id, outside.id, b"blocked")


def test_scheduler_orders_equal_timestamps_and_discards_destroyed_endpoint() -> None:
    engine = SyntheticEngine()
    engine.create_endpoint("left", network="lab", mac=mac(1))
    engine.scheduler.schedule(2.0, "left", "second")
    engine.scheduler.schedule(1.0, "left", "first-a")
    engine.scheduler.schedule(1.0, "left", "first-b")
    assert [event.kind for event in engine.scheduler.run_until(1.0)] == ["first-a", "first-b"]
    engine.destroy_endpoint("left")
    assert len(engine.scheduler) == 0


def test_limits_duplicates_and_queue_bounds_are_enforced() -> None:
    engine = SyntheticEngine(max_endpoints=1, max_events=1)
    endpoint = engine.create_endpoint(
        "one", network="lab", mac=mac(1), ipv4=IPv4Address("192.168.230.1")
    )
    with pytest.raises(SyntheticEngineError, match="endpoint limit"):
        engine.create_endpoint("two", network="lab", mac=mac(2))
    engine.scheduler.schedule(1, endpoint.id, "event")
    with pytest.raises(SyntheticEngineError, match="event limit"):
        engine.scheduler.schedule(2, endpoint.id, "event")


def test_duplicate_identity_fields_are_rejected_and_destroy_is_idempotent() -> None:
    engine = SyntheticEngine()
    engine.create_endpoint("one", network="lab", mac=mac(1), ipv4="192.168.230.1")
    with pytest.raises(SyntheticEngineError, match="already exists"):
        engine.create_endpoint("one", network="lab", mac=mac(2))
    with pytest.raises(SyntheticEngineError, match="MAC address"):
        engine.create_endpoint("two", network="lab", mac=mac(1))
    with pytest.raises(SyntheticEngineError, match="IPv4 address"):
        engine.create_endpoint("two", network="lab", mac=mac(2), ipv4="192.168.230.1")
    assert engine.destroy_endpoint("one") is True
    assert engine.destroy_endpoint("one") is False
