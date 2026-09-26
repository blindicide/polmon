"""Execution backend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from polmon.topology.models import Topology


@dataclass(frozen=True, slots=True)
class BackendInspection:
    backend: str
    resources: frozenset[str] = field(default_factory=frozenset)
    details: dict[str, object] = field(default_factory=dict)


class ExecutionBackend(ABC):
    """Minimal interface implemented by every fidelity-specific backend."""

    name: str

    @abstractmethod
    def validate(self, topology: Topology) -> None:
        """Validate backend-specific support without creating resources."""

    @abstractmethod
    def create(self, topology: Topology) -> set[str]:
        """Create stopped resources and return their globally unique ownership IDs."""

    @abstractmethod
    def start(self) -> None:
        """Start previously created resources."""

    @abstractmethod
    def stop(self) -> None:
        """Stop active resources while retaining their configuration."""

    @abstractmethod
    def destroy(self) -> None:
        """Idempotently remove every resource created by this backend instance."""

    @abstractmethod
    def inspect(self) -> BackendInspection:
        """Return current backend details without mutating state."""

