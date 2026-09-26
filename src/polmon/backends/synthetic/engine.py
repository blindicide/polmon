"""Resource-bounded L0 endpoint registry, virtual links, and scheduler."""

from __future__ import annotations

import heapq
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from ipaddress import IPv4Address

from polmon.core.errors import PolmonError


class SyntheticEngineError(PolmonError):
    code = "synthetic_engine_error"
    status_code = 409


@dataclass(slots=True)
class SyntheticEndpoint:
    id: str
    instance_id: uuid.UUID
    mac: str
    ipv4: IPv4Address | None
    network: str
    inbox: deque[bytes] = field(default_factory=lambda: deque(maxlen=256))


@dataclass(order=True, frozen=True, slots=True)
class ScheduledEvent:
    timestamp: float
    sequence: int
    endpoint_id: str = field(compare=False)
    kind: str = field(compare=False)
    payload: bytes = field(compare=False, default=b"")


@dataclass(frozen=True, slots=True)
class EngineStats:
    endpoint_count: int
    network_count: int
    scheduled_event_count: int
    queued_packet_count: int
    estimated_state_bytes: int


class EventScheduler:
    """Heap-based virtual-time scheduler; it never sleeps or starts worker processes."""

    def __init__(self, *, max_events: int = 10_000) -> None:
        self.max_events = max_events
        self._events: list[ScheduledEvent] = []
        self._sequence = 0

    def schedule(
        self, timestamp: float, endpoint_id: str, kind: str, payload: bytes = b""
    ) -> ScheduledEvent:
        if len(self._events) >= self.max_events:
            raise SyntheticEngineError("synthetic event limit reached")
        self._sequence += 1
        event = ScheduledEvent(timestamp, self._sequence, endpoint_id, kind, bytes(payload))
        heapq.heappush(self._events, event)
        return event

    def run_until(self, timestamp: float) -> list[ScheduledEvent]:
        due: list[ScheduledEvent] = []
        while self._events and self._events[0].timestamp <= timestamp:
            due.append(heapq.heappop(self._events))
        return due

    def discard_endpoint(self, endpoint_id: str) -> None:
        self._events = [event for event in self._events if event.endpoint_id != endpoint_id]
        heapq.heapify(self._events)

    def clear(self) -> None:
        self._events.clear()

    def __len__(self) -> int:
        return len(self._events)


class SyntheticEngine:
    """Manage many L0 endpoints as lightweight objects in one process."""

    def __init__(self, *, max_endpoints: int = 1_000, max_events: int = 10_000) -> None:
        if max_endpoints < 1:
            raise ValueError("max_endpoints must be positive")
        self.max_endpoints = max_endpoints
        self.endpoints: dict[str, SyntheticEndpoint] = {}
        self.networks: dict[str, set[str]] = {}
        self.scheduler = EventScheduler(max_events=max_events)
        self._macs: set[str] = set()
        self._addresses: set[IPv4Address] = set()

    def create_endpoint(
        self,
        endpoint_id: str,
        *,
        network: str,
        mac: str,
        ipv4: str | IPv4Address | None = None,
    ) -> SyntheticEndpoint:
        if len(self.endpoints) >= self.max_endpoints:
            raise SyntheticEngineError("synthetic endpoint limit reached")
        if endpoint_id in self.endpoints:
            raise SyntheticEngineError(f"endpoint '{endpoint_id}' already exists")
        normalized_mac = mac.lower().replace("-", ":")
        address = IPv4Address(ipv4) if ipv4 is not None else None
        if normalized_mac in self._macs:
            raise SyntheticEngineError(f"MAC address '{normalized_mac}' already exists")
        if address is not None and address in self._addresses:
            raise SyntheticEngineError(f"IPv4 address '{address}' already exists")
        endpoint = SyntheticEndpoint(
            id=endpoint_id,
            instance_id=uuid.uuid4(),
            mac=normalized_mac,
            ipv4=address,
            network=network,
        )
        self.endpoints[endpoint_id] = endpoint
        self.networks.setdefault(network, set()).add(endpoint_id)
        self._macs.add(normalized_mac)
        if address is not None:
            self._addresses.add(address)
        return endpoint

    def destroy_endpoint(self, endpoint_id: str) -> bool:
        endpoint = self.endpoints.pop(endpoint_id, None)
        if endpoint is None:
            return False
        self._macs.discard(endpoint.mac)
        if endpoint.ipv4 is not None:
            self._addresses.discard(endpoint.ipv4)
        members = self.networks[endpoint.network]
        members.discard(endpoint_id)
        if not members:
            del self.networks[endpoint.network]
        endpoint.inbox.clear()
        self.scheduler.discard_endpoint(endpoint_id)
        return True

    def dispatch(self, source_id: str, destination_id: str, payload: bytes) -> None:
        source = self._get(source_id)
        destination = self._get(destination_id)
        if source.network != destination.network:
            raise SyntheticEngineError("endpoints are not on the same virtual network")
        if len(destination.inbox) == destination.inbox.maxlen:
            raise SyntheticEngineError(f"endpoint '{destination_id}' receive queue is full")
        destination.inbox.append(bytes(payload))

    def destroy_all(self) -> None:
        for endpoint_id in tuple(self.endpoints):
            self.destroy_endpoint(endpoint_id)
        self.scheduler.clear()

    def stats(self) -> EngineStats:
        queued = sum(len(endpoint.inbox) for endpoint in self.endpoints.values())
        estimated = sys.getsizeof(self.endpoints) + sys.getsizeof(self.networks)
        for endpoint in self.endpoints.values():
            estimated += (
                sys.getsizeof(endpoint)
                + sys.getsizeof(endpoint.id)
                + sys.getsizeof(endpoint.mac)
                + sys.getsizeof(endpoint.inbox)
            )
        return EngineStats(
            endpoint_count=len(self.endpoints),
            network_count=len(self.networks),
            scheduled_event_count=len(self.scheduler),
            queued_packet_count=queued,
            estimated_state_bytes=estimated,
        )

    def _get(self, endpoint_id: str) -> SyntheticEndpoint:
        try:
            return self.endpoints[endpoint_id]
        except KeyError as error:
            raise SyntheticEngineError(f"unknown endpoint '{endpoint_id}'") from error

