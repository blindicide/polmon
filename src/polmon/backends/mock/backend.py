"""Failure-injectable backend with no operating-system side effects."""

from __future__ import annotations

from polmon.orchestration.base import BackendInspection
from polmon.topology.models import Topology


class MockBackend:
    name = "mock"

    def __init__(self, *, fail_on: str | None = None, resource_prefix: str = "mock") -> None:
        self.fail_on = fail_on
        self.resource_prefix = resource_prefix
        self.resources: set[str] = set()
        self.running = False
        self.calls: list[str] = []

    def _record(self, operation: str) -> None:
        self.calls.append(operation)
        if self.fail_on == operation:
            raise RuntimeError(f"injected {operation} failure")

    def validate(self, topology: Topology) -> None:
        self._record("validate")
        if not topology.nodes:
            raise ValueError("mock backend requires at least one node")

    def create(self, topology: Topology) -> set[str]:
        # Assign before injection to exercise partial-create rollback.
        self.resources = {
            f"{self.resource_prefix}:{topology.id}:{node.id}" for node in topology.nodes
        }
        self._record("create")
        return set(self.resources)

    def start(self) -> None:
        self._record("start")
        self.running = True

    def stop(self) -> None:
        self._record("stop")
        self.running = False

    def destroy(self) -> None:
        self.calls.append("destroy")
        self.running = False
        self.resources.clear()
        if self.fail_on == "destroy":
            raise RuntimeError("injected destroy failure")

    def inspect(self) -> BackendInspection:
        self._record("inspect")
        return BackendInspection(
            backend=self.name,
            resources=frozenset(self.resources),
            details={"running": self.running, "calls": list(self.calls)},
        )
